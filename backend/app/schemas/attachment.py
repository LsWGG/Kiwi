"""附件 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AttachmentOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    note_id: uuid.UUID | None
    filename: str
    content_type: str
    size: int
    url: str
    created_at: datetime


class MdBundleOut(BaseModel):
    """Markdown 压缩包解析结果：用于「插入附件」把 md 与资源插入当前笔记。"""

    found: bool
    title: str = ""
    markdown: str = ""
    main_entry: str = ""
    attachments: list[AttachmentOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rewritten_refs: int = 0
