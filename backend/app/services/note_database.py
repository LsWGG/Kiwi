"""数据表笔记：默认字段/视图、字段与行数据校验、懒创建集合。"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, NoteCollection

FIELD_TYPES = {
    "text",
    "long_text",
    "number",
    "rating",
    "progress",
    "select",
    "multi_select",
    "date",
    "checkbox",
    "url",
    "attachment",
}
VIEW_TYPES = {"table", "kanban", "gallery", "calendar"}
FIELD_ID_RE = re.compile(r"^[a-zA-Z0-9_]{1,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FIELDS = 40
MAX_VIEWS = 12
MAX_OPTIONS = 50
MAX_TEXT = 5000
MAX_LONG_TEXT = 20000
MAX_RATING = 5
MAX_PROGRESS = 100
MAX_ATTACHMENTS = 20
BAR_COLORS = {"slate", "blue", "green", "amber", "rose", "violet", "cyan", "orange"}
FILTER_OPS = {
    "contains",
    "not_contains",
    "is",
    "is_not",
    "is_empty",
    "is_not_empty",
    "gt",
    "gte",
    "lt",
    "lte",
}


def default_fields() -> list[dict]:
    return [
        {"id": "name", "name": "名称", "type": "text"},
        {
            "id": "status",
            "name": "状态",
            "type": "select",
            "options": [
                {"id": "todo", "name": "待办", "color": "slate"},
                {"id": "doing", "name": "进行中", "color": "blue"},
                {"id": "done", "name": "已完成", "color": "green"},
            ],
        },
        {"id": "date", "name": "日期", "type": "date"},
    ]


def default_views() -> list[dict]:
    return [
        {"id": "table", "name": "表格", "type": "table", "hidden_fields": []},
        {"id": "kanban", "name": "看板", "type": "kanban", "group_field": "status"},
        {"id": "gallery", "name": "画册", "type": "gallery", "cover_field": None, "title_field": "name"},
        {
            "id": "calendar",
            "name": "日历",
            "type": "calendar",
            "date_field": "date",
            "end_field": None,
            "title_field": "name",
            "bar_color": None,
        },
    ]


def default_schema() -> dict:
    return {"fields": default_fields()}


def default_views_for(fields: list[dict]) -> list[dict]:
    """按现有字段生成可用视图（字段被删后不产生失效引用）。"""
    text = _first_field_of(fields, {"text", "long_text", "url"})
    views: list[dict] = [{"id": "table", "name": "表格", "type": "table", "hidden_fields": []}]
    select = _first_field_of(fields, {"select"})
    if select is not None:
        views.append({"id": "kanban", "name": "看板", "type": "kanban", "group_field": select})
    views.append(
        {
            "id": "gallery",
            "name": "画册",
            "type": "gallery",
            "cover_field": None,
            "title_field": text,
        }
    )
    date = _first_field_of(fields, {"date"})
    if date is not None:
        views.append(
            {
                "id": "calendar",
                "name": "日历",
                "type": "calendar",
                "date_field": date,
                "end_field": None,
                "title_field": text,
                "bar_color": None,
            }
        )
    return views


def _normalize_options(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("select 字段的 options 必须是数组")
    if len(raw) > MAX_OPTIONS:
        raise ValueError(f"每个选择字段最多 {MAX_OPTIONS} 个选项")
    out: list[dict] = []
    seen: set[str] = set()
    for opt in raw:
        if not isinstance(opt, dict):
            raise ValueError("选项必须是对象")
        oid = str(opt.get("id") or "").strip()
        name = str(opt.get("name") or "").strip()
        if not oid or oid in seen:
            raise ValueError("选项 id 缺失或重复")
        if not name or len(name) > 60:
            raise ValueError("选项名称不能为空且不超过 60 字")
        seen.add(oid)
        item = {"id": oid, "name": name}
        color = opt.get("color")
        if isinstance(color, str) and color:
            item["color"] = color[:20]
        out.append(item)
    return out


def validate_fields(raw: Any) -> list[dict]:
    """校验并规范化字段定义；非法输入抛 ValueError。"""
    if not isinstance(raw, list) or not raw:
        raise ValueError("至少需要一个字段")
    if len(raw) > MAX_FIELDS:
        raise ValueError(f"最多 {MAX_FIELDS} 个字段")
    fields: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("字段必须是对象")
        fid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        ftype = str(item.get("type") or "").strip()
        if not FIELD_ID_RE.match(fid):
            raise ValueError("字段 id 只能包含字母、数字、下划线，长度 1-40")
        if fid in seen:
            raise ValueError(f"字段 id 重复：{fid}")
        if not name or len(name) > 60:
            raise ValueError("字段名称不能为空且不超过 60 字")
        if ftype not in FIELD_TYPES:
            raise ValueError(f"不支持的字段类型：{ftype}")
        seen.add(fid)
        field: dict = {"id": fid, "name": name, "type": ftype}
        if ftype in ("select", "multi_select"):
            field["options"] = _normalize_options(item.get("options"))
        fields.append(field)
    return fields


def _first_field_of(fields: list[dict], types: set[str]) -> str | None:
    for f in fields:
        if f["type"] in types:
            return f["id"]
    return None


def validate_views(raw: Any, fields: list[dict]) -> list[dict]:
    """校验视图配置，并确保引用字段存在。"""
    if not isinstance(raw, list) or not raw:
        return default_views_for(fields)
    if len(raw) > MAX_VIEWS:
        raise ValueError(f"最多 {MAX_VIEWS} 个视图")
    by_id = {f["id"]: f for f in fields}
    first_select = _first_field_of(fields, {"select"})
    first_date = _first_field_of(fields, {"date"})
    first_text = _first_field_of(fields, {"text", "long_text", "url"})
    views: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("视图必须是对象")
        vid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        vtype = str(item.get("type") or "").strip()
        if not vid or vid in seen:
            raise ValueError("视图 id 缺失或重复")
        if not name or len(name) > 60:
            raise ValueError("视图名称不能为空且不超过 60 字")
        if vtype not in VIEW_TYPES:
            raise ValueError(f"不支持的视图类型：{vtype}")
        seen.add(vid)
        view: dict = {"id": vid, "name": name, "type": vtype}

        if vtype == "table":
            hidden = item.get("hidden_fields") or []
            if not isinstance(hidden, list):
                raise ValueError("hidden_fields 必须是数组")
            view["hidden_fields"] = [h for h in hidden if h in by_id]
            raw_widths = item.get("column_widths") or {}
            if not isinstance(raw_widths, dict):
                raise ValueError("column_widths 必须是对象")
            widths: dict[str, int] = {}
            for field_id, width in raw_widths.items():
                if field_id not in by_id:
                    continue
                if isinstance(width, bool) or not isinstance(width, (int, float)):
                    continue
                widths[field_id] = max(60, min(600, int(width)))
            view["column_widths"] = widths
            raw_heights = item.get("row_heights") or {}
            if not isinstance(raw_heights, dict):
                raise ValueError("row_heights 必须是对象")
            heights: dict[str, int] = {}
            for row_id, height in list(raw_heights.items())[:500]:
                if not isinstance(row_id, str) or not row_id or len(row_id) > 64:
                    continue
                if isinstance(height, bool) or not isinstance(height, (int, float)):
                    continue
                heights[row_id] = max(36, min(400, int(height)))
            view["row_heights"] = heights

            raw_filters = item.get("filters") or []
            if not isinstance(raw_filters, list):
                raise ValueError("filters 必须是数组")
            filters: list[dict] = []
            for entry in raw_filters[:20]:
                if not isinstance(entry, dict):
                    continue
                field_id = entry.get("field")
                op = str(entry.get("op") or "").strip()
                if field_id not in by_id or op not in FILTER_OPS:
                    continue
                value = entry.get("value")
                if isinstance(value, (dict, list)):
                    continue
                if isinstance(value, str):
                    value = value[:500]
                elif not isinstance(value, (int, float, bool, type(None))):
                    continue
                filters.append(
                    {
                        "id": str(entry.get("id") or "")[:40],
                        "field": field_id,
                        "op": op,
                        "value": value,
                    }
                )
            view["filters"] = filters

            raw_sorts = item.get("sorts") or []
            if not isinstance(raw_sorts, list):
                raise ValueError("sorts 必须是数组")
            sorts: list[dict] = []
            seen_sort: set[str] = set()
            for entry in raw_sorts[:5]:
                if not isinstance(entry, dict):
                    continue
                field_id = entry.get("field")
                direction = str(entry.get("direction") or "").strip()
                if (
                    field_id not in by_id
                    or field_id in seen_sort
                    or direction not in {"asc", "desc"}
                ):
                    continue
                seen_sort.add(field_id)
                sorts.append({"field": field_id, "direction": direction})
            view["sorts"] = sorts

        elif vtype == "kanban":
            group = item.get("group_field") or first_select
            if not group or group not in by_id:
                raise ValueError("看板视图需要一个存在的分组字段")
            if by_id[group]["type"] != "select":
                raise ValueError("看板分组字段必须是单选类型")
            view["group_field"] = group
            display_fields = item.get("display_fields")
            if display_fields is None:
                view["display_fields"] = None
            else:
                if not isinstance(display_fields, list):
                    raise ValueError("display_fields 必须是数组")
                ordered: list[str] = []
                for field_id in display_fields:
                    if (
                        isinstance(field_id, str)
                        and field_id in by_id
                        and field_id != group
                        and field_id not in ordered
                    ):
                        ordered.append(field_id)
                view["display_fields"] = ordered

        elif vtype == "gallery":
            cover = item.get("cover_field")
            if cover and cover not in by_id:
                raise ValueError("画册封面字段不存在")
            title = item.get("title_field") or first_text
            if title and title not in by_id:
                raise ValueError("画册标题字段不存在")
            view["cover_field"] = cover or None
            view["title_field"] = title

        else:  # calendar
            date_field = item.get("date_field") or first_date
            if not date_field or date_field not in by_id:
                raise ValueError("日历视图需要一个日期字段")
            if by_id[date_field]["type"] != "date":
                raise ValueError("日历日期字段必须是日期类型")
            end_field = item.get("end_field")
            if end_field and end_field not in by_id:
                end_field = None
            if end_field and by_id[end_field]["type"] != "date":
                raise ValueError("日历结束字段必须是日期类型")
            if end_field == date_field:
                end_field = None
            title = item.get("title_field") or first_text
            if title and title not in by_id:
                raise ValueError("日历标题字段不存在")
            bar_color = item.get("bar_color")
            if bar_color is not None and bar_color not in BAR_COLORS:
                raise ValueError("不支持的横条颜色")
            view["date_field"] = date_field
            view["end_field"] = end_field or None
            view["title_field"] = title
            view["bar_color"] = bar_color or None

        views.append(view)
    return views


def _normalize_attachments(value: Any) -> list[dict]:
    """附件字段：允许一个或多个文件，保存预览所需的元数据快照。"""
    if not isinstance(value, list):
        raise ValueError("附件字段需要文件数组")
    if len(value) > MAX_ATTACHMENTS:
        raise ValueError(f"每个附件字段最多 {MAX_ATTACHMENTS} 个文件")
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("附件必须是对象")
        filename = str(item.get("filename") or "").strip()
        url = str(item.get("url") or "").strip()
        if not filename or len(filename) > 300:
            raise ValueError("附件名称不能为空且不超过 300 字")
        if not url or len(url) > 1000:
            raise ValueError("附件地址不能为空且不超过 1000 字")
        if not (url.startswith("/media/") or url.startswith("http://") or url.startswith("https://")):
            raise ValueError("附件地址不合法")
        raw_size = item.get("size", 0)
        if isinstance(raw_size, bool) or not isinstance(raw_size, (int, float)) or raw_size < 0:
            raise ValueError("附件大小不合法")
        content_type = str(item.get("content_type") or "").strip()[:120]
        out.append(
            {
                "id": str(item.get("id") or "").strip()[:64],
                "filename": filename,
                "url": url,
                "content_type": content_type,
                "size": int(raw_size),
            }
        )
    return out


def _validate_value(field: dict, value: Any) -> Any:
    ftype = field["type"]
    if ftype == "checkbox":
        if not isinstance(value, bool):
            raise ValueError(f"字段「{field['name']}」需要布尔值")
        return value
    if value is None:
        return None
    if ftype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"字段「{field['name']}」需要数字")
        return value
    if ftype == "attachment":
        return _normalize_attachments(value)
    if ftype == "rating":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"字段「{field['name']}」需要 0-{MAX_RATING} 的整数评分")
        if int(value) != value or value < 0 or value > MAX_RATING:
            raise ValueError(f"字段「{field['name']}」需要 0-{MAX_RATING} 的整数评分")
        return int(value)
    if ftype == "progress":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"字段「{field['name']}」需要 0-{MAX_PROGRESS} 的整数进度")
        if int(value) != value or value < 0 or value > MAX_PROGRESS:
            raise ValueError(f"字段「{field['name']}」需要 0-{MAX_PROGRESS} 的整数进度")
        return int(value)
    if ftype == "multi_select":
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError(f"字段「{field['name']}」需要选项 id 数组")
        allowed = {o["id"] for o in field.get("options", [])}
        invalid = [v for v in value if v not in allowed]
        if invalid:
            raise ValueError(f"字段「{field['name']}」包含未知选项")
        return list(dict.fromkeys(value))
    if not isinstance(value, str):
        raise ValueError(f"字段「{field['name']}」需要文本")
    limit = MAX_LONG_TEXT if ftype == "long_text" else MAX_TEXT
    if len(value) > limit:
        raise ValueError(f"字段「{field['name']}」超出长度限制")
    if ftype == "select":
        if value == "":
            return None
        allowed = {o["id"] for o in field.get("options", [])}
        if value not in allowed:
            raise ValueError(f"字段「{field['name']}」包含未知选项")
        return value
    if ftype == "date":
        if value == "":
            return None
        if not DATE_RE.match(value):
            raise ValueError(f"字段「{field['name']}」需要 YYYY-MM-DD 日期")
        return value
    # text / url
    return value


def normalize_row_data(raw: Any, fields: list[dict]) -> dict:
    """过滤未知字段并逐字段校验，返回可持久化的 data。"""
    if not isinstance(raw, dict):
        raise ValueError("行数据必须是对象")
    out: dict = {}
    for field in fields:
        fid = field["id"]
        if fid not in raw:
            continue
        value = _validate_value(field, raw[fid])
        # 显式传入的 null 也要保留，PATCH 合并后才能真正清空单元格
        out[fid] = value
    return out


def row_title(row_data: dict, fields: list[dict]) -> str:
    """行标题：优先 name/title 字段，其次第一个文本字段。"""
    for preferred in ("name", "title"):
        value = (row_data or {}).get(preferred)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    for field in fields:
        if field.get("type") in ("text", "long_text", "url"):
            value = (row_data or {}).get(field["id"])
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    return "未命名记录"


def _sync_row_note(note: Note, database_note: Note, coll: NoteCollection, row) -> None:
    title = row_title(row.data or {}, (coll.schema_json or {}).get("fields") or [])
    if note.title != title:
        note.title = title
    props = dict(note.props_json or {})
    props.update(
        {
            "collection_id": str(coll.id),
            "collection_note_id": str(database_note.id),
            "collection_row_id": str(row.id),
        }
    )
    if props != (note.props_json or {}):
        note.props_json = props


async def sync_row_note_if_exists(
    session: AsyncSession, database_note: Note, coll: NoteCollection, row
) -> Note | None:
    """记录已生成笔记时，同步标题与集合上下文；未生成则不做任何事。"""
    if row.note_id is None:
        return None
    note = await session.get(Note, row.note_id)
    if note is None:
        # 笔记被单独删除后外键会级联删行；这里兜底清掉悬空引用
        row.note_id = None
        return None
    _sync_row_note(note, database_note, coll, row)
    return note


async def ensure_row_note(
    session: AsyncSession, database_note: Note, coll: NoteCollection, row
) -> Note:
    """为指定行生成（或复用）一篇完整笔记（可打开、可链接、可打标签）。"""
    if row.note_id is not None:
        note = await session.get(Note, row.note_id)
        if note is not None:
            _sync_row_note(note, database_note, coll, row)
            return note
    fields = (coll.schema_json or {}).get("fields") or []
    note = Note(
        kb_id=database_note.kb_id,
        title=row_title(row.data or {}, fields),
        body_md="",
        kind="doc",
        folder_id=database_note.folder_id,
        status="active",
        view_mode="edit",
        props_json={
            "collection_id": str(coll.id),
            "collection_note_id": str(database_note.id),
            "collection_row_id": str(row.id),
        },
    )
    session.add(note)
    await session.flush()
    row.note_id = note.id
    return note


async def ensure_collection(session: AsyncSession, note: Note) -> NoteCollection:
    """取笔记对应的集合；历史数据缺失时懒修复。"""
    coll = (
        await session.execute(
            select(NoteCollection).where(
                NoteCollection.note_id == note.id, NoteCollection.kb_id == note.kb_id
            )
        )
    ).scalar_one_or_none()
    if coll is None:
        coll = NoteCollection(
            kb_id=note.kb_id,
            note_id=note.id,
            name=note.title,
            description="",
            schema_json=default_schema(),
            views_json=default_views(),
        )
        session.add(coll)
        await session.flush()
        return coll
    fields = (coll.schema_json or {}).get("fields")
    if not fields:
        coll.schema_json = default_schema()
        if not coll.views_json:
            coll.views_json = default_views()
        await session.flush()
    elif not coll.views_json:
        coll.views_json = default_views()
        await session.flush()
    return coll
