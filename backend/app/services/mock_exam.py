"""仿真考试：按模板组卷、锁定试卷、交卷统一判分与整卷分析。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    KnowledgeBase,
    LearningTopic,
    MockExam,
    MockExamItem,
    StudyAttempt,
    StudyQuestion,
    WikiPage,
)
from app.db.session import async_session_factory
from app.repositories import (
    ExamTemplateRepo,
    MockExamItemRepo,
    MockExamRepo,
    StudyAttemptRepo,
    StudyProfileRepo,
)
from app.schemas.study import (
    MockExamDetail,
    MockExamGenerateIn,
    MockExamItemOut,
    MockExamReport,
    MockExamReportSection,
    MockExamSummary,
)
from app.services.study_engine import (
    DIFFICULTY_CYCLE,
    OBJECTIVE_TYPES,
    QUESTION_TYPE_LABELS,
    StudyEngineError,
    _call_llm_questions,
    _grade_question,
    _save_question,
    apply_outcome,
)
from app.services.web_research import maybe_research_question

logger = __import__("logging").getLogger(__name__)


def _summary(exam: MockExam) -> MockExamSummary:
    return MockExamSummary.model_validate(exam)


def _difficulty_for_index(distribution: dict | None, index: int) -> str:
    dist = distribution or {"basic": 0.4, "medium": 0.4, "hard": 0.2}
    slots: list[str] = []
    for diff in DIFFICULTY_CYCLE:
        try:
            weight = float(dist.get(diff, 0))
        except (TypeError, ValueError):
            weight = 0.0
        slots.extend([diff] * max(1, round(weight * 10)))
    return slots[index % len(slots)] if slots else DIFFICULTY_CYCLE[index % 3]


async def create_mock_exam(
    db: AsyncSession,
    kb_id: uuid.UUID,
    payload: MockExamGenerateIn,
) -> MockExam:
    template = await ExamTemplateRepo(db).get_for_kb(kb_id, payload.exam_template_id)
    if template is None:
        raise StudyEngineError("考试模板不存在或不属于当前知识库。")
    sections = [
        s
        for s in (template.question_types_json or [])
        if isinstance(s, dict) and s.get("type") in QUESTION_TYPE_LABELS
    ]
    if not sections:
        raise StudyEngineError("该考试模板没有有效题型配置。")
    max_score = 0.0
    question_count = 0
    for sec in sections:
        count = max(0, int(sec.get("count", 0)))
        score = float(sec.get("score", 1))
        question_count += count
        max_score += count * score
    if question_count <= 0:
        raise StudyEngineError("该考试模板题量为 0，无法组卷。")

    profile = await StudyProfileRepo(db).get_by_kb(kb_id)
    passing = (template.passing_criteria_json or {}).get("total")
    title = payload.title or f"{template.name} 模拟卷 {datetime.now(timezone.utc):%m-%d %H:%M}"
    exam = MockExam(
        kb_id=kb_id,
        profile_id=profile.id if profile else None,
        exam_template_id=template.id,
        title=title,
        status="generating",
        duration_minutes=template.duration_minutes,
        question_count=question_count,
        max_score=round(max_score, 2),
        passing_score=float(passing) if passing is not None else None,
        template_snapshot_json={
            "name": template.name,
            "code": template.code,
            "description": template.description,
            "question_types": sections,
            "scoring_rules": template.scoring_rules_json or {},
            "passing_criteria": template.passing_criteria_json or {},
            "duration_minutes": template.duration_minutes,
            "difficulty_distribution": template.difficulty_distribution or {},
            "coverage_domains": template.coverage_domains or [],
        },
        generation_progress=0.0,
    )
    db.add(exam)
    await db.commit()
    await db.refresh(exam)
    return exam


async def _assemble(db: AsyncSession, exam_id: uuid.UUID) -> None:
    exam = await db.get(MockExam, exam_id)
    if exam is None or exam.status != "generating":
        return
    kb = await db.get(KnowledgeBase, exam.kb_id)
    if kb is None:
        raise StudyEngineError("知识库不存在。")
    snapshot = exam.template_snapshot_json or {}
    sections = [
        s
        for s in (snapshot.get("question_types") or [])
        if isinstance(s, dict) and s.get("type") in QUESTION_TYPE_LABELS
    ]
    pages = [
        p
        for p in (
            await db.execute(select(WikiPage).where(WikiPage.kb_id == exam.kb_id))
        ).scalars().all()
        if len((p.body_md or "").strip()) >= 40
    ]
    if not pages:
        raise StudyEngineError("知识库没有可出题的 Wiki 页面，无法组卷。")
    pages.sort(key=lambda p: (p.page_type or "", p.slug))

    # 覆盖度检查：优先从模板要求的知识域中轮转选页，避免整卷集中在少数页面
    topic_rows = (
        await db.execute(select(LearningTopic).where(LearningTopic.kb_id == exam.kb_id))
    ).scalars().all()
    domain_by_slug = {
        t.slug: (t.domain or "").strip() for t in topic_rows if t.domain
    }
    requested_domains = [
        str(d).strip() for d in (snapshot.get("coverage_domains") or []) if str(d).strip()
    ]
    available_domains = sorted({d for d in domain_by_slug.values() if d})
    if requested_domains:
        buckets: dict[str, list[WikiPage]] = {
            d: [] for d in requested_domains
        }
        for p in pages:
            domain = domain_by_slug.get(p.slug)
            if domain in buckets:
                buckets[domain].append(p)
        balanced: list[WikiPage] = []
        indices = {d: 0 for d in requested_domains}
        while any(indices[d] < len(buckets[d]) for d in requested_domains):
            for domain in requested_domains:
                idx = indices[domain]
                if idx < len(buckets[domain]):
                    balanced.append(buckets[domain][idx])
                    indices[domain] = idx + 1
        matched_ids = {p.id for p in balanced}
        pages = balanced + [p for p in pages if p.id not in matched_ids]
    exam_coverage = {
        "requested_domains": requested_domains,
        "available_domains": available_domains,
        "covered_domains": [],
        "missing_domains": [],
        "coverage_ratio": None,
        "warnings": [],
    }

    total = sum(max(0, int(s.get("count", 0))) for s in sections)
    if total <= 0:
        raise StudyEngineError("模板题量为 0。")
    exam.question_count = total

    order = 0
    stems: list[str] = []
    selected_slugs: list[str] = []
    for section_index, section in enumerate(sections):
        qtype = str(section.get("type"))
        count = max(0, int(section.get("count", 0)))
        score = float(section.get("score", 1))
        section_name = str(section.get("name") or QUESTION_TYPE_LABELS.get(qtype, qtype))
        batch_size = 3 if qtype in OBJECTIVE_TYPES else 1
        made = 0
        attempts = 0
        while made < count and attempts < count * 3 + 5:
            attempts += 1
            want = min(batch_size, count - made)
            page = pages[(section_index * 7 + made) % len(pages)]
            difficulty = _difficulty_for_index(
                snapshot.get("difficulty_distribution"), order
            )
            try:
                normalized = await _call_llm_questions(
                    db, kb, page, difficulty, qtype, want, stems
                )
            except StudyEngineError as e:
                logger.warning("组卷出题失败（%s/%s）：%s", qtype, page.slug, e)
                if attempts >= 3 and made == 0:
                    raise StudyEngineError(
                        f"组卷失败：{QUESTION_TYPE_LABELS.get(qtype, qtype)}出题连续失败（{e}）。"
                    ) from e
                await asyncio.sleep(0.4)
                continue

            for norm in normalized:
                if made >= count:
                    break
                fp = f"mock:{exam.id}:{order}"
                q = await _save_question(
                    db,
                    exam.kb_id,
                    page,
                    fp,
                    norm,
                    difficulty,
                    qtype,
                    confidence="unverified",
                )
                await maybe_research_question(db, exam.kb_id, q)
                item = MockExamItem(
                    mock_exam_id=exam.id,
                    question_id=q.id,
                    order_index=order,
                    section_type=qtype,
                    section_name=section_name,
                    score=round(score, 2),
                    feedback_json={},
                )
                db.add(item)
                stems.append(q.question_json.get("question", ""))
                selected_slugs.append(q.topic_slug or page.slug)
                order += 1
                made += 1
            exam.generation_progress = round(order / total, 4)
            await db.commit()

    warnings: list[str] = []
    if order < total:
        # 题型数量未凑齐时也允许保存已生成部分，但显式记录
        exam.question_count = order
        max_score = 0.0
        items = (
            await db.execute(
                select(MockExamItem).where(MockExamItem.mock_exam_id == exam.id)
            )
        ).scalars().all()
        max_score = sum(float(i.score) for i in items)
        exam.max_score = round(max_score, 2)
        warnings.append(f"部分题型题量不足，本卷实际生成 {order}/{total} 题。")

    covered_domains = sorted(
        {
            domain_by_slug.get(slug)
            for slug in selected_slugs
            if domain_by_slug.get(slug)
        }
    )
    missing_domains = [d for d in requested_domains if d not in covered_domains]
    if requested_domains and missing_domains:
        warnings.append(
            "知识库内容未能覆盖知识域："
            + "、".join(missing_domains)
            + "；建议先补充相应素材或 Wiki 页面。"
        )
    exam_coverage.update(
        {
            "covered_domains": covered_domains,
            "missing_domains": missing_domains,
            "coverage_ratio": (
                round(len(covered_domains) / len(requested_domains), 4)
                if requested_domains
                else None
            ),
            "warnings": list(warnings),
        }
    )
    snapshot = dict(snapshot)
    snapshot["coverage_check"] = exam_coverage
    snapshot["assembly_warnings"] = list(warnings)
    snapshot["partial"] = order < total
    exam.template_snapshot_json = snapshot
    exam.status = "ready"
    exam.generation_progress = 1.0
    exam.generated_at = datetime.now(timezone.utc)
    exam.error = None
    await db.commit()


async def generate_mock_exam_task(exam_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        try:
            await _assemble(db, exam_id)
        except Exception as e:  # 背景任务必须落错误状态，不能静默
            logger.exception("仿真试卷生成失败")
            await db.rollback()
            exam = await db.get(MockExam, exam_id)
            if exam is not None:
                exam.status = "error"
                exam.error = str(e)[:2000]
                await db.commit()


async def retry_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> MockExam:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status not in {"error", "generating"}:
        raise StudyEngineError("只有生成失败的试卷可以重新组卷。")
    await db.execute(delete(MockExamItem).where(MockExamItem.mock_exam_id == exam.id))
    exam.status = "generating"
    exam.error = None
    exam.generation_progress = 0.0
    exam.total_score = None
    exam.score_breakdown_json = {}
    await db.commit()
    await db.refresh(exam)
    return exam


async def retake_mock_exam(
    db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID
) -> MockExam:
    """基于已批阅试卷的模板快照重新组卷（README 14.4.3 支持重做）。"""
    source = await MockExamRepo(db).get(kb_id, exam_id)
    if source.status != "graded":
        raise StudyEngineError("只有已完成批阅的试卷可以重做。")
    snapshot = dict(source.template_snapshot_json or {})
    if not snapshot.get("question_types"):
        raise StudyEngineError("原卷缺少题型快照，无法重做。")
    profile = await StudyProfileRepo(db).get_by_kb(kb_id)
    exam = MockExam(
        kb_id=kb_id,
        profile_id=profile.id if profile else source.profile_id,
        exam_template_id=source.exam_template_id,
        title=f"{snapshot.get('name') or source.title} 重做 {datetime.now(timezone.utc):%m-%d %H:%M}",
        status="generating",
        duration_minutes=source.duration_minutes,
        question_count=0,
        max_score=0.0,
        passing_score=source.passing_score,
        template_snapshot_json=snapshot,
        generation_progress=0.0,
    )
    db.add(exam)
    await db.commit()
    await db.refresh(exam)
    return exam


async def delete_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> None:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    await db.delete(exam)
    await db.commit()


async def list_mock_exams(db: AsyncSession, kb_id: uuid.UUID) -> list[MockExamSummary]:
    rows = await MockExamRepo(db).list_for_kb(kb_id)
    return [_summary(r) for r in rows]


def _remaining_seconds(exam: MockExam) -> int | None:
    if exam.status != "in_progress" or exam.started_at is None:
        return None
    if exam.paused_at is not None:
        return max(0, int(exam.remaining_seconds or 0))
    end = (
        exam.started_at
        + timedelta(minutes=exam.duration_minutes)
        + timedelta(seconds=exam.paused_seconds or 0)
    )
    return max(0, int((end - datetime.now(timezone.utc)).total_seconds()))


async def maybe_auto_submit(db: AsyncSession, exam: MockExam) -> bool:
    if exam.status != "in_progress" or exam.started_at is None or exam.paused_at is not None:
        return False
    end = (
        exam.started_at
        + timedelta(minutes=exam.duration_minutes)
        + timedelta(seconds=exam.paused_seconds or 0)
    )
    now = datetime.now(timezone.utc)
    if now < end:
        return False
    exam.status = "grading"
    exam.submitted_at = end
    exam.time_spent_json = {
        **(exam.time_spent_json or {}),
        "auto_submitted": True,
        "used_seconds": int(exam.duration_minutes * 60),
    }
    await db.commit()
    return True


async def start_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> MockExam:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status == "in_progress":
        return exam
    if exam.status != "ready":
        raise StudyEngineError("试卷尚未生成完成，暂时不能开始考试。")
    exam.status = "in_progress"
    exam.started_at = datetime.now(timezone.utc)
    exam.submitted_at = None
    exam.paused_at = None
    exam.paused_seconds = 0
    exam.remaining_seconds = None
    await db.commit()
    await db.refresh(exam)
    return exam


async def pause_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> MockExam:
    """切出学习模式时暂停计时；暂停期间不会自动交卷。"""
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status != "in_progress" or exam.started_at is None:
        return exam
    if exam.paused_at is None:
        exam.remaining_seconds = _remaining_seconds(exam)
        exam.paused_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(exam)
    return exam


async def resume_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> MockExam:
    """回到学习模式时继续计时；已暂停的时长不计入考试用时。"""
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status != "in_progress" or exam.paused_at is None:
        return exam
    now = datetime.now(timezone.utc)
    paused = max(0, int((now - exam.paused_at).total_seconds()))
    exam.paused_seconds = int(exam.paused_seconds or 0) + paused
    remaining = max(0, int(exam.remaining_seconds or 0))
    # 调整起点，使有效截止时间 = 现在 + 剩余时间
    exam.started_at = now - timedelta(
        seconds=max(0, exam.duration_minutes * 60 + exam.paused_seconds - remaining)
    )
    exam.paused_at = None
    await db.commit()
    await db.refresh(exam)
    return exam


async def save_mock_answer(
    db: AsyncSession,
    kb_id: uuid.UUID,
    exam_id: uuid.UUID,
    item_id: uuid.UUID,
    selected_index: int | None,
    selected_indexes: list[int],
    text: str,
    time_spent_seconds: int,
) -> None:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status != "in_progress":
        raise StudyEngineError("考试不在进行中，无法保存作答。")
    if await maybe_auto_submit(db, exam):
        raise StudyEngineError("考试时间已到，系统已自动交卷。")
    item = await db.get(MockExamItem, item_id)
    if item is None or item.mock_exam_id != exam.id:
        raise StudyEngineError("题目不属于该试卷。")
    item.selected_index = selected_index
    item.user_answer = text
    feedback = dict(item.feedback_json or {})
    feedback["selected_indexes"] = sorted(set(int(i) for i in selected_indexes))
    feedback["time_spent_seconds"] = int(time_spent_seconds)
    item.feedback_json = feedback
    item.answered_at = datetime.now(timezone.utc)
    time_spent = dict(exam.time_spent_json or {})
    time_spent[str(item.id)] = int(time_spent_seconds)
    time_spent["total_seconds"] = sum(
        int(v) for k, v in time_spent.items() if k not in {"total_seconds", "auto_submitted", "used_seconds"}
    )
    exam.time_spent_json = time_spent
    await db.commit()


async def submit_mock_exam(db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID) -> MockExam:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status == "graded":
        return exam
    if exam.status not in {"in_progress", "grading"}:
        raise StudyEngineError("当前试卷状态不能交卷。")
    if exam.status == "in_progress":
        now = datetime.now(timezone.utc)
        paused = int(exam.paused_seconds or 0)
        if exam.paused_at is not None:
            paused += max(0, int((now - exam.paused_at).total_seconds()))
        exam.status = "grading"
        exam.submitted_at = now
        if exam.started_at:
            used = max(0, int((now - exam.started_at).total_seconds()) - paused)
            exam.time_spent_json = {
                **(exam.time_spent_json or {}),
                "used_seconds": used,
                "paused_seconds": paused,
            }
        exam.paused_at = None
        await db.commit()
        await db.refresh(exam)
    return exam


async def _item_out(
    item: MockExamItem,
    q: StudyQuestion | None,
    graded: bool,
    title_map: dict[str, str],
) -> MockExamItemOut:
    qj = (q.question_json or {}) if q else {}
    body = (q.body_json or {}) if q else {}
    feedback = dict(item.feedback_json or {})
    qtype = item.section_type or (q.question_type if q else "single_choice")
    selected_indexes = feedback.get("selected_indexes") or []
    answered = (
        item.selected_index is not None
        or bool(selected_indexes)
        or bool((item.user_answer or "").strip())
    )
    slug = q.topic_slug if q else None
    return MockExamItemOut(
        id=item.id,
        order_index=item.order_index,
        section_type=qtype,
        section_name=item.section_name,
        score=item.score,
        question_id=item.question_id,
        question=qj.get("question", "") if q else "（原题已删除）",
        options=qj.get("options", []) if q else [],
        material=body.get("material", ""),
        requirements=body.get("requirements", ""),
        min_words=body.get("min_words"),
        user_answer=item.user_answer or "",
        selected_index=item.selected_index,
        selected_indexes=selected_indexes,
        score_awarded=item.score_awarded,
        answered=answered,
        correct=(bool(feedback.get("correct")) if graded else None),
        correct_index=(feedback.get("correct_index") if graded else None),
        correct_indexes=(feedback.get("correct_indexes") or [] if graded else []),
        correct_answer=(feedback.get("correct_answer") or "" if graded else ""),
        explanation=(feedback.get("explanation") or "" if graded else ""),
        dimensions=(feedback.get("dimensions") or [] if graded else []),
        cite_slug=slug,
        cite_title=title_map.get(slug or "", ""),
        confidence_level=(q.confidence_level if q else "unverified"),
    )


async def _cite_titles(
    db: AsyncSession,
    kb_id: uuid.UUID,
    questions: dict[uuid.UUID, StudyQuestion],
) -> dict[str, str]:
    """报告里把题目引用从 slug 还原成可读标题。"""
    slugs = {
        q.topic_slug
        for q in questions.values()
        if q.topic_slug
    }
    if not slugs:
        return {}
    rows = (
        await db.execute(
            select(WikiPage.slug, WikiPage.title).where(
                WikiPage.kb_id == kb_id, WikiPage.slug.in_(slugs)
            )
        )
    ).all()
    return {slug: title for slug, title in rows}


async def _load_items(db: AsyncSession, exam_id: uuid.UUID):
    items = await MockExamItemRepo(db).list_for_exam(exam_id)
    question_ids = [i.question_id for i in items if i.question_id]
    questions: dict[uuid.UUID, StudyQuestion] = {}
    if question_ids:
        rows = (
            await db.execute(select(StudyQuestion).where(StudyQuestion.id.in_(question_ids)))
        ).scalars().all()
        questions = {q.id: q for q in rows}
    return items, questions


async def get_mock_exam_detail(
    db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID
) -> MockExamDetail:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    await maybe_auto_submit(db, exam)
    items, questions = await _load_items(db, exam.id)
    graded = exam.status == "graded"
    titles = await _cite_titles(db, kb_id, questions)
    out_items = [
        await _item_out(i, questions.get(i.question_id) if i.question_id else None, graded, titles)
        for i in items
    ]
    base = _summary(exam).model_dump()
    return MockExamDetail(
        **base,
        template=exam.template_snapshot_json or {},
        items=out_items,
        score_breakdown=exam.score_breakdown_json or {},
        time_spent=exam.time_spent_json or {},
        remaining_seconds=_remaining_seconds(exam),
    )


async def get_mock_exam_report(
    db: AsyncSession, kb_id: uuid.UUID, exam_id: uuid.UUID
) -> MockExamReport:
    exam = await MockExamRepo(db).get(kb_id, exam_id)
    if exam.status != "graded":
        raise StudyEngineError("试卷尚未批阅完成。")
    breakdown = exam.score_breakdown_json or {}
    items, questions = await _load_items(db, exam.id)
    titles = await _cite_titles(db, kb_id, questions)
    out_items = [
        await _item_out(i, questions.get(i.question_id) if i.question_id else None, True, titles)
        for i in items
    ]
    sections = [
        MockExamReportSection(**s) for s in (breakdown.get("sections") or [])
    ]
    return MockExamReport(
        exam_id=exam.id,
        title=exam.title,
        status=exam.status,
        total_score=exam.total_score,
        max_score=exam.max_score,
        passing_score=exam.passing_score,
        passed=breakdown.get("passed"),
        accuracy=breakdown.get("accuracy", 0.0),
        sections=sections,
        knowledge_points=breakdown.get("knowledge_points") or [],
        weak_topics=breakdown.get("weak_topics") or [],
        time_analysis=breakdown.get("time_analysis") or {},
        items=out_items,
        advice=breakdown.get("advice") or "",
    )


def _zero_grade(reason: str) -> dict:
    return {
        "correct": False,
        "ratio": 0.0,
        "correct_index": -1,
        "correct_indexes": [],
        "correct_answer": "",
        "explanation": reason,
        "dimensions": [],
        "grading_method": "rule",
    }


def _advice(
    total: float,
    max_score: float,
    passing: float | None,
    subject_rows: list[dict],
    weak: list[dict],
) -> str:
    weak_titles = "、".join(str(w.get("title") or w.get("slug")) for w in weak[:3])
    if passing is not None and total < passing:
        text = f"总分 {total:.0f}/{max_score:.0f}，距合格线还差 {passing - total:.0f} 分。"
        if weak_titles:
            text += f" 建议优先补强：{weak_titles}，先做针对性渐进训练，再重做整卷。"
        else:
            text += " 建议回看错题解析，按题型逐项突破。"
    elif passing is not None:
        text = f"总分 {total:.0f}/{max_score:.0f}，已达到合格线。"
        if weak_titles:
            text += f" 仍可补强：{weak_titles}，保持每周一次整卷维持手感。"
        else:
            text += " 各知识域表现均衡，建议保持整卷节奏并关注时间分配。"
    else:
        text = f"总分 {total:.0f}/{max_score:.0f}。"
        if weak_titles:
            text += f" 薄弱点集中在：{weak_titles}，建议针对薄弱点开始训练。"
    low_subjects = [
        s for s in subject_rows if s["max_score"] and s["accuracy"] < 0.6
    ]
    if low_subjects:
        names = "、".join(s["name"] for s in low_subjects[:3])
        text += f" 题型层面，{names} 得分率偏低，可做专项练习。"
    return text


async def grade_mock_exam_task(exam_id: uuid.UUID) -> None:
    """交卷后统一判分：客观题规则、主观题 LLM 维度评分，并写回掌握度。"""
    async with async_session_factory() as db:
        exam = await db.get(MockExam, exam_id)
        if exam is None or exam.status != "grading":
            return
        kb = await db.get(KnowledgeBase, exam.kb_id)
        if kb is None:
            exam.status = "error"
            exam.error = "知识库不存在。"
            await db.commit()
            return
        try:
            items, questions = await _load_items(db, exam.id)
            total = len(items) or 1
            # 模板可为每种题型配置评分维度，整卷判分时优先使用
            custom_dimensions: dict[str, list[dict]] = {}
            for sec in (exam.template_snapshot_json or {}).get("question_types") or []:
                if not isinstance(sec, dict) or not sec.get("type"):
                    continue
                dims = (sec.get("scoring") or {}).get("dimensions")
                if isinstance(dims, list) and dims:
                    custom_dimensions[str(sec["type"])] = dims
            for idx, item in enumerate(items):
                if (item.feedback_json or {}).get("graded"):
                    continue
                q = questions.get(item.question_id) if item.question_id else None
                if q is None:
                    item.feedback_json = {
                        **_zero_grade("原题已删除，按 0 分计。"),
                        "graded": True,
                        "selected_indexes": [],
                    }
                    item.score_awarded = 0.0
                    await db.commit()
                    continue
                selected_indexes = (item.feedback_json or {}).get("selected_indexes") or []
                answered = (
                    item.selected_index is not None
                    or bool(selected_indexes)
                    or bool((item.user_answer or "").strip())
                )
                if not answered:
                    grade = _zero_grade("未作答。")
                else:
                    try:
                        grade = await _grade_question(
                            db,
                            kb,
                            q,
                            item.selected_index if item.selected_index is not None else -1,
                            selected_indexes,
                            item.user_answer or "",
                            dimensions=custom_dimensions.get(q.question_type),
                        )
                    except Exception as e:  # 单题判分失败不拖垮整卷
                        logger.exception("单题判分失败 item=%s", item.id)
                        grade = _zero_grade(f"判分异常，按 0 分计：{e}")
                item.score_awarded = round(float(item.score) * float(grade["ratio"]), 2)
                time_spent = int((item.feedback_json or {}).get("time_spent_seconds", 0))
                item.feedback_json = {
                    **grade,
                    "graded": True,
                    "selected_indexes": sorted(set(int(i) for i in selected_indexes)),
                    "time_spent_seconds": time_spent,
                }

                existing = (
                    await db.execute(
                        select(StudyAttempt.id).where(
                            StudyAttempt.mock_exam_id == exam.id,
                            StudyAttempt.question_id == q.id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    await StudyAttemptRepo(db).create(
                        exam.kb_id,
                        None,
                        q.id,
                        grade["correct"],
                        item.selected_index if item.selected_index is not None else -1,
                        time_spent * 1000,
                        mock_exam_id=exam.id,
                        user_answer=item.user_answer or "",
                        llm_score=grade["ratio"] if q.question_type not in OBJECTIVE_TYPES else None,
                        score_breakdown_json={"dimensions": grade.get("dimensions", [])},
                        mode="mock",
                    )
                    await apply_outcome(
                        db, exam.kb_id, q, grade["ratio"], grade["correct"]
                    )
                exam.generation_progress = round((idx + 1) / total, 4)
                await db.commit()

            # 汇总
            items, questions = await _load_items(db, exam.id)
            profile = await StudyProfileRepo(db).get_by_kb(exam.kb_id)
            mastery = dict(profile.mastery or {}) if profile else {}
            section_map: dict[str, dict] = {}
            kp_map: dict[str, dict] = {}
            time_per_section: dict[str, int] = {}
            anomalies: list[str] = []
            total_score = 0.0
            correct_count = 0
            for item in items:
                feedback = item.feedback_json or {}
                score = float(item.score_awarded or 0.0)
                total_score += score
                if feedback.get("correct"):
                    correct_count += 1
                sec = section_map.setdefault(
                    item.section_name or item.section_type,
                    {
                        "name": item.section_name or item.section_type,
                        "type": item.section_type,
                        "question_count": 0,
                        "score": 0.0,
                        "max_score": 0.0,
                        "correct": 0,
                    },
                )
                sec["question_count"] += 1
                sec["score"] += score
                sec["max_score"] += float(item.score)
                if feedback.get("correct"):
                    sec["correct"] += 1
                q = questions.get(item.question_id) if item.question_id else None
                slug = (q.topic_slug if q else None) or "general"
                kp = kp_map.setdefault(
                    slug,
                    {
                        "slug": slug,
                        "title": slug,
                        "question_count": 0,
                        "correct_count": 0,
                        "score": 0.0,
                        "max_score": 0.0,
                    },
                )
                kp["question_count"] += 1
                kp["score"] += score
                kp["max_score"] += float(item.score)
                if feedback.get("correct"):
                    kp["correct_count"] += 1
                spent = int(feedback.get("time_spent_seconds", 0))
                time_per_section[sec["name"]] = time_per_section.get(sec["name"], 0) + spent
                if feedback.get("correct") and 0 < spent < 5:
                    anomalies.append(
                        f"第 {item.order_index + 1} 题用时仅 {spent} 秒却答对，建议自省。"
                    )
                elif spent > 360:
                    anomalies.append(f"第 {item.order_index + 1} 题耗时 {spent // 60} 分钟，注意时间分配。")

            sections = []
            for sec in section_map.values():
                sections.append(
                    {
                        "name": sec["name"],
                        "type": sec["type"],
                        "question_count": sec["question_count"],
                        "score": round(sec["score"], 2),
                        "max_score": round(sec["max_score"], 2),
                        "accuracy": round(
                            sec["correct"] / sec["question_count"], 4
                        )
                        if sec["question_count"]
                        else 0.0,
                    }
                )
            knowledge_points = []
            weak_topics = []
            for slug, kp in kp_map.items():
                kp["score"] = round(kp["score"], 2)
                kp["max_score"] = round(kp["max_score"], 2)
                kp["accuracy"] = round(
                    kp["correct_count"] / kp["question_count"], 4
                ) if kp["question_count"] else 0.0
                kp["mastery"] = round(float(mastery.get(slug, 0.0)), 4)
                topic = (
                    await db.execute(
                        select(LearningTopic).where(
                            LearningTopic.kb_id == exam.kb_id,
                            LearningTopic.slug == slug,
                        )
                    )
                ).scalars().first()
                if topic is not None:
                    kp["title"] = topic.title
                    kp["domain"] = topic.domain
                knowledge_points.append(kp)
                if kp["accuracy"] < 0.6 or kp["mastery"] < 0.4:
                    weak_topics.append(
                        {
                            "slug": slug,
                            "title": kp.get("title", slug),
                            "accuracy": kp["accuracy"],
                            "mastery": kp["mastery"],
                        }
                    )
            weak_topics.sort(key=lambda x: (x["accuracy"], x["mastery"]))
            knowledge_points.sort(key=lambda x: x["accuracy"])

            criteria = (exam.template_snapshot_json or {}).get("passing_criteria") or {}
            passed: bool | None = None
            if exam.passing_score is not None:
                passed = total_score >= exam.passing_score
                subject_min = criteria.get("subjects") or []
                section_scores = {s["name"]: s["score"] for s in sections}
                for subj in subject_min:
                    name = str(subj.get("name") or "")
                    min_score = float(subj.get("min_score", 0))
                    if name in section_scores and section_scores[name] < min_score:
                        passed = False

            used_seconds = int((exam.time_spent_json or {}).get("used_seconds", 0))
            if used_seconds <= 0 and exam.started_at and exam.submitted_at:
                used_seconds = int((exam.submitted_at - exam.started_at).total_seconds())
            if used_seconds > exam.duration_minutes * 60:
                anomalies.append("本次考试超时，系统已按实际作答自动交卷。")
            accuracy = round(correct_count / len(items), 4) if items else 0.0
            advice = _advice(
                total_score, exam.max_score, exam.passing_score, sections, weak_topics
            )
            breakdown = {
                "total": round(total_score, 2),
                "max": exam.max_score,
                "passing": exam.passing_score,
                "passed": passed,
                "accuracy": accuracy,
                "sections": sections,
                "knowledge_points": knowledge_points,
                "weak_topics": weak_topics,
                "time_analysis": {
                    "duration_minutes": exam.duration_minutes,
                    "used_minutes": round(used_seconds / 60, 1),
                    "per_section_seconds": time_per_section,
                    "anomalies": anomalies[:10],
                },
                "advice": advice,
            }
            exam.total_score = round(total_score, 2)
            exam.score_breakdown_json = breakdown
            exam.status = "graded"
            exam.generation_progress = 1.0
            await db.commit()
        except Exception as e:
            logger.exception("仿真试卷判分失败")
            await db.rollback()
            exam = await db.get(MockExam, exam_id)
            if exam is not None:
                exam.status = "error"
                exam.error = f"判分失败：{e}"[:2000]
                await db.commit()
