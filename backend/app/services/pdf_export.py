"""Markdown → PDF 导出：PyMuPDF Story + markdown-it-py。

设计取舍：

- 复用文档的 Markdown 作为唯一事实来源，先转 HTML 再交给 MuPDF 分页排版；
- 中文字体由 MuPDF 自动回退（优先系统 Droid Sans Fallback），生成后做字体子集化，
  避免每份 PDF 都携带完整 CJK 字体；
- 图片只读取 ``/media`` 下的本地文件，外链图片降级为文字链接，导出过程不发起网络请求；
- 尽量还原 Kiwi 编辑器里的自定义块（图片、图库、内嵌数据表、链接卡片等），
  无法还原的块给出文字占位，而不是把 JSON 配置直接印进 PDF。
"""

from __future__ import annotations

import html
import json
import re
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pymupdf
from markdown_it import MarkdownIt

from app.config import settings

_CM_TO_PT = 72.0 / 2.54
_MAX_PAGES = 500
_DEFAULT_MARGIN_CM = 2.54
_CODE_LINE_WIDTH = 88
_MAX_DATATABLE_FIELDS = 12
_MAX_DATATABLE_ROWS = 200

_TASK_ITEM_RE = re.compile(r"(<li[^>]*>)(\s*(?:<p[^>]*>)?)\[([ xX])\]\s*")
_SAFE_URL_PREFIXES = ("http://", "https://", "mailto:")
# 显式分页标记：MuPDF 的 break-before 在表格跨页时会多出空白页，改为分段排版。
_PAGEBREAK = "<!--kiwi-pagebreak-->"


def _css(font_size: float) -> str:
    """与正文结构对应的打印样式；字号按 docx_prefs 换算成 pt。"""
    small = max(7.5, font_size * 0.78)
    return f"""
body {{
  font-size: {font_size:.2f}pt;
  line-height: 1.72;
  color: #1f2937;
}}
h1, h2, h3, h4, h5, h6 {{
  color: #0f172a;
  font-weight: bold;
  line-height: 1.35;
  break-after: avoid;
}}
h1 {{ font-size: {font_size * 1.95:.2f}pt; margin: 0 0 14pt; }}
h2 {{ font-size: {font_size * 1.44:.2f}pt; margin: 17pt 0 7pt; }}
h3 {{ font-size: {font_size * 1.17:.2f}pt; margin: 13pt 0 5pt; }}
h4, h5, h6 {{ font-size: {font_size:.2f}pt; margin: 11pt 0 4pt; }}
p {{ margin: 0 0 8pt; }}
ul, ol {{ margin: 0 0 8pt; padding-left: 18pt; }}
li {{ margin: 0 0 3pt; }}
a {{ color: #2563eb; text-decoration: underline; }}
strong {{ font-weight: bold; }}
blockquote {{
  margin: 8pt 0 10pt;
  padding: 6pt 10pt;
  border-left: 3pt solid #93c5fd;
  background-color: #f8fafc;
  color: #475569;
}}
code {{
  font-family: "DejaVu Sans Mono", monospace;
  font-size: {small:.2f}pt;
  background-color: #f1f5f9;
  padding: 1pt 2pt;
}}
pre {{
  margin: 0 0 10pt;
  padding: 7pt 9pt;
  border: 1pt solid #e2e8f0;
  background-color: #f8fafc;
  font-family: "DejaVu Sans Mono", monospace;
  font-size: {small:.2f}pt;
  line-height: 1.5;
}}
pre code {{ background-color: transparent; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 0 0 10pt; font-size: {small:.2f}pt; }}
th, td {{ border: 1pt solid #dbe2ea; padding: 3.5pt 5pt; vertical-align: top; }}
th {{ background-color: #f1f5f9; font-weight: bold; }}
hr {{ border: 0; border-top: 1pt solid #e2e8f0; margin: 12pt 0; }}
img {{ max-width: 100%; }}
.figure {{ margin: 0 0 10pt; }}
.caption {{ color: #64748b; font-size: {small:.2f}pt; text-align: center; margin: 3pt 0 0; }}
.muted {{ color: #64748b; font-size: {small:.2f}pt; }}
.card {{
  margin: 0 0 10pt;
  padding: 7pt 10pt;
  border: 1pt solid #e2e8f0;
  background-color: #f8fafc;
}}
.card-title {{ font-weight: bold; color: #0f172a; margin: 0 0 2pt; }}
.card-meta {{ color: #64748b; font-size: {small:.2f}pt; margin: 0 0 4pt; }}
.card-excerpt {{ color: #475569; margin: 0; }}
.formula {{
  margin: 6pt 0 10pt;
  text-align: center;
  font-family: Georgia, serif;
  font-style: italic;
}}
tr {{ break-inside: avoid; }}
"""


