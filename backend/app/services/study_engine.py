"""学习模式核心引擎：出题 / 判分 / 掌握度 / 复习调度 / 计划 / 图谱。

设计要点（对齐 README §14）：
- 出题依据：Wiki 页面（优先）+ 学习画像 + 掌握度 + 场景模板；
- 题目按题型结构化存储，客观题规则判分，主观题按评分维度由 LLM 打分；
- 掌握度以 slug 为键做 EMA，难易度与置信度参与权重；
- FSRS-5 调度驱动「今日复习」；
- 计划引擎按覆盖率 / 正确率 / 剩余时间 / 仿真成绩给出阶段建议；
- 所有学习数据只写学习侧表，不回写 Wiki。
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ExamTemplate,
    KnowledgeBase,
    LearningTopic,
    MockExam,
    StudyAttempt,
    StudyPlan,
    StudyProfile,
    StudyQuestion,
    StudyReview,
    StudySession,
    WikiLink,
    WikiPage,
)
from app.db.session import async_session_factory
from app.repositories import (
    ExamTemplateRepo,
    LearningTopicRepo,
    StudyAttemptRepo,
    StudyPlanRepo,
    StudyProfileRepo,
    StudyQuestionRepo,
    StudyReviewRepo,
    StudySessionRepo,
)
from app.schemas.study import (
    AnswerOut,
    ExamTemplateOut,
    GradingDimension,
    LearnGraphEdge,
    LearnGraphNode,
    LearnGraphOut,
    MasteryItem,
    MasteryOut,
    PlanAdjustIn,
    PlanDay,
    QuestionOut,
    StudyPlanOut,
)
from app.services.fsrs import (
    AGAIN,
    REVIEW_STATES,
    FSRSState,
    difficulty_from_ease,
    ease_from_difficulty,
    fsrs_schedule,
    rating_for_ratio,
)
from app.services.llm_factory import LLMFactory
from app.services.web_research import maybe_research_question
from app.services.wiki_compiler import _parse_llm_json, _resolve_llm_config

logger = logging.getLogger(__name__)

MASTERY_DECAY = 0.3
MASTERY_GAIN = 0.25
QUESTION_PAGE_HEAD = 800  # 客观题出题依据正文头 N 字
SUBJECTIVE_PAGE_HEAD = 1600
MASTERY_THRESHOLD = 0.7
WEAK_THRESHOLD = 0.4


class StudyEngineError(Exception):
    """学习模式业务错误。"""


# ---------- 考试场景模板 ----------
QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "case_analysis": "案例分析",
    "essay": "论文",
}
OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false", "fill_blank"}
SUBJECTIVE_TYPES = {"short_answer", "case_analysis", "essay"}

DEFAULT_RUBRICS: dict[str, list[dict]] = {
    "short_answer": [
        {"key": "points", "label": "要点覆盖", "weight": 0.7, "description": "是否覆盖参考答案中的关键要点"},
        {"key": "expression", "label": "表达条理", "weight": 0.3, "description": "表述是否准确、有条理"},
    ],
    "case_analysis": [
        {"key": "problem", "label": "问题定位", "weight": 0.3, "description": "是否准确识别案例中的核心问题"},
        {"key": "analysis", "label": "原因分析", "weight": 0.4, "description": "原因分析是否完整、有依据"},
        {"key": "solution", "label": "措施建议", "weight": 0.3, "description": "建议是否可行、针对性强"},
    ],
    "essay": [
        {"key": "relevance", "label": "切题度", "weight": 0.2, "description": "是否紧扣题目主题"},
        {"key": "arguments", "label": "论点完整性", "weight": 0.25, "description": "论点是否完整、有层次"},
        {"key": "evidence", "label": "论据充分性", "weight": 0.25, "description": "是否结合真实项目实践展开"},
        {"key": "structure", "label": "结构逻辑", "weight": 0.2, "description": "结构是否清晰、逻辑连贯"},
        {"key": "language", "label": "语言表达", "weight": 0.1, "description": "语言是否规范、通顺"},
    ],
}


def _rubric_for(qtype: str) -> list[dict]:
    dims = DEFAULT_RUBRICS.get(qtype) or DEFAULT_RUBRICS["short_answer"]
    return [dict(d) for d in dims]


BUILTIN_TEMPLATES: list[dict] = [
    {
        "name": "信息系统项目管理师（软考高项）",
        "code": "ruankao_gao",
        "description": "软考高级：综合知识 75 道选择 + 案例分析 3 道 + 论文 1 篇；各科均需 45 分以上。",
        "question_types": [
            {
                "type": "single_choice",
                "name": "综合知识",
                "count": 75,
                "score": 1,
                "duration_minutes": 150,
                "scoring": {"dimensions": []},
            },
            {
                "type": "case_analysis",
                "name": "案例分析",
                "count": 3,
                "score": 25,
                "duration_minutes": 90,
                "scoring": {"dimensions": DEFAULT_RUBRICS["case_analysis"]},
            },
            {
                "type": "essay",
                "name": "论文",
                "count": 1,
                "score": 75,
                "duration_minutes": 120,
                "scoring": {"dimensions": DEFAULT_RUBRICS["essay"]},
            },
        ],
        "scoring_rules": {"objective": "按对错给分", "subjective": "按维度加权给分"},
        "passing_criteria": {
            "total": 135,
            "subjects": [
                {"name": "综合知识", "min_score": 45},
                {"name": "案例分析", "min_score": 45},
                {"name": "论文", "min_score": 45},
            ],
        },
        "duration_minutes": 360,
        "difficulty_distribution": {"basic": 0.4, "medium": 0.4, "hard": 0.2},
        "coverage_domains": [
            "项目管理概论",
            "范围管理",
            "进度管理",
            "成本管理",
            "质量管理",
            "风险管理",
            "采购管理",
            "干系人管理",
            "信息系统技术",
        ],
    },
    {
        "name": "系统集成项目管理工程师（软考中项）",
        "code": "ruankao_zhong",
        "description": "软考中级：综合知识 75 道选择 + 案例分析 3 道，无论文。",
        "question_types": [
            {
                "type": "single_choice",
                "name": "综合知识",
                "count": 75,
                "score": 1,
                "duration_minutes": 150,
                "scoring": {"dimensions": []},
            },
            {
                "type": "case_analysis",
                "name": "案例分析",
                "count": 3,
                "score": 25,
                "duration_minutes": 90,
                "scoring": {"dimensions": DEFAULT_RUBRICS["case_analysis"]},
            },
        ],
        "scoring_rules": {"objective": "按对错给分", "subjective": "按维度加权给分"},
        "passing_criteria": {
            "total": 90,
            "subjects": [
                {"name": "综合知识", "min_score": 45},
                {"name": "案例分析", "min_score": 45},
            ],
        },
        "duration_minutes": 240,
        "difficulty_distribution": {"basic": 0.45, "medium": 0.4, "hard": 0.15},
        "coverage_domains": [
            "项目管理基础",
            "立项管理",
            "整体管理",
            "范围管理",
            "进度管理",
            "成本管理",
            "质量管理",
            "风险管理",
            "系统集成技术",
        ],
    },
    {
        "name": "PMP 项目管理认证",
        "code": "pmp",
        "description": "PMP：180 道情景选择题，覆盖人员、过程、业务环境三大领域。",
        "question_types": [
            {
                "type": "single_choice",
                "name": "情景选择题",
                "count": 180,
                "score": 1,
                "duration_minutes": 230,
                "scoring": {"dimensions": []},
            }
        ],
        "scoring_rules": {"objective": "按对错给分"},
        "passing_criteria": {"total": 108},
        "duration_minutes": 230,
        "difficulty_distribution": {"basic": 0.25, "medium": 0.5, "hard": 0.25},
        "coverage_domains": ["人员", "过程", "业务环境"],
    },
    {
        "name": "通用考试（选择 + 简答）",
        "code": "generic_exam",
        "description": "默认通用模板：20 道选择 + 4 道简答 + 1 道案例分析，适合领域自测。",
        "question_types": [
            {
                "type": "single_choice",
                "name": "单项选择题",
                "count": 20,
                "score": 2,
                "duration_minutes": 30,
                "scoring": {"dimensions": []},
            },
            {
                "type": "short_answer",
                "name": "简答题",
                "count": 4,
                "score": 10,
                "duration_minutes": 30,
                "scoring": {"dimensions": DEFAULT_RUBRICS["short_answer"]},
            },
            {
                "type": "case_analysis",
                "name": "案例分析",
                "count": 1,
                "score": 20,
                "duration_minutes": 30,
                "scoring": {"dimensions": DEFAULT_RUBRICS["case_analysis"]},
            },
        ],
        "scoring_rules": {"objective": "按对错给分", "subjective": "按维度加权给分"},
        "passing_criteria": {"total": 60},
        "duration_minutes": 90,
        "difficulty_distribution": {"basic": 0.4, "medium": 0.4, "hard": 0.2},
        "coverage_domains": [],
    },
]


async def ensure_builtin_templates(db: AsyncSession) -> None:
    """惰性写入内置模板（按 code 幂等）。"""
    repo = ExamTemplateRepo(db)
    for tpl in BUILTIN_TEMPLATES:
        existing = await repo.get_builtin_by_code(tpl["code"])
        if existing is not None:
            continue
        db.add(
            ExamTemplate(
                kb_id=None,
                name=tpl["name"],
                code=tpl["code"],
                description=tpl["description"],
                is_builtin=True,
                question_types_json=tpl["question_types"],
                scoring_rules_json=tpl["scoring_rules"],
                passing_criteria_json=tpl["passing_criteria"],
                duration_minutes=tpl["duration_minutes"],
                difficulty_distribution=tpl["difficulty_distribution"],
                coverage_domains=tpl["coverage_domains"],
            )
        )
    await db.flush()


async def list_exam_templates(db: AsyncSession, kb_id: uuid.UUID) -> list[ExamTemplateOut]:
    await ensure_builtin_templates(db)
    rows = await ExamTemplateRepo(db).list_for_kb(kb_id)
    await db.commit()
    return [ExamTemplateOut.model_validate(r) for r in rows]


# ---------- LLM 基础 ----------
_llm_factory = LLMFactory()


async def chat_json(
    db: AsyncSession,
    kb: KnowledgeBase,
    prompt: str,
    *,
    system: str = "你是严谨的学习教练，只输出 JSON。",
    temperature: float = 0.3,
    timeout: float = 150.0,
) -> dict:
    """调用默认 LLM 并解析 JSON 对象（错误显式抛出，由上层重试/降级）。"""
    from openai import APIError

    cfg, api_key = await _resolve_llm_config(db, kb)
    client = _llm_factory.get_client(cfg.base_url, api_key or None, cfg.model_name)
    try:
        resp = await client.chat.completions.create(
            model=cfg.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            timeout=timeout,
        )
    except APIError as e:
        raise StudyEngineError(f"LLM 调用失败：{e}") from e
    except Exception as e:  # 本地推理服务可能抛连接错误
        raise StudyEngineError(f"LLM 调用失败：{e}") from e
    raw = resp.choices[0].message.content or ""
    try:
        return _parse_llm_json(raw)
    except Exception as e:
        raise StudyEngineError("LLM 返回内容不是合法 JSON。") from e


# ---------- 页面 / 知识点选择 ----------
def _page_body(page: WikiPage) -> str:
    return (page.body_md or "").strip()


def _fingerprint(
    kb_id: uuid.UUID, page_slug: str, difficulty: str, qtype: str = "single_choice", salt: str = ""
) -> str:
    raw = f"q:{kb_id}:{page_slug}|{difficulty}|{qtype}|{salt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _content_hash(page: WikiPage) -> str:
    return hashlib.sha1((page.body_md or "").encode("utf-8")).hexdigest()


DIFFICULTY_CYCLE = ["basic", "medium", "hard"]
DIFFICULTY_INDEX = {d: i for i, d in enumerate(DIFFICULTY_CYCLE)}
DIFFICULTY_LABEL = {"basic": "基础", "medium": "进阶", "hard": "挑战"}


def _level_start(profile: StudyProfile) -> int:
    return {"beginner": 0, "foundation": 1, "advanced": 2}.get(profile.level_prior, 0)


async def _difficulty_for_page(
    db: AsyncSession, profile: StudyProfile, page: WikiPage
) -> str:
    """基于同知识点最近作答自适应难度：连对升、连错降。"""
    rows = (
        await db.execute(
            select(StudyAttempt.correct)
            .join(StudyQuestion, StudyAttempt.question_id == StudyQuestion.id)
            .where(
                StudyAttempt.kb_id == profile.kb_id,
                StudyQuestion.topic_slug == page.slug,
            )
            .order_by(StudyAttempt.created_at.desc())
            .limit(2)
        )
    ).scalars().all()
    idx = _level_start(profile)
    if len(rows) >= 2 and all(rows):
        idx += 1
    elif len(rows) >= 2 and not any(rows):
        idx -= 1
    idx = max(0, min(len(DIFFICULTY_CYCLE) - 1, idx))
    return DIFFICULTY_CYCLE[idx]


async def _pick_topic_page(
    db: AsyncSession,
    kb_id: uuid.UUID,
    profile: StudyProfile,
    exclude_page_ids: set[uuid.UUID] | None = None,
    mode: str = "drill",
    topic_slug: str | None = None,
) -> WikiPage | None:
    """选出题目标页。

    review：最早到期的复习页；
    drill：薄弱点 → 前置未掌握 → 聚焦关键词 → 未覆盖页 → 引用最多页。
    """
    pages = [
        p
        for p in (
            await db.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))
        ).scalars().all()
        if len(_page_body(p)) >= 40
    ]
    if exclude_page_ids:
        pages = [p for p in pages if p.id not in exclude_page_ids]
    if not pages:
        return None
    if topic_slug:
        for page in pages:
            if page.slug == topic_slug and page.id not in (exclude_page_ids or set()):
                return page

    if mode == "review":
        now = datetime.now(timezone.utc)
        rows = (
            await db.execute(
                select(WikiPage)
                .join(
                    StudyReview,
                    (StudyReview.wiki_page_id == WikiPage.id)
                    & (StudyReview.kb_id == kb_id),
                )
                .where(WikiPage.kb_id == kb_id, StudyReview.due_at <= now)
                .order_by(StudyReview.due_at.asc())
                .limit(50)
            )
        ).scalars().all()
        for page in rows:
            if page.id not in (exclude_page_ids or set()) and len(_page_body(page)) >= 40:
                return page
        # 复习队列已空：释放排除，让下一轮可重复复习；仍无则返回 None
        if exclude_page_ids:
            rows = (
                await db.execute(
                    select(WikiPage)
                    .join(
                        StudyReview,
                        (StudyReview.wiki_page_id == WikiPage.id)
                        & (StudyReview.kb_id == kb_id),
                    )
                    .where(WikiPage.kb_id == kb_id, StudyReview.due_at <= now)
                    .order_by(StudyReview.due_at.asc())
                    .limit(1)
                )
            ).scalars().first()
            return rows
        return None

    mastery = dict(profile.mastery or {})
    page_by_id = {p.id: p for p in pages}

    # 1) 最近错题集中的知识点
    wrong_rows = (
        await db.execute(
            select(StudyQuestion.topic_slug, func.count(StudyAttempt.id))
            .join(StudyAttempt, StudyAttempt.question_id == StudyQuestion.id)
            .where(
                StudyAttempt.kb_id == kb_id,
                StudyAttempt.correct.is_(False),
                StudyQuestion.topic_slug.is_not(None),
            )
            .group_by(StudyQuestion.topic_slug)
            .order_by(func.count(StudyAttempt.id).desc())
            .limit(5)
        )
    ).all()
    for slug, _cnt in wrong_rows:
        page = next((p for p in pages if p.slug == slug), None)
        if page is not None:
            # 前置未掌握先补前置
            prereq = await _pick_prerequisite(db, kb_id, slug, mastery, page_by_id)
            return prereq or page

    # 2) 已作答但掌握度低的页
    weak_slugs = [
        s
        for s, score in mastery.items()
        if float(score) < WEAK_THRESHOLD and s in {p.slug for p in pages}
    ]
    weak_slugs.sort(key=lambda s: float(mastery.get(s, 0.0)))
    for slug in weak_slugs:
        page = next(p for p in pages if p.slug == slug)
        prereq = await _pick_prerequisite(db, kb_id, slug, mastery, page_by_id)
        return prereq or page

    # 3) 画像自述的薄弱环节（weak_areas）→ 优先匹配标题/slug
    weak_terms = [
        str(x).strip().lower() for x in (profile.weak_areas or []) if str(x).strip()
    ]
    for kw in weak_terms:
        for p in pages:
            haystack = f"{p.title} {p.slug}".lower()
            if kw in haystack:
                prereq = await _pick_prerequisite(db, kb_id, p.slug, mastery, page_by_id)
                return prereq or p

    # 4) 用户聚焦关键词
    focus = [str(x).strip().lower() for x in (profile.topics_focus or []) if str(x).strip()]
    for kw in focus:
        for p in pages:
            haystack = f"{p.title} {p.slug}".lower()
            if kw in haystack:
                return p

    # 5) 未覆盖页优先，按引用数排序
    uncovered = [p for p in pages if p.slug not in mastery]
    candidates = uncovered or pages
    link_counts: dict[uuid.UUID, int] = {}
    rows = (
        await db.execute(
            select(WikiLink.to_page_id, func.count())
            .join(WikiPage, WikiLink.to_page_id == WikiPage.id)
            .where(WikiPage.kb_id == kb_id)
            .group_by(WikiLink.to_page_id)
        )
    ).all()
    for page_id, cnt in rows:
        if page_id in page_by_id:
            link_counts[page_id] = cnt
    # 有前置关系的，先出前置
    for p in sorted(candidates, key=lambda x: link_counts.get(x.id, 0), reverse=True):
        prereq = await _pick_prerequisite(db, kb_id, p.slug, mastery, page_by_id)
        return prereq or p
    return None


async def _pick_prerequisite(
    db: AsyncSession,
    kb_id: uuid.UUID,
    slug: str,
    mastery: dict,
    page_by_id: dict[uuid.UUID, WikiPage],
) -> WikiPage | None:
    topic = await LearningTopicRepo(db).get_by_slug(kb_id, slug)
    if topic is None or not topic.prerequisite_topic_ids:
        return None
    prereq_ids = {str(x) for x in topic.prerequisite_topic_ids}
    rows = (
        await db.execute(
            select(LearningTopic).where(LearningTopic.kb_id == kb_id)
        )
    ).scalars().all()
    for row in rows:
        if str(row.id) in prereq_ids and row.wiki_page_id in page_by_id:
            if float(mastery.get(row.slug, 0.0)) < MASTERY_THRESHOLD:
                return page_by_id[row.wiki_page_id]
    return None


# ---------- 题型排程 ----------
DEFAULT_TYPE_SCHEDULE = [
    "single_choice",
    "single_choice",
    "true_false",
    "single_choice",
    "short_answer",
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "single_choice",
]


def _template_types(template: ExamTemplate | None) -> list[dict]:
    if template is None:
        return []
    items = template.question_types_json or []
    return [x for x in items if isinstance(x, dict) and x.get("type") in QUESTION_TYPE_LABELS]


def _type_schedule(template: ExamTemplate | None) -> list[str]:
    """构造一个 12 题内的题型轮换序列，保证模板中的每种题型至少出现一次。"""
    types = _template_types(template)
    if not types:
        return list(DEFAULT_TYPE_SCHEDULE)
    total = sum(max(1, int(x.get("count", 1))) for x in types)
    schedule: list[str] = []
    for item in types:
        count = max(1, int(item.get("count", 1)))
        quota = max(1, round(12 * count / total))
        schedule.extend([item["type"]] * quota)
    # 限制长度，同时确保每种题型至少一次
    seen: list[str] = []
    for t in schedule:
        if t not in seen:
            seen.append(t)
    schedule = seen + [t for t in schedule if t not in seen]
    return schedule[: max(12, len(seen))]


def pick_question_type(
    template: ExamTemplate | None, answered_count: int, requested: str | None = None
) -> str:
    if requested in QUESTION_TYPE_LABELS:
        return requested
    schedule = _type_schedule(template)
    return schedule[answered_count % len(schedule)]


async def _get_template_for_profile(
    db: AsyncSession, profile: StudyProfile
) -> ExamTemplate | None:
    if not profile.exam_template_id:
        return None
    return await ExamTemplateRepo(db).get_for_kb(profile.kb_id, profile.exam_template_id)


# ---------- 出题 ----------
def _to_int(value, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _letter_to_index(value) -> int:
    if isinstance(value, str) and len(value.strip()) == 1:
        ch = value.strip().upper()
        if "A" <= ch <= "Z":
            return ord(ch) - ord("A")
    return _to_int(value)


def _normalize_weights(rubric: list[dict]) -> list[dict]:
    cleaned = []
    for i, dim in enumerate(rubric):
        if not isinstance(dim, dict):
            continue
        key = str(dim.get("key") or f"dim_{i}")
        label = str(dim.get("label") or key)
        try:
            weight = float(dim.get("weight", 0))
        except (TypeError, ValueError):
            weight = 0.0
        cleaned.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "description": str(dim.get("description") or ""),
            }
        )
    if not cleaned:
        cleaned = _rubric_for("short_answer")
    total = sum(d["weight"] for d in cleaned) or 1.0
    for d in cleaned:
        d["weight"] = round(d["weight"] / total, 4)
    return cleaned


def _dedupe_options(raw: list[str]) -> tuple[list[str], dict[int, int]]:
    """去掉重复/同义选项，返回新选项与旧索引→新索引映射。"""
    options: list[str] = []
    mapping: dict[int, int] = {}
    seen: dict[str, int] = {}
    for i, option in enumerate(raw):
        key = _normalize_text(option)
        if not key:
            continue
        if key in seen:
            mapping[i] = seen[key]
            continue
        seen[key] = len(options)
        mapping[i] = len(options)
        options.append(option)
    return options, mapping


def _normalize_question(
    data: dict, qtype: str, difficulty: str, page: WikiPage
) -> tuple[dict, dict, dict]:
    """把 LLM 输出归一化为 (question_json, body_json, answer_json)。"""
    if not isinstance(data, dict):
        raise StudyEngineError("LLM 出题结果不是对象。")
    text = str(data.get("question") or data.get("stem") or "").strip()
    if not text:
        raise StudyEngineError("LLM 出题结果缺少题干。")
    explanation = str(data.get("explanation") or data.get("analysis") or "").strip()

    if qtype == "single_choice":
        raw_options = [str(o).strip() for o in (data.get("options") or []) if str(o).strip()]
        options, index_map = _dedupe_options(raw_options)
        if len(options) < 2:
            raise StudyEngineError("单选题选项不足或存在重复选项。")
        options = options[:4]
        idx = _letter_to_index(data.get("answer_index", data.get("answer")))
        idx = index_map.get(idx, -1)
        if idx < 0 or idx >= len(options):
            raise StudyEngineError("单选题答案不在选项范围内。")
        qj = {
            "question": text,
            "options": options,
            "answer_index": idx,
            "explanation": explanation,
            "cite_slug": page.slug,
            "difficulty": difficulty,
        }
        ans = {"correct_index": idx}
        return qj, {}, ans

    if qtype == "multiple_choice":
        raw_options = [str(o).strip() for o in (data.get("options") or []) if str(o).strip()]
        options, index_map = _dedupe_options(raw_options)
        if len(options) < 3:
            raise StudyEngineError("多选题选项不足或存在重复选项。")
        options = options[:6]
        raw_indexes = data.get("answer_indexes") or data.get("answer_indices") or []
        if not isinstance(raw_indexes, list):
            raw_indexes = [raw_indexes]
        indexes = sorted(
            index_map[i]
            for i in {_letter_to_index(x) for x in raw_indexes}
            if i in index_map
        )
        indexes = [i for i in indexes if 0 <= i < len(options)]
        if not indexes:
            raise StudyEngineError("多选题答案不在选项范围内。")
        qj = {
            "question": text,
            "options": options,
            "answer_index": indexes[0],
            "answer_indexes": indexes,
            "explanation": explanation,
            "cite_slug": page.slug,
            "difficulty": difficulty,
        }
        return qj, {}, {"correct_indexes": indexes}

    if qtype == "true_false":
        raw = data.get("answer")
        if isinstance(raw, bool):
            idx = 0 if raw else 1
        else:
            idx = _letter_to_index(raw)
            if idx not in (0, 1):
                idx = 0 if str(raw).strip().lower() in {"true", "t", "正确", "对", "是"} else 1
        qj = {
            "question": text,
            "options": ["正确", "错误"],
            "answer_index": idx,
            "explanation": explanation,
            "cite_slug": page.slug,
            "difficulty": difficulty,
        }
        return qj, {}, {"correct_index": idx}

    if qtype == "fill_blank":
        accepted = data.get("accepted_answers") or data.get("answers") or data.get("answer") or []
        if isinstance(accepted, str):
            accepted = [accepted]
        accepted = [str(a).strip() for a in accepted if str(a).strip()]
        if not accepted:
            raise StudyEngineError("填空题缺少参考答案。")
        qj = {
            "question": text,
            "options": [],
            "answer_index": -1,
            "explanation": explanation,
            "cite_slug": page.slug,
            "difficulty": difficulty,
        }
        return qj, {}, {"accepted_answers": accepted}

    # 主观题
    rubric = _normalize_weights(data.get("rubric") or [])
    if not data.get("rubric"):
        rubric = _normalize_weights(_rubric_for(qtype))
    material = str(data.get("material") or data.get("case_material") or "").strip()
    requirements = str(
        data.get("requirements") or data.get("task") or data.get("writing_requirements") or ""
    ).strip()
    if not requirements:
        requirements = "请结合知识库内容作答，条理清晰、要点完整。"
    min_words = _to_int(data.get("min_words"), 0)
    if min_words <= 0:
        min_words = {"short_answer": 80, "case_analysis": 200, "essay": 1200}[qtype]
    reference = str(
        data.get("reference_answer") or data.get("reference") or data.get("answer") or ""
    ).strip()
    key_points = data.get("key_points") or data.get("points") or []
    if isinstance(key_points, str):
        key_points = [key_points]
    key_points = [str(x).strip() for x in key_points if str(x).strip()]
    if not reference and key_points:
        reference = "\n".join(f"- {p}" for p in key_points)
    body = {
        "material": material,
        "requirements": requirements,
        "min_words": min_words,
        "scenario": str(data.get("scenario") or ""),
    }
    ans = {
        "reference_answer": reference,
        "key_points": key_points,
        "rubric": rubric,
    }
    qj = {
        "question": text,
        "options": [],
        "answer_index": -1,
        "explanation": explanation,
        "cite_slug": page.slug,
        "difficulty": difficulty,
    }
    return qj, body, ans


def _question_prompt(
    page: WikiPage,
    difficulty: str,
    qtype: str,
    count: int,
    avoid_stems: list[str] | None,
) -> str:
    label = QUESTION_TYPE_LABELS[qtype]
    difficulty_hint = {
        "basic": "基础：考查概念定义、分类、关键术语的记忆与辨识。",
        "medium": "进阶：考查理解与应用，需要把页面内容套到具体情境。",
        "hard": "挑战：考查分析、比较、边界条件或综合推理。",
    }.get(difficulty, "")
    body_head = SUBJECTIVE_PAGE_HEAD if qtype in SUBJECTIVE_TYPES else QUESTION_PAGE_HEAD
    body = _page_body(page)[:body_head]
    avoid_hint = ""
    if avoid_stems:
        previews = "\n".join(f"- {s[:80]}" for s in avoid_stems[-8:])
        avoid_hint = f"不要与以下已出题目重复或换汤不换药：\n{previews}\n"

    if qtype == "single_choice":
        shape = '{"question":"题干","options":["A","B","C","D"],"answer_index":0,"explanation":"解析"}'
    elif qtype == "multiple_choice":
        shape = (
            '{"question":"题干","options":["A","B","C","D"],'
            '"answer_indexes":[0,2],"explanation":"解析"}'
        )
    elif qtype == "true_false":
        shape = '{"question":"陈述句","answer":true,"explanation":"解析"}'
    elif qtype == "fill_blank":
        shape = (
            '{"question":"含____的题干","accepted_answers":["答案1","可接受同义词"],'
            '"explanation":"解析"}'
        )
    elif qtype == "short_answer":
        shape = (
            '{"question":"题目","requirements":"作答要求","min_words":120,'
            '"reference_answer":"参考答案","key_points":["要点"],'
            '"rubric":[{"key":"points","label":"要点覆盖","weight":0.7,"description":"..."}],'
            '"explanation":"判分依据"}'
        )
    elif qtype == "case_analysis":
        shape = (
            '{"question":"案例题标题/设问","material":"案例背景材料",'
            '"requirements":"作答要求","min_words":300,"reference_answer":"参考答案",'
            '"key_points":["问题定位","原因分析","措施建议"],'
            '"rubric":[{"key":"problem","label":"问题定位","weight":0.3,"description":"..."},'
            '{"key":"analysis","label":"原因分析","weight":0.4,"description":"..."},'
            '{"key":"solution","label":"措施建议","weight":0.3,"description":"..."}],'
            '"explanation":"判分依据"}'
        )
    else:  # essay
        shape = (
            '{"question":"论文题目","requirements":"写作要求（含字数、结构、结合项目实践）",'
            '"min_words":2000,"reference_answer":"论文提纲/参考要点","key_points":["论点"],'
            '"rubric":[{"key":"relevance","label":"切题度","weight":0.2,"description":"..."}],'
            '"explanation":"评分说明"}'
        )

    if count > 1:
        if qtype in SUBJECTIVE_TYPES:
            count = 1
        wrapper = f'{{"items":[{shape}]}}'
        count_hint = f"请生成 {count} 道互不相同的{label}，放在 items 数组中。"
    else:
        wrapper = shape
        count_hint = f"请生成 1 道{label}。"

    return (
        "你是知识库出题老师。请严格基于下方 Wiki 页内容出题，不得编造页面之外的事实。\n"
        f"{count_hint}\n"
        f"难度要求（{difficulty}）：{difficulty_hint}\n"
        "客观题必须有唯一确定答案；主观题需给出评分维度与参考要点。\n"
        f"{avoid_hint}"
        "只输出 JSON，不要分析过程。格式：\n"
        f"{wrapper}\n\n"
        f"Wiki 页标题：{page.title}\nWiki 页内容：\n{body}"
    )


async def _call_llm_questions(
    db: AsyncSession,
    kb: KnowledgeBase,
    page: WikiPage,
    difficulty: str,
    qtype: str,
    count: int = 1,
    avoid_stems: list[str] | None = None,
) -> list[tuple[dict, dict, dict]]:
    """调用 LLM 生成 1..N 道题，返回归一化后的三元组列表。"""
    prompt = _question_prompt(page, difficulty, qtype, count, avoid_stems)
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            data = await chat_json(db, kb, prompt)
            raw_items = data.get("items") if isinstance(data.get("items"), list) else [data]
            results = []
            for item in raw_items:
                try:
                    results.append(_normalize_question(item, qtype, difficulty, page))
                except StudyEngineError:
                    continue
            if results:
                return results[:count]
            last_error = StudyEngineError("LLM 未返回可用题目。")
        except StudyEngineError as e:
            last_error = e
    raise last_error or StudyEngineError("出题失败。")


async def _save_question(
    db: AsyncSession,
    kb_id: uuid.UUID,
    page: WikiPage,
    fingerprint: str,
    normalized: tuple[dict, dict, dict],
    difficulty: str,
    qtype: str,
    confidence: str = "unverified",
) -> StudyQuestion:
    qj, body, ans = normalized
    # 原始素材兜底生成的合成页没有数据库主键
    link_id = page.id if isinstance(getattr(page, "id", None), uuid.UUID) else None
    repo = StudyQuestionRepo(db)
    existing = await repo.find_by_fingerprint(kb_id, fingerprint)
    if existing is not None:
        if existing.cache_status != "invalid":
            return existing
        # 用户反馈 / 内容漂移 / 模板变更后重新生成，原地替换失效缓存
        existing.question_json = qj
        existing.body_json = body
        existing.answer_json = ans
        existing.difficulty = difficulty
        existing.question_type = qtype
        existing.topic_slug = page.slug
        existing.wiki_page_id = link_id
        existing.source_hash = _content_hash(page)
        existing.confidence_level = confidence
        existing.cache_status = "active"
        await db.flush()
        return existing
    try:
        async with db.begin_nested():
            row = await repo.save(
                kb_id,
                link_id,
                fingerprint,
                qj,
                difficulty,
                topic_slug=page.slug,
                question_type=qtype,
                body_json=body,
                answer_json=ans,
                source_hash=_content_hash(page),
                confidence_level=confidence,
                web_sources_json=[],
            )
        return row
    except Exception:
        # 并发写同一指纹：回读已存在行
        existing = await repo.find_by_fingerprint(kb_id, fingerprint)
        if existing is not None:
            return existing
        raise


def _question_out(
    q: StudyQuestion,
    page_slug: str | None = None,
    cite_title: str | None = None,
) -> QuestionOut:
    qj = q.question_json or {}
    body = q.body_json or {}
    qtype = q.question_type or "single_choice"
    source_slug = page_slug or q.topic_slug or qj.get("cite_slug")
    return QuestionOut(
        id=q.id,
        question=qj.get("question", ""),
        question_type=qtype,
        options=qj.get("options", []),
        difficulty=q.difficulty,
        cite_slug=source_slug,
        cite_page_id=q.wiki_page_id,
        topic_slug=q.topic_slug or source_slug,
        cite_title=cite_title,
        material=body.get("material", ""),
        requirements=body.get("requirements", ""),
        min_words=body.get("min_words"),
        web_sources=q.web_sources_json or [],
        confidence_level=q.confidence_level or "unverified",
        multiple=qtype == "multiple_choice",
    )


async def _page_for_question(db: AsyncSession, q: StudyQuestion) -> WikiPage | None:
    if q.wiki_page_id:
        return await db.get(WikiPage, q.wiki_page_id)
    if q.topic_slug:
        return (
            await db.execute(
                select(WikiPage).where(
                    WikiPage.kb_id == q.kb_id, WikiPage.slug == q.topic_slug
                )
            )
        ).scalars().first()
    return None


async def _generate_question(
    db: AsyncSession,
    kb: KnowledgeBase,
    profile: StudyProfile,
    page: WikiPage,
    qtype: str,
    difficulty: str,
    used_stems: list[str] | None = None,
    salt: str = "",
) -> StudyQuestion:
    fp = _fingerprint(kb.id, page.slug, difficulty, qtype, salt)
    repo = StudyQuestionRepo(db)
    existing = await repo.find_by_fingerprint(kb.id, fp)
    if existing is not None and existing.cache_status == "active":
        return existing
    items = await _call_llm_questions(
        db, kb, page, difficulty, qtype, 1, used_stems
    )
    q = await _save_question(db, kb.id, page, fp, items[0], difficulty, qtype)
    await maybe_research_question(db, kb.id, q)
    return q


# ---------- 会话 ----------
def _raw_fallback_page(db: AsyncSession, kb: KnowledgeBase) -> WikiPage | None:
    """Wiki 尚未编译时，用原始素材 chunk 兜底出题（README 14.4.1）。"""
    try:
        from app.services import qdrant_store

        payloads = qdrant_store.scroll_chunks(
            kb.id, limit=40, model=kb.embedding_model
        )
    except Exception as e:  # Qdrant 不可用时保持原有报错，不影响主流程
        logger.warning("读取原始素材 chunk 失败：%s", e)
        return None
    if not payloads:
        return None
    payloads = sorted(
        payloads,
        key=lambda p: (str(p.get("source_id") or ""), int(p.get("chunk_index") or 0)),
    )
    parts: list[str] = []
    title = ""
    source_id = ""
    for payload in payloads[:20]:
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        parts.append(text)
        title = title or str(payload.get("source_title") or payload.get("title") or "")
        source_id = source_id or str(payload.get("source_id") or "")
    if sum(len(x) for x in parts) < 200:
        return None
    return WikiPage(
        kb_id=kb.id,
        slug=f"raw:{source_id[:8] or 'fallback'}",
        title=(title or "原始素材")[:300],
        body_md="\n\n".join(parts),
        page_type="raw",
    )


async def generate_drill_question(
    kb_id: uuid.UUID,
    mode: str = "drill",
    question_type: str | None = None,
    topic_slug: str | None = None,
) -> QuestionOut:
    """生成一组训练的首题；topic_slug 用于「针对本页发起学习」。"""
    async with async_session_factory() as db:
        profile = await StudyProfileRepo(db).get_by_kb(kb_id)
        if profile is None:
            raise StudyEngineError("请先完善学习画像再开始训练。")
        kb = await db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise StudyEngineError("知识库不存在。")
        page = await _pick_topic_page(
            db, kb_id, profile, mode=mode, topic_slug=topic_slug
        )
        if page is None:
            if topic_slug:
                raise StudyEngineError("该 Wiki 页面没有足够内容用于出题。")
            if mode == "review":
                raise StudyEngineError("今日没有到期复习项，先去训练新知识点吧。")
            # Wiki 尚未编译：用原始素材兜底出题
            page = _raw_fallback_page(db, kb)
            if page is None:
                raise StudyEngineError(
                    "该知识库还没有可出题的 Wiki 页面或原始素材，请先「导入 → 编译」。"
                )

        template = await _get_template_for_profile(db, profile)
        attempts_count = int(
            (
                await db.execute(
                    select(func.count(StudyAttempt.id)).where(StudyAttempt.kb_id == kb_id)
                )
            ).scalar_one()
            or 0
        )
        qtype = pick_question_type(template, attempts_count, question_type)
        difficulty = await _difficulty_for_page(db, profile, page)
        q = await _generate_question(db, kb, profile, page, qtype, difficulty)
        await db.commit()
        return _question_out(q, page.slug, page.title)


async def generate_drill_question_for_session(
    session_id: uuid.UUID,
    previous_fingerprints: list[str] | None = None,
    used_stems: list[str] | None = None,
    question_type: str | None = None,
) -> QuestionOut:
    """为既有会话续出下一题。"""
    async with async_session_factory() as db:
        session = await db.get(StudySession, session_id)
        if session is None:
            raise StudyEngineError("训练会话不存在。")
        if session.status != "in_progress":
            raise StudyEngineError("该会话已结束。")
        kb_id = session.kb_id
        profile = await StudyProfileRepo(db).get_by_kb(kb_id)
        if profile is None:
            raise StudyEngineError("请先完善学习画像再开始训练。")
        kb = await db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise StudyEngineError("知识库不存在。")

        mode = session.mode or "drill"
        used = set(previous_fingerprints or [])
        stems = [s for s in (used_stems or []) if s]
        template = await _get_template_for_profile(db, profile)
        answered = int(
            (
                await db.execute(
                    select(func.count(StudyAttempt.id)).where(
                        StudyAttempt.session_id == session_id
                    )
                )
            ).scalar_one()
            or 0
        )
        qtype = pick_question_type(template, answered, question_type)
        page = await _pick_topic_page(
            db, kb_id, profile, mode=mode, topic_slug=session.topic_slug
        )
        if page is None:
            if session.topic_slug:
                raise StudyEngineError("该知识点的题目已全部练完，可以结束本组。")
            if mode == "review":
                raise StudyEngineError("今日到期复习已完成，可以结束本组。")
            page = _raw_fallback_page(db, kb)
            if page is None:
                raise StudyEngineError("该知识库还没有可出题的 Wiki 页面或原始素材。")

        candidates = [page]
        # 专题训练整组锁定在当前知识点；普通训练允许第二候选页兜底
        if not session.topic_slug:
            alt = await _pick_topic_page(
                db, kb_id, profile, exclude_page_ids={page.id}, mode=mode
            )
            if alt is not None:
                candidates.append(alt)

        # 优先按当前题型出题；同页缓存题目耗尽时轮换题型/难度
        type_cycle = [qtype] + [t for t in _type_schedule(template) if t != qtype][:3]
        for candidate in candidates:
            difficulty = await _difficulty_for_page(db, profile, candidate)
            for candidate_type in type_cycle:
                fp = _fingerprint(kb_id, candidate.slug, difficulty, candidate_type)
                if fp in used:
                    continue
                existing = await StudyQuestionRepo(db).find_by_fingerprint(kb_id, fp)
                if existing is not None and existing.cache_status == "active":
                    if existing.question_json.get("question", "") in set(stems):
                        continue
                    await db.commit()
                    return _question_out(existing, candidate.slug, candidate.title)
                q = await _generate_question(
                    db,
                    kb,
                    profile,
                    candidate,
                    candidate_type,
                    difficulty,
                    stems,
                    salt=f"fresh:{uuid.uuid4().hex[:8]}",
                )
                if q.question_json.get("question", "") in set(stems):
                    continue
                await db.commit()
                return _question_out(q, candidate.slug, candidate.title)

        if mode == "review":
            raise StudyEngineError("今日到期复习已完成，可以结束本组。")
        raise StudyEngineError("本组训练已覆盖当前可出题页的变体，换个焦点再练。")


async def generate_variant(
    kb_id: uuid.UUID, question_id: uuid.UUID, question_type: str | None = None
) -> QuestionOut:
    """同知识点、同难度的变式题（用于答错后追问）。"""
    async with async_session_factory() as db:
        q = await db.get(StudyQuestion, question_id)
        if q is None or q.kb_id != kb_id:
            raise StudyEngineError("题目不存在。")
        page = await _page_for_question(db, q)
        if page is None:
            raise StudyEngineError("原题关联页面已删除，无法生成变式题。")
        kb = await db.get(KnowledgeBase, kb_id)
        profile = await StudyProfileRepo(db).get_by_kb(kb_id)
        if profile is None:
            raise StudyEngineError("请先完善学习画像。")
        qtype = question_type or q.question_type or "single_choice"
        salt = f"variant:{datetime.now(timezone.utc).timestamp()}"
        fp = _fingerprint(kb_id, page.slug, q.difficulty, qtype, salt)
        items = await _call_llm_questions(
            db, kb, page, q.difficulty, qtype, 1, [q.question_json.get("question", "")]
        )
        new_q = await _save_question(db, kb_id, page, fp, items[0], q.difficulty, qtype)
        await db.commit()
        return _question_out(new_q, page.slug, page.title)


# ---------- 判分 ----------
def _normalize_text(value: str) -> str:
    return re.sub(r"[\s。，、；：,.；:!?！？\"'“”‘’（）()\[\]【】]+", "", value or "").lower()


def _grade_objective(
    q: StudyQuestion,
    selected_index: int,
    selected_indexes: list[int],
    text: str,
) -> dict:
    qtype = q.question_type or "single_choice"
    qj = q.question_json or {}
    ans = q.answer_json or {}
    if qtype == "multiple_choice":
        correct_indexes = ans.get("correct_indexes") or qj.get("answer_indexes") or []
        correct_indexes = sorted({_to_int(i, -1) for i in correct_indexes})
        correct_indexes = [i for i in correct_indexes if i >= 0]
        chosen = sorted(set(int(i) for i in selected_indexes))
        correct = bool(chosen) and chosen == correct_indexes
        return {
            "correct": correct,
            "ratio": 1.0 if correct else 0.0,
            "correct_index": correct_indexes[0] if correct_indexes else -1,
            "correct_indexes": correct_indexes,
            "correct_answer": "、".join(
                chr(ord("A") + i) for i in correct_indexes if i < 26
            ),
            "selected_indexes": chosen,
            "explanation": qj.get("explanation", ""),
            "dimensions": [],
            "grading_method": "rule",
        }
    if qtype == "fill_blank":
        accepted = [str(a) for a in (ans.get("accepted_answers") or [])]
        if ans.get("reference_answer"):
            accepted.append(str(ans["reference_answer"]))
        accepted = [a for a in accepted if a.strip()]

        def split_parts(value: str) -> list[str]:
            return [
                _normalize_text(p)
                for p in re.split(r"[;；\n]+", value or "")
                if _normalize_text(p)
            ]

        user_parts = split_parts(text)
        # 多空题：参考答案用分号分隔，每个空允许用 / 或 | 给出等价答案
        multi_expected = next(
            (a for a in accepted if re.search(r"[;；\n]", a)), None
        )
        if multi_expected is not None or len(user_parts) > 1:
            expected_parts = split_parts(multi_expected or (accepted[0] if accepted else ""))
            alternatives = [
                [
                    _normalize_text(alt)
                    for alt in re.split(r"[/|]", part)
                    if _normalize_text(alt)
                ]
                for part in expected_parts
            ]
            correct = (
                bool(user_parts)
                and len(user_parts) == len(alternatives)
                and all(
                    user in alts for user, alts in zip(user_parts, alternatives)
                )
            )
        else:
            user_norm = _normalize_text(text)
            correct = bool(user_norm) and any(
                user_norm == _normalize_text(a) for a in accepted
            )
        return {
            "correct": correct,
            "ratio": 1.0 if correct else 0.0,
            "correct_index": -1,
            "correct_indexes": [],
            "correct_answer": " / ".join(accepted),
            "explanation": qj.get("explanation", ""),
            "dimensions": [],
            "grading_method": "rule",
        }
    correct_index = _to_int(
        ans.get("correct_index", qj.get("answer_index", -1)), -1
    )
    correct = int(selected_index) == int(correct_index) and correct_index >= 0
    options = qj.get("options") or []
    correct_answer = ""
    if 0 <= correct_index < len(options):
        correct_answer = f"{chr(ord('A') + correct_index)}. {options[correct_index]}"
    return {
        "correct": correct,
        "ratio": 1.0 if correct else 0.0,
        "correct_index": correct_index,
        "correct_indexes": [correct_index] if correct_index >= 0 else [],
        "correct_answer": correct_answer,
        "explanation": qj.get("explanation", ""),
        "dimensions": [],
        "grading_method": "rule",
    }


def _heuristic_subjective_score(q: StudyQuestion, text: str) -> tuple[float, list[dict]]:
    """LLM 不可用时的降级评分：按参考要点字符覆盖率估算，不中断学习流程。"""
    ans = q.answer_json or {}
    reference = str(ans.get("reference_answer") or "")
    key_points = [str(x) for x in (ans.get("key_points") or [])]
    source = reference + "\n" + "\n".join(key_points)
    source_norm = _normalize_text(source)
    user_norm = _normalize_text(text)

    def bigrams(s: str) -> set[str]:
        return {s[i : i + 2] for i in range(max(0, len(s) - 1))}

    ref_grams = bigrams(source_norm)
    user_grams = bigrams(user_norm)
    overlap = len(ref_grams & user_grams) / len(ref_grams) if ref_grams else 0.0
    ratio = min(1.0, overlap * 1.6)
    if len(user_norm) < 20:
        ratio = 0.0
    rubric = _normalize_weights(ans.get("rubric") or _rubric_for(q.question_type))
    dims = [
        {
            "key": d["key"],
            "label": d["label"],
            "score": round(ratio * d["weight"] * 100, 1),
            "max_score": round(d["weight"] * 100, 1),
            "comment": "系统按参考要点覆盖率估算（LLM 判分不可用时的降级结果）。",
        }
        for d in rubric
    ]
    return ratio, dims


SUBJECTIVE_GRADE_PROMPT = """你是严格但公正的阅卷老师。请按评分维度给下面的主观题作答打分。

