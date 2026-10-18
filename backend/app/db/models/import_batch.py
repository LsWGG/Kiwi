"""导入批次：一次文件 / 语雀导入的进度与解析报告。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class ImportBatch(UUIDPkMixin, Base):
    """批量导入的聚合状态。

    provider: upload / yuque_token / yuque_zip
    status: running / completed / partial / failed
    """

    __tablename__ = "import_batches"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), default="upload", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    total_sources: Mapped[int] = mapped_column(default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(default=0, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ImportBatch {self.provider} {self.status} {self.processed_count}/{self.total_sources}>"
