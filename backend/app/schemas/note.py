"""笔记 schemas。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NoteKind = Literal["doc", "database", "link", "import", "canvas", "notebook", "sheet"]


class NoteFolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    sort_order: int
    pinned: bool = False


class NoteFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class NoteFolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    pinned: bool | None = None


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body_md: str = ""
    kind: Literal["doc", "database", "canvas", "notebook", "sheet"] = "doc"
    folder_id: uuid.UUID | None = None
    # 非空时作为该笔记的子笔记，实际分组跟随父笔记
    parent_note_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    view_mode: str = "edit"
    sort_order: int | None = None
    props_json: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body_md: str | None = None
    folder_id: uuid.UUID | None = None
    parent_note_id: uuid.UUID | None = None
    status: str | None = None
    view_mode: str | None = None
    sort_order: int | None = None
    props_json: dict | None = None
    tags: list[str] | None = Field(default=None, max_length=30)


class NoteLockIn(BaseModel):
    """设置 / 修改笔记密码锁。密码长度至少 4 位。

    ``encrypt=True`` 时正文以密码派生密钥加密存储；密码丢失后无法恢复，
    前端必须二次确认。已加密笔记改密时同样需要重新加密正文。
    """

    password: str = Field(min_length=4, max_length=128)
    hint: str | None = Field(default=None, max_length=120)
    encrypt: bool = False


class NoteUnlockIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class NoteLockRemoveIn(BaseModel):
    """移除密码锁：可用密码，或已持有的解锁令牌。"""

    password: str | None = Field(default=None, max_length=128)


class NoteLockOut(BaseModel):
    token: str
    expires_at: int
    is_locked: bool = True
    encrypted: bool = False


class NoteCopyIn(BaseModel):
    """复制笔记：默认复制到同一分组的末尾。"""

    title: str | None = Field(default=None, max_length=300)
    folder_id: uuid.UUID | None = None
    parent_note_id: uuid.UUID | None = None


class NoteTransferIn(BaseModel):
    """跨知识库移动笔记。"""

    target_kb_id: uuid.UUID
    folder_id: uuid.UUID | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    body_md: str
    kind: str
    folder_id: uuid.UUID | None
    parent_note_id: uuid.UUID | None = None
    source_id: uuid.UUID | None
    status: str
    view_mode: str
    sort_order: int
    props_json: dict
    tags: list[str] = Field(default_factory=list, validation_alias="tag_names")
    wiki_page_id: uuid.UUID | None = None
    is_locked: bool = False
    lock_hint: str | None = None
    # 正文是否以密文存储（密码丢失不可恢复）
    encrypted: bool = False
    # 本次响应是否已通过 X-Note-Token 解锁（上锁笔记的正文仅在解锁时返回）
    unlocked: bool = False
    created_at: datetime
    updated_at: datetime


class NoteLinkOut(BaseModel):
    from_note_id: uuid.UUID
    to_note_id: uuid.UUID
    context_text: str = ""


class NoteSummary(BaseModel):
    """树 / 列表项（不带正文，节省带宽）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    kind: str
    folder_id: uuid.UUID | None
    parent_note_id: uuid.UUID | None = None
    status: str
    sort_order: int
    props_json: dict
    tags: list[str] = Field(default_factory=list, validation_alias="tag_names")
    wiki_page_id: uuid.UUID | None = None
    is_locked: bool = False
    lock_hint: str | None = None
    created_at: datetime
    updated_at: datetime


class NoteBacklinkOut(NoteSummary):
    """反向链接条目：附带引用处上下文片段。"""

    context: str = ""


class NoteTreeOut(BaseModel):
    folders: list[NoteFolderOut]
    notes: list[NoteSummary]


class ReorderIn(BaseModel):
    """同级排序：parent_id 为空表示根级。"""

    parent_id: uuid.UUID | None = None
    # target=note 时可选：按父笔记排序其子笔记；为空表示分组根级笔记
    parent_note_id: uuid.UUID | None = None
    target: Literal["folder", "note"] = "note"
    ordered_ids: list[uuid.UUID]


class TreeReorderItem(BaseModel):
    """混合层级中的一个节点：分组或笔记。"""

    type: Literal["folder", "note"]
    id: uuid.UUID


class TreeReorderIn(BaseModel):
    """混合排序：分组与笔记共享同一顺序（parent_id 为空表示根级）。"""

    parent_id: uuid.UUID | None = None
    items: list[TreeReorderItem]


class LinkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    folder_id: uuid.UUID | None = None
    parent_note_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=300)
    # 只读：只保留链接卡片，不抓取 / 不生成可编辑正文
    readonly: bool = False


class LinkMetaIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class LinkMetaOut(BaseModel):
    url: str
    final_url: str
    title: str
    site: str
    excerpt: str
    favicon: str
    fetch_status: Literal["ok", "failed"]
    error: str | None = None


class RemoteFileImportIn(BaseModel):
    """按 URL 导入线上文件，复用文件入库与可选编译流程。"""

    url: str = Field(min_length=1, max_length=2000)
    folder_id: uuid.UUID | None = None
    parent_note_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=300)
    compile_now: bool = False
    batch_id: uuid.UUID | None = None
    readonly: bool = False


