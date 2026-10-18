"""Wiki 页面 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WikiPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    slug: str
    page_type: str
    title: str
    body_md: str
    frontmatter_json: dict
    compiled_from_source_ids: list
    version: int
    human_edited: bool
    created_at: datetime
    updated_at: datetime

    # 聚合 / 派生字段（接口里手工填充）
    tags: list[str] = Field(default_factory=list)
    mastery: float | None = None
    backlink_count: int = 0
    annotation_count: int = 0
    sources: list[dict] = Field(default_factory=list)
    related_notes: list[dict] = Field(default_factory=list)


class WikiSchemaOut(BaseModel):
    """知识库 Wiki Schema：编译时注入 LLM 的结构化规范。"""

    content: str
    customized: bool
    default_content: str
    max_chars: int


class WikiSchemaUpdate(BaseModel):
    content: str


class WikiPageCreate(BaseModel):
    """人工创建 Wiki 页面（含问答回写的综合页）。"""

    title: str = Field(min_length=1, max_length=300)
    body_md: str = ""
    page_type: str = "concept"
    tags: list[str] = Field(default_factory=list)
    slug: str | None = Field(default=None, max_length=200)


class WikiPageUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    body_md: str | None = None
    page_type: str | None = None
    tags: list[str] | None = None
    human_edited: bool | None = None
    frontmatter_json: dict | None = None


class WikiPageSummary(BaseModel):
    """列表项：摘要首行 + 元信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    slug: str
    page_type: str
    title: str
    version: int
    human_edited: bool
    updated_at: datetime

    # 聚合（非列）
    link_count: int = 0
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    mastery: float | None = None
    annotation_count: int = 0
    source_count: int = 0


class WikiOverview(BaseModel):
    """Wiki 总览仪表盘数据。"""

    page_count: int = 0
    page_type_distribution: dict[str, int] = {}
    pending_compile_count: int = 0
    pending_review_count: int = 0
    human_edited_count: int = 0
    study_status: dict = Field(default_factory=dict)
    recent_activity: list[dict] = []
    pages: list[WikiPageSummary] = []


class WikiSearchResult(BaseModel):
    page_id: uuid.UUID
    slug: str
    title: str
    snippet: str
    score: float


class GraphNode(BaseModel):
    id: str  # "wiki:{id}" 或 "note:{id}"
    kind: str  # wiki / note
    title: str
    page_type: str = "wiki"
    link_count: int = 0
    human_edited: bool = False
    mastery: float | None = None
    note_kind: str | None = None
    status: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = "reference"


class GraphData(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    performance_mode: bool = False
    truncated: bool = False
    total_nodes: int = 0


class LintIssue(BaseModel):
    code: str
    severity: str  # error / warning / info
    category: str  # dead_link / orphan / frontmatter / slug / index / conflict / gap / drift
    message: str
    page_id: str | None = None
    page_title: str | None = None
    detail: str | None = None


class LintReport(BaseModel):
    generated_at: datetime
    summary: dict = Field(default_factory=dict)
    issues: list[LintIssue] = []
    semantic_status: str = "skipped"  # skipped / ok / failed
    semantic_error: str | None = None


class LintReportOut(LintReport):
    """已持久化的健康检查快照。"""

    id: uuid.UUID
    trigger: str = "manual"  # quick / full / manual
