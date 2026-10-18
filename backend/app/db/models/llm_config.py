"""大模型连接配置（系统级）。API Key 加密存储，解密仅在服务端内部。"""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class LLMConfig(UUIDPkMixin, Base):
    """大模型连接配置。encrypted_api_key 为 Fernet 密文（base64 文本）。"""

    __tablename__ = "llm_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="openai-compatible", nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)  # 如 http://localhost:11434
    model_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra_params: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # temperature 等
