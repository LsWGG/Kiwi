"""Markdown 压缩包导入：md 原文 + 图片 / 附件目录。

很多工具（Obsidian、Typora、语雀导出等）会把 Markdown 与它引用的图片、
附件一起打包成 zip。直接导入 md 时相对路径全部失效，正文看不到图片。
这里统一处理：

- 复用 ``file_security.inspect_archive`` 做 ZIP 炸弹 / 加密条目 / 病毒扫描；
- 选择一个主 Markdown（单个 md；多个时优先与压缩包同名、根目录、层级最浅）；
- 把压缩包内其余文件逐个落盘到 ``/media/<kb>``，并建立 ``NoteAttachment``；
- 把 md 里的相对图片 / 附件引用（Markdown 内联、引用式、HTML、Obsidian
  ``![[...]]``）重写为可访问的 ``/media/...`` URL。

导入后的笔记就是普通 Markdown 正文，图片与附件直接可见、可下载。
"""

from __future__ import annotations

import mimetypes
import posixpath
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import NoteAttachment
from app.services.file_security import FileRejected, inspect_archive

MD_EXT = {".md", ".markdown"}
JUNK_DIRS = {"__macosx", ".git", ".svn", ".idea", ".vscode"}
JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
EXEC_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
)

MAX_BUNDLE_FILES = 2000
MAX_BUNDLE_TOTAL_BYTES = 300 * 1024 * 1024
MAX_MARKDOWN_BYTES = 20 * 1024 * 1024


