"""读取笔记内嵌附件（``kiwi-embed`` 文件块）的正文，供问答使用。

编辑器把上传文件保存为 ``/media/<kb_id>/<uuid>.<ext>``，笔记正文里只留下
``kind=file`` 的 JSON 元数据。问答检索拿到分块后，如果不读回文件内容，模型
就只能看到文件名与大小。本模块负责：

- 从 Markdown 中提取 ``kiwi-embed`` 围栏（支持普通 / 引用块、反引号 / 波浪线）；
- 把 ``/media/...`` 解析到上传目录，并阻止越过媒体根目录的路径；
- 读取文本 / 代码文件，PDF、DOCX 复用导入解析器；
- 按字符预算截断，避免单个大文件挤占问答上下文。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from app.config import settings

logger = logging.getLogger(__name__)

# 单文件与单次请求的内容预算。代码文件按字符计，20k 字符约 5k token。
MAX_FILE_CHARS = 20_000
MAX_TOTAL_CHARS = 32_000
MAX_FILES = 3
# 解析 PDF / DOCX 等二进制文档的源文件大小上限，防止异常大文件拖慢问答。
MAX_DOC_BYTES = 20 * 1024 * 1024

TEXT_EXTENSIONS = {
    "txt",
    "text",
    "md",
    "markdown",
    "mdx",
    "rst",
    "log",
    "csv",
    "tsv",
    "json",
    "jsonc",
    "jsonl",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "env",
    "properties",
    "py",
    "pyi",
    "ipynb",
    "js",
    "mjs",
    "cjs",
    "ts",
    "mts",
    "cts",
    "tsx",
    "jsx",
    "vue",
    "svelte",
    "astro",
    "html",
    "htm",
    "css",
    "scss",
    "sass",
    "less",
    "xml",
    "svg",
    "sh",
    "bash",
    "zsh",
    "fish",
    "ps1",
    "psm1",
    "bat",
    "cmd",
    "awk",
    "sed",
    "sql",
    "graphql",
    "gql",
    "proto",
    "c",
    "h",
    "cc",
    "cpp",
    "cxx",
    "hpp",
    "hxx",
    "m",
    "mm",
    "cs",
    "java",
    "kt",
    "kts",
    "scala",
    "groovy",
    "go",
    "rs",
    "rb",
    "php",
    "swift",
    "dart",
    "lua",
    "pl",
    "pm",
    "r",
    "jl",
    "ex",
    "exs",
    "erl",
    "hs",
    "clj",
    "cljs",
    "fs",
    "vb",
    "cmake",
    "gradle",
    "patch",
    "diff",
    "lock",
}

# 没有扩展名但通常是纯文本的文件名。
TEXT_FILENAMES = {
    "dockerfile",
    "makefile",
    "procfile",
    "gemfile",
    "rakefile",
    "requirements.txt",
    ".gitignore",
    ".editorconfig",
}

DOC_EXTENSIONS = {"pdf", "docx", "doc"}

TEXT_CONTENT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-httpd-php",
    "application/x-sh",
    "application/x-python",
    "application/x-yaml",
    "application/yaml",
    "application/sql",
    "application/graphql",
    "application/toml",
}

LANGUAGE_BY_EXT = {
    "py": "python",
    "pyi": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "mts": "typescript",
    "cts": "typescript",
    "tsx": "tsx",
    "jsx": "jsx",
    "vue": "vue",
    "svelte": "svelte",
    "json": "json",
    "jsonc": "json",
    "jsonl": "jsonl",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "md": "markdown",
    "markdown": "markdown",
    "mdx": "mdx",
    "sh": "bash",
    "bash": "bash",
    "zsh": "zsh",
    "ps1": "powershell",
    "bat": "bat",
    "cmd": "bat",
    "sql": "sql",
    "html": "html",
    "htm": "html",
    "css": "css",
    "scss": "scss",
    "xml": "xml",
    "svg": "xml",
    "java": "java",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "hpp": "cpp",
    "cs": "csharp",
    "go": "go",
    "rs": "rust",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "kts": "kotlin",
    "scala": "scala",
    "lua": "lua",
    "r": "r",
    "tex": "latex",
    "graphql": "graphql",
    "gql": "graphql",
    "proto": "protobuf",
}

# 附件常嵌在有序列表 / 引用块里，围栏行前会带缩进或 ``>`` 前缀。
_OPEN_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)$")
_QUOTE_PREFIX_RE = re.compile(r"^(?:[ \t]*>[ \t]?)+")


@dataclass(frozen=True)
class EmbeddedAttachment:
    """一个从笔记正文中读出的附件文件。"""

    filename: str
    url: str
    content_type: str
    size: int
    text: str
    language: str = ""
    truncated: bool = False


def _strip_quote_prefix(line: str) -> str:
    """去掉引用块前缀，使 ``> ```kiwi-embed`` 也能被识别。"""
    return _QUOTE_PREFIX_RE.sub("", line, count=1)


def embedded_file_blocks(body_md: str) -> list[dict]:
    """提取正文中所有 ``kiwi-embed`` 文件块（返回解析后的 JSON 字典）。

    同一文件被重复嵌入时只保留一次；链接卡片（``kind=link``）与损坏的 JSON
    会被忽略，避免把网页卡片当成附件内容。
    """
    blocks: list[dict] = []
    seen_urls: set[str] = set()
    lines = (body_md or "").splitlines()
    index = 0
    while index < len(lines):
        match = _OPEN_FENCE_RE.match(_strip_quote_prefix(lines[index]))
        if not match:
            index += 1
            continue
        fence = match.group("fence")
        info = match.group("info").strip().lower()
        if not info.startswith("kiwi-embed"):
            index += 1
            continue
        content: list[str] = []
        index += 1
        while index < len(lines):
            inner = _strip_quote_prefix(lines[index])
            closing = re.fullmatch(
                rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", inner
            )
            if closing:
                index += 1
                break
            content.append(inner)
            index += 1
        try:
            data = json.loads("\n".join(content).strip() or "{}")
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        kind = str(data.get("kind") or "file").strip().lower()
        url = str(data.get("url") or "").strip()
        if kind != "file" or not url.lower().startswith("/media/"):
            continue
        key = unquote(url)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        blocks.append(data)
    return blocks


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _is_text_file(filename: str, content_type: str) -> bool:
    ext = _extension(filename)
    if ext in TEXT_EXTENSIONS:
        return True
    if not ext and filename.lower() in TEXT_FILENAMES:
        return True
    ctype = content_type.split(";", 1)[0].strip().lower()
    return ctype.startswith("text/") or ctype in TEXT_CONTENT_TYPES


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def _read_text_file(path: Path, max_chars: int) -> tuple[str, bool]:
    # UTF-8 下中文最多 3 字节、emoji 4 字节；多读一点避免截断半个字符。
    max_bytes = max_chars * 4 + 16
    with path.open("rb") as fh:
        raw = fh.read(max_bytes)
    text = _decode_text(raw)
    truncated = len(text) > max_chars or path.stat().st_size > max_bytes
    return text[:max_chars], truncated


def _read_document_file(path: Path, filename: str, max_chars: int) -> tuple[str, bool]:
    # 延迟导入：parser 依赖 OCR 等可选组件，普通文本附件不需要加载。
    from app.services.parser import ParseError, parse_file

    if path.stat().st_size > MAX_DOC_BYTES:
        logger.info("跳过过大的内嵌文档：%s", filename)
        return "", False
    try:
        parsed = parse_file(path, _extension(filename))
    except ParseError as exc:
        logger.info("内嵌文档解析失败（%s）：%s", filename, exc)
        return "", False
    except Exception as exc:  # noqa: BLE001 —— 单个附件失败不影响问答
        logger.info("内嵌文档解析失败（%s）：%s", filename, exc)
        return "", False
    text = (parsed.text or "").strip()
    return text[:max_chars], len(text) > max_chars


def _resolve_media_path(url: str, media_root: Path) -> Path | None:
    """把 ``/media/<kb>/<file>`` 解析到媒体根目录内；越界或不存在返回 None。"""
    raw = unquote(url)
    if not raw.lower().startswith("/media/"):
        return None
    relative = raw[len("/media/") :].lstrip("/")
    if not relative:
        return None
    try:
        root = media_root.resolve()
        target = (root / relative).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return None
    if not target.is_file():
        return None
    return target


def _filename_for(data: dict, path: Path) -> str:
    name = str(data.get("filename") or "").strip()
    return name or path.name


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _language_for(filename: str) -> str:
    return LANGUAGE_BY_EXT.get(_extension(filename), "")


def _match_score(data: dict, filename: str, query: str) -> int:
    """文件名出现在问题中时优先读取；没有命中则按正文顺序。"""
    if not query:
        return 0
    haystack = query.casefold()
    candidates = {
        filename.casefold(),
        Path(filename).stem.casefold(),
        str(data.get("title") or "").strip().casefold(),
    }
    for candidate in candidates:
        if candidate and candidate in haystack:
            return 1
    return 0


def read_embedded_attachments(
    body_md: str,
    *,
    query: str = "",
    media_root: Path | None = None,
    max_files: int = MAX_FILES,
    max_chars: int = MAX_FILE_CHARS,
    total_chars: int = MAX_TOTAL_CHARS,
) -> list[EmbeddedAttachment]:
    """读取笔记里可解析的内嵌文件内容。

    只读取上传目录中的本地文件；链接卡片、远程 URL、图片 / 压缩包等无法
    直接转为文本的附件会被跳过。
    """
    if not body_md or "kiwi-embed" not in body_md:
        return []
    root = media_root if media_root is not None else settings.upload_dir / "media"
    blocks = embedded_file_blocks(body_md)
    if not blocks:
        return []

    ranked: list[tuple[int, int, dict, Path, str]] = []
    for order, data in enumerate(blocks):
        url = str(data.get("url") or "").strip()
        path = _resolve_media_path(url, root)
        if path is None:
            continue
        filename = _filename_for(data, path)
        content_type = str(data.get("content_type") or data.get("contentType") or "").strip()
        ext = _extension(filename)
        if not _is_text_file(filename, content_type) and ext not in DOC_EXTENSIONS:
            continue
        ranked.append((-_match_score(data, filename, query), order, data, path, filename))

    ranked.sort(key=lambda item: (item[0], item[1]))
    matched = [item for item in ranked if item[0] < 0]
    if matched:
        ranked = matched

    results: list[EmbeddedAttachment] = []
    remaining = max(0, total_chars)
    for _score, _order, data, path, filename in ranked:
        if len(results) >= max_files or remaining <= 0:
            break
        budget = min(max_chars, remaining)
        content_type = str(data.get("content_type") or data.get("contentType") or "").strip()
        try:
            if _is_text_file(filename, content_type):
                text, truncated = _read_text_file(path, budget)
            else:
                text, truncated = _read_document_file(path, filename, budget)
        except OSError as exc:
            logger.info("读取内嵌附件失败（%s）：%s", filename, exc)
            continue
        if not text.strip():
            continue
        results.append(
            EmbeddedAttachment(
                filename=filename,
                url=str(data.get("url") or ""),
                content_type=content_type,
                size=_safe_int(data.get("size")) or path.stat().st_size,
                text=text,
                language=_language_for(filename),
                truncated=truncated,
            )
        )
        remaining -= len(text)
    return results


def _fence_for(text: str) -> str:
    runs = re.findall(r"`+", text)
    longest = max((len(run) for run in runs), default=0)
    return "`" * max(3, longest + 1)


def format_attachments_for_context(items: list[EmbeddedAttachment]) -> str:
    """把附件内容格式化为给 LLM 的资料片段（同一笔记内使用）。"""
    if not items:
        return ""
    parts = ["笔记内嵌附件（用户上传文件的正文，可能因长度截断）："]
    for item in items:
        meta = "，".join(
            piece
            for piece in (
                item.content_type,
                f"{item.size} 字节" if item.size else "",
                "已截断" if item.truncated else "",
            )
            if piece
        )
        heading = f"### {item.filename}" + (f"（{meta}）" if meta else "")
        fence = _fence_for(item.text)
        language = item.language
        parts.append(f"{heading}\n{fence}{language}\n{item.text.rstrip()}\n{fence}")
        if item.truncated:
            parts.append("（附件内容过长，以上仅为截断后的前部内容。）")
    return "\n\n".join(parts)
