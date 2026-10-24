"""飞书妙记线上转写：云空间上传 → 生成妙记 → 导出逐字稿。

妙记的上传接口只接受 ``user_access_token``（应用身份无法直接生成妙记），
因此配置里保存一个用户令牌，或者「应用凭据 + refresh_token」自动续期。
refresh_token 每次刷新都会轮换，刷新成功后立即加密回写到系统设置，
避免进程重启后拿着已失效的旧令牌。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.db.session import async_session_factory
from app.services.llm_factory import LLMCrypto

logger = logging.getLogger("kiwi.feishu")

BASE_URL = "https://open.feishu.cn"
TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"
AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
# 妙记上传/导出与云空间读写；offline_access 用于拿到可续期的 refresh_token。
DEFAULT_SCOPES = (
    "drive:drive",
    "minutes:minutes.upload:write",
    "minutes:minutes.transcript:export",
    "offline_access",
)
UPLOAD_ALL_LIMIT = 20 * 1024 * 1024
DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024
MINUTE_POLL_SECONDS = 5.0
MINUTE_TIMEOUT_SECONDS = 20 * 60.0
TOKEN_REFRESH_MARGIN = 300.0

# 妙记异步生成中；继续轮询即可。
MINUTE_NOT_READY = 2091003

ERROR_HINTS = {
    20005: "飞书用户令牌无效或已过期",
    20037: "飞书刷新令牌已失效，请重新授权",
    99991663: "飞书用户令牌无效或已过期",
    2091001: "飞书妙记参数无效",
    2091002: "飞书妙记不存在或已被删除",
    2091006: "飞书妙记服务内部错误，请稍后重试",
    2091007: "飞书云空间文件无下载权限",
    2091008: "飞书妙记 ASR 额度不足",
    2091009: "飞书妙记无上传权限（安全策略管控）",
    2091010: "飞书妙记导入过于频繁，请稍后再试",
    2091011: "飞书妙记存储额度不足",
    2091012: "飞书云文档无下载权限",
}


class FeishuError(RuntimeError):
    """飞书接口不可用或返回业务错误。"""


class FeishuNotConfigured(FeishuError):
    """未配置可用的飞书妙记凭据。"""


@dataclass
class FeishuConfig:
    provider: str = "auto"
    app_id: str = ""
    app_secret: str = ""
    user_token: str = ""
    refresh_token: str = ""
    folder_token: str = ""

    @property
    def can_use(self) -> bool:
        if self.user_token:
            return True
        return bool(self.app_id and self.app_secret and self.refresh_token)


_token_lock = asyncio.Lock()
_cached_access_token = ""
_cached_access_expires = 0.0


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return LLMCrypto.decrypt(value)
    except Exception:  # noqa: BLE001 - 密钥损坏时按未配置处理
        logger.warning("飞书凭据解密失败，按未配置处理")
        return ""


def config_from_row(row: SystemSettings | None) -> FeishuConfig:
    if row is None:
        return FeishuConfig()
    return FeishuConfig(
        provider=row.transcribe_provider or "auto",
        app_id=(row.feishu_app_id or "").strip(),
        app_secret=_decrypt(row.feishu_app_secret_encrypted),
        user_token=_decrypt(row.feishu_user_token_encrypted),
        refresh_token=_decrypt(row.feishu_refresh_token_encrypted),
        folder_token=(row.feishu_folder_token or "").strip(),
    )


async def load_config(session: AsyncSession | None = None) -> FeishuConfig:
    if session is not None:
        return config_from_row(await session.get(SystemSettings, SYSTEM_SETTINGS_ID))
    async with async_session_factory() as db:
        return config_from_row(await db.get(SystemSettings, SYSTEM_SETTINGS_ID))


async def _persist_refresh_token(refresh_token: str) -> None:
    """刷新令牌轮换后立即回写；失败只记录日志，不阻断本次转写。"""
    try:
        async with async_session_factory() as session:
            row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
            if row is None:
                return
            row.feishu_refresh_token_encrypted = LLMCrypto.encrypt(refresh_token)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("回写飞书 refresh_token 失败：%s", exc)


def _error_message(code: int | None, msg: str | None) -> str:
    if code and code in ERROR_HINTS:
        return f"{ERROR_HINTS[code]}（错误码 {code}）"
    detail = (msg or "").strip()
    return f"飞书接口调用失败：{detail}" if detail else "飞书接口调用失败"


async def _token_request(payload: dict, *, action: str) -> dict:
    """调用飞书 v3 OAuth 令牌端点（表单编码，兼容 RFC 6749）。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(TOKEN_URL, data=payload)
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise FeishuError(f"{action}失败：{exc}") from exc
    if not isinstance(data, dict):
        raise FeishuError(f"{action}失败：返回格式异常")
    code = data.get("code")
    error = data.get("error")
    if resp.status_code >= 400 or error or code not in (None, 0):
        detail = (
            data.get("error_description")
            or data.get("msg")
            or error
            or f"HTTP {resp.status_code}"
        )
        raise FeishuError(f"{action}失败：{detail}")
    return data


