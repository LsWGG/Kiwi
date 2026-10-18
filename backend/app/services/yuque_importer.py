"""语雀导入适配器：令牌直连 + Markdown 导出包。

两条路径都归一化为 ImportItem，复用同一 ingest 流水线。
令牌仅用于本次请求，不落库、不写日志。
"""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import httpx

YUQUE_API = "https://www.yuque.com/api/v2"
MAX_DOCS = 1000


class YuqueError(Exception):
    pass


@dataclass
class ImportItem:
    title: str
    markdown: str
    external_id: str
    source_url: str = ""
    content_updated_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    # 语雀目录树中的父级标题链（不含知识库根），用于在笔记工作区还原分组。
    folder_path: tuple[str, ...] = ()

    def as_bytes(self) -> bytes:
        return self.markdown.encode("utf-8")

    def filename(self) -> str:
        safe = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", self.title).strip()[:120]
        return f"{safe or 'yuque-doc'}.md"


# --------------------------------------------------------------------------- #
# HTML / Lake → Markdown（轻量转换，覆盖语雀常见块）
# --------------------------------------------------------------------------- #
def _inline(node) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        content = _inline(child)
        if tag in ("strong", "b"):
            parts.append(f"**{content.strip()}**" if content.strip() else "")
        elif tag in ("em", "i"):
            parts.append(f"*{content.strip()}*" if content.strip() else "")
        elif tag == "code":
            parts.append(f"`{content}`")
        elif tag == "a":
            href = child.get("href") or ""
            label = content.strip() or href
            parts.append(f"[{label}]({href})" if href else label)
        elif tag == "img":
            src = child.get("src") or ""
            alt = child.get("alt") or ""
            parts.append(f"![{alt}]({src})" if src else "")
        elif tag == "br":
            parts.append("\n")
        elif tag in ("span", "font", "u", "s", "del", "sup", "sub"):
            parts.append(content)
        elif isinstance(child.tag, str) and child.tag.startswith(("lake-", "ne-")):
            parts.append(content)
        else:
            parts.append(content)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _render_list(node, ordered: bool, depth: int = 0) -> str:
    lines: list[str] = []
    index = 1
    for li in node:
        if li.tag not in ("li", "lake-li"):
            continue
        text = _inline(li).strip()
        prefix = f"{index}. " if ordered else "- "
        if text:
            lines.append("  " * depth + prefix + text)
        for nested in li:
            tag = nested.tag.lower() if isinstance(nested.tag, str) else ""
            if tag in ("ul", "ol"):
                sub = _render_list(nested, tag == "ol", depth + 1)
                if sub:
                    lines.append(sub)
        index += 1
    return "\n".join(lines)


def _table(node) -> str:
    rows: list[list[str]] = []
    for tr in node.iter():
        if not isinstance(tr.tag, str) or tr.tag.lower() != "tr":
            continue
        cells = []
        for cell in tr:
            tag = cell.tag.lower() if isinstance(cell.tag, str) else ""
            if tag in ("td", "th"):
                cells.append(_inline(cell).strip().replace("\n", " "))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(out)


def _block(node) -> str:
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        return f"\n\n{'#' * level} {_inline(node).strip()}\n\n"
    if tag == "p":
        text = _inline(node).strip()
        return f"\n\n{text}\n\n" if text else "\n"
    if tag == "pre":
        code = _inline(node).strip("\n")
        return f"\n\n```\n{code}\n```\n\n"
    if tag == "blockquote":
        inner = "".join(_block(child) for child in node).strip()
        quoted = "\n".join(f"> {line}" for line in inner.splitlines())
        return f"\n\n{quoted}\n\n"
    if tag in ("ul", "ol"):
        listing = _render_list(node, tag == "ol")
        return f"\n\n{listing}\n\n" if listing else ""
    if tag == "table":
        table = _table(node)
        return f"\n\n{table}\n\n" if table else ""
    if tag == "hr":
        return "\n\n---\n\n"
    if tag == "br":
        return "\n"
    if tag in ("div", "section", "article", "body"):
        return "".join(_block(child) for child in node) + (
            _inline_text(node) if len(node) == 0 else ""
        )
    if tag in ("img",):
        src = node.get("src") or ""
        return f"\n\n![{node.get('alt') or ''}]({src})\n\n" if src else ""
    text = _inline(node).strip()
    return f"\n\n{text}\n\n" if text else ""


def _inline_text(node) -> str:
    return node.text or ""


