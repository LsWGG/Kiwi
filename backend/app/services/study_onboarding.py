"""学习冷启动：对话式需求采集 + 画像生成。

对话由 LLM 引导；LLM 不可用时按固定脚本继续提问，保证流程不中断。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, Source, StudyProfile, WikiPage
from app.repositories import ExamTemplateRepo, StudyProfileRepo
from app.schemas.study import (
    OnboardingCompleteIn,
    OnboardingMessage,
    OnboardingTurnIn,
    OnboardingTurnOut,
    StudyProfileOut,
)
from app.services.study_engine import StudyEngineError, chat_json, ensure_builtin_templates

GOAL_LABELS = {"exam": "通过考试", "domain": "系统掌握领域", "explore": "兴趣探索"}

FALLBACK_QUESTIONS = [
    "你这次学习是为了通过某个考试，还是想系统掌握某个领域？如果是为了考试，考试名称是什么？",
    "你之前接触过这部分内容吗？做过真题或实际项目吗？大概处于什么水平（新手 / 有基础 / 进阶）？",
    "距离目标（考试或阶段目标）还有多久？每天大概能投入多少分钟？",
    "你觉得自己哪部分最没把握？可以列出几个知识点或章节。",
    "平时你更希望一题一题练（渐进式），还是直接做整套模拟卷（仿真）？也可以交给系统安排。",
]


async def _kb_context(db: AsyncSession, kb_id: uuid.UUID) -> tuple[KnowledgeBase, int, int]:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise StudyEngineError("知识库不存在。")
    page_count = int(
        (
            await db.execute(
                select(func.count(WikiPage.id)).where(WikiPage.kb_id == kb_id)
            )
        ).scalar_one()
        or 0
    )
    source_count = int(
        (
            await db.execute(select(func.count(Source.id)).where(Source.kb_id == kb_id))
        ).scalar_one()
        or 0
    )
    return kb, page_count, source_count


def _fallback_turn(messages: list[OnboardingMessage]) -> OnboardingTurnOut:
    user_turns = [m for m in messages if m.role == "user"]
    idx = len(user_turns)
    if idx >= len(FALLBACK_QUESTIONS):
        return OnboardingTurnOut(
            reply=(
                "信息已经足够。我会按你的目标生成画像：你也可以在右侧直接选择考试模板、"
                "目标日期和每日时长，然后开始第一组训练。"
            ),
            done=True,
            profile_patch={},
            missing=[],
        )
    reply = FALLBACK_QUESTIONS[idx]
    if idx == 0:
        reply = (
            "我们先花一分钟明确目标。你这次学习是为了通过某个考试，还是想系统掌握某个领域？"
            "如果是为了考试，考试名称是什么？"
        )
    return OnboardingTurnOut(reply=reply, done=False, profile_patch={}, missing=[])


async def _inherited_profile(db: AsyncSession, kb_id: uuid.UUID) -> dict:
    """已有画像、新增知识库时，继承目标/水平/时间，只补充本库范围（README 14.2.3）。"""
    row = (
        await db.execute(
            select(StudyProfile)
            .where(StudyProfile.kb_id != kb_id, StudyProfile.onboarded.is_(True))
            .order_by(StudyProfile.updated_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        return {}
    return {
        "goal_type": row.goal_type,
        "level_prior": row.level_prior,
        "daily_minutes": row.daily_minutes,
        "preferred_mode": row.preferred_mode,
        "target_date": row.target_date.isoformat() if row.target_date else None,
    }


async def onboarding_turn(
    db: AsyncSession, kb_id: uuid.UUID, payload: OnboardingTurnIn
) -> OnboardingTurnOut:
    kb, page_count, source_count = await _kb_context(db, kb_id)
    await ensure_builtin_templates(db)
    templates = await ExamTemplateRepo(db).list_for_kb(kb_id)
    template_hint = "\n".join(
        f"- {t.name}（code={t.code}，{'内置' if t.is_builtin else '自定义'}）" for t in templates
    )
    inherited = await _inherited_profile(db, kb_id)

    if not payload.messages:
        await db.commit()
        if inherited:
            goal_label = GOAL_LABELS.get(str(inherited.get("goal_type")), "领域掌握")
            return OnboardingTurnOut(
                reply=(
                    f"你已经有学习画像（{goal_label}，每日约 {inherited.get('daily_minutes')} 分钟），"
                    f"这次只为知识库「{kb.name}」补充本库的学习范围，不重复采集目标信息。\n\n"
                    f"这个知识库有 {page_count} 个 Wiki 页面、{source_count} 篇素材。"
                    "你希望优先学哪些主题？哪些部分最没把握？"
                ),
                done=False,
                profile_patch={**inherited, "topics_focus": [], "weak_areas": []},
                missing=["topics_focus", "weak_areas"],
            )
        return OnboardingTurnOut(
            reply=(
                f"开始前先了解一下你的目标。你的知识库「{kb.name}」里有 {page_count} 个 Wiki 页面、"
                f"{source_count} 篇原始素材，我会以这些内容为主要出题依据。\n\n"
                + FALLBACK_QUESTIONS[0]
            ),
            done=False,
            profile_patch={},
            missing=["goal_type", "level_prior", "daily_minutes"],
        )

    conversation = "\n".join(
        f"{'用户' if m.role == 'user' else '教练'}：{m.content}" for m in payload.messages
    )
    prompt = (
        "你在为个人知识库应用做学习冷启动访谈。目标是通过渐进式提问采集：\n"
        "1. 学习目标（考试 / 领域掌握 / 兴趣探索）与目标考试名称；\n"
        "2. 当前水平（新手 / 有基础 / 进阶）；\n"
        "3. 时间约束（目标日期、每天可投入分钟数）；\n"
        "4. 薄弱环节自述；\n"
        "5. 输出形式偏好（渐进式 drill / 仿真 mock / 交给系统 auto）。\n\n"
        f"可选考试模板：\n{template_hint}\n\n"
        f"知识库规模：{page_count} 个 Wiki 页面，{source_count} 篇素材。\n"
        + (
            "该用户已有画像，本次只为新知识库补充范围：不要重复追问学习目标、当前水平、"
            f"每日时长，只采集本库的主题重点与薄弱环节。已有画像：{inherited}\n"
            if inherited
            else ""
        )
        + "用户回复“跳过这个问题”时，视为该项暂无信息，直接追问下一个缺口，不要重复同一问题。\n"
        f"前端已采集的草稿：{payload.draft}\n\n"
        f"对话记录：\n{conversation}\n\n"
        "请判断信息是否足够。不足则只追问一个最关键的缺口；足够则总结画像并置 done=true。\n"
        "只输出 JSON：\n"
        '{"reply":"对用户说的话","done":false,'
        '"profile_patch":{"goal_type":"exam|domain|explore","level_prior":"beginner|foundation|advanced",'
        '"daily_minutes":30,"target_date":"YYYY-MM-DD 或 null","weak_areas":["..."],'
        '"topics_focus":["..."],"preferred_mode":"auto|drill|mock","exam_template_code":"ruankao_gao"},'
        '"missing":["还缺的信息"]}\n'
        "profile_patch 只包含对话中已经明确的字段，不要臆造。"
    )
    try:
        data = await chat_json(
            db,
            kb,
            prompt,
            system="你是耐心、简洁的学习教练，只输出 JSON。",
            temperature=0.4,
            timeout=120.0,
        )
        reply = str(data.get("reply") or "").strip()
        if not reply:
            raise StudyEngineError("LLM 未返回追问内容。")
        patch = data.get("profile_patch") if isinstance(data.get("profile_patch"), dict) else {}
        # 模板 code → id
        code = patch.pop("exam_template_code", None)
        if code:
            for t in templates:
                if t.code == code:
                    patch["exam_template_id"] = str(t.id)
                    break
        missing = data.get("missing") if isinstance(data.get("missing"), list) else []
        await db.commit()
        return OnboardingTurnOut(
            reply=reply,
            done=bool(data.get("done")),
            profile_patch=patch,
            missing=[str(x) for x in missing],
        )
    except StudyEngineError:
        await db.commit()
        return _fallback_turn(payload.messages)


async def complete_onboarding(
    db: AsyncSession, kb_id: uuid.UUID, payload: OnboardingCompleteIn
) -> StudyProfileOut:
    profile = await StudyProfileRepo(db).get_or_create(kb_id)
    values = payload.profile
    profile.goal_type = values.goal_type
    profile.level_prior = values.level_prior
    profile.daily_minutes = values.daily_minutes
    profile.topics_focus = list(values.topics_focus)
    profile.weak_areas = list(values.weak_areas)
    profile.preferred_mode = values.preferred_mode
    profile.target_date = values.target_date
    profile.exam_template_id = values.exam_template_id
    profile.onboarded = True
    if values.profile_json:
        profile.profile_json = dict(values.profile_json)
    else:
        profile.profile_json = {}
    profile.profile_json = {
        **(profile.profile_json or {}),
        "conversation": [m.model_dump() for m in payload.messages][-30:],
        "quick_start": payload.quick_start,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "initial_mastery_prior": {"beginner": 0.0, "foundation": 0.3, "advanced": 0.5}[
            values.level_prior
        ],
    }
    profile.status = "active"
    await db.flush()
    await db.commit()
    await db.refresh(profile)
    return StudyProfileOut.model_validate(profile)


async def default_profile_payload(kb_id: uuid.UUID) -> dict:
    """快速开始使用的默认画像（领域掌握型、无时间约束、渐进式）。"""
    return {
        "goal_type": "domain",
        "level_prior": "beginner",
        "daily_minutes": 30,
        "topics_focus": [],
        "exam_template_id": None,
        "target_date": None,
        "preferred_mode": "auto",
        "weak_areas": [],
        "onboarded": True,
        "profile_json": {"quick_start": True},
        "kb_id": str(kb_id),
    }


def profile_is_ready(profile: StudyProfile | None) -> bool:
    return profile is not None and bool(profile.onboarded)
