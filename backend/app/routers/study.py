"""学习模式路由：画像 / 冷启动 / 模板 / 训练 / 仿真考试 / 计划 / 图谱 / 批注。"""

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    KnowledgeBase,
    LearningAnnotation,
    LearningTopic,
    Note,
    StudyAttempt,
    StudyQuestion,
    StudySession,
    WikiPage,
)
from app.db.session import get_session
from app.repositories import (
    ExamTemplateRepo,
    LearningAnnotationRepo,
    StudyAttemptRepo,
    StudyProfileRepo,
    StudyReviewRepo,
    StudySessionRepo,
)
from app.schemas.study import (
    ActiveSessionOut,
    AnnotationIn,
    AnnotationOut,
    AnnotationUpdate,
    AnswerIn,
    AnswerOut,
    ExamTemplateIn,
    ExamTemplateOut,
    FinishOut,
    LearnGraphOut,
    LearningTopicOut,
    MasteryOut,
    MistakeListOut,
    MistakeOut,
    MockExamAnswerIn,
    MockExamDetail,
    MockExamGenerateIn,
    MockExamReport,
    MockExamSummary,
    OnboardingCompleteIn,
    OnboardingTurnIn,
    OnboardingTurnOut,
    PlanAdjustIn,
    QuestionFeedbackIn,
    QuestionFeedbackOut,
    QuestionOut,
    ReviewDueOut,
    ReviewItemOut,
    SessionStartOut,
    StudyPlanOut,
    StudyProfileIn,
    StudyProfileOut,
    TopicNoteOut,
)
from app.services import mock_exam as mock_service
from app.services.study_engine import (
    WEAK_THRESHOLD,
    StudyEngineError,
    _page_for_question,
    _question_out,
    adjust_study_plan,
    build_weak_topic_drill,
    finish_session,
    generate_drill_question,
    generate_drill_question_for_session,
    generate_variant,
    get_learn_graph,
    get_mastery,
    get_study_plan,
    grade_and_record,
    list_exam_templates,
    list_mistakes,
    sync_learning_topics,
)
from app.services.study_onboarding import complete_onboarding, onboarding_turn
from app.services.web_research import research_question

