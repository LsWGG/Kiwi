"""媒体文件服务：本地目录与 S3 / MinIO 共用同一个 ``/media/<key>`` 地址。

访问控制由 AccessControlMiddleware 统一负责（``/media`` 属于受保护路径），
这里只处理存储读取、Range 与缓存头，保持现有笔记正文里的 URL 不变。
"""

from __future__ import annotations

import re
from email.utils import formatdate

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.services.object_store import ObjectStoreError, get_object_store

router = APIRouter(prefix="/media", tags=["media"])

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(value: str, size: int) -> tuple[int, int] | None | str:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        length = int(end_text)
        if length <= 0:
            return None
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    if size <= 0 or start >= size or start > end:
        return "invalid"
    return start, min(end, size - 1)


def _headers(stat, content_length: int) -> dict[str, str]:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": stat.content_type or "application/octet-stream",
        # 媒体键都是 UUID / 内容哈希，内容不会原地变化；鉴权仍由中间件负责。
        "Cache-Control": "private, max-age=86400",
    }
    if stat.etag:
        headers["ETag"] = f'"{stat.etag.strip(chr(34))}"'
    if stat.last_modified:
        headers["Last-Modified"] = formatdate(stat.last_modified, usegmt=True)
    return headers


@router.api_route("/{path:path}", methods=["GET", "HEAD"])
async def serve_media(path: str, request: Request):
    store = get_object_store()
    key = f"media/{path}"
    try:
        stat = await store.stat(key)
    except ObjectStoreError as e:
        raise HTTPException(400, str(e)) from e
    if stat is None:
        raise HTTPException(404, "媒体文件不存在")

    etag = f'"{stat.etag.strip(chr(34))}"' if stat.etag else ""
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    start, end = 0, stat.size - 1
    status_code = 200
    range_header = request.headers.get("range")
    if range_header:
        parsed = _parse_range(range_header, stat.size)
        if parsed == "invalid":
            return Response(
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{stat.size}",
                    "Accept-Ranges": "bytes",
                },
            )
        if parsed is not None:
            start, end = parsed
            status_code = 206

    content_length = max(0, end - start + 1)
    headers = _headers(stat, content_length)
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{stat.size}"

    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)

    async def body():
        if status_code == 206:
            stream = store.open(key, start=start, end=end)
        else:
            stream = store.open(key)
        async for chunk in stream:
            yield chunk

    return StreamingResponse(
        body(), status_code=status_code, headers=headers, media_type=None
    )
