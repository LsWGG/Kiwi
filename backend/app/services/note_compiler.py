"""把工作区笔记转成可编译进 Wiki 的 Markdown。

文档 / 导入 / 链接直接使用正文；数据表、画布、Notebook 与表格把结构化内容
序列化，保证「全部笔记类型都能沉淀为 Wiki 知识」。
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionRow, Note, NoteCollection

MAX_TABLE_ROWS = 200
MAX_SHEET_ROWS = 200
MAX_SHEET_COLS = 20
MAX_CANVAS_TEXT = 4000

CANVAS_SHAPE_LABEL = {
    "rect": "矩形",
    "round": "圆角框",
    "ellipse": "椭圆",
    "diamond": "菱形判断",
    "text": "文本",
    "sticky": "便签",
    "uml": "UML 类",
    "table": "表结构",
    "network": "网络设备",
}

NETWORK_LABEL = {
    "cloud": "云",
    "server": "服务器",
    "database": "数据库",
    "router": "路由器",
    "firewall": "防火墙",
    "client": "客户端",
    "switch": "交换机",
    "storage": "存储",
}

FIELD_TYPE_LABEL = {
    "text": "文本",
    "long_text": "长文本",
    "number": "数字",
    "rating": "评分",
    "progress": "进度",
    "select": "单选",
    "multi_select": "多选",
    "date": "日期",
    "checkbox": "勾选",
    "url": "链接",
    "attachment": "附件",
}


def _cell(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


def _option_name(field: dict, raw: Any) -> str:
    """select / multi_select 的存储值可能是选项 id 或对象。"""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("label") or raw.get("id") or "")
    text = str(raw)
    for option in field.get("options") or []:
        if isinstance(option, dict) and str(option.get("id")) == text:
            return str(option.get("name") or option.get("label") or text)
    return text


def _field_value(field: dict, value: Any) -> str:
    if value is None or value == "" or value == []:
        return ""
    kind = field.get("type")
    if kind == "select":
        return _option_name(field, value)
    if kind == "multi_select":
        if isinstance(value, list):
            return "、".join(_option_name(field, item) for item in value if item)
        return _option_name(field, value)
    if kind == "checkbox":
        return "是" if value else "否"
    if kind == "attachment":
        if isinstance(value, list):
            names = []
            for item in value:
                if isinstance(item, dict):
                    names.append(str(item.get("filename") or item.get("name") or ""))
                elif item:
                    names.append(str(item))
            return "、".join(name for name in names if name)
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _database_markdown(
    note: Note, collection: NoteCollection, rows: list[CollectionRow], row_notes: dict[str, Note]
) -> str:
    fields = [
        field
        for field in (collection.schema_json or {}).get("fields") or []
        if isinstance(field, dict) and field.get("id")
    ]
    lines: list[str] = [f"# {note.title or collection.name or '数据表'}", ""]
    if collection.description.strip():
        lines += [collection.description.strip(), ""]
    lines.append(f"> 数据表：{len(rows)} 条记录，{len(fields)} 个字段。")
    lines.append("")

    if fields:
        lines.append("## 字段")
        for field in fields:
            label = FIELD_TYPE_LABEL.get(str(field.get("type")), str(field.get("type") or "文本"))
            extra = ""
            if field.get("type") in ("select", "multi_select"):
                names = [
                    str(option.get("name") or option.get("id"))
                    for option in field.get("options") or []
                    if isinstance(option, dict)
                ]
                if names:
                    extra = f"：{' / '.join(names)}"
            lines.append(f"- {field.get('name') or field.get('id')}（{label}{extra}）")
        lines.append("")

    if rows and fields:
        lines.append("## 记录")
        lines.append("")
        lines.append("| " + " | ".join(_cell(f.get("name") or f.get("id")) for f in fields) + " |")
        lines.append("| " + " | ".join("---" for _ in fields) + " |")
        for row in rows[:MAX_TABLE_ROWS]:
            data = row.data or {}
            lines.append(
                "| "
                + " | ".join(
                    _cell(_field_value(field, data.get(field.get("id")))) for field in fields
                )
                + " |"
            )
        if len(rows) > MAX_TABLE_ROWS:
            lines.append("")
            lines.append(f"> 仅列出前 {MAX_TABLE_ROWS} 条，共 {len(rows)} 条记录。")
        lines.append("")

    # 行笔记可能承载长文描述，附在表格之后一起沉淀。
    detailed = [
        (row, row_notes.get(str(row.note_id)))
        for row in rows
        if row.note_id and str(row.note_id) in row_notes
    ]
    if detailed:
        lines.append("## 记录详情")
        for row, row_note in detailed:
            body = (row_note.body_md or "").strip()
            if not body:
                continue
            title = (row_note.title or "").strip() or str(
                (row.data or {}).get("name") or "未命名记录"
            )
            lines += [f"### {title}", "", body, ""]

    return "\n".join(lines).strip()


def _canvas_markdown(note: Note) -> str:
    props = note.props_json or {}
    doc = props.get("canvas_doc") if isinstance(props.get("canvas_doc"), dict) else {}
    nodes = [node for node in doc.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in doc.get("edges") or [] if isinstance(edge, dict)]
    if not nodes and not edges:
        return ""

    node_text: dict[str, str] = {}
    lines: list[str] = [f"# {note.title or '画布'}", ""]
    theme = str(doc.get("theme") or "engineering")
    theme_label = {
        "blueprint": "工程蓝图",
        "engineering": "工程制图",
        "paper": "纸质草图",
        "midnight": "深色夜间",
    }.get(theme, theme)
    lines.append(f"> 画布（{theme_label}）：{len(nodes)} 个节点，{len(edges)} 条连线。")
    lines.append("")

    if nodes:
        lines.append("## 节点")
        ordered = sorted(
            nodes,
            key=lambda node: (float(node.get("y") or 0), float(node.get("x") or 0)),
        )
        for node in ordered:
            text = str(node.get("text") or "").strip()
            if len(text) > MAX_CANVAS_TEXT:
                text = text[:MAX_CANVAS_TEXT] + "…"
            shape = str(node.get("shape") or "rect")
            shape_label = CANVAS_SHAPE_LABEL.get(shape, shape)
            if shape == "network" and node.get("variant"):
                shape_label = NETWORK_LABEL.get(str(node["variant"]), shape_label)
            node_id = str(node.get("id") or "")
            node_text[node_id] = text.splitlines()[0][:120] if text else shape_label
            if text:
                lines.append(f"- **{shape_label}**：{text}")
            else:
                lines.append(f"- **{shape_label}**（空）")
        lines.append("")

    if edges:
        lines.append("## 连线")
        for edge in edges:
            from_id = str((edge.get("from") or {}).get("nodeId") or "")
            to_id = str((edge.get("to") or {}).get("nodeId") or "")
            source = node_text.get(from_id, from_id or "自由端点")
            target = node_text.get(to_id, to_id or "自由端点")
            label = str(edge.get("label") or "").strip()
            arrow = f"{source} → {target}"
            lines.append(f"- {arrow}" + (f"（{label}）" if label else ""))
        lines.append("")

    return "\n".join(lines).strip()


def _link_markdown(note: Note) -> str:
    body = (note.body_md or "").strip()
    props = note.props_json or {}
    link = props.get("link") if isinstance(props.get("link"), dict) else {}
    url = str(link.get("final_url") or link.get("url") or "")
    site = str(link.get("site") or "")
    excerpt = str(link.get("excerpt") or "").strip()
    if not body and not excerpt and not url:
        return ""
    lines = [f"# {note.title or '链接笔记'}", ""]
    if site or url:
        lines.append(f"> 来源：{site + ' · ' if site else ''}{url}")
        lines.append("")
    if body:
        lines.append(body)
    elif excerpt:
        lines.append(excerpt)
    return "\n".join(lines).strip()


class _HtmlTableParser(HTMLParser):
    """把 Notebook 的 DataFrame HTML 输出还原成 Markdown 表格。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _html_table_markdown(html: str) -> str:
    if "<table" not in html.lower():
        return ""
    parser = _HtmlTableParser()
    try:
        parser.feed(html)
    except Exception:
        return ""
    rows = parser.rows
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header, body = normalized[0], normalized[1:]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"

    lines = [line(header), "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines.extend(line(row) for row in body)
    return "\n".join(lines)


def _a1_position(address: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+)", address.strip())
    if not match:
        return None
    col = 0
    for char in match.group(1).upper():
        col = col * 26 + (ord(char) - 64)
    return int(match.group(2)) - 1, col - 1


def _column_label(index: int) -> str:
    label = ""
    value = index + 1
    while value > 0:
        value, rem = divmod(value - 1, 26)
        label = chr(65 + rem) + label
    return label


def _sheet_cell_text(cell: object) -> tuple[str, bool]:
    """单元格展示文本与是否加粗；公式优先取导入时缓存的计算结果。"""
    if not isinstance(cell, dict):
        return "", False
    style = cell.get("s") if isinstance(cell.get("s"), dict) else {}
    bold = bool(style.get("bold"))
    for key in ("v", "cached"):
        value = cell.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return ("是" if value else "否"), bold
        if isinstance(value, float) and value.is_integer():
            return str(int(value)), bold
        return str(value), bold
    return "", bold


def _sheet_markdown(note: Note) -> str:
    """表格笔记：说明正文 + 每个工作表转成 Markdown 表格。"""
    props = note.props_json or {}
    workbook = props.get("sheet") if isinstance(props.get("sheet"), dict) else {}
    sheets = [item for item in workbook.get("sheets") or [] if isinstance(item, dict)]
    blocks: list[list[str]] = []
    for sheet in sheets:
        cells = sheet.get("cells") if isinstance(sheet.get("cells"), dict) else {}
        used: dict[tuple[int, int], tuple[str, bool]] = {}
        for address, cell in cells.items():
            position = _a1_position(str(address))
            text, bold = _sheet_cell_text(cell)
            if position is not None and text:
                used[position] = (text, bold)
        if not used:
            continue
        min_row = min(row for row, _ in used)
        max_row = max(row for row, _ in used)
        min_col = min(col for _, col in used)
        max_col = max(col for _, col in used)
        row_count = max_row - min_row + 1
        col_count = max_col - min_col + 1
        visible_rows = min(row_count, MAX_SHEET_ROWS)
        visible_cols = min(col_count, MAX_SHEET_COLS)
        columns = list(range(min_col, min_col + visible_cols))
        first_row = [used.get((min_row, col)) for col in columns]
        # 首行整行加粗（导入表格常见）时作为表头，否则用列号保证数据不丢。
        header_bold = bool(first_row) and all(item and item[1] for item in first_row if item)
        if header_bold and any(first_row):
            header = [item[0] if item else "" for item in first_row]
            data_start = min_row + 1
        else:
            header = [_column_label(col) for col in columns]
            data_start = min_row
        name = str(sheet.get("name") or f"工作表 {len(blocks) + 1}")
        block: list[str] = [f"## {name}", ""]
        block.append("| " + " | ".join(_cell(value) for value in header) + " |")
        block.append("| " + " | ".join("---" for _ in header) + " |")
        for row in range(data_start, min_row + visible_rows):
            values = [used.get((row, col), ("", False))[0] for col in columns]
            block.append("| " + " | ".join(_cell(value) for value in values) + " |")
        block.append("")
        if row_count > MAX_SHEET_ROWS or col_count > MAX_SHEET_COLS:
            block += [
                f"> 仅列出前 {visible_rows} 行、{visible_cols} 列，"
                f"工作表共 {row_count} 行 × {col_count} 列。",
                "",
            ]
        blocks.append(block)

    body = (note.body_md or "").strip()
    if not blocks:
        return body
    lines: list[str] = [f"# {note.title or '表格'}", ""]
    if body:
        lines += [body, ""]
    for block in blocks:
        lines += block
    return "\n".join(lines).strip()


def _notebook_markdown(note: Note) -> str:
    doc = (note.props_json or {}).get("notebook_doc")
    if not isinstance(doc, dict):
        return ""
    cells = [cell for cell in doc.get("cells") or [] if isinstance(cell, dict)]
    if not cells:
        return ""
    language = str(doc.get("language") or "python")
    lines: list[str] = [f"# {note.title or 'Notebook'}", ""]
    for index, cell in enumerate(cells, start=1):
        kind = str(cell.get("type") or "code")
        source = str(cell.get("source") or "").rstrip()
        if kind == "markdown":
            if source:
                lines += [source, ""]
            continue
        if not source:
            continue
        lines += [f"## 代码单元 {index}", "", f"```{language}", source, "```", ""]
        output_blocks: list[str] = []
        for output in cell.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            table = _html_table_markdown(str(output.get("html") or ""))
            if table:
                output_blocks.append(table)
                continue
            text = str(output.get("text") or "").rstrip()
            if text:
                output_blocks.append(f"```text\n{text}\n```")
        if output_blocks:
            lines += ["**运行输出**", "", "\n\n".join(output_blocks), ""]
    return "\n".join(lines).strip()


async def build_note_compile_markdown(session: AsyncSession, note: Note) -> str:
    """返回编译用 Markdown；没有可编译内容时返回空字符串。"""
    if note.kind == "canvas":
        return _canvas_markdown(note)
    if note.kind == "link":
        return _link_markdown(note)
    if note.kind == "notebook":
        return _notebook_markdown(note)
    if note.kind == "sheet":
        return _sheet_markdown(note)
    if note.kind == "database":
        collection = (
            await session.execute(select(NoteCollection).where(NoteCollection.note_id == note.id))
        ).scalar_one_or_none()
        if collection is None:
            return ""
        rows = list(
            (
                await session.execute(
                    select(CollectionRow)
                    .where(CollectionRow.collection_id == collection.id)
                    .order_by(CollectionRow.sort_order, CollectionRow.created_at)
                )
            )
            .scalars()
            .all()
        )
        row_note_ids = [row.note_id for row in rows if row.note_id]
        row_notes: dict[str, Note] = {}
        if row_note_ids:
            for row_note in (
                await session.execute(select(Note).where(Note.id.in_(row_note_ids)))
            ).scalars():
                row_notes[str(row_note.id)] = row_note
        return _database_markdown(note, collection, rows, row_notes)
    return (note.body_md or "").strip()
