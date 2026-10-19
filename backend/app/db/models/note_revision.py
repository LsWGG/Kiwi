"""笔记历史版本：用于查看与还原任意一次保存。"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class NoteRevision(UUIDPkMixin, Base):
    """笔记内容快照。

    ``source`` 记录快照产生方式：``auto`` 自动保存、``manual`` 手动创建、
    ``restore`` 还原前备份、``import`` 导入完成。正文与属性完整保存，
    还原时覆盖当前笔记。
    """

    __tablename__ = "note_revisions"
    __table_args__ = (
        Index("ix_note_revisions_note_created", "note_id", "created_at"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    props_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
