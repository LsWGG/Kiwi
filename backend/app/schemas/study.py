"""学习模式 schemas：画像 / 场景模板 / 训练 / 仿真考试 / 计划 / 图谱 / 批注。"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionType = Literal[
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
    "case_analysis",
    "essay",
]
StudyMode = Literal["drill", "review"]


# ---------- 画像 ----------
class StudyProfileIn(BaseModel):
    goal_type: str = Field(default="domain", pattern="^(exam|domain|explore)$")
    level_prior: str = Field(default="beginner", pattern="^(beginner|foundation|advanced)$")
    daily_minutes: int = Field(default=30, ge=5, le=600)
    topics_focus: list[str] = Field(default_factory=list, max_length=30)
    exam_template_id: uuid.UUID | None = None
    target_date: date | None = None
    preferred_mode: Literal["auto", "drill", "mock"] = "auto"
    weak_areas: list[str] = Field(default_factory=list, max_length=30)
    onboarded: bool | None = None
    profile_json: dict = Field(default_factory=dict)


class StudyProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    goal_type: str
    level_prior: str
    daily_minutes: int
    exam_template_id: uuid.UUID | None = None
    target_date: date | None = None
    preferred_mode: str = "auto"
    topics_focus: list
    weak_areas: list = Field(default_factory=list)
    mastery: dict
    profile_json: dict = Field(default_factory=dict)
    onboarded: bool = False
    status: str
    created_at: datetime
    updated_at: datetime


class OnboardingMessage(BaseModel):
    role: Literal["assistant", "user"]
    content: str = Field(min_length=1, max_length=8000)


class OnboardingTurnIn(BaseModel):
    messages: list[OnboardingMessage] = Field(default_factory=list, max_length=40)
    # 前端已采集的表单值（可空），用于 LLM 追问时参考
    draft: dict = Field(default_factory=dict)


class OnboardingTurnOut(BaseModel):
    reply: str
    done: bool = False
    profile_patch: dict = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class OnboardingCompleteIn(BaseModel):
    messages: list[OnboardingMessage] = Field(default_factory=list)
    profile: StudyProfileIn
    quick_start: bool = False


# ---------- 考试场景模板 ----------
class ExamTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=80)
    description: str = Field(default="", max_length=2000)
    question_types: list[dict] = Field(default_factory=list, max_length=20)
    scoring_rules: dict = Field(default_factory=dict)
    passing_criteria: dict = Field(default_factory=dict)
    duration_minutes: int = Field(default=120, ge=5, le=1440)
    difficulty_distribution: dict = Field(default_factory=dict)
    coverage_domains: list[str] = Field(default_factory=list, max_length=30)


class ExamTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID | None = None
    name: str
    code: str
    description: str
    is_builtin: bool
    question_types: list = Field(validation_alias="question_types_json")
    scoring_rules: dict = Field(validation_alias="scoring_rules_json")
    passing_criteria: dict = Field(validation_alias="passing_criteria_json")
    duration_minutes: int
    difficulty_distribution: dict
    coverage_domains: list
    created_at: datetime


# ---------- 题目 ----------
class QuestionOut(BaseModel):
    """出题返回：答案与解析留到判分后返回。"""

    id: uuid.UUID
    question: str
    question_type: str = "single_choice"
    options: list[str] = Field(default_factory=list)
    difficulty: str
    cite_slug: str | None = None
    cite_page_id: uuid.UUID | None = None
    topic_slug: str | None = None
    cite_title: str | None = None
    # 主观题材料 / 作答要求 / 字数下限
    material: str = ""
    requirements: str = ""
    min_words: int | None = None
    # 联网核查：参考来源与置信度
    web_sources: list[dict] = Field(default_factory=list)
    confidence_level: str = "unverified"
    # 选择题选项是否多选
    multiple: bool = False


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    selected_index: int = Field(default=-1, ge=-1, le=9)
    selected_indexes: list[int] = Field(default_factory=list, max_length=10)
    text: str = Field(default="", max_length=30000)
    time_ms: int = Field(default=0, ge=0)


class GradingDimension(BaseModel):
    key: str
    label: str
    score: float
    max_score: float
    comment: str = ""


class AnswerOut(BaseModel):
    correct: bool
    score: float = 0.0
    max_score: float = 1.0
    explanation: str = ""
    cite_slug: str | None = None
    correct_index: int = -1
    correct_indexes: list[int] = Field(default_factory=list)
    correct_answer: str = ""
    selected_index: int = -1
    selected_indexes: list[int] = Field(default_factory=list)
    user_answer: str = ""
    question_type: str = "single_choice"
    dimensions: list[GradingDimension] = Field(default_factory=list)
    # 更新后的掌握度快照（该题关联页 slug → 分数）
    mastery: dict = {}
    review_due_at: datetime | None = None
    # 是否可继续生成同知识点变式题
    variant_available: bool = True
    confidence_level: str = "unverified"


# ---------- 训练会话 ----------
class SessionStartOut(BaseModel):
    session_id: uuid.UUID
    mode: str = "drill"
    size: int = 10
    question: QuestionOut


class ActiveSessionOut(BaseModel):
    session_id: uuid.UUID
    mode: str = "drill"
    answered_count: int
    correct_count: int
    size: int = 10
    # 离开时未作答的题目；存在时前端直接恢复，不重新生成
    question: QuestionOut | None = None


class FinishOut(BaseModel):
    session_id: uuid.UUID
    correct_count: int
    question_count: int
    accuracy: float
    mastery: dict = {}
    weak_topics: list[dict] = Field(default_factory=list)
    recommended_mode: str = "drill"
    break_hint: str | None = None


# ---------- 错题本 ----------
class MistakeOut(BaseModel):
    attempt_id: uuid.UUID
    question_id: uuid.UUID | None = None
    question: str
    question_type: str = "single_choice"
    options: list[str]
    correct_index: int
    correct_indexes: list[int] = Field(default_factory=list)
    selected_index: int
    selected_indexes: list[int] = Field(default_factory=list)
    user_answer: str = ""
    score: float | None = None
    dimensions: list[dict] = Field(default_factory=list)
    explanation: str
    cite_slug: str | None = None
    cite_title: str = ""
    difficulty: str
    created_at: datetime
    confidence_level: str = "unverified"


class MistakeListOut(BaseModel):
    total: int
    items: list[MistakeOut]


class QuestionFeedbackIn(BaseModel):
    kind: Literal["content", "grading", "source"] = "content"
    detail: str = Field(default="", max_length=4000)


class QuestionFeedbackOut(BaseModel):
    ok: bool = True
    cache_invalidated: bool = True
    message: str = ""


# ---------- 掌握度 / 知识点 ----------
class MasteryItem(BaseModel):
    slug: str
    title: str
    score: float
    domain: str = ""
    weak: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    content_updated: bool = False


class MasteryOut(BaseModel):
    items: list[MasteryItem]
    coverage: float  # 覆盖知识库页面比例
    mastered_count: int = 0
    total_topics: int = 0


class LearningTopicOut(BaseModel):
    """知识点列表项：供笔记「关联知识点」块选择。"""

    id: uuid.UUID
    slug: str
    title: str
    domain: str = ""
    mastery: float = 0.0
    weak: bool = False
    wiki_page_id: uuid.UUID | None = None


class TopicNoteOut(BaseModel):
    """知识点关联的学习笔记片段（复习时作为「我的笔记」）。"""

    note_id: uuid.UUID
    title: str
    excerpt: str
    updated_at: datetime


class LearnGraphNode(BaseModel):
    id: str
    slug: str
    title: str
    mastery: float
    weak: bool
    domain: str = ""
    page_type: str = "concept"
    link_count: int = 0
    wiki_page_id: uuid.UUID | None = None
    # 复习调度：是否到期 / 到期时间；知识点内容是否已更新
    due: bool = False
    due_at: datetime | None = None
    content_updated: bool = False


class LearnGraphEdge(BaseModel):
    source: str
    target: str
    type: str = "reference"
    prerequisite: bool = False


class LearnGraphOut(BaseModel):
    nodes: list[LearnGraphNode]
    edges: list[LearnGraphEdge]
    coverage: float = 0.0


# ---------- 今日复习 ----------
class ReviewItemOut(BaseModel):
    slug: str
    title: str
    mastery: float
    due_at: datetime
    interval_days: float
    repetitions: int
    domain: str = ""
    content_updated: bool = False


class ReviewDueOut(BaseModel):
    total: int
    items: list[ReviewItemOut]
    next_due_at: datetime | None = None


# ---------- 学习计划 ----------
class PlanDay(BaseModel):
    date: date
    mode: str
    minutes: int
    focus: list[str] = Field(default_factory=list)
    note: str = ""
    # 用户手动调整过的日期（计划引擎不再覆盖）
    adjusted: bool = False


class PlanAdjustIn(BaseModel):
    date: date
    mode: str = Field(default="drill", pattern="^(drill|mock)$")
    minutes: int | None = Field(default=None, ge=5, le=600)
    focus: list[str] | None = None
    note: str | None = Field(default=None, max_length=300)
    clear: bool = False


class StudyPlanOut(BaseModel):
    phase: str
    suggested_mode: str
    coverage: float
    accuracy_trend: float
    days_to_target: int | None = None
    weak_topics: list[dict] = Field(default_factory=list)
    week: list[PlanDay] = Field(default_factory=list)
    rationale: str = ""
    # 右侧进度面板：连续学习天数 / 今日到期复习数
    streak_days: int = 0
    due_count: int = 0
    # 最近三次仿真成绩摘要：{count, avg_rate, latest_rate, passed, passing_known}
    exam_history: dict = Field(default_factory=dict)
    computed_at: datetime


# ---------- 仿真考试 ----------
class MockExamGenerateIn(BaseModel):
    exam_template_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)


class MockExamSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    status: str
    duration_minutes: int
    question_count: int
    total_score: float | None = None
    max_score: float
    passing_score: float | None = None
    generation_progress: float = 0.0
    error: str | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    paused_at: datetime | None = None
    paused_seconds: int = 0
    generated_at: datetime
    created_at: datetime


class MockExamItemOut(BaseModel):
    id: uuid.UUID
    order_index: int
    section_type: str
    section_name: str
    score: float
    question_id: uuid.UUID | None = None
    question: str = ""
    options: list[str] = Field(default_factory=list)
    material: str = ""
    requirements: str = ""
    min_words: int | None = None
    user_answer: str = ""
    selected_index: int | None = None
    selected_indexes: list[int] = Field(default_factory=list)
    score_awarded: float | None = None
    answered: bool = False
    # 仅在已批阅后返回
    correct: bool | None = None
    correct_index: int | None = None
    correct_indexes: list[int] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    dimensions: list[dict] = Field(default_factory=list)
    cite_slug: str | None = None
    cite_title: str = ""
    confidence_level: str = "unverified"


class MockExamDetail(MockExamSummary):
    template: dict = Field(default_factory=dict)
    items: list[MockExamItemOut] = Field(default_factory=list)
    score_breakdown: dict = Field(default_factory=dict)
    time_spent: dict = Field(default_factory=dict)


class MockExamAnswerIn(BaseModel):
    selected_index: int | None = Field(default=None, ge=0, le=9)
    selected_indexes: list[int] = Field(default_factory=list, max_length=10)
    text: str = Field(default="", max_length=30000)
    time_spent_seconds: int = Field(default=0, ge=0)


class MockExamReportSection(BaseModel):
    name: str
    type: str
    question_count: int
    score: float
    max_score: float
    accuracy: float = 0.0


class MockExamReport(BaseModel):
    exam_id: uuid.UUID
    title: str
    status: str
    total_score: float | None = None
    max_score: float
    passing_score: float | None = None
    passed: bool | None = None
    accuracy: float = 0.0
    sections: list[MockExamReportSection] = Field(default_factory=list)
    knowledge_points: list[dict] = Field(default_factory=list)
    weak_topics: list[dict] = Field(default_factory=list)
    time_analysis: dict = Field(default_factory=dict)
    items: list[MockExamItemOut] = Field(default_factory=list)
    advice: str = ""


# ---------- 学习批注 ----------
class AnnotationIn(BaseModel):
    target_type: Literal["wiki", "note", "question"] = "wiki"
    target_id: uuid.UUID
    content_md: str = Field(min_length=1, max_length=20000)
    quote: str = Field(default="", max_length=2000)


class AnnotationUpdate(BaseModel):
    content_md: str = Field(min_length=1, max_length=20000)


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    content_md: str
    quote: str
    created_at: datetime
    updated_at: datetime
