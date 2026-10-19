"""系统设置路由：品牌信息、主题色与线上 OCR。"""

import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.db.session import get_session
from app.schemas.system import (
    LogoUploadOut,
    OcrTestIn,
    OcrTestOut,
    SystemSettingsOut,
    SystemSettingsUpdate,
)
from app.services import ocr_service, system_settings
from app.services.llm_factory import CryptoError, LLMCrypto

router = APIRouter(prefix="/api/settings/system", tags=["settings"])

LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".webp": (b"RIFF",),
}


def _out(row: SystemSettings | None) -> SystemSettingsOut:
    if row is None:
        return SystemSettingsOut(
            app_name=system_settings.DEFAULT_APP_NAME,
            app_description=system_settings.DEFAULT_APP_DESCRIPTION,
            logo_url="",
            theme_color=system_settings.DEFAULT_THEME_COLOR,
            learn_theme_color=system_settings.DEFAULT_LEARN_THEME_COLOR,
            ocr_enabled=False,
            ocr_provider="openai",
            ocr_api_base="",
            ocr_api_model="",
            has_ocr_api_key=False,
            ocr_timeout=120.0,
            ocr_language="auto",
            source="default",
        )
    return SystemSettingsOut(
        app_name=row.app_name,
        app_description=row.app_description,
        logo_url=row.logo_url,
        theme_color=row.theme_color,
        learn_theme_color=row.learn_theme_color,
        ocr_enabled=bool(row.ocr_enabled),
        ocr_provider=row.ocr_provider,
        ocr_api_base=row.ocr_api_base,
        ocr_api_model=row.ocr_api_model,
        has_ocr_api_key=bool(row.ocr_encrypted_api_key),
        ocr_timeout=row.ocr_timeout,
        ocr_language=row.ocr_language,
        source="saved",
    )


@router.get("", response_model=SystemSettingsOut)
async def get_system_settings(session: AsyncSession = Depends(get_session)):
    return _out(await system_settings.get_row(session))


@router.put("", response_model=SystemSettingsOut)
async def save_system_settings(
    data: SystemSettingsUpdate, session: AsyncSession = Depends(get_session)
):
    row = await system_settings.get_row(session)
    if row is None:
        row = SystemSettings(id=SYSTEM_SETTINGS_ID)
        session.add(row)

    if data.app_name is not None:
        row.app_name = data.app_name.strip() or system_settings.DEFAULT_APP_NAME
    if data.app_description is not None:
        row.app_description = data.app_description.strip()
    if data.logo_url is not None:
        row.logo_url = data.logo_url.strip()
    if data.theme_color is not None:
        row.theme_color = data.theme_color.lower()
    if data.learn_theme_color is not None:
        row.learn_theme_color = data.learn_theme_color.lower()
    if data.ocr_enabled is not None:
        row.ocr_enabled = data.ocr_enabled
    if data.ocr_provider is not None:
        row.ocr_provider = data.ocr_provider.strip() or "openai"
    if data.ocr_api_base is not None:
        row.ocr_api_base = data.ocr_api_base.strip().rstrip("/")
    if data.ocr_api_model is not None:
        row.ocr_api_model = data.ocr_api_model.strip()
    if data.ocr_timeout is not None:
        row.ocr_timeout = data.ocr_timeout
    if data.ocr_language is not None:
        row.ocr_language = data.ocr_language.strip() or "auto"

    if row.ocr_enabled and (
        not row.ocr_api_base or not row.ocr_api_model
    ):
        raise HTTPException(400, "启用线上 OCR 前请填写接口地址与模型名")
    if row.ocr_api_base and not row.ocr_api_base.startswith(("http://", "https://")):
        raise HTTPException(400, "OCR 接口地址必须以 http:// 或 https:// 开头")

    if data.ocr_api_key is not None:
        try:
            row.ocr_encrypted_api_key = (
                LLMCrypto.encrypt(data.ocr_api_key) if data.ocr_api_key else ""
            )
        except CryptoError as exc:
            raise HTTPException(500, str(exc)) from exc

    await session.commit()
    await session.refresh(row)
    system_settings.apply_row(row)
    return _out(row)


@router.post("/ocr/test", response_model=OcrTestOut)
async def test_ocr(
    data: OcrTestIn, session: AsyncSession = Depends(get_session)
):
    """用内置测试页验证 OCR 接口是否可用。"""
    row = await system_settings.get_row(session)
    saved = system_settings.runtime_from_row(row)
    key = data.api_key if data.api_key is not None else saved.api_key
    config = ocr_service.OcrConfig(
        enabled=True,
        provider=saved.provider,
        api_base=(data.api_base or saved.api_base or "").strip().rstrip("/"),
        api_key=key or "",
        api_model=(data.api_model or saved.api_model or "").strip(),
        timeout=data.timeout or saved.timeout or 120.0,
        language=data.language or saved.language or "auto",
    )
    ok, message, sample = await asyncio.to_thread(
        ocr_service.test_connection, config
    )
    return OcrTestOut(ok=ok, message=message, sample_text=sample)


@router.post("/logo", response_model=LogoUploadOut, status_code=201)
async def upload_logo(file: UploadFile = File(...)):
    filename = (file.filename or "logo.png").strip() or "logo.png"
    ext = re.sub(r"[^a-z0-9.]", "", Path(filename).suffix.lower())[:10]
    if ext not in LOGO_EXT:
        raise HTTPException(415, "Logo 仅支持 PNG / JPG / WebP / GIF / BMP")
    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(413, "Logo 不能超过 2MB")
    if not any(content.startswith(magic) for magic in LOGO_MAGIC[ext]):
        raise HTTPException(415, "图片内容与扩展名不符")
    if ext == ".webp" and content[8:12] != b"WEBP":
        raise HTTPException(415, "图片内容与扩展名不符")

    storage_dir = settings.upload_dir / "media" / "branding"
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (storage_dir / stored_name).write_bytes(content)
    return LogoUploadOut(url=f"/media/branding/{stored_name}")