def _display_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _wrap_code(text: str, limit: int = _CODE_LINE_WIDTH) -> str:
    """MuPDF 的 pre 不会自动换行，手动按显示宽度折行，避免长行溢出页面。"""
    wrapped: list[str] = []
    for raw in (text or "").split("\n"):
        line = raw
        while _display_width(line) > limit:
            width = 0
            cut = 0
            for index, ch in enumerate(line):
                next_width = width + (2 if ord(ch) > 0x2E7F else 1)
                if next_width > limit:
                    break
                width = next_width
                cut = index + 1
            if cut <= 0:
                cut = 1
            wrapped.append(line[:cut])
            line = line[cut:]
        wrapped.append(line)
    return "\n".join(wrapped)


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _safe_href(value: Any) -> str | None:
    url = str(value or "").strip()
    return url if url.lower().startswith(_SAFE_URL_PREFIXES) else None


def _media_root() -> Path:
    return (settings.upload_dir / "media").resolve()


def _media_rel(src: str) -> str | None:
    """把 ``/media/<kb>/<file>`` 转成相对于媒体根目录的路径，越权路径返回 None。"""
    if not src.startswith("/media/"):
        return None
    rel = unquote(src[len("/media/") :].split("?", 1)[0].split("#", 1)[0])
    root = _media_root()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path.relative_to(root).as_posix()


def _image_tag(src: Any, alt: Any, width: Any = None) -> str | None:
    raw_src = str(src or "").strip()
    rel = _media_rel(raw_src)
    if rel is None:
        return None
    label = _escape(alt or "图片")
    try:
        width_px = int(float(width or 0))
    except (TypeError, ValueError):
        width_px = 0
    style = "max-width:100%;"
    if width_px > 0:
        style += f"width:{min(width_px, 2400)}px;"
    return f'<img src="{_escape(rel)}" alt="{label}" style="{style}" />'


def _image_fallback(src: Any, alt: Any) -> str:
    label = _escape(f"[图片：{alt or '未命名'}]")
    href = _safe_href(src)
    if href:
        return f'<p class="muted"><a href="{_escape(href)}">{label}</a>（外链图片未嵌入）</p>'
    return f'<p class="muted">{label}</p>'


def _render_image(tokens, idx, options, env):  # noqa: ANN001 - markdown-it 规则签名
    token = tokens[idx]
    src = token.attrGet("src") or ""
    alt = token.attrGet("alt") or ""
    image = _image_tag(src, alt, token.attrGet("width"))
    if image is None:
        return _image_fallback(src, alt)
    title = token.attrGet("title") or ""
    caption = f'<div class="caption">{_escape(title)}</div>' if title else ""
    return f'<div class="figure">{image}{caption}</div>\n'


def _option_name(field: dict, value: Any) -> str:
    options = field.get("options") if isinstance(field.get("options"), list) else []
    by_id = {str(item.get("id")): str(item.get("name") or "") for item in options if isinstance(item, dict)}
    if isinstance(value, list):
        return " / ".join(by_id.get(str(item), str(item)) for item in value)
    return by_id.get(str(value), str(value))