def html_to_markdown(source: str) -> str:
    """把语雀 Lake / 导出 HTML 转成可读 Markdown。"""
    if not source.strip():
        return ""
    from lxml import html as lxml_html

    try:
        doc = lxml_html.fromstring(source)
    except Exception:  # noqa: BLE001 - 非法 HTML 退化为纯文本
        return re.sub(r"<[^>]+>", "", source).strip()
    body = doc.body if doc.body is not None else doc
    text = "".join(_block(child) for child in body)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# --------------------------------------------------------------------------- #
# 令牌直连
# --------------------------------------------------------------------------- #
def normalize_repo(repo: str) -> str:
    value = (repo or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        match = re.search(r"yuque\.com/([^/?#]+/[^/?#]+)", value)
        if not match:
            raise YuqueError("无法从链接解析语雀知识库路径，请填写 user/repo 形式")
        return match.group(1)
    value = value.strip("/")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        raise YuqueError("知识库路径格式应为 user/repo（例如 alice/engineering）")
    return value


async def _get_json(
    client: httpx.AsyncClient, url: str, *, params: dict | None = None
) -> dict:
    last_error = ""
    for attempt in range(3):
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_error = f"网络错误：{exc}"
            await asyncio.sleep(1.2 * (attempt + 1))
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            last_error = f"语雀接口限流或暂时不可用（HTTP {resp.status_code}）"
            await asyncio.sleep(1.5 * (2**attempt))
            continue
        if resp.status_code in (401, 403):
            raise YuqueError("语雀令牌无效，或没有该知识库的访问权限")
        if resp.status_code == 404:
            raise YuqueError("语雀知识库不存在，请检查 user/repo 路径")
        if resp.status_code >= 400:
            raise YuqueError(f"语雀接口返回 HTTP {resp.status_code}：{resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise YuqueError("语雀接口返回了非 JSON 内容") from exc
        if not isinstance(payload, dict):
            raise YuqueError("语雀接口返回结构异常")
        return payload
    raise YuqueError(last_error or "语雀接口请求失败")


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _headers(token: str) -> dict[str, str]:
    return {
        "X-Auth-Token": token.strip(),
        "Accept": "application/json",
        "User-Agent": "Kiwi-Import/1.0",
    }


async def fetch_user_repos(token: str) -> list[dict]:
    """用令牌列出当前用户可访问的知识库（个人 + 团队）。

    只返回展示所需字段；令牌仅用于本次调用，不落库、不写日志。
    """
    if not token.strip():
        raise YuqueError("请填写语雀访问令牌")
    repos: dict[str, dict] = {}

    def _collect(payload: dict, group: str | None = None) -> int:
        batch = payload.get("data") or []
        if not isinstance(batch, list):
            return 0
        for repo in batch:
            if not isinstance(repo, dict):
                continue
            namespace = str(repo.get("namespace") or "").strip()
            if not namespace:
                continue
            repos[namespace] = {
                "id": repo.get("id"),
                "name": str(repo.get("name") or namespace),
                "namespace": namespace,
                "description": str(repo.get("description") or ""),
                "items_count": int(repo.get("items_count") or 0),
                "updated_at": repo.get("updated_at") or repo.get("content_updated_at"),
                "group": group,
            }
        return len(batch)

    async with httpx.AsyncClient(
        base_url=YUQUE_API, headers=_headers(token), timeout=40, follow_redirects=True
    ) as client:
        offset = 0
        while offset < 1000:
            payload = await _get_json(
                client, "/user/repos", params={"limit": 100, "offset": offset}
            )
            count = _collect(payload)
            if count < 100:
                break
            offset += count
            await asyncio.sleep(0.2)

        # 团队知识库需要按 group namespace 再拉一次；无权限或接口不可用时静默跳过。
        try:
            groups_payload = await _get_json(client, "/user/groups")
            groups = groups_payload.get("data") or []
            for group in groups if isinstance(groups, list) else []:
                if not isinstance(group, dict):
                    continue
                login = str(group.get("login") or group.get("namespace") or "").strip()
                if not login:
                    continue
                offset = 0
                while offset < 1000:
                    payload = await _get_json(
                        client,
                        f"/groups/{quote(login)}/repos",
                        params={"limit": 100, "offset": offset},
                    )
                    count = _collect(payload, group=str(group.get("name") or login))
                    if count < 100:
                        break
                    offset += count
                    await asyncio.sleep(0.2)
        except YuqueError:
            pass

    return sorted(
        repos.values(),
        key=lambda repo: str(repo.get("updated_at") or ""),
        reverse=True,
    )


async def fetch_repo_documents(token: str, repo: str) -> tuple[list[ImportItem], list[str]]:
    """串行拉取目录树与正文；返回 (items, errors)。"""
    namespace = normalize_repo(repo)
    items: list[ImportItem] = []
    errors: list[str] = []
    async with httpx.AsyncClient(
        base_url=YUQUE_API, headers=_headers(token), timeout=40, follow_redirects=True
    ) as client:
        docs: list[dict] = []
        offset = 0
        while len(docs) < MAX_DOCS:
            payload = await _get_json(
                client,
                f"/repos/{quote(namespace, safe='/')}/docs",
                params={"limit": 100, "offset": offset},
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list) or not batch:
                break
            docs.extend(doc for doc in batch if isinstance(doc, dict))
            if len(batch) < 100:
                break
            offset += len(batch)
            await asyncio.sleep(0.2)

        # 目录树：还原标题分组的层级与顺序；失败时退化为平铺导入。
        folder_by_doc: dict[str, tuple[str, ...]] = {}
        order: dict[str, int] = {}
        try:
            toc_payload = await _get_json(
                client, f"/repos/{quote(namespace, safe='/')}/toc"
            )
            toc = toc_payload.get("data") or []
            if isinstance(toc, list):
                nodes = {
                    str(node.get("uuid")): node
                    for node in toc
                    if isinstance(node, dict) and node.get("uuid")
                }

                def _path_of(node: dict) -> tuple[str, ...]:
                    titles: list[str] = []
                    parent_uuid = node.get("parent_uuid")
                    guard = 0
                    while parent_uuid and guard < 100:
                        parent = nodes.get(str(parent_uuid))
                        if parent is None:
                            break
                        if str(parent.get("type") or "").upper() == "TITLE":
                            title = str(parent.get("title") or "").strip()
                            if title:
                                titles.insert(0, title)
                        parent_uuid = parent.get("parent_uuid")
                        guard += 1
                    return tuple(titles)

                for index, node in enumerate(toc):
                    if not isinstance(node, dict):
                        continue
                    if str(node.get("type") or "").upper() != "DOC":
                        continue
                    doc_id = node.get("doc_id")
                    if doc_id is None:
                        continue
                    folder_by_doc[str(doc_id)] = _path_of(node)
                    order.setdefault(str(doc_id), index)
        except YuqueError as exc:
            errors.append(f"目录树：{exc}")

        docs.sort(key=lambda item: order.get(str(item.get("id")), 10**9))
        for doc in docs[:MAX_DOCS]:
            doc_id = doc.get("id")
            slug = doc.get("slug") or str(doc_id or "")
            title = (doc.get("title") or doc.get("slug") or "未命名文档").strip()
            updated = _parse_time(doc.get("updated_at") or doc.get("content_updated_at"))
            try:
                detail_payload = await _get_json(
                    client,
                    f"/repos/{quote(namespace, safe='/')}/docs/{quote(str(doc_id or slug))}",
                )
                data = detail_payload.get("data") or {}
            except YuqueError as exc:
                errors.append(f"{title}：{exc}")
                data = {}
            body = (data.get("body") or "").strip()
            body_html = (data.get("body_html") or data.get("body_lake") or "").strip()
            if body and not body.lstrip().startswith(("<", "{")):
                markdown = body
            elif body_html:
                markdown = html_to_markdown(body_html)
            elif body:
                markdown = html_to_markdown(body)
            else:
                markdown = (data.get("description") or doc.get("description") or "").strip()
            warnings: list[str] = []
            if not markdown:
                warnings.append("语雀文档正文为空")
            if markdown and not re.match(r"^#\s", markdown):
                markdown = f"# {title}\n\n{markdown}"
            url = data.get("url") or doc.get("url") or ""
            if not url and slug:
                url = f"https://www.yuque.com/{namespace}/{slug}"
            items.append(
                ImportItem(
                    title=title,
                    markdown=markdown + "\n",
                    external_id=f"yuque:{namespace}:{doc_id or slug}",
                    source_url=url,
                    content_updated_at=updated or _parse_time(data.get("updated_at")),
                    warnings=warnings,
                    folder_path=folder_by_doc.get(str(doc_id), ()),
                )
            )
            await asyncio.sleep(0.15)
    return items, errors


# --------------------------------------------------------------------------- #
# 导出包
# --------------------------------------------------------------------------- #
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
MAX_ASSET_BYTES = 20 * 1024 * 1024
MD_EXTS = (".md", ".markdown", ".txt")

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
HTML_IMG_RE = re.compile(r"(<img[^>]+src=[\"'])([^\"']+)([\"'])", re.IGNORECASE)


def _norm_zip_path(value: str) -> str:
    return posixpath.normpath(value.replace("\\", "/")).lstrip("/")


def _common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    if not paths:
        return ()
    prefix = list(paths[0])
    for parts in paths[1:]:
        cut = 0
        while cut < len(prefix) and cut < len(parts) and prefix[cut] == parts[cut]:
            cut += 1
        prefix = prefix[:cut]
    return tuple(prefix)


def read_export_zip(
    zf: zipfile.ZipFile,
    *,
    media_dir: Path | None = None,
    kb_id: str | None = None,
) -> tuple[list[ImportItem], list[str]]:
    """解析语雀 Markdown 导出包。

    - 按压缩包目录还原笔记分组；
    - 把正文引用的本地图片写入 /media，并把链接改写成可访问 URL；
    - 只读取 .md/.markdown/.txt，其余文件忽略。
    """
    items: list[ImportItem] = []
    errors: list[str] = []
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if any(part == "__MACOSX" or part.startswith(".") for part in path.parts):
            continue
        entries[_norm_zip_path(info.filename)] = info

    doc_paths = [
        path
        for path in entries
        if PurePosixPath(path).suffix.lower() in MD_EXTS
    ]
    doc_paths.sort()
    # 导出包通常带一层知识库根目录；所有文档共享的前缀不计入笔记分组。
    common = _common_prefix(
        [tuple(PurePosixPath(path).parent.parts) for path in doc_paths]
    )

    asset_urls: dict[str, str | None] = {}

    def resolve_asset(url: str, parent: PurePosixPath) -> str | None:
        clean = unquote(url.split("#", 1)[0].split("?", 1)[0]).strip()
        if not clean or re.match(r"^(?:https?:|data:|//|mailto:)", clean, re.I):
            return None
        candidates = (
            [_norm_zip_path(clean)]
            if clean.startswith("/")
            else [_norm_zip_path(str(parent / clean))]
        )
        resolved = next((candidate for candidate in candidates if candidate in entries), None)
        if resolved is None:
            basename = PurePosixPath(clean).name
            matches = [path for path in entries if PurePosixPath(path).name == basename]
            if len(matches) == 1:
                resolved = matches[0]
        if resolved is None:
            return None
        if resolved in asset_urls:
            return asset_urls[resolved]
        info = entries[resolved]
        suffix = PurePosixPath(resolved).suffix.lower()
        if suffix not in IMAGE_EXTS or info.file_size > MAX_ASSET_BYTES:
            asset_urls[resolved] = None
            return None
        if media_dir is None or not kb_id:
            return None
        try:
            raw = zf.read(info)
        except (KeyError, RuntimeError, zipfile.BadZipFile):
            asset_urls[resolved] = None
            return None
        digest = hashlib.sha256(raw).hexdigest()[:16]
        filename = f"yuque-{digest}{suffix}"
        target_dir = Path(media_dir) / kb_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if not target.exists():
            target.write_bytes(raw)
        url_out = f"/media/{kb_id}/{filename}"
        asset_urls[resolved] = url_out
        return url_out

    def rewrite_assets(text: str, parent: PurePosixPath) -> str:
        def _image(match: re.Match[str]) -> str:
            alt, url = match.group(1), match.group(2)
            replacement = resolve_asset(url, parent)
            return f"![{alt}]({replacement})" if replacement else match.group(0)

        def _html_image(match: re.Match[str]) -> str:
            replacement = resolve_asset(match.group(2), parent)
            return (
                f"{match.group(1)}{replacement}{match.group(3)}"
                if replacement
                else match.group(0)
            )

        return HTML_IMG_RE.sub(_html_image, IMAGE_RE.sub(_image, text))

    for path in doc_paths:
        info = entries[path]
        if info.file_size > 50 * 1024 * 1024:
            errors.append(f"{info.filename}：文件超过 50MB，已跳过")
            continue
        try:
            raw = zf.read(info)
        except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
            errors.append(f"{info.filename}：读取失败（{exc}）")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
        pure = PurePosixPath(path)
        text = rewrite_assets(text, pure.parent)
        title = pure.stem
        for line in text.splitlines():
            if line.strip().startswith("# "):
                title = line.strip()[2:].strip() or title
                break
        try:
            updated = datetime(*info.date_time, tzinfo=timezone.utc)
        except (ValueError, OverflowError):
            updated = None
        parent_parts = tuple(pure.parent.parts)
        folder_path = parent_parts[len(common) :] if parent_parts[: len(common)] == common else parent_parts
        items.append(
            ImportItem(
                title=title,
                markdown=text + "\n",
                external_id=f"yuque-zip:{path}",
                source_url="",
                content_updated_at=updated,
                folder_path=tuple(part for part in folder_path if part.strip()),
            )
        )
    if not items:
        errors.append("导出包中未找到 Markdown 文档（.md / .markdown / .txt）")
    return items, errors