class NoteImportStartOut(BaseModel):
    note: NoteOut
    # 只读导入不进入解析流水线，因此没有任务
    job_id: uuid.UUID | None = None


class TablePreviewOut(BaseModel):
    sheets: list[dict]
    sheet: str
    fields: list[dict]
    sample_rows: list[dict]
    row_count: int
    truncated: bool


class TableImportOut(BaseModel):
    note: NoteOut
    sheet: str
    fields: list[dict]
    row_count: int
    truncated: bool


class NoteRevisionSummary(BaseModel):
    """历史版本列表项（不含正文，节省带宽）。"""

    id: uuid.UUID
    note_id: uuid.UUID
    title: str
    source: str
    created_at: datetime


class NoteRevisionOut(NoteRevisionSummary):
    body_md: str
    props_json: dict = Field(default_factory=dict)


class NoteImportStatusOut(BaseModel):
    status: Literal["importing", "ready", "failed"]
    progress: float = 0.0
    error: str | None = None
    source_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    source_status: str | None = None
    parse_quality: str | None = None
    parse_engine: str | None = None
    scan_status: str | None = None
    scan_detail: str | None = None
    quality_report: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    body_ready: bool = False


class NoteAssistIn(BaseModel):
    """编辑器 AI 助手请求：动作 + 选中文本 + 文档上下文。"""

    action: Literal[
        "continue",
        "polish",
        "shorten",
        "summarize",
        "translate",
        "explain",
        "custom",
    ] = "custom"
    selection: str = Field(default="", max_length=20000)
    context: str = Field(default="", max_length=20000)
    instruction: str | None = Field(default=None, max_length=2000)


class NoteAssistReference(BaseModel):
    """「基于知识库解释」引用的条目。"""

    kind: Literal["wiki", "source"]
    title: str
    quote: str = ""
    score: float = 0.0
    wiki_page_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None


class NoteAssistOut(BaseModel):
    result: str
    references: list[NoteAssistReference] = Field(default_factory=list)


# ---------- 标签 ----------
class NoteTagOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    usage_count: int = 0
    last_used_at: datetime | None = None


class NoteTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None


class NoteTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None


class NoteTagsSet(BaseModel):
    """按标签名整体替换笔记标签；不存在的标签自动创建。"""

    names: list[str] = Field(default_factory=list, max_length=30)


# ---------- 模板 ----------
class NoteTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="note", max_length=32)
    title_pattern: str = Field(default="", max_length=300)
    body_md: str = ""
    tags_json: list[str] = Field(default_factory=list, max_length=30)
    props_json: dict = Field(default_factory=dict)
    sort_order: int | None = None


class NoteTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=32)
    title_pattern: str | None = Field(default=None, max_length=300)
    body_md: str | None = None
    tags_json: list[str] | None = Field(default=None, max_length=30)
    props_json: dict | None = None
    sort_order: int | None = None


class NoteTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    name: str
    description: str
    icon: str
    title_pattern: str
    body_md: str
    tags_json: list
    props_json: dict
    is_builtin: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class NoteTemplateUseIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    folder_id: uuid.UUID | None = None
    parent_note_id: uuid.UUID | None = None


# ---------- 搜索 / 相关笔记 ----------
class NoteSearchItem(BaseModel):
    note: NoteSummary
    snippet: str = ""
    matched_fields: list[str] = Field(default_factory=list)
    score: float = 0.0


class NoteSearchOut(BaseModel):
    total: int
    items: list[NoteSearchItem]


class RelatedNoteItem(BaseModel):
    note: NoteSummary
    score: float
    reasons: list[str] = Field(default_factory=list)


# ---------- 生命周期 / 编译 / Wiki 关联 / 学习要点 ----------
class NoteTrashOut(BaseModel):
    total: int
    items: list[NoteSummary]
    retention_days: int = 30


class NoteCompileOut(BaseModel):
    job_id: uuid.UUID
    source_id: uuid.UUID
    reused_source: bool = False


class NoteCompileStatusOut(BaseModel):
    job_id: uuid.UUID | None = None
    status: str = "idle"
    progress: float = 0.0
    error: str | None = None
    source_id: uuid.UUID | None = None
    compiled: bool = False
    page_count: int = 0
    finished_at: datetime | None = None


class NoteWikiLinkIn(BaseModel):
    wiki_page_id: uuid.UUID | None = None


class NoteWikiLinkOut(BaseModel):
    wiki_page_id: uuid.UUID | None = None
    slug: str | None = None
    title: str | None = None


class StudyPointIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    wiki_slug: str | None = Field(default=None, max_length=200)


class NoteStudyPointsIn(BaseModel):
    points: list[StudyPointIn] = Field(default_factory=list, max_length=50)


class NoteStudyPointOut(BaseModel):
    id: str
    text: str
    wiki_slug: str | None = None
    created_at: str


class NoteGraphOut(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class NoteArchiveOut(BaseModel):
    total: int
    items: list[NoteSummary]


class QuickCaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=300)
    folder_id: uuid.UUID | None = None