def _token_payload(data: dict) -> tuple[str, float, str]:
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    token = str(body.get("access_token") or "")
    if not token:
        raise FeishuError("飞书授权失败：未返回 access_token")
    expires_in = float(body.get("expires_in") or 7200)
    refresh = str(body.get("refresh_token") or "")
    return token, expires_in, refresh


def prime_access_token(token: str, expires_in: float = 7200.0) -> None:
    """扫码授权拿到新令牌后注入缓存，避免立即再刷新一次。"""
    global _cached_access_token, _cached_access_expires
    _cached_access_token = token
    _cached_access_expires = time.time() + max(60.0, expires_in - TOKEN_REFRESH_MARGIN)


def build_authorize_url(app_id: str, redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(DEFAULT_SCOPES),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    *, app_id: str, app_secret: str, code: str, redirect_uri: str
) -> tuple[str, str]:
    """授权码换 user_access_token / refresh_token。"""
    data = await _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        action="飞书授权码换令牌",
    )
    token, _expires_in, refresh = _token_payload(data)
    return token, refresh


async def store_user_tokens(access_token: str, refresh_token: str) -> None:
    """加密保存扫码授权结果（只覆盖非空字段）。"""
    async with async_session_factory() as session:
        row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
        if row is None:
            row = SystemSettings(id=SYSTEM_SETTINGS_ID)
            session.add(row)
        if access_token:
            row.feishu_user_token_encrypted = LLMCrypto.encrypt(access_token)
        if refresh_token:
            row.feishu_refresh_token_encrypted = LLMCrypto.encrypt(refresh_token)
        await session.commit()


async def _refresh_access_token(config: FeishuConfig) -> str:
    global _cached_access_token, _cached_access_expires

    async with _token_lock:
        if _cached_access_token and time.time() < _cached_access_expires:
            return _cached_access_token
        if not (config.app_id and config.app_secret and config.refresh_token):
            raise FeishuNotConfigured("飞书妙记缺少应用凭据或刷新令牌")

        data = await _token_request(
            {
                "grant_type": "refresh_token",
                "client_id": config.app_id,
                "client_secret": config.app_secret,
                "refresh_token": config.refresh_token,
            },
            action="飞书授权刷新",
        )
        token, expires_in, new_refresh = _token_payload(data)
        _cached_access_token = token
        _cached_access_expires = time.time() + max(60.0, expires_in - TOKEN_REFRESH_MARGIN)
        if new_refresh and new_refresh != config.refresh_token:
            await _persist_refresh_token(new_refresh)
        return _cached_access_token


async def access_token(config: FeishuConfig) -> str:
    """优先用 refresh_token 续期；没有刷新令牌时直接使用粘贴的用户令牌。"""
    if config.app_id and config.app_secret and config.refresh_token:
        return await _refresh_access_token(config)
    if config.user_token:
        return config.user_token
    raise FeishuNotConfigured("飞书妙记未配置用户访问令牌")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _json(resp: httpx.Response, action: str) -> dict:
    try:
        data = resp.json()
    except ValueError as exc:
        raise FeishuError(f"{action}失败：HTTP {resp.status_code}") from exc
    if not isinstance(data, dict):
        raise FeishuError(f"{action}失败：返回格式异常")
    return data


def _check_json(data: dict, *, action: str) -> dict:
    code = data.get("code")
    if code not in (0, None):
        raise FeishuError(f"{action}失败：{_error_message(code, data.get('msg'))}")
    return data.get("data") or {}


