"""待办镜像：把知识库内散落的待办聚合到收件箱，并保持双向同步。"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class TodoMirror(UUIDPkMixin, Base):
    """一条待办在收件箱中的镜像记录。

    ``source_kind`` 为 ``task``（文档中的 Markdown 任务项）或
    ``database_row``（数据表中状态为待办的行）。``source_ref`` 是任务项的
    文本指纹或行 ID，用于在源内容更新后重新匹配。
    """

    __tablename__ = "todo_mirrors"
    __table_args__ = (
        UniqueConstraint(
            "kb_id", "source_note_id", "source_kind", "source_ref",
            name="uq_todo_mirror_source",
        ),
        Index("ix_todo_mirrors_kb_status", "kb_id", "status"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    hub_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    source_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