class MdBundleError(Exception):
    """压缩包无法按 Markdown 包导入。"""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ImportedBundle:
    title: str
    markdown: str
    main_entry: str
    attachments: list[NoteAttachment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rewritten_refs: int = 0


def _safe_entry(name: str) -> str | None:
    """规范 zip 内路径；拒绝绝对路径与 ``..`` 穿越。"""
    normalized = (name or "").replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        return None
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _is_junk(entry: str) -> bool:
    parts = entry.split("/")
    if any(part.lower() in JUNK_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    lowered = name.lower()
    if lowered in JUNK_FILES or name.startswith("._"):
        return True
    return False


def _decode_text(data: bytes) -> str:
    """优先 UTF-8（含 BOM），其次 GB18030；都失败时替换非法字符。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _safe_ext(entry: str) -> str:
    ext = Path(entry).suffix.lower()
    return re.sub(r"[^a-z0-9.]", "", ext)[:16]


def _content_type(entry: str) -> str:
    return mimetypes.guess_type(entry)[0] or "application/octet-stream"


def _pick_main_entry(entries: list[tuple[str, object]], filename: str) -> str:
    """从多个 md 中挑主文档：同名 > 根目录 > 层级浅 > 字典序。"""
    stem = Path(filename or "").stem.strip().lower()

    def rank(item: tuple[str, object]) -> tuple:
        entry = item[0]
        base = posixpath.basename(entry).lower()
        entry_stem = posixpath.splitext(base)[0]
        depth = entry.count("/")
        return (
            0 if stem and entry_stem == stem else 1,
            0 if depth == 0 else 1,
            depth,
            entry.lower(),
        )

    return min(entries, key=rank)[0]


def _clean_heading(text: str) -> str:
    value = text.strip()
    value = re.sub(r"\s+#+\s*$", "", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_`~]+", "", value)
    return value.strip()[:300]


def _title_from_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    # YAML frontmatter 的 title 优先（Obsidian / Hexo 等常见导出格式）。
    if lines and lines[0].strip() == "---":
        end = None
        for index, line in enumerate(lines[1:60], start=1):
            stripped = line.strip()
            if stripped == "---":
                end = index
                break
            match = re.match(r"(?i)^title\s*:\s*(.+)$", stripped)
            if match:
                value = match.group(1).strip().strip("'\"")
                if value:
                    return value[:300]
        if end is not None:
            lines = lines[end + 1 :]
    for line in lines:
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            title = _clean_heading(match.group(1))
            if title:
                return title
    return ""


def _make_resolver(
    base_dir: str, url_by_entry: dict[str, str]
) -> Callable[[str], str | None]:
    lower_map = {entry.lower(): url for entry, url in url_by_entry.items()}

    def resolve(raw: str) -> str | None:
        target = (raw or "").strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if not target:
            return None
        lowered = target.lower()
        if lowered.startswith(
            ("#", "/", "data:", "mailto:", "tel:", "javascript:", "file:")
        ):
            return None
        if re.match(r"^[a-z][a-z0-9+.-]*://", lowered):
            return None
        target = target.split("#", 1)[0].split("?", 1)[0]
        if not target:
            return None
        try:
            decoded = urllib.parse.unquote(target)
        except Exception:  # noqa: BLE001 - 非法百分号编码按原样处理
            decoded = target
        decoded = decoded.replace("\\", "/")
        entry = (
            posixpath.normpath(posixpath.join(base_dir, decoded))
            if base_dir
            else posixpath.normpath(decoded)
        )
        if entry.startswith(".."):
            return None
        return url_by_entry.get(entry) or lower_map.get(entry.lower())

    return resolve


_INLINE_LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^)\n]*)(\))")
_REF_DEF = re.compile(r"(?m)^(\s{0,3}\[[^\]\n]+\]:\s*)(<[^>]*>|\S+)")
_HTML_ATTR = re.compile(r"""((?:src|href)\s*=\s*)(["'])([^"']+)\2""", re.IGNORECASE)
_WIKI_EMBED = re.compile(r"(!?\[\[)([^\]|#\n]+)(\|[^\]\n]*)?(\]\])")
_INNER_TARGET = re.compile(
    r"""^(\s*)(<[^>]*>|[^\s"']+)(\s+(?:"[^"]*"|'[^']*'))?(\s*)$"""
)


def _rewrite_inner(inner: str, resolve: Callable[[str], str | None]) -> str | None:
    match = _INNER_TARGET.match(inner)
    if match:
        lead, target, title, tail = match.groups()
        url = resolve(target)
        if url is None:
            return None
        return f"{lead}{url}{title or ''}{tail}"
    # 路径含未编码空格：整体当作目标，保留首尾空白。
    stripped = inner.strip()
    url = resolve(stripped)
    if url is None:
        return None
    return inner.replace(stripped, url, 1)


def rewrite_markdown_refs(
    markdown: str, base_dir: str, url_by_entry: dict[str, str]
) -> tuple[str, int]:
    """把 md 中指向压缩包内文件的引用重写为 /media URL，返回 (新 md, 替换数)。"""
    if not url_by_entry:
        return markdown, 0
    resolve = _make_resolver(base_dir, url_by_entry)
    count = 0

    def inline_repl(match: re.Match[str]) -> str:
        nonlocal count
        rewritten = _rewrite_inner(match.group(2), resolve)
        if rewritten is None:
            return match.group(0)
        count += 1
        return f"{match.group(1)}{rewritten}{match.group(3)}"

    markdown = _INLINE_LINK.sub(inline_repl, markdown)

    def ref_repl(match: re.Match[str]) -> str:
        nonlocal count
        url = resolve(match.group(2))
        if url is None:
            return match.group(0)
        count += 1
        return f"{match.group(1)}{url}"

    # 引用式链接定义要在内联替换之后处理，避免把新 URL 再匹配一次。
    markdown = _REF_DEF.sub(ref_repl, markdown)

    def html_repl(match: re.Match[str]) -> str:
        nonlocal count
        url = resolve(match.group(3))
        if url is None:
            return match.group(0)
        count += 1
        return f"{match.group(1)}{match.group(2)}{url}{match.group(2)}"

    markdown = _HTML_ATTR.sub(html_repl, markdown)

    def wiki_repl(match: re.Match[str]) -> str:
        nonlocal count
        url = resolve(match.group(2))
        if url is None:
            return match.group(0)
        count += 1
        suffix = match.group(3) or ""
        return f"{match.group(1)}{url}{suffix}{match.group(4)}"

    markdown = _WIKI_EMBED.sub(wiki_repl, markdown)
    return markdown, count


async def import_md_bundle(
    session: AsyncSession,
    *,
    kb_id: uuid.UUID,
    note_id: uuid.UUID | None,
    content: bytes,
    filename: str,
    user_title: str | None = None,
    require_markdown: bool = True,
) -> ImportedBundle | None:
    """解析 Markdown 压缩包并把资源落盘为附件。

    返回 ``None`` 仅发生在 ``require_markdown=False`` 且包内没有 Markdown 时；
    调用方负责提交事务（本函数只 ``flush`` 取得附件 id）。
    """
    try:
        archive = inspect_archive(content, filename)
    except FileRejected as exc:
        raise MdBundleError(exc.message, exc.status_code) from exc

    written: list[Path] = []
    try:
        entries: list[tuple[str, object]] = []
        warnings: list[str] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            entry = _safe_entry(info.filename)
            if entry is None:
                warnings.append(f"已跳过不安全的路径：{info.filename[:120]}")
                continue
            if _is_junk(entry):
                continue
            entries.append((entry, info))

        md_entries = [
            (entry, info)
            for entry, info in entries
            if Path(entry).suffix.lower() in MD_EXT
        ]
        if not md_entries:
            if require_markdown:
                raise MdBundleError(
                    "压缩包内未找到 Markdown 文件（.md / .markdown）", 422
                )
            return None

        main_entry = _pick_main_entry(md_entries, filename)
        md_info = next(info for entry, info in md_entries if entry == main_entry)
        if md_info.file_size > MAX_MARKDOWN_BYTES:
            raise MdBundleError("Markdown 文件超过 20MB，无法导入", 413)
        markdown = _decode_text(archive.read(md_info))
        base_dir = posixpath.dirname(main_entry)

        storage_dir = settings.upload_dir / "media" / str(kb_id)
        storage_dir.mkdir(parents=True, exist_ok=True)

        url_by_entry: dict[str, str] = {}
        attachments: list[NoteAttachment] = []
        total_bytes = 0
        skipped = 0
        for entry, info in entries:
            if entry == main_entry:
                continue
            if len(attachments) >= MAX_BUNDLE_FILES:
                skipped += 1
                continue
            if info.file_size > MAX_BUNDLE_TOTAL_BYTES - total_bytes:
                warnings.append(f"压缩包内容超过大小上限，已跳过：{entry[:120]}")
                skipped += 1
                continue

            ext = _safe_ext(entry)
            stored_name = f"{uuid.uuid4().hex}{ext}"
            target = storage_dir / stored_name
            try:
                with archive.open(info) as src, target.open("wb") as out:
                    head = src.read(8)
                    if any(head.startswith(magic) for magic in EXEC_MAGIC):
                        warnings.append(f"已跳过可执行文件：{entry[:120]}")
                        skipped += 1
                        target.unlink(missing_ok=True)
                        continue
                    out.write(head)
                    while chunk := src.read(1024 * 1024):
                        out.write(chunk)
            except OSError as exc:
                target.unlink(missing_ok=True)
                raise MdBundleError(f"附件写入失败，请检查磁盘空间：{exc}", 500) from exc
            written.append(target)
            size = target.stat().st_size
            total_bytes += size
            attachment = NoteAttachment(
                kb_id=kb_id,
                note_id=note_id,
                filename=(posixpath.basename(entry) or f"文件{ext}")[:300],
                content_type=_content_type(entry)[:120],
                size=size,
                storage_path=f"{kb_id}/{stored_name}",
            )
            session.add(attachment)
            attachments.append(attachment)
            url_by_entry[entry] = f"/media/{kb_id}/{stored_name}"

        if skipped:
            warnings.append(f"另有 {skipped} 个文件未导入（数量 / 大小限制）")

        rewritten, count = rewrite_markdown_refs(markdown, base_dir, url_by_entry)
        title = (
            (user_title or "").strip()
            or _title_from_markdown(rewritten)
            or Path(main_entry).stem
            or "Markdown 笔记"
        )
        await session.flush()
        return ImportedBundle(
            title=title[:300],
            markdown=rewritten,
            main_entry=main_entry,
            attachments=attachments,
            warnings=warnings,
            rewritten_refs=count,
        )
    except Exception:
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        archive.close()
