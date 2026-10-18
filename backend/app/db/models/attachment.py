"""笔记附件 / 编辑器内嵌媒体。"""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class NoteAttachment(UUIDPkMixin, Base):
    """上传到工作区的文件；storage_path 相对 media_dir。"""

    __tablename__ = "note_attachments"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
