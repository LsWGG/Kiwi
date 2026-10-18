"""笔记集合（Collection）：数据表笔记的结构化容器。"""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class NoteCollection(UUIDPkMixin, Base):
    """与 kind='database' 的笔记一一对应；schema_json 存字段定义，views_json 存视图。"""

    __tablename__ = "note_collections"
    __table_args__ = (
        UniqueConstraint("note_id", name="uq_note_collections_note_id"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    views_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
