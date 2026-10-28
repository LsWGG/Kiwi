"""语音转写：音频上传入队、实时预览、飞书妙记扫码授权与状态查询。"""

from __future__ import annotations

import html
import logging
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase
from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.db.session import get_session
from app.services import feishu_minutes, job_queue, transcription
from app.services.desktop_guard import require_online_feature

logger = logging.getLogger("kiwi.transcribe")

router = APIRouter(prefix="/api/transcribe", tags=["transcribe"])

AUDIO_SUFFIXES = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".oga",
    ".flac",
    ".webm",
    ".mp4",
    ".opus",
}
MAX_AUDIO_BYTES = 500 * 1024 * 1024
MAX_PREVIEW_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
CALLBACK_PATH = "/api/transcribe/feishu/oauth/callback"

# 扫码授权是一次性短流程：state 只保留 10 分钟，结果再留 10 分钟供前端轮询。
OAUTH_TTL_SECONDS = 10 * 60
_oauth_states: dict[str, dict] = {}
_oauth_results: dict[str, dict] = {}


class FeishuOAuthStartIn(BaseModel):
    # 前端页面来源（window.location.origin），未配置回调地址时据此推导。
    origin: str = Field(default="", max_length=200)


class FeishuTestOut(BaseModel):
    ok: bool
    message: str


def _cleanup_oauth() -> None:
    now = time.time()
    for store, ttl in ((_oauth_states, OAUTH_TTL_SECONDS), (_oauth_results, OAUTH_TTL_SECONDS)):
        for key in [k for k, v in store.items() if now - v["created"] > ttl]:
            store.pop(key, None)


def _valid_origin(origin: str) -> str:
    value = (origin or "").strip().rstrip("/")
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(status_code=400, detail="页面来源无效")
    return f"{parts.scheme}://{parts.netloc}"


async def _save_upload(file: UploadFile, target_dir: Path, suffix: str, limit: int) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with path.open("wb") as out:
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"音频不能超过 {limit // (1024 * 1024)}MB",
                    )
                out.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="保存音频失败") from e
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="音频文件为空")
    return path


def _check_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="仅支持 mp3 / wav / m4a / aac / ogg / flac / webm / mp4 / opus 音频",
        )
    return suffix


def _normalize_language(language: str) -> str:
    value = (language or "auto").strip().lower()
    if value != "auto" and not (2 <= len(value) <= 3 and value.isalpha()):
        raise HTTPException(status_code=400, detail="语言代码无效")
    return value


@router.get("/status")
async def transcribe_status():
    """转写通道、飞书妙记配置与本地模型加载状态。"""
    return await transcription.build_status()


@router.post("")
async def create_transcription(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    title: str = Form(default=""),
    summarize: bool = Form(default=True),
    session: AsyncSession = Depends(get_session),
):
    """保存音频并创建后台转写任务；完成后生成会议笔记。"""
    require_online_feature("transcribe")
    status = await transcription.build_status()
    if not status["enabled"]:
        raise HTTPException(
            status_code=400, detail="语音转写已关闭：请配置飞书妙记或启用本地模型"
        )
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.deleted_at is not None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    filename = file.filename or "audio"
    suffix = _check_suffix(filename)
    language = _normalize_language(language)
    path = await _save_upload(
        file, settings.upload_dir / "transcribe", suffix, MAX_AUDIO_BYTES
    )

    job = await job_queue.enqueue(
        "transcribe",
        {
            "path": str(path),
            "kb_id": str(kb_id),
            "language": language,
            "title": title.strip()[:300],
            "filename": filename,
            "summarize": summarize,
            "create_note": True,
        },
        kb_id=kb_id,
        ref_id=filename[:120],
        max_attempts=1,
        priority=80,
    )
    return {
        "job_id": str(job.id),
        "filename": filename,
        "size": path.stat().st_size,
        "status": job.status,
        "provider": status["provider"],
    }


@router.post("/preview")
async def preview_transcription(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    offset: float = Form(default=0.0),
):
    """录音过程中的实时预览：只走本地轻量模型，失败不进入任务队列。"""
    if not settings.whisper_enabled:
        raise HTTPException(status_code=400, detail="本地实时预览已关闭")
    filename = file.filename or "chunk.webm"
    suffix = _check_suffix(filename)
    language = _normalize_language(language)
    path = await _save_upload(
        file, settings.upload_dir / "transcribe", suffix, MAX_PREVIEW_BYTES
    )
    try:
        result = await transcription.transcribe_preview(path, language=language)
    except transcription.TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)

    shift = max(0.0, float(offset or 0.0))
    segments = [
        {
            **segment,
            "start": round(float(segment.get("start", 0)) + shift, 2),
            "end": round(float(segment.get("end", 0)) + shift, 2),
        }
        for segment in result.get("segments") or []
    ]
    return {
        "text": result.get("text", ""),
        "segments": segments,
        "language": result.get("language", ""),
        "duration": result.get("duration", 0),
        "offset": round(shift, 2),
    }


