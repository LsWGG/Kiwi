"""主题自定义背景：100MB 图片 / 动图 / 视频的存储与清理。

自定义背景不再塞进 `system_settings` 的 JSONB（data URL 会把单行记录撑大），
而是流式写入媒体存储（本地目录或 S3 / MinIO），覆盖值里只保存站内 URL。
文件类型按魔数判断，不信任扩展名。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from fastapi import UploadFile

from app.services.object_store import ObjectStoreError, get_object_store

MAX_BACKGROUND_BYTES = 100 * 1024 * 1024
UPLOAD_SUBDIR = "theme-backgrounds"
MEDIA_URL_PREFIX = f"/media/{UPLOAD_SUBDIR}/"
CHUNK_SIZE = 1024 * 1024
SNIFF_BYTES = 64 * 1024
# 未被覆盖值引用的上传文件保留 6 小时，给「上传后还没点保存」留出窗口。
ORPHAN_TTL_SECONDS = 6 * 60 * 60

_MP4_BRANDS = {
    b"isom",
    b"iso2",
    b"iso4",
    b"iso5",
    b"iso6",
    b"mp41",
    b"mp42",
    b"avc1",
    b"M4V ",
    b"M4A ",
    b"dash",
    b"3gp4",
    b"3gp5",
}


class BackgroundTooLarge(ValueError):
    pass


class BackgroundUnsupported(ValueError):
    pass


@dataclass(frozen=True)
class BackgroundMedia:
    kind: str  # image | video
    ext: str
    content_type: str


@dataclass(frozen=True)
class StoredBackground:
    url: str
    kind: str
    content_type: str
    size: int


MEDIA_KEY_PREFIX = f"media/{UPLOAD_SUBDIR}/"


def sniff(head: bytes) -> BackgroundMedia | None:
    """按文件头识别图片 / 视频；SVG 等可执行内容不在允许范围内。"""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return BackgroundMedia("image", ".png", "image/png")
    if head.startswith(b"\xff\xd8\xff"):
        return BackgroundMedia("image", ".jpg", "image/jpeg")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return BackgroundMedia("image", ".gif", "image/gif")
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return BackgroundMedia("image", ".webp", "image/webp")
    if head.startswith(b"BM"):
        return BackgroundMedia("image", ".bmp", "image/bmp")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return BackgroundMedia("image", ".avif", "image/avif")
        if brand == b"qt  ":
            return BackgroundMedia("video", ".mov", "video/quicktime")
        if brand in _MP4_BRANDS:
            return BackgroundMedia("video", ".mp4", "video/mp4")
        return None
    if head.startswith(b"\x1aE\xdf\xa3"):
        return BackgroundMedia("video", ".webm", "video/webm")
    if head.startswith(b"OggS"):
        return BackgroundMedia("video", ".ogv", "video/ogg")
    return None


def background_key(url: str | None) -> str | None:
    """只接受 `/media/theme-backgrounds/<文件名>` 形式的站内 URL。"""
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith(MEDIA_URL_PREFIX):
        return None
    name = unquote(parsed.path[len(MEDIA_URL_PREFIX) :])
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        return None
    return f"{MEDIA_KEY_PREFIX}{name}"


def is_local_url(url: str | None) -> bool:
    return background_key(url) is not None


async def save_upload(upload: UploadFile) -> StoredBackground:
    if upload.size is not None and upload.size > MAX_BACKGROUND_BYTES:
        raise BackgroundTooLarge("背景文件不能超过 100MB")

    first = await upload.read(SNIFF_BYTES)
    if not first:
        raise BackgroundUnsupported("背景文件为空")
    media = sniff(first)
    if media is None:
        raise BackgroundUnsupported(
            "仅支持 PNG / APNG / JPEG / GIF / WebP / AVIF / BMP 图片，"
            "或 MP4 / WebM / Ogg / MOV 视频"
        )

    token = uuid.uuid4().hex
    key = f"{MEDIA_KEY_PREFIX}{token}{media.ext}"
    total = 0

    async def chunks():
        nonlocal total
        chunk = first
        while chunk:
            total += len(chunk)
            if total > MAX_BACKGROUND_BYTES:
                raise BackgroundTooLarge("背景文件不能超过 100MB")
            yield chunk
            chunk = await upload.read(CHUNK_SIZE)

    try:
        stored = await get_object_store().save_stream(
            key, chunks(), content_type=media.content_type
        )
    except ObjectStoreError as exc:
        raise BackgroundUnsupported(f"背景文件写入失败：{exc}") from exc

    return StoredBackground(
        url=get_object_store().media_url(key),
        kind=media.kind,
        content_type=media.content_type,
        size=stored.size,
    )


async def remove_url(url: str | None) -> bool:
    key = background_key(url)
    if key is None:
        return False
    store = get_object_store()
    try:
        if await store.stat(key) is None:
            return False
        await store.delete(key)
    except (OSError, ObjectStoreError):
        return False
    return True


async def prune_replaced(old_values: set[str], new_values: set[str]) -> None:
    """覆盖值更新后，删除不再被引用的旧背景文件。"""
    for value in old_values - new_values:
        await remove_url(value)


async def prune_orphans(
    referenced: set[str], *, ttl_seconds: int = ORPHAN_TTL_SECONDS
) -> None:
    """清理长期没有被任何覆盖值引用的上传文件。"""
    cutoff = time.time() - ttl_seconds
    referenced_keys = {
        key for key in (background_key(url) for url in referenced) if key is not None
    }
    store = get_object_store()
    try:
        items = await store.list(f"media/{UPLOAD_SUBDIR}")
    except ObjectStoreError:
        return
    for item in items:
        if item.key in referenced_keys:
            continue
        if item.last_modified is not None and item.last_modified > cutoff:
            continue
        try:
            await store.delete(item.key)
        except (OSError, ObjectStoreError):
            continue
