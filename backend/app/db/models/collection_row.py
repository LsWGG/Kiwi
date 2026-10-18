"""数据表笔记的行。"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class CollectionRow(UUIDPkMixin, Base):
    """一行数据：data 以字段 id 为键，值随字段类型变化。"""

    __tablename__ = "collection_rows"
    __table_args__ = (Index("ix_collection_rows_collection_sort", "collection_id", "sort_order"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("note_collections.id", ondelete="CASCADE"), index=True
    )
    # 每一行同时是一篇完整笔记（README §笔记集合）；删除笔记时行级联删除
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