def _db_cell(field: dict, value: Any) -> str:
    if value is None or value == "":
        return ""
    kind = str(field.get("type") or "text")
    if kind in ("select", "multi_select"):
        return _option_name(field, value)
    if kind == "checkbox":
        return "是" if value else "否"
    if kind == "attachment":
        if isinstance(value, list):
            names = [
                str(item.get("filename") or item.get("url") or "")
                for item in value
                if isinstance(item, dict)
            ]
            return " / ".join(name for name in names if name)
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    return text if len(text) <= 300 else text[:300] + "…"


def _datatable_html(data: dict) -> str:
    fields = [item for item in data.get("fields") or [] if isinstance(item, dict)]
    rows = [item for item in data.get("rows") or [] if isinstance(item, dict)]
    title = str(data.get("title") or "").strip()
    parts: list[str] = []
    if title:
        parts.append(f'<h3>{_escape(title)}</h3>')
    if not fields:
        return "".join(parts) + '<p class="muted">[空数据表]</p>'
    shown = fields[:_MAX_DATATABLE_FIELDS]
    parts.append("<table><thead><tr>")
    for field in shown:
        parts.append(f"<th>{_escape(field.get('name') or '')}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows[:_MAX_DATATABLE_ROWS]:
        row_data = row.get("data") if isinstance(row.get("data"), dict) else row
        parts.append("<tr>")
        for field in shown:
            parts.append(f"<td>{_escape(_db_cell(field, row_data.get(str(field.get('id')))))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    omitted: list[str] = []
    if len(fields) > len(shown):
        omitted.append(f"{len(fields) - len(shown)} 列")
    if len(rows) > _MAX_DATATABLE_ROWS:
        omitted.append(f"{len(rows) - _MAX_DATATABLE_ROWS} 行")
    if omitted:
        parts.append(f'<p class="muted">PDF 已省略 {" / ".join(omitted)}，完整数据请查看原笔记。</p>')
    return "".join(parts)


def _gallery_html(data: dict) -> str:
    images = data.get("images") if isinstance(data.get("images"), list) else []
    parts: list[str] = []
    for item in images:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        caption = item.get("caption") or item.get("name") or ""
        image = _image_tag(url, caption)
        if image is None:
            parts.append(_image_fallback(url, caption))
            continue
        caption_html = f'<div class="caption">{_escape(caption)}</div>' if caption else ""
        parts.append(f'<div class="figure">{image}{caption_html}</div>')
    return "".join(parts) or '<p class="muted">[空图库]</p>'


def _embed_html(data: dict) -> str:
    title = str(data.get("title") or data.get("filename") or data.get("url") or "").strip()
    site = str(data.get("site") or "").strip()
    excerpt = str(data.get("excerpt") or "").strip()
    href = _safe_href(data.get("url"))
    title_html = _escape(title or "未命名内容")
    if href:
        title_html = f'<a href="{_escape(href)}">{title_html}</a>'
    meta = f'<div class="card-meta">{_escape(site or href or "")}</div>' if (site or href) else ""
    excerpt_html = f'<p class="card-excerpt">{_escape(excerpt)}</p>' if excerpt else ""
    return (
        f'<div class="card"><div class="card-title">{title_html}</div>'
        f"{meta}{excerpt_html}</div>"
    )


def _note_html(data: dict) -> str:
    title = str(data.get("title") or "未命名笔记")
    kind = {"database": "数据表", "canvas": "画布", "notebook": "Notebook", "sheet": "表格"}.get(
        str(data.get("kind") or ""), "笔记"
    )
    return (
        f'<div class="card"><div class="card-meta">{_escape(kind)}</div>'
        f'<div class="card-title">{_escape(title)}</div></div>'
    )


def _calendar_html(data: dict) -> str:
    events = data.get("events") if isinstance(data.get("events"), list) else []
    title = str(data.get("title") or "").strip()
    parts = [f"<h3>{_escape(title)}</h3>"] if title else []
    if not events:
        parts.append('<p class="muted">[空日历]</p>')
        return "".join(parts)
    parts.append("<table><thead><tr><th>日期</th><th>安排</th></tr></thead><tbody>")
    rows = sorted(
        (item for item in events if isinstance(item, dict)),
        key=lambda item: str(item.get("start") or ""),
    )
    for item in rows:
        start = str(item.get("start") or "")
        end = str(item.get("end") or "")
        date_text = start if not end or end == start else f"{start} → {end}"
        parts.append(f"<tr><td>{_escape(date_text)}</td><td>{_escape(item.get('title') or '')}</td></tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _task_progress_html(data: dict) -> str:
    label = str(data.get("label") or "待办进度")
    return f'<div class="card"><div class="card-meta">待办进度</div><div class="card-title">{_escape(label)}</div></div>'


def _custom_fence(lang: str, content: str) -> str | None:
    """把编辑器自定义围栏还原成可打印的 HTML；无法解析时返回 None 走代码块。"""
    if lang == "kiwi-pagebreak":
        return _PAGEBREAK
    if lang == "kiwi-math":
        return f'<div class="formula">{_escape(content.strip())}</div>'
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if lang == "kiwi-image":
        image = _image_tag(data.get("src"), data.get("alt"), data.get("width"))
        if image is None:
            return _image_fallback(data.get("src"), data.get("alt"))
        title = str(data.get("title") or "").strip()
        caption = f'<div class="caption">{_escape(title)}</div>' if title else ""
        return f'<div class="figure">{image}{caption}</div>'
    if lang == "kiwi-gallery":
        return _gallery_html(data)
    if lang == "kiwi-embed":
        return _embed_html(data)
    if lang == "kiwi-note":
        return _note_html(data)
    if lang == "kiwi-datatable":
        return _datatable_html(data)
    if lang == "kiwi-calendar":
        return _calendar_html(data)
    if lang == "kiwi-task-progress":
        return _task_progress_html(data)
    return None


def _render_fence(tokens, idx, options, env):  # noqa: ANN001 - markdown-it 规则签名
    token = tokens[idx]
    info = (token.info or "").strip()
    lang = info.split()[0].lower() if info else ""
    content = token.content.rstrip("\n")
    custom = _custom_fence(lang, content)
    if custom is not None:
        return custom + "\n"
    if lang in {"kiwi-output", "kiwi-mermaid", "mermaid"}:
        label = "运行输出" if lang == "kiwi-output" else "Mermaid 图表源码"
        return (
            f'<p class="muted">{label}</p><pre><code>{_escape(_wrap_code(content))}</code></pre>\n'
        )
    code = _escape(_wrap_code(content))
    return f"<pre><code>{code}</code></pre>\n"


def _task_list_html(body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        box = "☑" if match.group(3).lower() == "x" else "☐"
        return f"{match.group(1)}{match.group(2)}{box} "

    return _TASK_ITEM_RE.sub(replace, body)


def markdown_to_html(body_md: str) -> str:
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    md.renderer.rules["fence"] = _render_fence
    md.renderer.rules["image"] = _render_image
    tokens = md.parse(body_md or "")
    # 先清洗链接协议，避免 javascript: 等 URL 进入 PDF 链接注解。
    for token in tokens:
        if token.type == "link_open":
            href = token.attrGet("href") or ""
            if not href.lower().startswith(_SAFE_URL_PREFIXES):
                token.attrSet("href", "#")
    rendered = md.renderer.render(tokens, md.options, {})
    return _task_list_html(rendered)


def _page_setup(prefs: dict) -> tuple[pymupdf.Rect, tuple[float, float, float, float], float]:
    paper = str(prefs.get("paper") or "a4").lower()
    if paper not in {"a4", "letter", "a5"}:
        paper = "a4"
    rect = pymupdf.paper_rect(paper)
    if prefs.get("orientation") == "landscape":
        rect = pymupdf.Rect(0, 0, rect.height, rect.width)

    margins = prefs.get("margins") if isinstance(prefs.get("margins"), dict) else {}

    def margin(key: str) -> float:
        try:
            value = float(margins.get(key, _DEFAULT_MARGIN_CM))
        except (TypeError, ValueError):
            value = _DEFAULT_MARGIN_CM
        return min(6.0, max(0.0, value)) * _CM_TO_PT

    left, right = margin("left"), margin("right")
    top, bottom = margin("top"), margin("bottom")
    # 防止极端页边距把版心压成 0，Story 会陷入无法排版的循环。
    if rect.width - left - right < 120:
        left = right = max(0.0, (rect.width - 120) / 2)
    if rect.height - top - bottom < 120:
        top = bottom = max(0.0, (rect.height - 120) / 2)

    try:
        size_px = float(prefs.get("size", 15))
    except (TypeError, ValueError):
        size_px = 15.0
    font_size = min(24.0, max(7.0, size_px * 0.75))
    return rect, (left, top, right, bottom), font_size


def _decorate_pages(doc: pymupdf.Document, margins: tuple[float, float, float, float]) -> None:
    """在版心外写页码；使用内置 Helvetica，不额外嵌入字体。"""
    total = doc.page_count
    left, _top, right, bottom = margins
    for index, page in enumerate(doc):
        text = f"{index + 1} / {total}"
        width = pymupdf.get_text_length(text, fontname="helv", fontsize=8.5)
        x = (page.rect.width - width) / 2 + (left - right) / 2
        y = page.rect.height - max(16.0, bottom / 2)
        page.insert_text(
            (x, y),
            text,
            fontname="helv",
            fontsize=8.5,
            color=(0.55, 0.6, 0.67),
        )


def markdown_to_pdf(title: str, body_md: str, prefs: dict | None = None) -> BytesIO:
    """把 Markdown 笔记渲染为多页 A4（或用户纸张设置）PDF。"""
    prefs = prefs if isinstance(prefs, dict) else {}
    page_rect, margins, font_size = _page_setup(prefs)
    left, top, right, bottom = margins
    content_rect = page_rect + (left, top, -right, -bottom)

    clean_title = (title or "无标题文档").strip() or "无标题文档"
    body = body_md or ""
    first_line = body.lstrip().splitlines()[0].strip() if body.strip() else ""
    if first_line != f"# {clean_title}":
        body = f"# {clean_title}\n\n{body}"

    html_body = markdown_to_html(body)
    media_root = _media_root()
    archive = pymupdf.Archive(str(media_root)) if media_root.is_dir() else None
    css = _css(font_size)
    # 显式分页：每个片段单独排版，片段之间自然从新页开始。
    segments = [part for part in html_body.split(_PAGEBREAK) if part.strip()]

    with tempfile.TemporaryDirectory(prefix="kiwi-pdf-") as tmp:
        path = Path(tmp) / "note.pdf"
        writer = pymupdf.DocumentWriter(str(path))
        pages = 0
        for segment in segments:
            story = pymupdf.Story(html=segment, user_css=css, archive=archive)
            more = True
            while more:
                if pages >= _MAX_PAGES:
                    raise ValueError("文档过长，超过 PDF 导出的页数上限")
                device = writer.begin_page(page_rect)
                more, _ = story.place(content_rect)
                story.draw(device)
                writer.end_page()
                pages += 1
        writer.close()

        doc = pymupdf.open(path)
        doc.set_metadata(
            {
                "title": clean_title,
                "creator": "Kiwi",
                "producer": "Kiwi",
                "subject": "Kiwi 笔记导出",
            }
        )
        _decorate_pages(doc, margins)
        # 子集化 CJK 字体，避免每份 PDF 都带上完整字体文件（通常可降到几十 KB）。
        doc.subset_fonts()
        buffer = BytesIO()
        doc.save(buffer, garbage=4, deflate=True, clean=True)
        doc.close()

    buffer.seek(0)
    return buffer