题目：{question}
{material}
作答要求：{requirements}
评分维度（权重之和为 1）：{rubric}
参考要点：
{reference}

考生作答：
{answer}

要求：
1. 每个维度给出 0-1 的得分比例（score_ratio）与简短评语；
2. 总分为各维度加权和，范围 0-1；
3. 指出遗漏的关键点，并说明可改进方向；
4. 若知识库有可补充的论据，引用一句原文作为依据（cite_quote，可为空）。
只输出 JSON：
{{"dimensions":[{{"key":"维度 key","score_ratio":0.8,"comment":"评语"}}],
"total_ratio":0.8,"overall":"总体评价","suggestions":["改进建议"],"cite_quote":"原文引用"}}
"""


async def _llm_subjective_grade(
    db: AsyncSession,
    kb: KnowledgeBase,
    q: StudyQuestion,
    text: str,
    page: WikiPage | None,
    dimensions: list[dict] | None = None,
) -> tuple[float, list[dict], str]:
    ans = q.answer_json or {}
    body = q.body_json or {}
    rubric = _normalize_weights(
        dimensions or ans.get("rubric") or _rubric_for(q.question_type)
    )
    rubric_text = "\n".join(
        f"- {d['label']}（{d['key']}，权重 {d['weight']}）：{d['description']}"
        for d in rubric
    )
    reference = str(ans.get("reference_answer") or "")[:4000]
    if not reference and page is not None:
        reference = _page_body(page)[:2000]
    material = body.get("material") or ""
    prompt = SUBJECTIVE_GRADE_PROMPT.format(
        question=q.question_json.get("question", ""),
        material=(f"案例材料：\n{material}\n" if material else ""),
        requirements=body.get("requirements", ""),
        rubric=rubric_text,
        reference=reference or "（无参考答案，请依据题目与知识库内容判断）",
        answer=text[:8000],
    )
    data = await chat_json(
        db, kb, prompt, system="你是严谨的阅卷老师，只输出 JSON。", temperature=0.2, timeout=180.0
    )
    raw_dims = data.get("dimensions") or []
    by_key = {
        str(d.get("key")): d for d in raw_dims if isinstance(d, dict) and d.get("key")
    }
    dims: list[dict] = []
    weighted = 0.0
    for d in rubric:
        raw = by_key.get(d["key"], {})
        try:
            ratio = float(raw.get("score_ratio", raw.get("ratio", 0.0)))
        except (TypeError, ValueError):
            ratio = 0.0
        ratio = max(0.0, min(1.0, ratio))
        weighted += ratio * d["weight"]
        dims.append(
            {
                "key": d["key"],
                "label": d["label"],
                "score": round(ratio * d["weight"] * 100, 1),
                "max_score": round(d["weight"] * 100, 1),
                "comment": str(raw.get("comment") or ""),
            }
        )
    try:
        total = float(data.get("total_ratio", weighted))
    except (TypeError, ValueError):
        total = weighted
    total = max(0.0, min(1.0, total))
    feedback = str(data.get("overall") or "").strip()
    suggestions = data.get("suggestions") or []
    if isinstance(suggestions, list) and suggestions:
        feedback += "\n改进建议：\n" + "\n".join(f"- {s}" for s in suggestions[:6])
    cite = str(data.get("cite_quote") or "").strip()
    if cite:
        feedback += f"\n\n依据原文：「{cite[:300]}」"
    return total, dims, feedback


async def _grade_question(
    db: AsyncSession,
    kb: KnowledgeBase,
    q: StudyQuestion,
    selected_index: int,
    selected_indexes: list[int],
    text: str,
    dimensions: list[dict] | None = None,
) -> dict:
    qtype = q.question_type or "single_choice"
    if qtype in OBJECTIVE_TYPES:
        return _grade_objective(q, selected_index, selected_indexes, text)
    if not text.strip():
        return {
            "correct": False,
            "ratio": 0.0,
            "correct_index": -1,
            "correct_indexes": [],
            "correct_answer": (q.answer_json or {}).get("reference_answer", ""),
            "explanation": "未作答。",
            "dimensions": [],
            "grading_method": "rule",
        }
    page = await _page_for_question(db, q)
    try:
        ratio, dims, feedback = await _llm_subjective_grade(
            db, kb, q, text, page, dimensions
        )
        method = "llm"
    except StudyEngineError as e:
        logger.warning("主观题 LLM 判分失败，使用降级评分：%s", e)
        ratio, dims = _heuristic_subjective_score(q, text)
        feedback = (
            "LLM 判分暂不可用，已按参考要点覆盖率给出估算分。"
            "建议对照参考答案自行复核，或稍后提交判分异议。"
        )
        method = "heuristic"
    ans = q.answer_json or {}
    explanation = feedback
    if q.question_json.get("explanation"):
        explanation = f"{feedback}\n\n评分依据：{q.question_json['explanation']}"
    return {
        "correct": ratio >= 0.6,
        "ratio": ratio,
        "correct_index": -1,
        "correct_indexes": [],
        "correct_answer": str(ans.get("reference_answer") or "")[:4000],
        "explanation": explanation,
        "dimensions": dims,
        "grading_method": method,
    }


# ---------- 掌握度 / 复习 ----------
def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _legacy_fsrs_state(review: StudyReview) -> FSRSState:
    """从 ORM 行读取 FSRS 状态；旧行缺失/为空时按旧字段推导。"""

    interval = _as_float(getattr(review, "interval_days", 0.0))
    legacy_reps = _as_int(getattr(review, "repetitions", 0))
    ease = _as_float(getattr(review, "ease_factor", None), 2.5)
    stability = _as_float(getattr(review, "stability", None))
    difficulty = _as_float(getattr(review, "difficulty", None))
    review_state = str(getattr(review, "review_state", "") or "")
    if review_state not in REVIEW_STATES:
        # 迁移前写入的旧行没有 review_state：有复习记录视为 review。
        review_state = "review" if (legacy_reps > 0 or interval > 0) else "new"
    if stability <= 0 and review_state != "new":
        stability = max(interval, 1.0)
    if difficulty <= 0:
        difficulty = difficulty_from_ease(ease)
    fsrs_reps = _as_int(getattr(review, "fsrs_reps", 0))
    return FSRSState(
        stability=stability,
        difficulty=difficulty,
        reps=fsrs_reps or legacy_reps,
        lapses=_as_int(getattr(review, "lapses", 0)),
        state=review_state,
        last_rating=getattr(review, "last_rating", None),
    )


def _apply_review_schedule(
    review: StudyReview,
    ratio: float,
    difficulty: str,
    now: datetime,
    *,
    correct: bool | None = None,
) -> None:
    """按 FSRS-5 更新复习状态，并同步旧字段（ease/interval/repetitions）。"""

    state = _legacy_fsrs_state(review)
    last_reviewed = getattr(review, "last_reviewed_at", None)
    elapsed_days: float | None = None
    if last_reviewed is not None:
        try:
            elapsed_days = max(0.0, (now - last_reviewed).total_seconds() / 86400.0)
        except TypeError:
            # 旧数据可能带 naive datetime，视为无历史间隔。
            elapsed_days = None
    rating = rating_for_ratio(ratio, difficulty)
    result = fsrs_schedule(state, rating, elapsed_days=elapsed_days)

    success = result.last_rating != AGAIN
    if correct is not None:
        success = bool(correct)

    review.stability = result.stability
    review.difficulty = result.difficulty
    review.lapses = result.lapses
    review.review_state = result.state
    review.last_rating = result.last_rating
    review.fsrs_reps = result.reps
    # 旧字段保持可读：ease 由 FSRS 难度反推，repetitions 表示连续成功次数。
    review.ease_factor = round(ease_from_difficulty(result.difficulty), 2)
    review.interval_days = result.interval_days
    review.repetitions = _as_int(getattr(review, "repetitions", 0)) + 1 if success else 0
    review.last_reviewed_at = now
    review.last_correct = (
        bool(correct) if correct is not None else result.last_rating >= 3
    )
    review.due_at = now + timedelta(days=result.interval_days)


CONFIDENCE_WEIGHT = {"verified": 1.0, "unverified": 0.7, "disputed": 0.5}


async def apply_outcome(
    db: AsyncSession,
    kb_id: uuid.UUID,
    q: StudyQuestion,
    ratio: float,
    correct: bool,
) -> tuple[float, datetime]:
    """更新知识点掌握度（EMA）与复习调度，返回 (新掌握度, 下次复习时间)。"""
    profile_repo = StudyProfileRepo(db)
    profile = await profile_repo.get_or_create(kb_id)
    slug = q.topic_slug
    if not slug and q.wiki_page_id:
        page = await db.get(WikiPage, q.wiki_page_id)
        slug = page.slug if page else "general"
    slug = slug or "general"
    mastery = dict(profile.mastery or {})
    if slug in mastery:
        prev = float(mastery[slug])
    else:
        prev = {"beginner": 0.0, "foundation": 0.3, "advanced": 0.5}.get(
            profile.level_prior, 0.0
        )
    difficulty = q.difficulty or "basic"
    gain = {"basic": 0.2, "medium": 0.26, "hard": 0.32}.get(difficulty, MASTERY_GAIN)
    decay = {"basic": 0.2, "medium": 0.28, "hard": 0.35}.get(difficulty, MASTERY_DECAY)
    confidence = CONFIDENCE_WEIGHT.get(q.confidence_level or "unverified", 1.0)
    if ratio >= 0.6:
        score = prev + gain * ratio * confidence
    else:
        score = prev - decay * (1.0 - ratio) * confidence
    score = round(max(0.0, min(1.0, score)), 4)
    mastery[slug] = score
    profile.mastery = mastery
    await db.flush()

    # 知识点元数据同步
    topic = await LearningTopicRepo(db).get_by_slug(kb_id, slug)
    if topic is not None:
        topic.mastery_score = score
        topic.weak_flag = score < WEAK_THRESHOLD
        # 用户已重新学习该知识点，清除「内容已更新」提示
        topic.content_updated = False
        await db.flush()

    now = datetime.now(timezone.utc)
    review = await StudyReviewRepo(db).get_or_create(kb_id, slug, q.wiki_page_id)
    _apply_review_schedule(review, ratio, difficulty, now, correct=correct)
    await db.flush()
    return score, review.due_at


# ---------- 会话作答 ----------
async def grade_and_record(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    selected_index: int = -1,
    time_ms: int = 0,
    selected_indexes: list[int] | None = None,
    text: str = "",
) -> AnswerOut:
    """训练会话判分：客观题规则、主观题 LLM 维度评分，随后更新掌握度。"""
    async with async_session_factory() as db:
        q = await db.get(StudyQuestion, question_id)
        if q is None:
            raise StudyEngineError("题目不存在。")
        session = await StudySessionRepo(db).get(q.kb_id, session_id)
        if session is None:
            raise StudyEngineError("训练会话不存在。")

        dup = (
            await db.execute(
                select(StudyAttempt.id).where(
                    StudyAttempt.session_id == session_id,
                    StudyAttempt.question_id == question_id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise StudyEngineError("该题在本组训练中已作答。")

        kb = await db.get(KnowledgeBase, q.kb_id)
        if kb is None:
            raise StudyEngineError("知识库不存在。")
        qtype = q.question_type or "single_choice"
        indexes = sorted(set(int(i) for i in (selected_indexes or [])))
        if qtype == "multiple_choice" and indexes:
            selected_index = indexes[0]
        grade = await _grade_question(db, kb, q, selected_index, indexes, text)

        await StudyAttemptRepo(db).create(
            q.kb_id,
            session_id,
            question_id,
            grade["correct"],
            selected_index,
            time_ms,
            user_answer=text,
            llm_score=grade["ratio"] if qtype in SUBJECTIVE_TYPES else None,
            score_breakdown_json={
                "dimensions": grade["dimensions"],
                "selected_indexes": indexes if qtype == "multiple_choice" else [],
            },
            mode=session.mode or "drill",
        )
        score, due_at = await apply_outcome(
            db, q.kb_id, q, grade["ratio"], grade["correct"]
        )
        await db.commit()

        dims = [
            GradingDimension(
                key=d["key"],
                label=d["label"],
                score=d["score"],
                max_score=d["max_score"],
                comment=d.get("comment", ""),
            )
            for d in grade["dimensions"]
        ]
        max_score = 100.0 if qtype in SUBJECTIVE_TYPES else 1.0
        return AnswerOut(
            correct=grade["correct"],
            score=round(grade["ratio"] * max_score, 2),
            max_score=max_score,
            explanation=grade["explanation"],
            cite_slug=q.topic_slug,
            correct_index=grade["correct_index"],
            correct_indexes=grade["correct_indexes"],
            correct_answer=grade["correct_answer"],
            selected_index=selected_index,
            selected_indexes=indexes,
            user_answer=text,
            question_type=qtype,
            dimensions=dims,
            mastery={q.topic_slug or "general": score},
            review_due_at=due_at,
            variant_available=qtype in OBJECTIVE_TYPES,
            confidence_level=q.confidence_level or "unverified",
        )


async def finish_session(session_id: uuid.UUID) -> dict:
    """结束会话：正确率、薄弱知识点、形态建议与休息提示。"""
    async with async_session_factory() as db:
        session = await db.get(StudySession, session_id)
        if session is None:
            raise StudyEngineError("训练会话不存在。")
        attempts = list(
            (
                await db.execute(
                    select(StudyAttempt).where(StudyAttempt.session_id == session_id)
                )
            ).scalars().all()
        )
        if session.status == "completed":
            correct_count = session.correct_count or 0
            question_count = session.question_count or 0
        else:
            correct_count = sum(1 for a in attempts if a.correct)
            question_count = len(attempts)
            session.status = "completed"
            session.correct_count = correct_count
            session.question_count = question_count
            session.finished_at = datetime.now(timezone.utc)
            await db.commit()

        profile = await StudyProfileRepo(db).get_by_kb(session.kb_id)
        mastery = dict(profile.mastery or {}) if profile else {}
        accuracy = (correct_count / question_count) if question_count else 0.0

        # 本组薄弱知识点
        qids = [a.question_id for a in attempts if a.question_id]
        q_rows = (
            await db.execute(select(StudyQuestion).where(StudyQuestion.id.in_(qids)))
        ).scalars().all() if qids else []
        qmap = {q.id: q for q in q_rows}
        stats: dict[str, dict] = {}
        for a in attempts:
            q = qmap.get(a.question_id)
            slug = q.topic_slug if q else None
            if not slug:
                continue
            item = stats.setdefault(slug, {"slug": slug, "total": 0, "correct": 0})
            item["total"] += 1
            if a.correct:
                item["correct"] += 1
        weak_topics = [
            {
                "slug": slug,
                "title": slug,
                "accuracy": round(v["correct"] / v["total"], 4),
                "mastery": round(float(mastery.get(slug, 0.0)), 4),
            }
            for slug, v in sorted(stats.items(), key=lambda kv: kv[1]["correct"] / kv[1]["total"])
            if v["correct"] / v["total"] < 0.6
        ][:5]
        # 标题映射
        if weak_topics:
            title_rows = (
                await db.execute(
                    select(WikiPage.slug, WikiPage.title).where(
                        WikiPage.kb_id == session.kb_id,
                        WikiPage.slug.in_([w["slug"] for w in weak_topics]),
                    )
                )
            ).all()
            titles = dict(title_rows)
            for w in weak_topics:
                w["title"] = titles.get(w["slug"], w["slug"])

        coverage = 0.0
        total_pages = int(
            (
                await db.execute(
                    select(func.count(WikiPage.id)).where(WikiPage.kb_id == session.kb_id)
                )
            ).scalar_one()
            or 0
        )
        if total_pages:
            coverage = len(mastery) / total_pages
        recommended = "mock" if accuracy >= 0.8 and coverage >= 0.5 else "drill"

        break_hint = None
        if session.finished_at and session.created_at:
            minutes = (session.finished_at - session.created_at).total_seconds() / 60
            if minutes >= 90:
                break_hint = "本组学习已超过 90 分钟，建议起身休息 10 分钟再继续。"

        return {
            "session_id": session_id,
            "correct_count": correct_count,
            "question_count": question_count,
            "accuracy": round(accuracy, 4),
            "mastery": mastery,
            "weak_topics": weak_topics,
            "recommended_mode": recommended,
            "break_hint": break_hint,
        }


async def list_mistakes(
    db: AsyncSession,
    kb_id: uuid.UUID,
    question_type: str | None = None,
    topic_slug: str | None = None,
    limit: int = 100,
) -> tuple[list[dict], int]:
    rows = await StudyAttemptRepo(db).list_wrong(kb_id)
    page_ids = {q.wiki_page_id for _, q in rows if q.wiki_page_id}
    slug_map: dict[uuid.UUID, str] = {}
    title_map: dict[str, str] = {}
    if page_ids:
        slug_rows = (
            await db.execute(
                select(WikiPage.id, WikiPage.slug, WikiPage.title).where(
                    WikiPage.id.in_(page_ids)
                )
            )
        ).all()
        slug_map = {pid: slug for pid, slug, _ in slug_rows}
        title_map = {slug: title for _, slug, title in slug_rows}
    items = []
    for attempt, q in rows:
        qj = q.question_json or {}
        slug = q.topic_slug or slug_map.get(q.wiki_page_id) or qj.get("cite_slug", "")
        if question_type and (q.question_type or "single_choice") != question_type:
            continue
        if topic_slug and slug != topic_slug:
            continue
        ans = q.answer_json or {}
        breakdown = attempt.score_breakdown_json or {}
        items.append(
            {
                "attempt_id": attempt.id,
                "question_id": q.id,
                "question": qj.get("question", ""),
                "question_type": q.question_type or "single_choice",
                "options": qj.get("options", []),
                "correct_index": _to_int(ans.get("correct_index", qj.get("answer_index", 0)), 0),
                "correct_indexes": ans.get("correct_indexes", []),
                "selected_index": attempt.selected_index,
                "selected_indexes": breakdown.get("selected_indexes", []),
                "user_answer": attempt.user_answer or "",
                "score": (
                    round(float(attempt.llm_score) * 100, 1)
                    if attempt.llm_score is not None
                    else None
                ),
                "dimensions": breakdown.get("dimensions", []),
                "explanation": qj.get("explanation", ""),
                "cite_slug": slug,
                "cite_title": title_map.get(slug) or qj.get("topic_title", ""),
                "difficulty": q.difficulty,
                "created_at": attempt.created_at,
                "confidence_level": q.confidence_level or "unverified",
            }
        )
    return items[:limit], len(items)


# ---------- 知识点 / 掌握度 / 图谱 ----------
async def sync_learning_topics(db: AsyncSession, kb_id: uuid.UUID) -> list[LearningTopic]:
    """按 Wiki 页面同步知识点元数据（标题、摘要、内容指纹、前置关系）。"""
    pages = list(
        (
            await db.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))
        ).scalars().all()
    )
    profile = await StudyProfileRepo(db).get_by_kb(kb_id)
    mastery = dict(profile.mastery or {}) if profile else {}
    repo = LearningTopicRepo(db)
    existing = {t.slug: t for t in await repo.list_for_kb(kb_id, active_only=False)}
    by_slug: dict[str, LearningTopic] = {}
    for page in pages:
        topic = existing.get(page.slug)
        if topic is None:
            topic = LearningTopic(
                kb_id=kb_id,
                slug=page.slug,
                title=page.title,
                wiki_page_id=page.id,
            )
            db.add(topic)
        topic.wiki_page_id = page.id
        topic.title = page.title
        topic.summary = _page_body(page)[:240]
        new_hash = _content_hash(page)
        # 内容漂移只标记、不重置掌握度（README 14.2 / 知识点标识绑定规则）
        if topic.content_hash and topic.content_hash != new_hash:
            topic.content_updated = True
        frontmatter = page.frontmatter_json or {}
        topic.domain = str(
            frontmatter.get("domain")
            or frontmatter.get("category")
            or page.page_type
            or ""
        )[:120]
        topic.content_hash = new_hash
        topic.mastery_score = float(mastery.get(page.slug, 0.0))
        topic.weak_flag = page.slug in mastery and topic.mastery_score < WEAK_THRESHOLD
        topic.active = True
        by_slug[page.slug] = topic
    await db.flush()
    # 前置关系：frontmatter.prerequisites（slug 列表）→ topic id
    for page in pages:
        topic = by_slug.get(page.slug)
        if topic is None:
            continue
        prereq_slugs = (page.frontmatter_json or {}).get("prerequisites") or []
        prereq_ids = []
        if isinstance(prereq_slugs, list):
            for slug in prereq_slugs:
                target = by_slug.get(str(slug))
                if target is not None and target.id != topic.id:
                    prereq_ids.append(str(target.id))
        topic.prerequisite_topic_ids = prereq_ids
    existing_slugs = {p.slug for p in pages}
    for slug, topic in existing.items():
        if slug not in existing_slugs:
            topic.active = False
    await db.flush()
    return list(by_slug.values())


async def get_mastery(db: AsyncSession, kb_id: uuid.UUID) -> MasteryOut:
    topics = await sync_learning_topics(db, kb_id)
    profile = await StudyProfileRepo(db).get_by_kb(kb_id)
    mastery = dict(profile.mastery or {}) if profile else {}

    items = []
    for t in topics:
        score = round(float(mastery.get(t.slug, t.mastery_score or 0.0)), 4)
        items.append(
            MasteryItem(
                slug=t.slug,
                title=t.title,
                score=score,
                domain=t.domain or "",
                weak=t.slug in mastery and score < WEAK_THRESHOLD,
                prerequisites=list(t.prerequisite_topic_ids or []),
                content_updated=bool(t.content_updated),
            )
        )
    items.sort(key=lambda it: it.score)
    total = len(topics)
    mastered = sum(1 for it in items if it.score >= MASTERY_THRESHOLD)
    coverage = round(mastered / total, 4) if total else 0.0
    await db.commit()
    return MasteryOut(
        items=items,
        coverage=coverage,
        mastered_count=mastered,
        total_topics=total,
    )


async def get_learn_graph(db: AsyncSession, kb_id: uuid.UUID) -> LearnGraphOut:
    topics = await sync_learning_topics(db, kb_id)
    profile = await StudyProfileRepo(db).get_by_kb(kb_id)
    mastery = dict(profile.mastery or {}) if profile else {}
    topic_by_page = {t.wiki_page_id: t for t in topics if t.wiki_page_id}

    link_counts: dict[uuid.UUID, int] = {}
    edge_rows = (
        await db.execute(
            select(WikiLink).join(WikiPage, WikiLink.from_page_id == WikiPage.id).where(
                WikiPage.kb_id == kb_id
            )
        )
    ).scalars().all()
    for e in edge_rows:
        link_counts[e.from_page_id] = link_counts.get(e.from_page_id, 0) + 1
        link_counts[e.to_page_id] = link_counts.get(e.to_page_id, 0) + 1

    page_rows = (
        await db.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))
    ).scalars().all()
    page_type_by_id = {p.id: (p.page_type or "concept") for p in page_rows}
    review_rows = (
        await db.execute(select(StudyReview).where(StudyReview.kb_id == kb_id))
    ).scalars().all()
    review_by_slug = {r.slug: r for r in review_rows}
    now = datetime.now(timezone.utc)

    def _review_of(t: LearningTopic):
        return review_by_slug.get(t.slug)

    nodes = [
        LearnGraphNode(
            id=str(t.id),
            slug=t.slug,
            title=t.title,
            mastery=round(float(mastery.get(t.slug, t.mastery_score or 0.0)), 4),
            weak=t.slug in mastery and float(mastery.get(t.slug, 0.0)) < WEAK_THRESHOLD,
            domain=t.domain or "",
            page_type=page_type_by_id.get(t.wiki_page_id, "concept"),
            link_count=link_counts.get(t.wiki_page_id, 0),
            wiki_page_id=t.wiki_page_id,
            due=bool(
                _review_of(t)
                and _review_of(t).due_at
                and _review_of(t).due_at <= now
            ),
            due_at=_review_of(t).due_at if _review_of(t) else None,
            content_updated=bool(t.content_updated),
        )
        for t in topics
    ]
    edges: list[LearnGraphEdge] = []
    seen: set[tuple[str, str, bool]] = set()
    for e in edge_rows:
        src = topic_by_page.get(e.from_page_id)
        dst = topic_by_page.get(e.to_page_id)
        if src is None or dst is None or src.id == dst.id:
            continue
        key = (str(src.id), str(dst.id), False)
        if key not in seen:
            seen.add(key)
            edges.append(
                LearnGraphEdge(
                    source=str(src.id),
                    target=str(dst.id),
                    type=e.link_type or "reference",
                )
            )
    for t in topics:
        for prereq_id in t.prerequisite_topic_ids or []:
            key = (str(prereq_id), str(t.id), True)
            if key in seen or key[0] not in {str(x.id) for x in topics}:
                continue
            seen.add(key)
            edges.append(
                LearnGraphEdge(
                    source=str(prereq_id),
                    target=str(t.id),
                    type="prerequisite",
                    prerequisite=True,
                )
            )

    total = len(nodes)
    mastered = sum(1 for n in nodes if n.mastery >= MASTERY_THRESHOLD)
    coverage = round(mastered / total, 4) if total else 0.0
    await db.commit()
    return LearnGraphOut(nodes=nodes, edges=edges, coverage=coverage)


# ---------- 学习计划 ----------
def _weekdays_next_week(today: date) -> list[date]:
    return [today + timedelta(days=i) for i in range(14)]


async def get_study_plan(db: AsyncSession, kb_id: uuid.UUID) -> StudyPlanOut:
    profile = await StudyProfileRepo(db).get_or_create(kb_id)
    topics = await sync_learning_topics(db, kb_id)
    mastery = dict(profile.mastery or {})
    total = len(topics)
    mastered = sum(
        1 for t in topics if float(mastery.get(t.slug, 0.0)) >= MASTERY_THRESHOLD
    )
    coverage = round(mastered / total, 4) if total else 0.0

    attempt_rows = list(
        (
            await db.execute(
                select(StudyAttempt)
                .where(StudyAttempt.kb_id == kb_id)
                .order_by(StudyAttempt.created_at.desc())
                .limit(30)
            )
        ).scalars().all()
    )
    recent_accuracy = (
        round(sum(1 for a in attempt_rows if a.correct) / len(attempt_rows), 4)
        if attempt_rows
        else 0.0
    )

    weak_topics = [
        {
            "slug": t.slug,
            "title": t.title,
            "mastery": round(float(mastery.get(t.slug, 0.0)), 4),
            "domain": t.domain,
        }
        for t in topics
        if t.slug in mastery and float(mastery.get(t.slug, 0.0)) < WEAK_THRESHOLD
    ]
    weak_topics.sort(key=lambda x: x["mastery"])
    weak_topics = weak_topics[:8]

    today = datetime.now(timezone.utc).date()
    attempt_dates = {
        d.astimezone(timezone.utc).date()
        for d in (
            await db.execute(
                select(StudyAttempt.created_at)
                .where(StudyAttempt.kb_id == kb_id)
                .order_by(StudyAttempt.created_at.desc())
                .limit(400)
            )
        ).scalars().all()
    }
    cursor = today if today in attempt_dates else today - timedelta(days=1)
    streak_days = 0
    while cursor in attempt_dates:
        streak_days += 1
        cursor -= timedelta(days=1)
    due_count = int(
        (
            await db.execute(
                select(func.count(StudyReview.id)).where(
                    StudyReview.kb_id == kb_id,
                    StudyReview.due_at <= datetime.now(timezone.utc),
                )
            )
        ).scalar_one()
        or 0
    )
    days_to_target = (
        (profile.target_date - today).days if profile.target_date else None
    )
    if days_to_target is not None and days_to_target <= 14:
        phase = "sprint"
    elif coverage > 0.7:
        phase = "late"
    elif coverage >= 0.4:
        phase = "middle"
    else:
        phase = "initial"

    if profile.preferred_mode == "mock":
        suggested = "mock"
        rationale = "你已手动选择以仿真考试为主，计划按整卷训练节奏安排，并在报告中提示薄弱点。"
    elif profile.preferred_mode == "drill":
        suggested = "drill"
        rationale = "你已手动选择以渐进式训练为主，计划保留每周一次整卷检验。"
    elif phase in {"late", "sprint"}:
        suggested = "mock"
        rationale = (
            "掌握度覆盖率已达 {:.0%}，建议以仿真考试为主检验水平"
            "{}。".format(
                coverage,
                "，距目标日期不足两周，进入冲刺节奏" if phase == "sprint" else "",
            )
        )
    elif phase == "middle":
        suggested = "drill"
        rationale = "覆盖率处于 40%–70%，以渐进式训练补齐薄弱点，穿插专项练习，每周末做一次仿真。"
    else:
        suggested = "drill"
        rationale = "当前覆盖知识面尚不足 40%，先以渐进式训练建立基础，暂不急于整卷模拟。"

    # 仿真考试历史参与计划建议（最近三次已判分试卷）
    recent_exams = list(
        (
            await db.execute(
                select(MockExam)
                .where(MockExam.kb_id == kb_id, MockExam.status == "graded")
                .order_by(
                    func.coalesce(MockExam.submitted_at, MockExam.generated_at).desc()
                )
                .limit(3)
            )
        ).scalars()
    )
    exam_rates = [
        float(e.total_score or 0) / float(e.max_score)
        for e in recent_exams
        if e.max_score
    ]
    passed = sum(
        1
        for e in recent_exams
        if e.passing_score is not None
        and e.total_score is not None
        and e.total_score >= e.passing_score
    )
    exam_history = {
        "count": len(exam_rates),
        "avg_rate": round(sum(exam_rates) / len(exam_rates), 4) if exam_rates else None,
        "latest_rate": round(exam_rates[0], 4) if exam_rates else None,
        "passed": passed,
        "passing_known": sum(1 for e in recent_exams if e.passing_score is not None),
    }
    if exam_rates and not profile.preferred_mode:
        avg_rate = sum(exam_rates) / len(exam_rates)
        if avg_rate >= 0.75 and suggested == "drill" and coverage >= 0.4:
            suggested = "mock"
            rationale = (
                f"最近 {len(exam_rates)} 次仿真平均得分率 {avg_rate:.0%}，"
                "已具备整卷检验水平，计划转为以仿真考试为主。"
            )
        elif avg_rate < 0.5 and suggested == "mock":
            suggested = "drill"
            rationale = (
                f"最近 {len(exam_rates)} 次仿真平均得分率仅 {avg_rate:.0%}，"
                "先回到渐进式训练补齐薄弱点，再安排整卷模拟。"
            )

    focus_pool = [w["title"] for w in weak_topics] or [
        t.title for t in topics[:4]
    ] or ["知识库核心概念"]
    plan_repo = StudyPlanRepo(db)
    plan = await plan_repo.get_by_profile(profile.id)
    manual_raw = (plan.plan_json or {}).get("manual") if plan else {}
    manual = (
        {
            str(k): v
            for k, v in manual_raw.items()
            if str(k) >= today.isoformat() and isinstance(v, dict)
        }
        if isinstance(manual_raw, dict)
        else {}
    )
    week: list[PlanDay] = []
    for i, day in enumerate(_weekdays_next_week(today)):
        weekend = day.weekday() >= 5
        if phase in {"late", "sprint"}:
            mode = "mock" if (weekend and i < 7) or (suggested == "mock" and day.weekday() in (1, 6)) else "drill"
        elif phase == "middle":
            mode = "mock" if weekend and i < 7 else "drill"
        else:
            mode = "mock" if weekend and coverage >= 0.2 and i < 7 else "drill"
        focus = [focus_pool[j % len(focus_pool)] for j in range(i, i + 2)]
        minutes = profile.daily_minutes * (2 if mode == "mock" else 1)
        note = "整卷模拟 + 错题复盘" if mode == "mock" else "薄弱点渐进训练"
        entry = PlanDay(date=day, mode=mode, minutes=minutes, focus=focus, note=note)
        patch = manual.get(day.isoformat())
        if patch:
            if patch.get("mode") in {"drill", "mock"}:
                entry.mode = str(patch["mode"])
            try:
                if patch.get("minutes") is not None:
                    entry.minutes = max(5, min(600, int(patch["minutes"])))
            except (TypeError, ValueError):
                pass
            if isinstance(patch.get("focus"), list):
                entry.focus = [str(x) for x in patch["focus"] if str(x).strip()][:6]
            if isinstance(patch.get("note"), str) and patch["note"].strip():
                entry.note = patch["note"].strip()[:300]
            entry.adjusted = True
        week.append(entry)

    rationale += (
        f" 近 {len(attempt_rows)} 题正确率 {recent_accuracy:.0%}。"
        if attempt_rows
        else " 还没有作答记录，建议从一组 10 题的渐进训练开始。"
    )
    if exam_rates:
        avg_rate = sum(exam_rates) / len(exam_rates)
        passed_note = (
            f"，其中 {passed}/{exam_history['passing_known']} 次达到合格线"
            if exam_history["passing_known"]
            else ""
        )
        if len(exam_rates) >= 2:
            delta = exam_rates[0] - exam_rates[-1]
            trend_note = (
                f"，较更早一次{'提升' if delta >= 0 else '下降'} {abs(delta):.0%}"
                if abs(delta) >= 0.01
                else "，成绩基本稳定"
            )
        else:
            trend_note = ""
        rationale += (
            f" 最近 {len(exam_rates)} 次仿真平均得分率 {avg_rate:.0%}"
            f"（最近一次 {exam_rates[0]:.0%}{passed_note}{trend_note}）。"
        )
    if days_to_target is not None:
        rationale += f" 距目标日期还有 {max(0, days_to_target)} 天。"

    now = datetime.now(timezone.utc)
    payload = {
        "phase": phase,
        "suggested_mode": suggested,
        "coverage": coverage,
        "accuracy_trend": recent_accuracy,
        "days_to_target": days_to_target,
        "weak_topics": weak_topics,
        "week": [d.model_dump(mode="json") for d in week],
        "rationale": rationale,
        "streak_days": streak_days,
        "due_count": due_count,
        "exam_history": exam_history,
        "manual": manual,
    }
    if plan is None:
        plan = StudyPlan(
            profile_id=profile.id,
            kb_id=kb_id,
            phase=phase,
            suggested_mode=suggested,
            plan_json=payload,
            computed_at=now,
        )
        db.add(plan)
    else:
        plan.phase = phase
        plan.suggested_mode = suggested
        plan.plan_json = payload
        plan.computed_at = now
    await db.commit()

    return StudyPlanOut(computed_at=now, **{k: v for k, v in payload.items()})


async def adjust_study_plan(
    db: AsyncSession, kb_id: uuid.UUID, payload: PlanAdjustIn
) -> StudyPlanOut:
    """手动调整未来 14 天计划；调整过的日期在后续重算时保持。"""
    profile = await StudyProfileRepo(db).get_or_create(kb_id)
    plan = await StudyPlanRepo(db).get_by_profile(profile.id)
    if plan is None:
        await get_study_plan(db, kb_id)
        plan = await StudyPlanRepo(db).get_by_profile(profile.id)
    if plan is None:
        raise StudyEngineError("学习计划尚未生成。")
    manual = dict((plan.plan_json or {}).get("manual") or {})
    key = payload.date.isoformat()
    if payload.clear:
        manual.pop(key, None)
    else:
        patch: dict = {"mode": payload.mode}
        if payload.minutes is not None:
            patch["minutes"] = payload.minutes
        if payload.focus is not None:
            patch["focus"] = [str(x).strip() for x in payload.focus if str(x).strip()][:6]
        if payload.note is not None:
            patch["note"] = payload.note.strip()[:300]
        manual[key] = patch
    plan.plan_json = {**(plan.plan_json or {}), "manual": manual}
    await db.commit()
    return await get_study_plan(db, kb_id)


async def build_weak_topic_drill(kb_id: uuid.UUID) -> QuestionOut:
    """针对计划中的薄弱点直接开始训练：把薄弱 slug 临时写入关注点。"""
    async with async_session_factory() as db:
        profile = await StudyProfileRepo(db).get_or_create(kb_id)
        topics = await sync_learning_topics(db, kb_id)
        mastery = dict(profile.mastery or {})
        weak = sorted(
            [
                t
                for t in topics
                if t.slug in mastery and float(mastery.get(t.slug, 0.0)) < WEAK_THRESHOLD
            ],
            key=lambda t: float(mastery.get(t.slug, 0.0)),
        )
        if weak:
            profile.topics_focus = [weak[0].slug]
            await db.commit()
    return await generate_drill_question(kb_id, "drill")
