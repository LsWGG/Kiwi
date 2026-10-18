"""异步摄入任务追踪。"""

import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class IngestJob(UUIDPkMixin, Base):
    """单个素材的异步摄入/编译任务状态。"""

    __tablename__ = "ingest_jobs"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), default="ingest", nullable=False
    )  # ingest / compile / recompile
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending/running/succeeded/failed
    progress: Mapped[float] = mapped_column(default=0.0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    touched_page_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    import_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 由工作区导入创建的笔记；任务删除/笔记删除时仅置空，Source 仍保留
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True, index=True
    )
