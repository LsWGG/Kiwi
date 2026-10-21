"""系统基础设置：品牌信息 + 线上 OCR 配置。

单行表模式，未写入时使用默认值。OCR 配置在启动与保存后注入
``ocr_service`` 运行时，解析线程可直接读取。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.services import ocr_service
from app.services.llm_factory import LLMCrypto

DEFAULT_APP_NAME = "Kiwi"
DEFAULT_APP_DESCRIPTION = "知识编译与检索系统"
DEFAULT_THEME_COLOR = "#5a55c7"
DEFAULT_LEARN_THEME_COLOR = "#10b981"
DEFAULT_LEARN_DESCRIPTION = "学习训练 · 复习"


def runtime_from_row(row: SystemSettings | None) -> ocr_service.OcrConfig:
    if row is None:
        return ocr_service.OcrConfig()
    key = ""
    if row.ocr_encrypted_api_key:
        try:
            key = LLMCrypto.decrypt(row.ocr_encrypted_api_key)
        except Exception:  # noqa: BLE001 - 密钥损坏时按未配置处理
            key = ""
    return ocr_service.OcrConfig(
        enabled=bool(row.ocr_enabled),
        provider=row.ocr_provider,
        api_base=row.ocr_api_base,
        api_key=key,
        api_model=row.ocr_api_model,
        timeout=row.ocr_timeout,
        language=row.ocr_language,
    )


async def get_row(session: AsyncSession) -> SystemSettings | None:
    return await session.get(SystemSettings, SYSTEM_SETTINGS_ID)


async def load_runtime(session: AsyncSession) -> SystemSettings | None:
    row = await get_row(session)
    ocr_service.configure_runtime(runtime_from_row(row))
    return row


def apply_row(row: SystemSettings | None) -> None:
    ocr_service.configure_runtime(runtime_from_row(row))
