"""操作审计：删除、清空回收站、跨库迁移、知识库重建等危险动作留痕。"""

import uuid

from sqlalchemy import Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class AuditLog(UUIDPkMixin, Base):
    """一条审计记录。

    ``kb_id`` 不设外键：知识库被删除后，删除动作本身仍应可追溯。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_kb_created", "kb_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )

    kb_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="local", nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
