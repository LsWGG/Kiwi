"""知识库实体。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    # 系统内置演示库：删除为硬删除，并可按随包内容重新创建
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    builtin_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # 旧版本内置库的软删除标记；新删除均为硬删除，仅用于兼容历史数据。
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 知识库卡片手动排序（越小越靠前）
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # 定时编译 Wiki：间隔为 0 表示关闭。last_status 记录最近一次结果。
    wiki_compile_interval_hours: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    wiki_compile_last_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wiki_compile_last_status: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    # 待办聚合到收件箱：间隔为 0 表示仅手动同步。
    todo_sync_interval_hours: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    todo_sync_last_at: Mapped[datetime | None] = mapped_column(
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
