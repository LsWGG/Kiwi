"""学习模式实体：画像 / 场景模板 / 训练 / 仿真考试 / 掌握度 / 批注。"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class ExamTemplate(UUIDPkMixin, Base):
    """考试场景模板：题型结构、评分规则、合格标准与难度分布。

    kb_id 为 NULL 表示内置模板（全局可用）；用户自定义模板归属于某个知识库。
    """

    __tablename__ = "exam_templates"
    __table_args__ = (
        Index("ix_exam_templates_kb_code", "kb_id", "code"),
    )

    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # [{type,name,count,score,duration_minutes,scoring:{dimensions:[{key,label,weight}]}}]
    question_types_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    scoring_rules_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # {total: 45, subjects: [{name, min_score}]}
    passing_criteria_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    # {basic: 0.4, medium: 0.4, hard: 0.2}
    difficulty_distribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    coverage_domains: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    def __repr__(self) -> str:
        return f"<ExamTemplate {self.code} {self.name}>"


class StudyProfile(UUIDPkMixin, Base):
    """学习画像：每个知识库一行。

    掌握度以 mastery JSONB 聚合存储：{wiki_page_slug: 0-1 float}。
    """

    __tablename__ = "study_profiles"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    goal_type: Mapped[str] = mapped_column(
        String(20), default="domain", nullable=False
    )  # exam / domain / explore
    level_prior: Mapped[str] = mapped_column(
        String(20), default="beginner", nullable=False
    )  # beginner / foundation / advanced
    daily_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    exam_template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_mode: Mapped[str] = mapped_column(
        String(20), default="auto", nullable=False
    )  # auto / drill / mock
    # 薄弱环节 / 重点关注知识点（用户自述 + 系统推断）
    topics_focus: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    weak_areas: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # 掌握度聚合 {slug: float 0-1}
    mastery: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # 冷启动对话原文 / 补充信息
    profile_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    def __repr__(self) -> str:
        return f"<StudyProfile kb={self.kb_id}>"


class StudySession(UUIDPkMixin, Base):
    """渐进式训练会话。profile 通过 kb+时间取最近画像，不加 FK（避免迁移耦合）。"""

    __tablename__ = "study_sessions"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # drill（渐进训练）/ review（今日复习）
    mode: Mapped[str] = mapped_column(String(20), default="drill", nullable=False)
    # 针对指定 Wiki 页发起的专项训练：整组会话保持在该知识点
    topic_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 当前未作答的题目：切换模式/刷新后从原题继续（README 4.6 会话记忆）
    last_question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("study_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<StudySession {self.id}>"


class StudyQuestion(UUIDPkMixin, Base):
    """出题缓存 + 错题引源。题目以结构化 JSONB 存储。

    question_json（兼容字段）：
      {"question","options":[],"answer_index","explanation","cite_slug","difficulty"}
    body_json：主观题材料 / 作答要求 / 字数下限
    answer_json：{"reference_answer","accepted_answers":[],"rubric":[...]}
    """

    __tablename__ = "study_questions"
    __table_args__ = (
        Index("ix_study_questions_kb_type", "kb_id", "question_type"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    wiki_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="SET NULL"), nullable=True
    )
    topic_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )  # sha1 题目指纹去重
    question_type: Mapped[str] = mapped_column(
        String(30), default="single_choice", nullable=False
    )
    question_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    body_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    answer_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="basic", nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    web_sources_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # verified / unverified / disputed
    confidence_level: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    # active / invalid
    cache_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    def __repr__(self) -> str:
        return f"<StudyQuestion {self.id}>"


class StudyAttempt(UUIDPkMixin, Base):
    """作答记录：判分结果 + 掌握度更新的原始事件。"""

    __tablename__ = "study_attempts"
    __table_args__ = (
        Index("ix_study_attempts_kb_created", "kb_id", "created_at"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_questions.id", ondelete="SET NULL"), nullable=True
    )
    mock_exam_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mock_exams.id", ondelete="SET NULL"), nullable=True
    )
    correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="drill", nullable=False)
    time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<StudyAttempt {self.id} correct={self.correct}>"


class StudyReview(UUIDPkMixin, Base):
    """知识点复习调度（FSRS-5）。

    每个 (kb_id, slug) 一行：FSRS 状态（stability / difficulty / lapses /
    review_state 等）为调度事实源；ease_factor / interval_days / repetitions
    保留用于旧接口展示与向后兼容。
    调度键用 slug 而非内容指纹——内容更新后复习进度保留（README 14.7.1）。
    """

    __tablename__ = "study_reviews"
    __table_args__ = (
        UniqueConstraint("kb_id", "slug", name="uq_study_reviews_kb_slug"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    wiki_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="SET NULL"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # FSRS-5 状态；新列为空/0 时调度器按旧字段做防御式初始化。
    stability: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    difficulty: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    lapses: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # new / learning / review / relearning
    review_state: Mapped[str] = mapped_column(
        String(20), default="new", server_default="new", nullable=False
    )
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fsrs_reps: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    def __repr__(self) -> str:
        return f"<StudyReview {self.slug} due={self.due_at}>"


class LearningTopic(UUIDPkMixin, Base):
    """知识点：以 Wiki 页面为内容载体，维护掌握度、前置关系与薄弱标记。

    掌握度的事实源仍是 study_profiles.mastery（slug → 0-1）；
    本表负责知识点元数据、前置关系与内容指纹，供图谱 / 计划 / 前置约束使用。
    """

    __tablename__ = "learning_topics"
    __table_args__ = (
        UniqueConstraint("kb_id", "slug", name="uq_learning_topics_kb_slug"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    wiki_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="SET NULL"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sm2_state_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    prerequisite_topic_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    weak_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Wiki 正文在掌握度建立后发生变化 → 提示「内容已更新，建议重新学习」
    content_updated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<LearningTopic {self.slug} mastery={self.mastery_score}>"


class StudyPlan(UUIDPkMixin, Base):
    """学习计划：每次读取按最新状态重算并覆盖（每个画像一行）。"""

    __tablename__ = "study_plans"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("study_profiles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(20), default="initial", nullable=False)
    suggested_mode: Mapped[str] = mapped_column(String(20), default="drill", nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<StudyPlan {self.phase} {self.suggested_mode}>"


class MockExam(UUIDPkMixin, Base):
    """仿真试卷：生成后锁定；状态 generating → ready → in_progress → grading → graded。"""

    __tablename__ = "mock_exams"
    __table_args__ = (
        Index("ix_mock_exams_kb_created", "kb_id", "created_at"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_profiles.id", ondelete="SET NULL"), nullable=True
    )
    exam_template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="generating", nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    passing_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    time_spent_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    template_snapshot_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    generation_progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 切出学习模式即暂停计时（README 4.6）；paused_seconds 累计暂停时长
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<MockExam {self.title} [{self.status}]>"


class MockExamItem(UUIDPkMixin, Base):
    """试卷题目快照（锁定顺序、分值；作答与得分逐题保存）。"""

    __tablename__ = "mock_exam_items"
    __table_args__ = (
        UniqueConstraint("mock_exam_id", "order_index", name="uq_mock_exam_items_order"),
    )

    mock_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mock_exams.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_questions.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str] = mapped_column(String(30), default="single_choice", nullable=False)
    section_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    selected_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<MockExamItem {self.mock_exam_id}#{self.order_index}>"


class WebResearchLog(UUIDPkMixin, Base):
    """联网核查日志：只作为出题参考，不写入知识库。"""

    __tablename__ = "web_research_logs"

    question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_questions.id", ondelete="CASCADE"), nullable=True
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    sources_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LearningAnnotation(UUIDPkMixin, Base):
    """学习模式个人批注：不写回 Wiki 正文。target_type: wiki / note / question。"""

    __tablename__ = "learning_annotations"
    __table_args__ = (
        Index("ix_learning_annotations_kb_target", "kb_id", "target_type", "target_id"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20), default="wiki", nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    quote: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self) -> str:
        return f"<LearningAnnotation {self.target_type}:{self.target_id}>"
