"""Markdown → DOCX 导出：基于 python-docx 与 markdown-it-py 的轻量转换。

只依赖本地资源（/media 下的图片），外链图片降级为文字说明，避免导出时发起网络请求。
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from markdown_it import MarkdownIt

from app.config import settings

_HEADING_COLOR = RGBColor(0x1F, 0x29, 0x37)
_MUTED_COLOR = RGBColor(0x64, 0x74, 0x8B)

# 与前端 modes.ts 的 DOCX_FONTS / DOCX_PAPERS 保持一致
_PAPER_SIZES_CM = {
    "a4": (21.0, 29.7),
    "letter": (21.59, 27.94),
    "a5": (14.8, 21.0),
}
_FONT_NAMES = {
    "serif": "宋体",
    "sans": "黑体",
    "kai": "楷体",
    "fangsong": "仿宋",
    "yahei": "微软雅黑",
    "pingfang": "苹方",
    "sourceSerif": "思源宋体",
    "sourceSans": "思源黑体",
    "times": "Times New Roman",
    "arial": "Arial",
    "calibri": "Calibri",
    "georgia": "Georgia",
    "mono": "Consolas",
}


_MENTION_LINK_RE = re.compile(
    r"\[@?([^\]]*)\]\(kiwi://note/([0-9a-fA-F-]{36})(?:\?display=([a-z]+))?\)"
)
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}")


def resolve_note_mentions(markdown: str, titles: dict[str, str]) -> str:
    """把 `[@id](kiwi://note/<id>)` 换成笔记标题，避免导出后露出 UUID。"""
    by_id = {key.lower(): value for key, value in titles.items() if value}

    def replace_link(match: re.Match[str]) -> str:
        label = (match.group(1) or "").strip()
        note_id = match.group(2).lower()
        display = (match.group(3) or "mention").lower()
        title = by_id.get(note_id)
        text = title or (label if label and not _UUID_RE.fullmatch(label) else "已删除笔记")
        # 只有行内提及保留 @；卡片 / 嵌入导出为笔记标题
        return f"@{text}" if display == "mention" else text

    resolved = _MENTION_LINK_RE.sub(replace_link, markdown)

    def replace_plain(match: re.Match[str]) -> str:
        if match.start() == 0 or match.string[match.start() - 1] != "@":
            return match.group(0)
        return by_id.get(match.group(0).lower(), match.group(0))

    return _UUID_RE.sub(replace_plain, resolved)


def _docx_prefs(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {}


def _page_setup(doc: Document, prefs: dict) -> dict:
    """应用纸张、方向与页边距，返回字体与段落排版参数（pt）。"""
    paper = prefs.get("paper")
    width_cm, height_cm = _PAPER_SIZES_CM.get(str(paper), _PAPER_SIZES_CM["a4"])
    if prefs.get("orientation") == "landscape":
        width_cm, height_cm = height_cm, width_cm
    margins = prefs.get("margins") if isinstance(prefs.get("margins"), dict) else {}

    def margin(key: str) -> float:
        try:
            return min(6.0, max(0.0, float(margins.get(key, 2.54))))
        except (TypeError, ValueError):
            return 2.54

    section = doc.sections[0]
    section.page_width = Cm(width_cm)
    section.page_height = Cm(height_cm)
    section.top_margin = Cm(margin("top"))
    section.bottom_margin = Cm(margin("bottom"))
    section.left_margin = Cm(margin("left"))
    section.right_margin = Cm(margin("right"))

    # 与前端 DEFAULT_DOCX_PREFS.font = 'serif' 保持一致
    font_name = _FONT_NAMES.get(str(prefs.get("font")), "宋体")
    try:
        size_px = float(prefs.get("size", 15))
    except (TypeError, ValueError):
        size_px = 15.0
    # 编辑器里的字号是 CSS px，Word 用 pt（1px = 0.75pt）
    size_pt = min(48.0, max(6.0, size_px * 0.75))
    def number(key: str, fallback: float) -> float:
        try:
            return float(prefs.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    line_mode = "fixed" if prefs.get("lineHeightMode") == "fixed" else "multiple"
    line_value = min(3.0, max(0.8, number("lineHeight", 1.9)))
    fixed_pt = min(72.0, max(8.0, number("lineHeightFixed", 20.0)))
    space_before_px = min(48.0, max(0.0, number("spaceBefore", 0)))
    space_after_px = min(48.0, max(0.0, number("spaceAfter", 8)))
    indent_left = min(10.0, max(0.0, number("indentLeft", 0)))
    indent_right = min(10.0, max(0.0, number("indentRight", 0)))
    indent_first = min(4.0, max(0.0, number("firstLineIndent", 0)))
    hanging = prefs.get("hangingIndent") is True
    letter_px = min(8.0, max(-1.0, number("letterSpacing", 0)))
    if abs(letter_px) > 0.01:
        # Word 字符间距以 1/20 pt 存储
        _set_letter_spacing(doc.styles["Normal"], letter_px)
    return {
        "font_name": font_name,
        "size_pt": size_pt,
        "line_spacing": Pt(fixed_pt) if line_mode == "fixed" else line_value,
        "space_before_pt": space_before_px * 0.75,
        "space_after_pt": space_after_px * 0.75,
        "indent_left_pt": indent_left * size_pt,
        "indent_right_pt": indent_right * size_pt,
        "hanging_pt": indent_first * size_pt if hanging else 0.0,
        "first_indent_pt": -indent_first * size_pt if hanging else indent_first * size_pt,
    }


def _apply_paragraph_layout(paragraph, typo: dict) -> None:
    """正文段落缩进：左/右缩进、首行缩进或悬挂缩进。"""
    fmt = paragraph.paragraph_format
    fmt.left_indent = Pt(typo["indent_left_pt"] + typo["hanging_pt"])
    fmt.right_indent = Pt(typo["indent_right_pt"])
    if abs(typo["first_indent_pt"]) > 0.01:
        fmt.first_line_indent = Pt(typo["first_indent_pt"])


# ---------- 段落级排版（来自前端 props_json.paragraph_formats） ----------

_PF_ALIGNMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def _paragraph_formats(raw: object) -> dict[int, dict]:
    """把 [{index, text, ...}] 转成按段落序号索引的字典。"""
    formats: dict[int, dict] = {}
    if not isinstance(raw, list):
        return formats
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index >= 0:
            formats[index] = item
    return formats


def _pf_number(fmt: dict, key: str, minimum: float, maximum: float) -> float | None:
    try:
        value = float(fmt.get(key))
    except (TypeError, ValueError):
        return None
    return min(maximum, max(minimum, value))


def _run_east_asia(run, font_name: str) -> None:
    try:
        r_pr = run._element.get_or_add_rPr()
        r_fonts = r_pr.find(qn("w:rFonts"))
        if r_fonts is None:
            r_fonts = OxmlElement("w:rFonts")
            r_pr.append(r_fonts)
        r_fonts.set(qn("w:eastAsia"), font_name)
    except Exception:  # noqa: BLE001 - 字体写入失败不影响正文
        pass


def _text_formats(raw: object) -> list[dict]:
    """字符级字体 / 字号记录（来自 props_json.text_formats）。"""
    records: list[dict] = []
    if not isinstance(raw, list):
        return records
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue
        font = str(item.get("font") or "")
        try:
            size = float(item.get("size"))
        except (TypeError, ValueError):
            size = 0.0
        if font not in _FONT_NAMES and size <= 0:
            continue
        records.append(
            {
                "text": text,
                "font": font if font in _FONT_NAMES else "",
                "size": min(96.0, max(6.0, size)) if size > 0 else 0.0,
            }
        )
    return records


def _apply_run_text_format(run, fmt: dict) -> None:
    font_name = _FONT_NAMES.get(fmt.get("font")) if fmt.get("font") else None
    if font_name:
        run.font.name = font_name
        _run_east_asia(run, font_name)
    if fmt.get("size"):
        run.font.size = Pt(fmt["size"] * 0.75)


def _add_text_runs(
    paragraph,
    text: str,
    bold: bool,
    italic: bool,
    strike: bool,
    formats: dict | None,
) -> None:
    """按 text_formats 顺序切分文本 run，只给命中的片段套用字体 / 字号。"""
    remaining = text
    records = formats.get("records", []) if formats else []
    while remaining and formats is not None and formats["index"] < len(records):
        record = records[formats["index"]]
        needle = record["text"]
        pos = remaining.find(needle)
        if pos < 0:
            break
        if pos > 0:
            prefix = paragraph.add_run(remaining[:pos])
            prefix.bold = bold or None
            prefix.italic = italic or None
            prefix.font.strike = strike or None
        run = paragraph.add_run(needle)
        run.bold = bold or None
        run.italic = italic or None
        run.font.strike = strike or None
        _apply_run_text_format(run, record)
        formats["index"] += 1
        remaining = remaining[pos + len(needle):]
    if remaining:
        run = paragraph.add_run(remaining)
        run.bold = bold or None
        run.italic = italic or None
        run.font.strike = strike or None


def _apply_paragraph_format(paragraph, fmt: dict, typo: dict) -> None:
    """把单段排版（字体/字号/行距/段间距/缩进/对齐）写入 Word 段落。"""
    explicit_size = _pf_number(fmt, "size", 6.0, 72.0)
    size_pt = explicit_size * 0.75 if explicit_size is not None else typo["size_pt"]
    font_name = _FONT_NAMES.get(str(fmt.get("font"))) if fmt.get("font") else None

    for run in paragraph.runs:
        r_pr = run._element.rPr
        # 字符级字体 / 字号（text_formats）优先于整段排版，不能被段落设置覆盖
        has_run_font = r_pr is not None and r_pr.find(qn("w:rFonts")) is not None
        has_run_size = r_pr is not None and r_pr.find(qn("w:sz")) is not None
        if font_name and not has_run_font:
            run.font.name = font_name
            _run_east_asia(run, font_name)
        if explicit_size is not None and not has_run_size:
            run.font.size = Pt(size_pt)

    p_fmt = paragraph.paragraph_format
    mode = fmt.get("lineHeightMode")
    if mode == "fixed":
        fixed = _pf_number(fmt, "lineHeightFixed", 8.0, 72.0)
        if fixed is not None:
            p_fmt.line_spacing = Pt(fixed)
    else:
        multiple = _pf_number(fmt, "lineHeight", 0.8, 3.0)
        if multiple is not None:
            p_fmt.line_spacing = multiple

    before = _pf_number(fmt, "spaceBefore", 0.0, 48.0)
    after = _pf_number(fmt, "spaceAfter", 0.0, 48.0)
    if before is not None:
        p_fmt.space_before = Pt(before * 0.75)
    if after is not None:
        p_fmt.space_after = Pt(after * 0.75)

    left = _pf_number(fmt, "indentLeft", 0.0, 10.0)
    right = _pf_number(fmt, "indentRight", 0.0, 10.0)
    first = _pf_number(fmt, "firstLineIndent", 0.0, 4.0)
    hanging = fmt.get("hangingIndent") is True
    if left is not None:
        left_pt = left * size_pt + ((first or 0.0) * size_pt if hanging else 0.0)
        p_fmt.left_indent = Pt(left_pt)
    if right is not None:
        p_fmt.right_indent = Pt(right * size_pt)
    if first is not None:
        p_fmt.first_line_indent = Pt(-first * size_pt if hanging else first * size_pt)

    align = _PF_ALIGNMENTS.get(str(fmt.get("align")))
    if align is not None:
        paragraph.alignment = align


def _set_letter_spacing(style, px: float) -> None:
    try:
        r_pr = style.element.get_or_add_rPr()
        spacing = r_pr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            r_pr.append(spacing)
        spacing.set(qn("w:val"), str(int(round(px * 0.75 * 20))))
    except Exception:  # noqa: BLE001 - 样式缺失时不影响导出
        pass


def _east_asia(style, font_name: str) -> None:
    """中文字体需要单独写 eastAsia，否则 Word 会回退到宋体。"""
    try:
        r_pr = style.element.get_or_add_rPr()
        r_fonts = r_pr.find(qn("w:rFonts"))
        if r_fonts is None:
            r_fonts = OxmlElement("w:rFonts")
            r_pr.append(r_fonts)
        r_fonts.set(qn("w:eastAsia"), font_name)
    except Exception:  # noqa: BLE001 - 样式缺失时不影响导出
        pass


def _shade_paragraph(paragraph, fill: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    p_pr.append(shd)


def _add_hr(doc: Document) -> None:
    paragraph = doc.add_paragraph()
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "CBD5E1")
    borders.append(bottom)
    p_pr.append(borders)


def _add_hyperlink(paragraph, url: str, text: str) -> None:
    """python-docx 无原生超链接，手工拼 w:hyperlink。"""
    try:
        r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    except Exception:  # noqa: BLE001 - 非法 URL 退化为普通文本
        paragraph.add_run(text)
        return
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "2563EB")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    r_pr.append(color)
    r_pr.append(underline)
    run.append(r_pr)
    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _media_path(src: str) -> Path | None:
    if not src.startswith("/media/"):
        return None
    rel = unquote(src[len("/media/") :].split("?", 1)[0].split("#", 1)[0])
    root = (settings.upload_dir / "media").resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def _add_image(paragraph, token) -> None:
    src = (token.attrs or {}).get("src", "")
    alt = (token.attrs or {}).get("alt", "")
    path = _media_path(src)
    if path is not None:
        try:
            paragraph.add_run().add_picture(str(path), width=Inches(5.5))
            return
        except Exception:  # noqa: BLE001 - 损坏图片降级为文字
            pass
    label = f"[图片：{alt or '未命名'}]"
    if src.startswith(("http://", "https://")):
        _add_hyperlink(paragraph, src, label)
    else:
        run = paragraph.add_run(label)
        run.font.color.rgb = _MUTED_COLOR


def _add_inline(paragraph, children, bold: bool = False, italic: bool = False,
                strike: bool = False, link: str | None = None,
                text_formats: dict | None = None) -> None:
    for child in children or []:
        kind = child.type
        if kind == "text":
            text = child.content
            if link:
                _add_hyperlink(paragraph, link, text)
            else:
                _add_text_runs(paragraph, text, bold, italic, strike, text_formats)
        elif kind == "strong_open":
            bold = True
        elif kind == "strong_close":
            bold = False
        elif kind == "em_open":
            italic = True
        elif kind == "em_close":
            italic = False
        elif kind == "s_open":
            strike = True
        elif kind == "s_close":
            strike = False
        elif kind == "code_inline":
            run = paragraph.add_run(child.content)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        elif kind in ("softbreak", "hardbreak"):
            if kind == "hardbreak":
                paragraph.add_run().add_break()
            else:
                paragraph.add_run(" ")
        elif kind == "link_open":
            link = (child.attrs or {}).get("href")
        elif kind == "link_close":
            link = None
        elif kind == "image":
            _add_image(paragraph, child)
        # html_inline / 未知 inline 直接忽略


def _inline_plain(children) -> str:
    parts: list[str] = []
    for child in children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type == "image":
            attrs = child.attrs or {}
            parts.append(attrs.get("alt") or "")
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts).strip()


def _add_code_block(doc: Document, content: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.12)
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(8)
    _shade_paragraph(paragraph, "F1F5F9")
    lines = (content or "").rstrip("\n").split("\n")
    for index, line in enumerate(lines):
        run = paragraph.add_run(line or " ")
        run.font.name = "Consolas"
        run.font.size = Pt(9.5)
        if index < len(lines) - 1:
            run.add_break()


def _add_table(doc: Document, tokens, start: int) -> int:
    """收集表格 token，返回 table_close 之后的下标。"""
    rows: list[list[str]] = []
    current: list[str] | None = None
    index = start + 1
    while index < len(tokens) and tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "tr_open":
            current = []
            rows.append(current)
        elif token.type in ("th_open", "td_open"):
            text = ""
            if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                text = _inline_plain(tokens[index + 1].children)
                index += 1
            if current is not None:
                current.append(text)
        index += 1
    if rows:
        width = max(len(row) for row in rows)
        table = doc.add_table(rows=len(rows), cols=width)
        table.style = "Table Grid"
        for r_index, row in enumerate(rows):
            for c_index in range(width):
                cell = table.cell(r_index, c_index)
                cell.text = row[c_index] if c_index < len(row) else ""
                if r_index == 0:
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
        doc.add_paragraph()
    return index


_PAPER_LABELS = {"a4": "A4", "letter": "Letter", "a5": "A5"}
_FIELD_TOKEN_RE = re.compile(r"\{(page|pages|total)\}", re.I)


def _paper_label(prefs: dict) -> str:
    key = str(prefs.get("paper") or "a4")
    label = _PAPER_LABELS.get(key, "A4")
    width, height = _PAPER_SIZES_CM.get(key, _PAPER_SIZES_CM["a4"])
    if prefs.get("orientation") == "landscape":
        width, height = height, width
    return f"{label} · {width:g} × {height:g} cm"


def _style_chrome_run(run, font_name: str, size_pt: float = 9.0) -> None:
    run.font.name = font_name
    _run_east_asia(run, font_name)
    run.font.size = Pt(size_pt)
    run.font.color.rgb = _MUTED_COLOR


def _add_field(paragraph, instruction: str, fallback: str, font_name: str) -> None:
    """插入 Word 域（PAGE / NUMPAGES），打开文档时由 Word 自动更新。"""
    parts: list[tuple[str, str | None]] = [
        ("begin", None),
        ("instr", f" {instruction} "),
        ("separate", None),
        ("text", fallback),
        ("end", None),
    ]
    for kind, value in parts:
        run = paragraph.add_run()
        _style_chrome_run(run, font_name)
        if kind == "instr":
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = value
        elif kind == "text":
            node = OxmlElement("w:t")
            node.text = value
        else:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
        run._r.append(node)


def _add_chrome_text(paragraph, template: str, font_name: str, pages: int) -> None:
    """页眉 / 页脚文本，支持 {page} / {pages} / {total} 占位符。"""
    position = 0
    for match in _FIELD_TOKEN_RE.finditer(template):
        if match.start() > position:
            _style_chrome_run(paragraph.add_run(template[position:match.start()]), font_name)
        token = match.group(1).lower()
        if token == "page":
            _add_field(paragraph, "PAGE", "1", font_name)
        else:
            _add_field(paragraph, "NUMPAGES", str(pages), font_name)
        position = match.end()
    if position < len(template):
        _style_chrome_run(paragraph.add_run(template[position:]), font_name)


def _apply_header_footer(doc: Document, prefs: dict, title: str) -> None:
    """把页眉 / 页脚写入 DOCX，与编辑器中纸张上的样式保持一致。"""
    section = doc.sections[0]
    font_name = _FONT_NAMES.get(str(prefs.get("font")), "宋体")
    different_first = prefs.get("differentFirstPage") is True
    section.different_first_page_header_footer = different_first

    def distance(key: str) -> Cm:
        try:
            value = float(prefs.get(key, 1.25))
        except (TypeError, ValueError):
            value = 1.25
        return Cm(min(8.0, max(0.0, value)))

    section.header_distance = distance("headerDistance")
    section.footer_distance = distance("footerDistance")

    header_text = str(prefs.get("headerText") or "").strip() or (title or "无标题文档")
    footer_template = str(prefs.get("footerText") or "").strip()
    if not footer_template:
        footer_template = f"{_paper_label(prefs)}  ·  第 {{page}} 页"

    if prefs.get("showHeader") is not False:
        paragraph = section.header.paragraphs[0]
        paragraph.clear()
        _style_chrome_run(paragraph.add_run(header_text), font_name)
    if prefs.get("showFooter") is not False:
        paragraph = section.footer.paragraphs[0]
        paragraph.clear()
        _add_chrome_text(paragraph, footer_template, font_name, 1)

    if not different_first:
        return
    first_header = str(prefs.get("firstHeaderText") or "").strip()
    first_footer = str(prefs.get("firstFooterText") or "").strip()
    header_paragraph = section.first_page_header.paragraphs[0]
    header_paragraph.clear()
    if first_header:
        _style_chrome_run(header_paragraph.add_run(first_header), font_name)
    footer_paragraph = section.first_page_footer.paragraphs[0]
    footer_paragraph.clear()
    if first_footer:
        _add_chrome_text(footer_paragraph, first_footer, font_name, 1)


def markdown_to_docx(
    title: str,
    body_md: str,
    prefs: dict | None = None,
    paragraph_formats: list | None = None,
    text_formats: list | None = None,
) -> BytesIO:
    prefs = _docx_prefs(prefs)
    formats = _paragraph_formats(paragraph_formats)
    run_formats = {"records": _text_formats(text_formats), "index": 0}
    doc = Document()
    typo = _page_setup(doc, prefs)
    _apply_header_footer(doc, prefs, title)
    font_name = typo["font_name"]
    size_pt = typo["size_pt"]
    normal = doc.styles["Normal"]
    normal.font.name = font_name
    normal.font.size = Pt(size_pt)
    _east_asia(normal, font_name)
    normal.paragraph_format.line_spacing = typo["line_spacing"]
    normal.paragraph_format.space_before = Pt(typo["space_before_pt"])
    normal.paragraph_format.space_after = Pt(typo["space_after_pt"])
    for style_name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        try:
            _east_asia(doc.styles[style_name], font_name)
        except KeyError:
            continue

    # 笔记标题属于文档元信息（Word 模式显示在纸张外），不写进正文，避免预览与编辑区不一致。
    doc.core_properties.title = title or "无标题文档"

    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    tokens = md.parse(body_md or "")
    list_stack: list[str] = []
    quote_depth = 0
    block_index = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type

        if kind == "heading_open":
            level = min(int(token.tag[1]), 4)
            paragraph = doc.add_heading("", level=level)
            if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                _add_inline(paragraph, tokens[index + 1].children, text_formats=run_formats)
                for run in paragraph.runs:
                    run.font.color.rgb = _HEADING_COLOR
            fmt = formats.get(block_index)
            if fmt:
                _apply_paragraph_format(paragraph, fmt, typo)
            block_index += 1
            index += 3
            continue

        if kind == "paragraph_open":
            paragraph = None
            if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                children = tokens[index + 1].children
                if list_stack:
                    depth = min(len(list_stack), 3)
                    base = "List Bullet" if list_stack[-1] == "bullet" else "List Number"
                    style = base if depth == 1 else f"{base} {depth}"
                    paragraph = doc.add_paragraph(style=style)
                elif quote_depth:
                    paragraph = doc.add_paragraph(style="Quote")
                else:
                    paragraph = doc.add_paragraph()
                    _apply_paragraph_layout(paragraph, typo)
                _add_inline(paragraph, children, text_formats=run_formats)
                if not list_stack and not quote_depth and children and all(
                    c.type == "image" for c in children
                ):
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            fmt = formats.get(block_index)
            if paragraph is not None and fmt:
                _apply_paragraph_format(paragraph, fmt, typo)
            block_index += 1
            index += 3
            continue

        if kind == "bullet_list_open":
            list_stack.append("bullet")
        elif kind == "ordered_list_open":
            list_stack.append("ordered")
        elif kind in ("bullet_list_close", "ordered_list_close"):
            if list_stack:
                list_stack.pop()
        elif kind == "blockquote_open":
            quote_depth += 1
        elif kind == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
        elif kind in ("fence", "code_block"):
            if kind == "fence" and token.info.strip() == "kiwi-pagebreak":
                doc.add_page_break()
            else:
                _add_code_block(doc, token.content)
        elif kind == "table_open":
            index = _add_table(doc, tokens, index)
            continue
        elif kind == "hr":
            _add_hr(doc)
        index += 1

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
