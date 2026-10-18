"""知识库实体。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base, UUIDPkMixin


class KnowledgeBase(UUIDPkMixin, Base):
    """知识库：所有数据（素材/Wiki/笔记/检索/模型）的隔离锚点。"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 知识库置顶：在知识库列表中优先展示
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 是否开启学习模式：关闭后该库仅用于记录 / 检索
    learning_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    # 系统内置演示库：允许用户隐藏，但保留数据与「还原」入口
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    builtin_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # 内置库软删除时间；非内置库仍为硬删除
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 默认 Embedding 模型（知识库级）
    embedding_model: Mapped[str] = mapped_column(
        String(200), default=settings.embed_model, nullable=False
    )
    # 默认大模型配置（知识库级）
    llm_config_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("llm_configs.id", ondelete="SET NULL"), nullable=True
    )

    sources = relationship("Source", back_populates="kb", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="kb", cascade="all, delete-orphan")
    wiki_pages = relationship("WikiPage", back_populates="kb", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<KnowledgeBase {self.slug}>"