async def _require_learning_enabled(
    kb_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> None:
    """知识库可关闭学习模式；关闭后拒绝学习接口，避免前端误入。"""
    if kb_id is None:
        return
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is not None and not kb.learning_enabled:
        raise HTTPException(403, "该知识库未开启学习模式，仅用于记录与检索")


router = APIRouter(
    prefix="/api/study", tags=["study"], dependencies=[Depends(_require_learning_enabled)]
)


# ---------- 画像 ----------
@router.get("/profile", response_model=StudyProfileOut | None)
async def get_profile(
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    return await StudyProfileRepo(session).get_by_kb(kb_id)


@router.put("/profile", response_model=StudyProfileOut)
async def put_profile(
    payload: StudyProfileIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    repo = StudyProfileRepo(session)
    profile = await repo.get_or_create(kb_id)
    profile.goal_type = payload.goal_type
    profile.level_prior = payload.level_prior
    profile.daily_minutes = payload.daily_minutes
    profile.topics_focus = list(payload.topics_focus)
    profile.exam_template_id = payload.exam_template_id
    profile.target_date = payload.target_date
    profile.preferred_mode = payload.preferred_mode
    profile.weak_areas = list(payload.weak_areas)
    if payload.profile_json:
        profile.profile_json = dict(payload.profile_json)
    if payload.onboarded is not None:
        profile.onboarded = payload.onboarded
    profile.status = "active"
    await session.flush()
    await session.commit()
    await session.refresh(profile)
    return profile


# ---------- 冷启动 ----------
@router.post("/onboarding/turn", response_model=OnboardingTurnOut)
async def onboarding_turn_api(
    payload: OnboardingTurnIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await onboarding_turn(session, kb_id, payload)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/onboarding/complete", response_model=StudyProfileOut)
async def onboarding_complete_api(
    payload: OnboardingCompleteIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await complete_onboarding(session, kb_id, payload)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


# ---------- 考试场景模板 ----------
@router.get("/exam-templates", response_model=list[ExamTemplateOut])
async def exam_templates(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await list_exam_templates(session, kb_id)


def _validate_template_sections(payload: ExamTemplateIn) -> None:
    if not payload.question_types:
        raise HTTPException(400, "至少需要配置一种题型。")
    from app.services.study_engine import QUESTION_TYPE_LABELS

    for item in payload.question_types:
        if not isinstance(item, dict):
            raise HTTPException(400, "题型配置必须是对象。")
        if item.get("type") not in QUESTION_TYPE_LABELS:
            raise HTTPException(400, f"未知题型：{item.get('type')}")
        if int(item.get("count", 0)) < 0 or float(item.get("score", 0)) < 0:
            raise HTTPException(400, "题型数量与分值不能为负。")


@router.post("/exam-templates", response_model=ExamTemplateOut, status_code=201)
async def create_exam_template(
    payload: ExamTemplateIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    _validate_template_sections(payload)
    code = (payload.code or "").strip()
    if not code:
        code = f"custom_{uuid.uuid4().hex[:8]}"
    existing = await ExamTemplateRepo(session).list_for_kb(kb_id)
    if any(t.kb_id == kb_id and t.code == code for t in existing):
        raise HTTPException(400, "模板 code 已存在，请换一个。")
    from app.db.models import ExamTemplate

    row = ExamTemplate(
        kb_id=kb_id,
        name=payload.name,
        code=code,
        description=payload.description,
        is_builtin=False,
        question_types_json=payload.question_types,
        scoring_rules_json=payload.scoring_rules,
        passing_criteria_json=payload.passing_criteria,
        duration_minutes=payload.duration_minutes,
        difficulty_distribution=payload.difficulty_distribution,
        coverage_domains=payload.coverage_domains,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/exam-templates/{template_id}", response_model=ExamTemplateOut)
async def update_exam_template(
    template_id: uuid.UUID,
    payload: ExamTemplateIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    _validate_template_sections(payload)
    row = await ExamTemplateRepo(session).get_for_kb(kb_id, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在。")
    if row.is_builtin:
        raise HTTPException(400, "内置模板不可修改，请复制后自定义。")
    row.name = payload.name
    row.description = payload.description
    row.question_types_json = payload.question_types
    row.scoring_rules_json = payload.scoring_rules
    row.passing_criteria_json = payload.passing_criteria
    row.duration_minutes = payload.duration_minutes
    row.difficulty_distribution = payload.difficulty_distribution
    row.coverage_domains = payload.coverage_domains
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/exam-templates/{template_id}", status_code=204)
async def delete_exam_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    row = await ExamTemplateRepo(session).get_for_kb(kb_id, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在。")
    if row.is_builtin:
        raise HTTPException(400, "内置模板不可删除。")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


# ---------- 训练会话 ----------
@router.post("/sessions", response_model=SessionStartOut)
async def start_session(
    kb_id: uuid.UUID,
    mode: str = Query(default="drill", pattern="^(drill|review)$"),
    question_type: str | None = Query(default=None),
    topic_slug: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    try:
        question = await generate_drill_question(kb_id, mode, question_type, topic_slug)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    sess = await StudySessionRepo(session).create(
        kb_id, mode, topic_slug=topic_slug, last_question_id=question.id
    )
    await session.commit()
    return SessionStartOut(session_id=sess.id, mode=mode, question=question)


@router.post("/sessions/weak", response_model=SessionStartOut)
async def start_weak_session(
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """从学习计划/整卷报告直接针对薄弱点开始训练。"""
    try:
        question = await build_weak_topic_drill(kb_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    sess = await StudySessionRepo(session).create(
        kb_id, "drill", last_question_id=question.id
    )
    await session.commit()
    return SessionStartOut(session_id=sess.id, mode="drill", question=question)


@router.get("/sessions/active", response_model=ActiveSessionOut | None)
async def active_session(
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    sess = await StudySessionRepo(session).get_latest_active(kb_id)
    if sess is None:
        return None
    correct, total = await StudyAttemptRepo(session).counts_for_session(sess.id)
    pending = None
    if sess.last_question_id is not None:
        answered = (
            await session.execute(
                select(StudyAttempt.id).where(
                    StudyAttempt.session_id == sess.id,
                    StudyAttempt.question_id == sess.last_question_id,
                )
            )
        ).scalar_one_or_none()
        if answered is None:
            q = await session.get(StudyQuestion, sess.last_question_id)
            if q is not None:
                page = await _page_for_question(session, q)
                pending = _question_out(
                    q,
                    page.slug if page else None,
                    page.title if page else None,
                )
    return ActiveSessionOut(
        session_id=sess.id,
        mode=sess.mode or "drill",
        answered_count=total,
        correct_count=correct,
        question=pending,
    )


@router.post("/sessions/{session_id}/questions", response_model=QuestionOut)
async def next_question(
    session_id: uuid.UUID,
    question_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    attempts = (
        await session.execute(
            select(StudyAttempt.question_id).where(StudyAttempt.session_id == session_id)
        )
    ).scalars().all()
    used: list[str] = []
    used_stems: list[str] = []
    if attempts:
        rows = (
            await session.execute(
                select(StudyQuestion.fingerprint, StudyQuestion.question_json).where(
                    StudyQuestion.id.in_(attempts)
                )
            )
        ).all()
        used = [fp for fp, _ in rows]
        used_stems = [
            (qj or {}).get("question", "") for _, qj in rows if (qj or {}).get("question")
        ]
    try:
        question = await generate_drill_question_for_session(
            session_id, used, used_stems, question_type
        )
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    sess = await session.get(StudySession, session_id)
    if sess is not None:
        sess.last_question_id = question.id
        await session.commit()
    return question


@router.post("/sessions/{session_id}/answer", response_model=AnswerOut)
async def answer(
    session_id: uuid.UUID,
    payload: AnswerIn,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await grade_and_record(
            session_id,
            payload.question_id,
            payload.selected_index,
            payload.time_ms,
            payload.selected_indexes,
            payload.text,
        )
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    sess = await session.get(StudySession, session_id)
    if sess is not None and sess.last_question_id == payload.question_id:
        sess.last_question_id = None
        await session.commit()
    return result


@router.post("/sessions/{session_id}/finish", response_model=FinishOut)
async def finish(session_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    try:
        return await finish_session(session_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


# ---------- 题目附加动作 ----------
@router.post("/questions/{question_id}/variant", response_model=QuestionOut)
async def question_variant(
    question_id: uuid.UUID,
    kb_id: uuid.UUID,
    question_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await generate_variant(kb_id, question_id, question_type)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/questions/{question_id}/feedback", response_model=QuestionFeedbackOut)
async def question_feedback(
    question_id: uuid.UUID,
    payload: QuestionFeedbackIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = await session.get(StudyQuestion, question_id)
    if q is None or q.kb_id != kb_id:
        raise HTTPException(404, "题目不存在。")
    qj = dict(q.question_json or {})
    feedback = list(qj.get("feedback") or [])
    feedback.append(
        {
            "kind": payload.kind,
            "detail": payload.detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    qj["feedback"] = feedback
    q.question_json = qj
    q.cache_status = "invalid"
    if payload.kind == "source":
        await research_question(session, kb_id, q)
    await session.commit()
    return QuestionFeedbackOut(
        ok=True,
        cache_invalidated=True,
        message="已记录反馈，题目缓存已失效，下次会重新生成。",
    )


@router.post("/questions/{question_id}/verify", response_model=QuestionOut)
async def question_verify(
    question_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = await session.get(StudyQuestion, question_id)
    if q is None or q.kb_id != kb_id:
        raise HTTPException(404, "题目不存在。")
    await research_question(session, kb_id, q)
    page = await _page_for_question(session, q)
    await session.commit()
    from app.services.study_engine import _question_out

    return _question_out(q, page.slug if page else None, page.title if page else None)


# ---------- 仿真考试 ----------
@router.post("/mock-exams", response_model=MockExamSummary, status_code=201)
async def create_mock_exam_api(
    payload: MockExamGenerateIn,
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        exam = await mock_service.create_mock_exam(session, kb_id, payload)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(mock_service.generate_mock_exam_task, exam.id)
    return exam


@router.get("/mock-exams", response_model=list[MockExamSummary])
async def list_mock_exams_api(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await mock_service.list_mock_exams(session, kb_id)


@router.get("/mock-exams/{exam_id}", response_model=MockExamDetail)
async def mock_exam_detail(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        detail = await mock_service.get_mock_exam_detail(session, kb_id, exam_id)
    except Exception as e:
        raise HTTPException(404, f"试卷不存在：{e}") from e
    if detail.status == "grading":
        background.add_task(mock_service.grade_mock_exam_task, exam_id)
    return detail


@router.post("/mock-exams/{exam_id}/start", response_model=MockExamSummary)
async def start_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await mock_service.start_mock_exam(session, kb_id, exam_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/mock-exams/{exam_id}/pause", response_model=MockExamSummary)
async def pause_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """切出学习模式时暂停计时（README 4.6）。"""
    return await mock_service.pause_mock_exam(session, kb_id, exam_id)


@router.post("/mock-exams/{exam_id}/resume", response_model=MockExamSummary)
async def resume_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """回到学习模式时继续计时。"""
    return await mock_service.resume_mock_exam(session, kb_id, exam_id)


@router.patch("/mock-exams/{exam_id}/items/{item_id}")
async def save_mock_answer_api(
    exam_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: MockExamAnswerIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        await mock_service.save_mock_answer(
            session,
            kb_id,
            exam_id,
            item_id,
            payload.selected_index,
            payload.selected_indexes,
            payload.text,
            payload.time_spent_seconds,
        )
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.post("/mock-exams/{exam_id}/submit", response_model=MockExamSummary)
async def submit_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        exam = await mock_service.submit_mock_exam(session, kb_id, exam_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    if exam.status == "grading":
        background.add_task(mock_service.grade_mock_exam_task, exam.id)
    return exam


@router.get("/mock-exams/{exam_id}/report", response_model=MockExamReport)
async def mock_exam_report(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await mock_service.get_mock_exam_report(session, kb_id, exam_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/mock-exams/{exam_id}/retry", response_model=MockExamSummary)
async def retry_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        exam = await mock_service.retry_mock_exam(session, kb_id, exam_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(mock_service.generate_mock_exam_task, exam.id)
    return exam


@router.post("/mock-exams/{exam_id}/retake", response_model=MockExamSummary)
async def retake_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        exam = await mock_service.retake_mock_exam(session, kb_id, exam_id)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(mock_service.generate_mock_exam_task, exam.id)
    return exam


@router.delete("/mock-exams/{exam_id}", status_code=204)
async def delete_mock_exam_api(
    exam_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        await mock_service.delete_mock_exam(session, kb_id, exam_id)
    except Exception as e:
        raise HTTPException(400, f"删除失败：{e}") from e
    return Response(status_code=204)


# ---------- 错题本 / 复习 / 掌握度 ----------
@router.get("/mistakes", response_model=MistakeListOut)
async def mistakes(
    kb_id: uuid.UUID,
    question_type: str | None = Query(default=None),
    topic_slug: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
):
    items, total = await list_mistakes(session, kb_id, question_type, topic_slug, limit)
    return MistakeListOut(total=total, items=[MistakeOut(**i) for i in items])


@router.get("/reviews/due", response_model=ReviewDueOut)
async def due_reviews(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    repo = StudyReviewRepo(session)
    rows = await repo.list_due(kb_id, now)
    profile = await StudyProfileRepo(session).get_by_kb(kb_id)
    mastery_map = dict(profile.mastery or {}) if profile else {}
    topic_rows = (
        await session.execute(
            select(LearningTopic).where(LearningTopic.kb_id == kb_id)
        )
    ).scalars().all()
    topic_map = {t.slug: t for t in topic_rows}
    items = [
        ReviewItemOut(
            slug=review.slug,
            title=topic_map[review.slug].title if review.slug in topic_map else (page.title if page else review.slug),
            mastery=round(float(mastery_map.get(review.slug, 0.0)), 4),
            due_at=review.due_at,
            interval_days=review.interval_days,
            repetitions=review.repetitions,
            domain=(topic_map[review.slug].domain or "") if review.slug in topic_map else "",
            content_updated=bool(topic_map[review.slug].content_updated) if review.slug in topic_map else False,
        )
        for review, page in rows
    ]
    next_due = None if items else await repo.next_due_at(kb_id, now)
    return ReviewDueOut(total=len(items), items=items, next_due_at=next_due)


@router.get("/mastery", response_model=MasteryOut)
async def mastery(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await get_mastery(session, kb_id)


@router.get("/topics", response_model=list[LearningTopicOut])
async def topics(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """知识点列表：供笔记「关联知识点」块挑选。"""
    rows = await sync_learning_topics(session, kb_id)
    profile = await StudyProfileRepo(session).get_by_kb(kb_id)
    mastery_map = dict(profile.mastery or {}) if profile else {}
    await session.commit()
    items = [
        LearningTopicOut(
            id=topic.id,
            slug=topic.slug,
            title=topic.title,
            domain=topic.domain or "",
            mastery=round(float(mastery_map.get(topic.slug, topic.mastery_score or 0.0)), 4),
            weak=(
                topic.slug in mastery_map
                and float(mastery_map.get(topic.slug, 0.0)) < WEAK_THRESHOLD
            ),
            wiki_page_id=topic.wiki_page_id,
        )
        for topic in rows
        if topic.active
    ]
    items.sort(key=lambda item: item.mastery)
    return items


TOPIC_MARKER_RE = re.compile(r"#kiwi-topic-[0-9a-fA-F-]{36}")
MAX_TOPIC_NOTE_CHARS = 2000


def _topic_note_excerpt(body_md: str, marker: str) -> str:
    """从笔记 Markdown 中提取包含知识点标记的引用块正文。"""
    blocks = re.split(r"\n\s*\n", body_md or "")
    parts: list[str] = []
    for block in blocks:
        if marker not in block:
            continue
        lines: list[str] = []
        for raw in block.splitlines():
            line = raw[1:].lstrip() if raw.startswith(">") else raw
            if not line.strip():
                lines.append("")
                continue
            if line.startswith("[!TIP]"):
                continue
            if marker in line:
                continue
            lines.append(line)
        text = "\n".join(lines).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)[:MAX_TOPIC_NOTE_CHARS]


async def _load_topic_notes(
    session: AsyncSession, kb_id: uuid.UUID, topic: LearningTopic
) -> list[TopicNoteOut]:
    marker = f"#kiwi-topic-{topic.id}"
    rows = (
        (
            await session.execute(
                select(Note)
                .where(Note.kb_id == kb_id, Note.body_md.contains(marker))
                .order_by(Note.updated_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [
        TopicNoteOut(
            note_id=note.id,
            title=note.title or "无标题笔记",
            excerpt=_topic_note_excerpt(note.body_md or "", marker),
            updated_at=note.updated_at,
        )
        for note in rows
        if TOPIC_MARKER_RE.search(note.body_md or "")
    ]


# 训练题只携带 topic_slug，按 slug 提供同一份「我的笔记」。
# 必须声明在 /topics/{topic_id}/notes 之前，避免被 UUID 路径抢先匹配。
@router.get("/topics/by-slug/{topic_slug}/notes", response_model=list[TopicNoteOut])
async def topic_notes_by_slug(
    topic_slug: str,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    topic = (
        await session.execute(
            select(LearningTopic).where(
                LearningTopic.kb_id == kb_id, LearningTopic.slug == topic_slug
            )
        )
    ).scalars().first()
    if topic is None:
        raise HTTPException(404, "知识点不存在。")
    return await _load_topic_notes(session, kb_id, topic)


@router.get("/topics/{topic_id}/notes", response_model=list[TopicNoteOut])
async def topic_notes(
    topic_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """知识点关联的学习笔记：复习时作为「我的笔记」引用。"""
    topic = await session.get(LearningTopic, topic_id)
    if topic is None or topic.kb_id != kb_id:
        raise HTTPException(404, "知识点不存在。")
    return await _load_topic_notes(session, kb_id, topic)


@router.get("/graph", response_model=LearnGraphOut)
async def learn_graph(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await get_learn_graph(session, kb_id)


@router.get("/plan", response_model=StudyPlanOut)
async def study_plan(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await get_study_plan(session, kb_id)


@router.patch("/plan", response_model=StudyPlanOut)
async def adjust_plan(
    kb_id: uuid.UUID,
    payload: PlanAdjustIn,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await adjust_study_plan(session, kb_id, payload)
    except StudyEngineError as e:
        raise HTTPException(400, str(e)) from e


# ---------- 个人批注 ----------
@router.get("/annotations", response_model=list[AnnotationOut])
async def annotations(
    kb_id: uuid.UUID,
    target_type: str | None = Query(default=None, pattern="^(wiki|note|question)$"),
    target_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
):
    repo = LearningAnnotationRepo(session)
    if target_type and target_id:
        rows = await repo.list_for_target(kb_id, target_type, target_id)
    else:
        stmt = select(LearningAnnotation).where(LearningAnnotation.kb_id == kb_id)
        if target_type:
            stmt = stmt.where(LearningAnnotation.target_type == target_type)
        if target_id:
            stmt = stmt.where(LearningAnnotation.target_id == target_id)
        stmt = stmt.order_by(LearningAnnotation.created_at.desc()).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
    return rows


async def _validate_annotation_target(
    session: AsyncSession,
    kb_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
) -> None:
    if target_type == "wiki":
        page = await session.get(WikiPage, target_id)
        if page is None or page.kb_id != kb_id:
            raise HTTPException(404, "Wiki 页面不存在。")
    elif target_type == "note":
        note = await session.get(Note, target_id)
        if note is None or note.kb_id != kb_id:
            raise HTTPException(404, "笔记不存在。")
    elif target_type == "question":
        q = await session.get(StudyQuestion, target_id)
        if q is None or q.kb_id != kb_id:
            raise HTTPException(404, "题目不存在。")


@router.post("/annotations", response_model=AnnotationOut, status_code=201)
async def create_annotation(
    payload: AnnotationIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _validate_annotation_target(
        session, kb_id, payload.target_type, payload.target_id
    )
    row = LearningAnnotation(
        kb_id=kb_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        content_md=payload.content_md,
        quote=payload.quote,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
async def update_annotation(
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await LearningAnnotationRepo(session).get(kb_id, annotation_id)
    except Exception as e:
        raise HTTPException(404, "批注不存在。") from e
    row.content_md = payload.content_md
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await LearningAnnotationRepo(session).get(kb_id, annotation_id)
    except Exception as e:
        raise HTTPException(404, "批注不存在。") from e
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


# ---------- 知识库学习状态（供 KB 概览展示） ----------
@router.get("/status")
async def study_status(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    profile = await StudyProfileRepo(session).get_by_kb(kb_id)
    from sqlalchemy import func

    page_count = int(
        (
            await session.execute(
                select(func.count(WikiPage.id)).where(WikiPage.kb_id == kb_id)
            )
        ).scalar_one()
        or 0
    )
    reviews = await StudyReviewRepo(session).list_due(kb_id, datetime.now(timezone.utc))
    mastery = dict(profile.mastery or {}) if profile else {}
    kb = await session.get(KnowledgeBase, kb_id)
    return {
        "kb_id": str(kb_id),
        "kb_name": kb.name if kb else "",
        "onboarded": bool(profile.onboarded) if profile else False,
        "goal_type": profile.goal_type if profile else None,
        "daily_minutes": profile.daily_minutes if profile else None,
        "target_date": profile.target_date.isoformat() if profile and profile.target_date else None,
        "page_count": page_count,
        "attempted_topics": len(mastery),
        "due_reviews": len(reviews),
        "mastered_topics": sum(1 for v in mastery.values() if float(v) >= 0.7),
    }
