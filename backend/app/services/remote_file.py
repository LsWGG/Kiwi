"""线上文件导入：按 URL 下载原始文件，复用链接抓取的 SSRF 防护。

与 link_fetcher 的区别：这里期望目标是 PDF / Word / Markdown / 文本文件，
返回原始字节交给统一入库流水线（解析、切片、向量化、可选编译）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.services.link_fetcher import (
    LinkFetchError,
    SSRFError,
    ensure_public_url,
    normalize_url,
)

MAX_REMOTE_FILE_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = httpx.Timeout(30.0, connect=10.0, read=60.0)
MAX_REDIRECTS = 5
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 KiwiImport/1.0"
)
ALLOWED_EXT = {".md", ".markdown", ".txt", ".text", ".pdf", ".docx", ".doc"}
HTML_TYPES = ("text/html", "application/xhtml+xml")
CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/x-msword": ".doc",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/plain": ".txt",
}
_DISPOSITION_STAR = re.compile(r"filename\*\s*=\s*([^;]+)", re.IGNORECASE)
_DISPOSITION = re.compile(r'filename\s*=\s*"([^"]+)"', re.IGNORECASE)
_DISPOSITION_BARE = re.compile(r"filename\s*=\s*([^;]+)", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class RemoteFile:
    url: str
    final_url: str
    filename: str
    content: bytes
    content_type: str


def _clean_filename(raw: str) -> str:
    name = unquote(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    return name[:200]


def _filename_from_disposition(value: str) -> str:
    match = _DISPOSITION_STAR.search(value or "")
    if match:
        raw = match.group(1).strip().strip('"')
        if "''" in raw:
            charset, _, encoded = raw.partition("''")
            try:
                return _clean_filename(unquote(encoded, encoding=charset or "utf-8"))
            except LookupError:
                return _clean_filename(unquote(encoded))
        return _clean_filename(raw)
    match = _DISPOSITION.search(value or "") or _DISPOSITION_BARE.search(value or "")
    return _clean_filename(match.group(1).strip()) if match else ""


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    return _clean_filename(Path(parsed.path).name)


def _resolve_filename(final_url: str, disposition: str, content_type: str) -> str:
    """按 Content-Disposition → URL 路径 → Content-Type 的顺序确定文件名。"""
    name = _filename_from_disposition(disposition) or _filename_from_url(final_url)
    suffix = Path(name).suffix.lower()
    if suffix in ALLOWED_EXT:
        return name

    mapped = CONTENT_TYPE_EXT.get(content_type)
    if mapped is None:
        raise LinkFetchError(
            "链接不是可导入的文件（仅支持 PDF / Word / Markdown / 文本直链）"
        )
    stem = Path(name).stem.strip() if name and suffix else (name or "线上文件")
    return f"{stem[:190]}{mapped}"


async def _download(url: str) -> tuple[str, bytes, str, str]:
    """返回 (final_url, content, content_type, content_disposition)。"""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await ensure_public_url(current)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise LinkFetchError("重定向缺少目标地址")
                        current = urljoin(current, location)
                        parsed = urlparse(current)
                        if parsed.scheme not in ("http", "https"):
                            raise LinkFetchError("重定向到不支持的协议")
                        continue
                    if resp.status_code >= 400:
                        raise LinkFetchError(f"下载失败：目标返回 {resp.status_code}")

                    content_type = (
                        (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                    )
                    if content_type in HTML_TYPES:
                        raise LinkFetchError(
                            "该链接是网页而不是文件；网页内容请使用「新建 → 链接」导入"
                        )
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_REMOTE_FILE_BYTES:
                        raise LinkFetchError("线上文件超过 50MB 上限")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_REMOTE_FILE_BYTES:
                            raise LinkFetchError("线上文件超过 50MB 上限")
                        chunks.append(chunk)
                    return (
                        current,
                        b"".join(chunks),
                        content_type,
                        resp.headers.get("content-disposition") or "",
                    )
            except httpx.HTTPError as exc:
                raise LinkFetchError(f"下载失败：{exc}") from exc
    raise LinkFetchError("重定向次数过多")


async def fetch_remote_file(raw_url: str) -> RemoteFile:
    """下载线上文件；URL 非法或目标不可访问时抛 LinkFetchError。"""
    url = normalize_url(raw_url)
    final_url, content, content_type, disposition = await _download(url)
    filename = _resolve_filename(final_url, disposition, content_type)
    return RemoteFile(
        url=url,
        final_url=final_url,
        filename=filename,
        content=content,
        content_type=content_type,
    )


__all__ = [
    "LinkFetchError",
    "RemoteFile",
    "SSRFError",
    "fetch_remote_file",
    "MAX_REMOTE_FILE_BYTES",
]