@router.post("/feishu/test", response_model=FeishuTestOut)
async def test_feishu(session: AsyncSession = Depends(get_session)):
    """用已保存的应用凭据与用户令牌验证飞书妙记是否可用。"""
    require_online_feature("feishu")
    config = await feishu_minutes.load_config(session)
    ok, message = await feishu_minutes.test_connection(config)
    return FeishuTestOut(ok=ok, message=message)


@router.post("/feishu/oauth/start")
async def feishu_oauth_start(
    data: FeishuOAuthStartIn,
    session: AsyncSession = Depends(get_session),
):
    """生成飞书授权页链接；PC 端打开后可直接用飞书扫码登录。"""
    require_online_feature("feishu")
    _cleanup_oauth()
    row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
    app_id = (row.feishu_app_id if row else "") or ""
    app_secret_encrypted = row.feishu_app_secret_encrypted if row else ""
    if not app_id or not app_secret_encrypted:
        raise HTTPException(status_code=400, detail="请先填写并保存飞书应用 App ID / App Secret")

    origin = _valid_origin(data.origin)
    redirect_uri = ((row.feishu_redirect_uri if row else "") or "").strip()
    if not redirect_uri:
        if not origin:
            raise HTTPException(
                status_code=400, detail="请填写回调地址，或从页面内发起授权"
            )
        redirect_uri = f"{origin}{CALLBACK_PATH}"

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "created": time.time(),
        "origin": origin,
        "redirect_uri": redirect_uri,
    }
    return {
        "state": state,
        "redirect_uri": redirect_uri,
        "authorize_url": feishu_minutes.build_authorize_url(app_id, redirect_uri, state),
    }


@router.get("/feishu/oauth/status")
async def feishu_oauth_status(state: str = Query(default="", max_length=200)):
    """前端轮询扫码结果；授权成功后系统设置会自动带令牌。"""
    _cleanup_oauth()
    if state in _oauth_results:
        return _oauth_results[state]["result"]
    if state in _oauth_states:
        return {"status": "pending", "message": "等待飞书扫码授权"}
    return {"status": "expired", "message": "授权会话已过期，请重新发起扫码"}


def _callback_page(ok: bool, message: str, origin: str) -> str:
    import json

    title = "授权成功" if ok else "授权失败"
    color = "#16a34a" if ok else "#dc2626"
    payload_ok = "true" if ok else "false"
    target = json.dumps(origin or "*")
    js_message = json.dumps(message, ensure_ascii=False)
    safe_message = html.escape(message)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Kiwi · 飞书授权</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#f8fafc; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; color:#0f172a; }}
  .card {{ background:#fff; border-radius:16px; padding:36px 40px; max-width:420px; text-align:center;
          box-shadow:0 12px 32px rgba(15,23,42,.08); }}
  h1 {{ font-size:18px; color:{color}; margin:0 0 10px; }}
  p {{ font-size:13px; line-height:1.7; color:#475569; margin:0; }}
</style></head><body>
<div class="card"><h1>{title}</h1><p>{safe_message}</p>
<p style="margin-top:14px">窗口将自动关闭，可回到 Kiwi 继续。</p></div>
<script>
  try {{ window.opener && window.opener.postMessage(
    {{ type: "kiwi-feishu-oauth", ok: {payload_ok}, message: {js_message} }}, {target} ); }} catch (e) {{}}
  setTimeout(function () {{ try {{ window.close(); }} catch (e) {{}} }}, 1200);
</script></body></html>"""


@router.get("/feishu/oauth/callback", include_in_schema=False)
async def feishu_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """飞书授权回调（浏览器 302 进入，靠一次性 state 校验）。"""
    require_online_feature("feishu")
    _cleanup_oauth()
    entry = _oauth_states.pop(state, None)
    if entry is None:
        return HTMLResponse(_callback_page(False, "授权会话无效或已过期，请重新发起扫码", ""))
    origin = entry.get("origin") or ""

    def finish(ok: bool, message: str) -> HTMLResponse:
        _oauth_results[state] = {
            "created": time.time(),
            "result": {"status": "done" if ok else "error", "message": message},
        }
        return HTMLResponse(_callback_page(ok, message, origin))

    if error:
        return finish(False, f"飞书授权被拒绝：{error}")
    if not code:
        return finish(False, "飞书未返回授权码，请重试")

    config = await feishu_minutes.load_config()
    if not (config.app_id and config.app_secret):
        return finish(False, "飞书应用凭据缺失，请先在设置中填写并保存 App ID / App Secret")
    try:
        access, refresh = await feishu_minutes.exchange_code(
            app_id=config.app_id,
            app_secret=config.app_secret,
            code=code,
            redirect_uri=entry["redirect_uri"],
        )
    except feishu_minutes.FeishuError as exc:
        logger.warning("飞书扫码授权失败：%s", exc)
        return finish(False, str(exc))
    await feishu_minutes.store_user_tokens(access, refresh)
    feishu_minutes.prime_access_token(access)
    if not refresh:
        return finish(
            True,
            "已获取用户授权，但飞书未返回刷新令牌（约 2 小时后过期）。"
            "请在开放平台为应用开启 offline_access 权限后重新扫码。",
        )
    return finish(True, "已获取用户授权，飞书妙记转写可用")
