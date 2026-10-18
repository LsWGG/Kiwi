"""向量模型配置（系统级单行）。API Key 加密存储，不上送前端。"""

import uuid

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin

# 单例行固定主键：应用内只维护这一条配置。
EMBEDDING_CONFIG_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


class EmbeddingConfig(UUIDPkMixin, Base):
    """向量化服务配置。

    未写入该行时，回退到 ``KIWI_EMBED_*`` 环境变量；写入后应用内配置优先。
    """

    __tablename__ = "embedding_config"

    provider: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    api_base: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    api_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    api_timeout: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    api_batch_size: Mapped[int] = mapped_column(Integer, default=64, nullable=False)
    api_concurrency: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
