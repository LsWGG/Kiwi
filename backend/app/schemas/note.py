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
    # 增量刷新：只返回 since 之后变化的节点与已删除 ID
    incremental: bool = False
    # 本次响应对应的服务端时间，客户端下次作为 since 传回
    server_time: datetime | None = None
    deleted_note_ids: list[uuid.UUID] = Field(default_factory=list)
    deleted_folder_ids: list[uuid.UUID] = Field(default_factory=list)
    # 懒加载模式：仅返回根级 / 置顶笔记，子节点通过 /tree/children 拉取
    lazy: bool = False
    # 知识库活跃笔记总数（懒加载时前端仍能展示真实计数）
    total_notes: int | None = None


class NoteTreeChildrenOut(BaseModel):
    notes: list[NoteSummary]
    # 命中上限时前端提示「仅显示前 N 条」
    truncated: bool = False


class NoteTreeLocationOut(BaseModel):
    """深链定位：笔记摘要 + 需要展开的祖先分组 / 父笔记。"""

    note: NoteSummary
    ancestor_ids: list[uuid.UUID] = Field(default_factory=list)


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
    # 即使 PDF 文本层可用也强制走 OCR（部分扫描版 PDF 文本层为空 / 乱码）
    use_ocr: bool = False


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
    # 用户在导入时是否勾选了强制 OCR
    use_ocr: bool = False


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

    kind: Literal["wiki", "note", "source"]
    title: str
    quote: str = ""
    score: float = 0.0
    wiki_page_id: uuid.UUID | None = None
    note_id: uuid.UUID | None = None
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
    # 正文已存在双向链接；前端据此决定是否还能给出「复制引用」建议。
    linked: bool = False
    # 正文二元组 Jaccard 相似度（0-1），用于展示内容关联强度。
    similarity: float = 0.0
    # 内容高度重合，可能是同一份笔记的副本。
    duplicate: bool = False


class NoteTagSuggestion(BaseModel):
    name: str
    # existing = 复用语料库已有标签；ai = 大模型新建议
    source: str = "existing"
    evidence: str = ""


class NoteTagSuggestionsOut(BaseModel):
    tags: list[NoteTagSuggestion] = Field(default_factory=list)
    ai_error: str | None = None


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



class NoteShareCreate(BaseModel):
    """创建只读分享：有效期 1 小时 ~ 30 天，可选访问密码。"""

    expires_in_hours: int = Field(default=168, ge=1, le=720)
    password: str | None = Field(default=None, min_length=4, max_length=128)


class NoteShareOut(BaseModel):
    id: uuid.UUID
    note_id: uuid.UUID
    token: str
    # 前端拼接站点域名后得到完整分享地址
    path: str
    # 配置了 KIWI_PUBLIC_BASE_URL 时直接返回公网完整地址
    url: str | None = None
    expires_at: datetime
    has_password: bool
    view_count: int
    last_viewed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    active: bool


class SharedNoteOut(BaseModel):
    """公开分享页内容：不含上锁 / 加密笔记正文。

    ``payload`` 按笔记类型携带只读的结构化内容：数据表字段/行、表格工作簿、
    画布文档、Notebook 单元格、链接元数据。文档类笔记只需 ``body_md``。
    """

    title: str
    body_md: str
    kind: str
    updated_at: datetime
    expires_at: datetime
    has_password: bool
    # 阅读态与工作区保持一致：展示笔记 emoji 与页面偏好（纸宽 / 底色 / 字号）
    emoji: str | None = None
    page_prefs: dict | None = None
    # 供前端在正文中替换图片地址后校验 / 调试
    media_expires_at: int
    payload: dict | None = None
