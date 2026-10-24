"""系统基础设置与 OCR 配置（单行表）。"""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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

    # 编辑器内置扩展组件中被停用的 key（日期 / 公式 / 绘图 / 图册 / 分栏…）；
    # 保存停用集合而不是启用集合，新增组件默认可用。
    editor_disabled_extensions: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    # 线上 OCR：OpenAI 兼容的视觉模型接口；关闭时回退本地 tesseract。
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_provider: Mapped[str] = mapped_column(String(40), default="openai", nullable=False)
    ocr_api_base: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    ocr_api_model: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    ocr_encrypted_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ocr_timeout: Mapped[float] = mapped_column(Float, default=120.0, nullable=False)
    ocr_language: Mapped[str] = mapped_column(String(40), default="auto", nullable=False)

    # 语音转写：auto 表示「配置了飞书妙记就用线上，否则本地 faster-whisper」。
    transcribe_provider: Mapped[str] = mapped_column(
        String(20), default="auto", nullable=False
    )
    # 飞书自建应用凭据；妙记上传要求 user_access_token，因此还需要用户授权。
    feishu_app_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    feishu_app_secret_encrypted: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    feishu_user_token_encrypted: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    feishu_refresh_token_encrypted: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    # 录音文件在云空间中的存放目录；留空使用用户根目录。
    feishu_folder_token: Mapped[str] = mapped_column(
        String(200), default="", nullable=False
    )
    # OAuth 回调地址；留空时按当前访问域名自动推导（需与开放平台重定向 URL 一致）。
    feishu_redirect_uri: Mapped[str] = mapped_column(
        String(500), default="", nullable=False
    )

    # Web Push 提醒：每日复习到期 / 待办，以及每周学习报告。
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push_reminder_hour: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    push_weekly_report: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_last_daily_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    push_last_weekly_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # VAPID 服务端密钥：私钥用 KIWI_FERNET_KEY 加密存储。
    push_vapid_private_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    push_vapid_public_key: Mapped[str] = mapped_column(String(200), default="", nullable=False)
