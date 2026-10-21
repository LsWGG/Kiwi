"""系统基础设置与 OCR 配置（单行表）。"""

import uuid

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin

SYSTEM_SETTINGS_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


class SystemSettings(UUIDPkMixin, Base):
    """全站唯一配置：品牌信息、主题色与线上 OCR 接口。"""

    __tablename__ = "system_settings"

    app_name: Mapped[str] = mapped_column(String(100), default="Kiwi", nullable=False)
    app_description: Mapped[str] = mapped_column(
        Text, default="知识编译与检索系统", nullable=False
    )
    logo_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    # 编辑模式与学习模式是两套视觉语言：主题色、图标与描述分别配置。
    theme_color: Mapped[str] = mapped_column(String(20), default="#5a55c7", nullable=False)
    learn_theme_color: Mapped[str] = mapped_column(
        String(20), default="#10b981", nullable=False
    )
    # 学习模式 Logo；留空时沿用品牌 Logo / 内置学习标记。
    learn_logo_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    learn_description: Mapped[str] = mapped_column(
        Text, default="学习训练 · 复习", nullable=False
    )

    # 线上 OCR：OpenAI 兼容的视觉模型接口；关闭时回退本地 tesseract。
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_provider: Mapped[str] = mapped_column(String(40), default="openai", nullable=False)
    ocr_api_base: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    ocr_api_model: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    ocr_encrypted_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ocr_timeout: Mapped[float] = mapped_column(Float, default=120.0, nullable=False)
    ocr_language: Mapped[str] = mapped_column(String(40), default="auto", nullable=False)