async def _root_folder(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.get(
        f"{BASE_URL}/open-apis/drive/explorer/v2/root_folder/meta",
        headers=_headers(token),
    )
    data = _check_json(_json(resp, "读取飞书云空间根目录"), action="读取飞书云空间根目录")
    folder = str(data.get("token") or "")
    if not folder:
        raise FeishuError("读取飞书云空间根目录失败：未返回文件夹 token")
    return folder


async def _upload_drive_file(
    client: httpx.AsyncClient, token: str, folder: str, path: Path, file_name: str = ""
) -> str:
    size = path.stat().st_size
    name = (file_name or path.name)[:250]
    headers = _headers(token)
    if size <= UPLOAD_ALL_LIMIT:
        with path.open("rb") as fh:
            resp = await client.post(
                f"{BASE_URL}/open-apis/drive/v1/files/upload_all",
                headers=headers,
                data={
                    "file_name": name,
                    "parent_type": "explorer",
                    "parent_node": folder,
                    "size": str(size),
                },
                files={"file": (name, fh, "application/octet-stream")},
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
        data = _check_json(_json(resp, "上传录音到飞书云空间"), action="上传录音到飞书云空间")
        file_token = str(data.get("file_token") or "")
        if not file_token:
            raise FeishuError("上传录音到飞书云空间失败：未返回 file_token")
        return file_token

    # 超过 20MB 使用分片上传：预上传 → 逐片上传 → 完成。
    resp = await client.post(
        f"{BASE_URL}/open-apis/drive/v1/files/upload_prepare",
        headers=headers,
        json={
            "file_name": name,
            "parent_type": "explorer",
            "parent_node": folder,
            "size": size,
        },
    )
    data = _check_json(_json(resp, "初始化飞书分片上传"), action="初始化飞书分片上传")
    upload_id = str(data.get("upload_id") or "")
    block_size = int(data.get("block_size") or DEFAULT_BLOCK_SIZE)
    block_num = int(data.get("block_num") or 0)
    if not upload_id or block_num <= 0:
        raise FeishuError("初始化飞书分片上传失败：返回参数不完整")

    with path.open("rb") as fh:
        for seq in range(block_num):
            chunk = fh.read(block_size)
            if not chunk:
                break
            resp = await client.post(
                f"{BASE_URL}/open-apis/drive/v1/files/upload_part",
                headers=headers,
                data={
                    "upload_id": upload_id,
                    "seq": str(seq),
                    "size": str(len(chunk)),
                },
                files={"file": (name, chunk, "application/octet-stream")},
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
            _check_json(
                _json(resp, f"上传飞书分片 {seq + 1}/{block_num}"),
                action=f"上传飞书分片 {seq + 1}/{block_num}",
            )

    resp = await client.post(
        f"{BASE_URL}/open-apis/drive/v1/files/upload_finish",
        headers=headers,
        json={"upload_id": upload_id, "block_num": block_num},
    )
    data = _check_json(_json(resp, "完成飞书分片上传"), action="完成飞书分片上传")
    file_token = str(data.get("file_token") or "")
    if not file_token:
        raise FeishuError("完成飞书分片上传失败：未返回 file_token")
    return file_token


def minute_token_from_url(minute_url: str) -> str:
    path = urlsplit(minute_url).path.rstrip("/")
    token = path.rsplit("/", 1)[-1] if path else ""
    if not token:
        raise FeishuError("飞书妙记返回的链接无效")
    return token


_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis.ljust(3, "0")) / 1000
    )


def parse_srt(content: str) -> list[dict]:
    """把飞书导出的 SRT 转成 [{start,end,text}]；忽略无法解析的块。"""
    text = (content or "").lstrip("﻿").replace("\r\n", "\n")
    segments: list[dict] = []
    seen: set[tuple[float, float, str]] = set()
    for block in re.split(r"\n{2,}", text):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        time_index = next(
            (index for index, line in enumerate(lines) if _SRT_TIME.search(line)), None
        )
        if time_index is None:
            continue
        match = _SRT_TIME.search(lines[time_index])
        if match is None:
            continue
        body = " ".join(lines[time_index + 1 :]).strip()
        if not body:
            continue
        start = _seconds(*match.groups()[:4])
        end = _seconds(*match.groups()[4:])
        key = (start, end, body)
        if key in seen:
            continue
        seen.add(key)
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": body})
    segments.sort(key=lambda item: item["start"])
    return segments


async def _export_transcript(
    client: httpx.AsyncClient, token: str, minute_token: str
) -> str:
    url = (
        f"{BASE_URL}/open-apis/minutes/v1/minutes/"
        f"{quote(minute_token, safe='')}/transcript"
    )
    deadline = time.monotonic() + MINUTE_TIMEOUT_SECONDS
    last_error = ""
    while time.monotonic() < deadline:
        try:
            resp = await client.get(
                url,
                headers=_headers(token),
                params={
                    "need_speaker": "false",
                    "need_timestamp": "true",
                    "file_format": "srt",
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            last_error = f"拉取飞书逐字稿失败：{exc}"
            await asyncio.sleep(MINUTE_POLL_SECONDS)
            continue

        content_type = resp.headers.get("content-type", "")
        if resp.status_code < 400 and "json" not in content_type:
            body = resp.text
            if body.strip():
                return body
            # 空响应通常表示仍在生成，继续等。
            await asyncio.sleep(MINUTE_POLL_SECONDS)
            continue

        try:
            data = resp.json()
        except ValueError:
            last_error = f"拉取飞书逐字稿失败：HTTP {resp.status_code}"
            await asyncio.sleep(MINUTE_POLL_SECONDS)
            continue

        code = data.get("code")
        if code == MINUTE_NOT_READY:
            await asyncio.sleep(MINUTE_POLL_SECONDS)
            continue
        raise FeishuError(
            f"拉取飞书逐字稿失败：{_error_message(code, data.get('msg'))}"
        )

    raise FeishuError(last_error or "飞书妙记生成超时，请稍后重试")


async def transcribe_audio(
    path: Path,
    *,
    original_name: str = "",
    config: FeishuConfig | None = None,
) -> dict:
    """上传本地音频到飞书妙记并等待逐字稿，返回与本地转写一致的结构。"""
    cfg = config or await load_config()
    if not cfg.can_use:
        raise FeishuNotConfigured("飞书妙记未配置用户访问令牌")
    if not path.exists():
        raise FeishuError("音频文件不存在或已被清理")

    token = await access_token(cfg)
    async with httpx.AsyncClient(timeout=60.0) as client:
        folder = cfg.folder_token or await _root_folder(client, token)
        file_token = await _upload_drive_file(
            client, token, folder, path, original_name or path.name
        )

        resp = await client.post(
            f"{BASE_URL}/open-apis/minutes/v1/minutes/upload",
            headers=_headers(token),
            json={"file_token": file_token},
        )
        data = _check_json(_json(resp, "生成飞书妙记"), action="生成飞书妙记")
        minute_url = str(data.get("minute_url") or "")
        if not minute_url:
            raise FeishuError("生成飞书妙记失败：未返回妙记链接")

        minute_token = minute_token_from_url(minute_url)
        transcript = await _export_transcript(client, token, minute_token)

    segments = parse_srt(transcript)
    text = "\n".join(item["text"] for item in segments).strip()
    if not text and transcript.strip():
        text = transcript.strip()
        segments = [{"start": 0.0, "end": 0.0, "text": text}]
    duration = segments[-1]["end"] if segments else 0.0
    return {
        "text": text,
        "segments": segments,
        "language": "",
        "language_probability": 0.0,
        "duration": round(float(duration), 2),
        "provider": "feishu",
        "minute_url": minute_url,
    }


async def test_connection(config: FeishuConfig | None = None) -> tuple[bool, str]:
    cfg = config or await load_config()
    if not cfg.can_use:
        return False, "尚未配置飞书妙记用户令牌或刷新令牌"
    try:
        token = await access_token(cfg)
        async with httpx.AsyncClient(timeout=30.0) as client:
            await _root_folder(client, token)
        return True, "飞书授权有效，可访问云空间并生成妙记"
    except FeishuError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("测试飞书妙记连接失败：%s", exc)
        return False, f"测试连接失败：{exc}"


def new_recording_name(suffix: str = ".webm") -> str:
    return f"kiwi-recording-{uuid.uuid4().hex[:12]}{suffix}"
