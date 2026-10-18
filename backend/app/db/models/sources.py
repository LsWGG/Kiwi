"""原始素材实体（不可变）。"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPkMixin

SourceType = Literal["md", "pdf", "docx", "doc", "txt", "note"]
SourceStatus = Literal["received", "parsing", "parsed", "compiled", "failed"]


class Source(UUIDPkMixin, Base):
    """导入的原始素材。内容不可变，sha256 用于去重与源漂移检测。"""

    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_kb_sha", "kb_id", "sha256"),
        Index("ix_sources_kb_external", "kb_id", "external_id"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20), default="md", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)  # 对象存储/本地路径
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    parse_quality: Mapped[str] = mapped_column(
        String(30), default="clean", nullable=False
    )  # clean/ocr_aided/review
    parse_engine: Mapped[str] = mapped_column(
        String(40), default="native", nullable=False
    )
    # 解析器给出的质量细节：页数、文本覆盖率、警告、表格结构等
    quality_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # 三层安全校验结果：clean / heuristic / unavailable / infected / error
    scan_status: Mapped[str] = mapped_column(
        String(20), default="unavailable", nullable=False
    )
    scan_detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    import_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 外部来源幂等键（语雀文档 id / 导出包内相对路径）
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    kb = relationship("KnowledgeBase", back_populates="sources")

    def __repr__(self) -> str:
        return f"<Source {self.title} [{self.sha256[:8]}]>"
