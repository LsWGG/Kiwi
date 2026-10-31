"""待办双向同步：把知识库内散落的待办汇总到「收件箱」。

来源：
- 笔记正文中的 Markdown 任务项（``- [ ]`` / ``- [x]``）；
- 时间轴组件时间点正文中的任务项（``props.points[].content``）；
- 数据表中带状态字段的行（状态为待办 / 进行中 / 已完成）。

收件箱是一篇自动维护的笔记：每条待办都带来源笔记链接（正向追溯），
勾选状态会写回来源；来源笔记 / 数据表更新后，下一次同步会把状态带回收件箱
（逆向同步）。定时周期由知识库配置 ``todo_sync_interval_hours`` 控制。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CollectionRow,
    KnowledgeBase,
    Note,
    NoteCollection,
    NoteFolder,
    TodoMirror,
)
from app.db.session import async_session_factory
from app.services.note_database import row_title, sync_row_note_if_exists

logger = logging.getLogger("kiwi.todo")

HUB_FOLDER_NAME = "收件箱"
HUB_NOTE_TITLE = "待办汇总"

# 支持块引用中的任务项：`> - [ ] xxx`（子笔记复制引用块时很常见），
# 前缀原样保留，勾选回写时不会破坏引用结构。
TASK_RE = re.compile(
    r"^(?P<quote>(?:\s*>\s*)*)(?P<indent>\s*)[-*+]\s+"
    r"\[(?P<state>[ xX])\]\s+(?P<text>.+?)\s*$"
)
TODO_LINK_RE = re.compile(r"kiwi://todo/([0-9a-fA-F-]{36})")
PLUGIN_LANGUAGE = "kiwi-plugin"
PLUGIN_FENCE_OPEN_RE = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*" + PLUGIN_LANGUAGE + r"[ \t]*$"
)
PLUGIN_FENCE_CLOSE_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*$")
# source_ref 形如 plugin:<区块序号>:<时间点指纹>:<任务文本指纹>:<同文序号>
PLUGIN_TASK_REF_RE = re.compile(
    r"^plugin:(?P<block>\d+):(?P<point>[0-9a-f]{12}|i\d+):"
    r"(?P<digest>[0-9a-f]{16}):(?P<ordinal>\d+)$"
)
DONE_NAMES = {
    "done",
    "complete",
    "completed",
    "closed",
    "finished",
    "完成",
    "已完成",
    "已结束",
}
OPEN_NAMES = {
    "todo",
    "to do",
    "open",
    "pending",
    "doing",
    "in progress",
    "in_progress",
    "in review",
    "待办",
    "未开始",
    "进行中",
    "待处理",
    "处理中",
}

# KB → 延迟同步任务（合并短时间内的大量编辑）
_pending: dict[uuid.UUID, asyncio.Task[None]] = {}


@dataclass(frozen=True)
class PluginFence:
    """正文中的一个 ```kiwi-plugin 围栏（序号按文档顺序，包含无法解析的围栏）。"""

    index: int
    open_line: int
    content_start: int
    close_line: int
    fence: str
    payload: dict | None


@dataclass(frozen=True)
class PluginTask:
    """组件插件里的一个任务项（目前来自时间轴的时间点正文）。"""

    ref: str
    text: str
    checked: bool
    block_index: int
    block_title: str
    point_id: str
    point_index: int
    point_time: str
    point_summary: str
    task_index: int


def _norm(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())


def _task_ref(text: str, ordinal: int) -> str:
    return f"task:{sha1(text.encode('utf-8')).hexdigest()[:16]}:{ordinal}"


def _option_by_value(field: dict, raw) -> dict | None:
    options = [o for o in field.get("options") or [] if isinstance(o, dict)]
    if isinstance(raw, dict):
        raw_id = raw.get("id")
        raw_name = _norm(raw.get("name") or "")
    else:
        raw_id = raw
        raw_name = _norm(str(raw or ""))
    for option in options:
        if raw_id is not None and str(option.get("id")) == str(raw_id):
            return option
        if raw_name and _norm(option.get("name") or "") == raw_name:
            return option
    return None


def _status_field(fields: list[dict]) -> dict | None:
    for field in fields:
        if field.get("type") != "select":
            continue
        label = _norm(f"{field.get('id')} {field.get('name')}")
        names = {
            _norm(option.get("name") or "")
            for option in field.get("options") or []
            if isinstance(option, dict)
        }
        if "status" in label or "状态" in label or (
            names & DONE_NAMES and names & OPEN_NAMES
        ):
            return field
    return None


def _row_state(status_field: dict, data: dict) -> tuple[str, str] | None:
    """返回 (state, label)：state 为 open / done；不是待办性质的状态返回 None。"""
    raw = (data or {}).get(status_field.get("id"))
    if raw is None or raw == "" or raw == []:
        return None
    option = _option_by_value(status_field, raw)
    name = str((option or {}).get("name") or raw)
    normalized = _norm(name)
    if normalized in DONE_NAMES:
        return "done", name
    if normalized in OPEN_NAMES:
        return "open", name
    return None


def _find_done_option(status_field: dict) -> dict | None:
    for option in status_field.get("options") or []:
        if isinstance(option, dict) and _norm(option.get("name") or "") in DONE_NAMES:
            return option
    return None


def _find_open_option(status_field: dict) -> dict | None:
    for option in status_field.get("options") or []:
        if isinstance(option, dict) and _norm(option.get("name") or "") in OPEN_NAMES:
            return option
    return None


def _task_matches(markdown: str) -> list[tuple[str, int, str, bool]]:
    """提取 Markdown 任务项：[(文本指纹, 同文序号, 文本, 是否完成)]。"""
    counters: dict[str, int] = {}
    items: list[tuple[str, int, str, bool]] = []
    for line in (markdown or "").splitlines():
        match = TASK_RE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        digest = sha1(text.encode("utf-8")).hexdigest()[:16]
        counters[digest] = counters.get(digest, 0) + 1
        items.append(
            (digest, counters[digest], text, match.group("state").lower() == "x")
        )
    return items


def task_items(body: str) -> list[tuple[str, str, bool]]:
    """提取正文任务项：[(ref, text, checked)]，相同文本按出现顺序编号。"""
    return [
        (_task_ref(text, ordinal), text, checked)
        for _digest, ordinal, text, checked in _task_matches(body)
    ]


def plugin_fences(body: str) -> list[PluginFence]:
    """按文档顺序解析 ```kiwi-plugin 围栏；解析失败时 payload 为 None。"""
    lines = (body or "").splitlines(keepends=True)
    fences: list[PluginFence] = []
    index = 0
    line_no = 0
    while line_no < len(lines):
        open_match = PLUGIN_FENCE_OPEN_RE.match(lines[line_no].rstrip("\r\n"))
        if not open_match:
            line_no += 1
            continue
        fence = open_match.group("fence")
        close_line = line_no + 1
        while close_line < len(lines):
            close_match = PLUGIN_FENCE_CLOSE_RE.match(
                lines[close_line].rstrip("\r\n")
            )
            if (
                close_match
                and close_match.group("fence")[0] == fence[0]
                and len(close_match.group("fence")) >= len(fence)
            ):
                break
            close_line += 1
        payload = None
        if close_line < len(lines):
            raw = "".join(lines[line_no + 1 : close_line]).strip()
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                payload = parsed
        fences.append(
            PluginFence(
                index=index,
                open_line=line_no,
                content_start=line_no + 1,
                close_line=close_line,
                fence=fence,
                payload=payload,
            )
        )
        index += 1
        line_no = close_line + 1 if close_line < len(lines) else len(lines)
    return fences


def _point_ref(point: dict, index: int) -> str:
    point_id = str(point.get("id") or "").strip()
    if point_id:
        return sha1(point_id.encode("utf-8")).hexdigest()[:12]
    # 旧数据可能没有 id：退回位置序号，位置变化时镜像会自然重建。
    return f"i{index}"


def plugin_task_items(body: str) -> list[PluginTask]:
    """提取时间轴时间点正文中的任务项。"""
    items: list[PluginTask] = []
    for fence in plugin_fences(body):
        payload = fence.payload
        if not payload:
            continue
        plugin = str(payload.get("plugin") or "").strip()
        block = str(payload.get("block") or "").strip()
        if plugin != "timeline" and block != "timeline":
            continue
        props = payload.get("props")
        if not isinstance(props, dict):
            continue
        points = props.get("points")
        if not isinstance(points, list):
            continue
        title = str(props.get("title") or "").strip()
        for point_index, point in enumerate(points):
            if not isinstance(point, dict):
                continue
            content = point.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            point_ref = _point_ref(point, point_index)
            for task_index, (digest, ordinal, text, checked) in enumerate(
                _task_matches(content)
            ):
                items.append(
                    PluginTask(
                        ref=f"plugin:{fence.index}:{point_ref}:{digest}:{ordinal}",
                        text=text,
                        checked=checked,
                        block_index=fence.index,
                        block_title=title,
                        point_id=str(point.get("id") or "").strip(),
                        point_index=point_index,
                        point_time=str(point.get("time") or "").strip(),
                        point_summary=str(point.get("summary") or "").strip(),
                        task_index=task_index,
                    )
                )
    return items


def plugin_task_label(task: PluginTask) -> str:
    """收件箱中展示的来源前缀，带上时间轴标题与时间点摘要。"""
    title = task.block_title or "时间轴"
    meta = " · ".join(
        part for part in (task.point_time, task.point_summary) if part
    )
    return f"{title} · {meta}：{task.text}" if meta else f"{title}：{task.text}"


def plugin_task_location(body: str, source_ref: str) -> dict | None:
    """镜像 → 时间轴位置：供前端展开并定位到具体时间点的任务。"""
    for task in plugin_task_items(body):
        if task.ref != source_ref:
            continue
        return {
            "plugin_block_index": task.block_index,
            "plugin_point_id": task.point_id,
            "plugin_point_index": task.point_index,
            "plugin_point_time": task.point_time,
            "plugin_point_summary": task.point_summary,
            "plugin_task_index": task.task_index,
        }
    return None


def _toggle_task_markdown(
    markdown: str, digest: str, ordinal: int, done: bool
) -> str | None:
    """在 Markdown 中切换指定任务项；已是目标状态或找不到时返回 None。"""
    counters: dict[str, int] = {}
    lines = (markdown or "").splitlines(keepends=True)
    for index, line in enumerate(lines):
        task = TASK_RE.match(line)
        if not task:
            continue
        text = task.group("text").strip()
        if not text:
            continue
        item_digest = sha1(text.encode("utf-8")).hexdigest()[:16]
        if item_digest != digest:
            continue
        counters[digest] = counters.get(digest, 0) + 1
        if counters[digest] != ordinal:
            continue
        checked = task.group("state").lower() == "x"
        if checked == done:
            return None
        newline = "\n" if line.endswith("\n") else ""
        core = line[: -1] if newline else line
        new_state = "x" if done else " "
        lines[index] = TASK_RE.sub(
            lambda m: (
                f"{m.group('quote')}{m.group('indent')}- [{new_state}] {m.group('text')}"
            ),
            core,
        ) + newline
        return "".join(lines)
    return None


def set_plugin_task_state(body: str, source_ref: str, done: bool) -> str | None:
    """把时间轴时间点正文中的任务切换到目标状态，返回新的笔记正文。"""
    match = PLUGIN_TASK_REF_RE.match(source_ref or "")
    if not match:
        return None
    block_index = int(match.group("block"))
    point_ref = match.group("point")
    digest = match.group("digest")
    ordinal = int(match.group("ordinal"))

    lines = (body or "").splitlines(keepends=True)
    fences = plugin_fences(body)
    # 优先按记录时的区块序号查找；区块被移动 / 增删时再全量搜索。
    ordered = sorted(fences, key=lambda fence: fence.index != block_index)
    for fence in ordered:
        payload = fence.payload
        if payload is None:
            continue
        props = payload.get("props")
        if not isinstance(props, dict):
            continue
        points = props.get("points")
        if not isinstance(points, list):
            continue
        for point_index, point in enumerate(points):
            if not isinstance(point, dict):
                continue
            if _point_ref(point, point_index) != point_ref:
                continue
            content = point.get("content")
            new_content = _toggle_task_markdown(
                content if isinstance(content, str) else "",
                digest,
                ordinal,
                done,
            )
            if new_content is None:
                return None
            point["content"] = new_content
            payload_json = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
            open_line = lines[fence.open_line]
            indent_match = re.match(r"^[ \t]*", open_line)
            indent = indent_match.group(0) if indent_match else ""
            newline = "\r\n" if open_line.endswith("\r\n") else "\n"
            lines[fence.content_start : fence.close_line] = [
                f"{indent}{payload_json}{newline}"
            ]
            return "".join(lines)
    return None


async def _ensure_hub(session: AsyncSession, kb: KnowledgeBase) -> Note:
    hub = (
        await session.execute(
            select(Note).where(
                Note.kb_id == kb.id,
                Note.kind == "doc",
                Note.status.in_(("active", "archived")),
                Note.props_json["todo_hub"].astext == "true",
            )
        )
    ).scalars().first()
    if hub is not None:
        return hub

    folder = (
        await session.execute(
            select(NoteFolder).where(
                NoteFolder.kb_id == kb.id,
                NoteFolder.parent_id.is_(None),
                NoteFolder.name == HUB_FOLDER_NAME,
            )
        )
    ).scalars().first()
    if folder is None:
        sort_order = (
            await session.execute(
                select(NoteFolder.sort_order)
                .where(NoteFolder.kb_id == kb.id, NoteFolder.parent_id.is_(None))
                .order_by(NoteFolder.sort_order.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0
        folder = NoteFolder(
            kb_id=kb.id,
            name=HUB_FOLDER_NAME,
            parent_id=None,
            sort_order=int(sort_order) + 1,
        )
        session.add(folder)
        await session.flush()

    hub = Note(
        kb_id=kb.id,
        title=HUB_NOTE_TITLE,
        body_md=_render_hub([]),
        kind="doc",
        folder_id=folder.id,
        status="active",
        # 收件箱默认进入可编辑态：复选框需要能勾选并回写来源，
        # 阅读态会把 TipTap 任务项渲染成禁用复选框。
        view_mode="edit",
        sort_order=0,
        props_json={"todo_hub": True, "todo_auto": True},
    )
    session.add(hub)
    await session.flush()
    return hub


def _render_hub(open_items: list[TodoMirror]) -> str:
    # 只汇总未完成待办。已完成项仍保留在 todo_mirrors 中用于双向状态核对，
    # 但不再渲染「近期完成」，避免收件箱被刚勾选的任务反复占满。
    # 标题由笔记头部展示，正文不再重复一级标题（编辑态会重复显示）。
    lines = [
        "> 由 Kiwi 自动汇总当前知识库中的全部待办。勾选后会同步回来源笔记或数据表；",
        "> 来源中完成后也会在此更新。点击「定位」可回到原始任务。",
        "",
    ]
    # 链接同时带上来源笔记 id：点击标题可直接跳回来源，
    # 老版本收件箱没有 ?note= 时前端会调 /todos/{id} 兜底解析。
    def link(item: TodoMirror) -> str:
        return f"[{item.title}](kiwi://todo/{item.id}?note={item.source_note_id})"

    def groups(items: list[TodoMirror]) -> list[list[TodoMirror]]:
        """按来源笔记聚合，同组内保持稳定顺序。"""
        grouped: dict[uuid.UUID, list[TodoMirror]] = {}
        for item in items:
            grouped.setdefault(item.source_note_id, []).append(item)
        return sorted(
            grouped.values(),
            key=lambda group: (
                (group[0].title or "").lower(),
                group[0].source_text.lower(),
            ),
        )

    def section(heading: str, items: list[TodoMirror], checked: bool) -> None:
        mark = "x" if checked else " "
        lines.extend([f"## {heading}", ""])
        for group in groups(items):
            label = group[0].title or "未命名笔记"
            lines.append(f"### {label}（{len(group)}）")
            lines.append("")
            for item in group:
                lines.append(f"- [{mark}] {item.source_text} · {link(item)}")
            lines.append("")

    if open_items:
        section("待办", open_items, False)
    else:
        lines.extend(["_暂无待办，去笔记里添加任务或更新数据表状态吧。_", ""])
    return "\n".join(lines)


async def collect_sources(
    session: AsyncSession, kb_id: uuid.UUID, hub_id: uuid.UUID
) -> dict[tuple[uuid.UUID, str, str], dict]:
    """扫描所有笔记任务与数据表行，返回 key → 描述。"""
    notes = (
        (
            await session.execute(
                select(Note).where(
                    Note.kb_id == kb_id,
                    Note.status == "active",
                    Note.id != hub_id,
                    # 上锁笔记的待办不汇总到收件箱，避免旁路泄露正文。
                    Note.lock_hash.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    found: dict[tuple[uuid.UUID, str, str], dict] = {}
    database_notes: list[Note] = []
    for note in notes:
        for ref, text, checked in task_items(note.body_md or ""):
            found[(note.id, "task", ref)] = {
                "source_note_id": note.id,
                "source_kind": "task",
                "source_ref": ref,
                "source_text": text,
                "title": note.title or "未命名笔记",
                "status": "done" if checked else "open",
            }
        for task in plugin_task_items(note.body_md or ""):
            found[(note.id, "plugin_task", task.ref)] = {
                "source_note_id": note.id,
                "source_kind": "plugin_task",
                "source_ref": task.ref,
                "source_text": plugin_task_label(task),
                "title": note.title or "未命名笔记",
                "status": "done" if task.checked else "open",
            }
        if note.kind == "database":
            database_notes.append(note)

    if database_notes:
        colls = (
            (
                await session.execute(
                    select(NoteCollection).where(
                        NoteCollection.note_id.in_([n.id for n in database_notes])
                    )
                )
            )
            .scalars()
            .all()
        )
        coll_by_note = {coll.note_id: coll for coll in colls}
        for database_note in database_notes:
            coll = coll_by_note.get(database_note.id)
            if coll is None:
                continue
            fields = (coll.schema_json or {}).get("fields") or []
            status_field = _status_field(fields)
            if status_field is None:
                continue
            rows = (
                (
                    await session.execute(
                        select(CollectionRow)
                        .where(CollectionRow.collection_id == coll.id)
                        .order_by(CollectionRow.sort_order, CollectionRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                state = _row_state(status_field, row.data or {})
                if state is None:
                    continue
                status, label = state
                title = row_title(row.data or {}, fields)
                found[(database_note.id, "database_row", f"row:{row.id}")] = {
                    "source_note_id": database_note.id,
                    "source_kind": "database_row",
                    "source_ref": f"row:{row.id}",
                    "source_text": f"{title}（{label}）",
                    "title": database_note.title or "数据表",
                    "status": status,
                }
    return found


async def sync_kb_todos(session: AsyncSession, kb_id: uuid.UUID) -> dict:
    """全量核对并刷新收件箱；返回统计。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        return {"ok": False, "error": "知识库不存在"}
    hub = await _ensure_hub(session, kb)

    existing = (
        (
            await session.execute(
                select(TodoMirror).where(
                    TodoMirror.kb_id == kb_id, TodoMirror.hub_note_id == hub.id
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {
        (m.source_note_id, m.source_kind, m.source_ref): m for m in existing
    }
    found = await collect_sources(session, kb_id, hub.id)

    created = updated = removed = 0
    for key, info in found.items():
        mirror = by_key.get(key)
        if mirror is None:
            mirror = TodoMirror(
                kb_id=kb_id,
                hub_note_id=hub.id,
                **info,
            )
            session.add(mirror)
            by_key[key] = mirror
            created += 1
        else:
            changed = False
            for field in ("source_text", "title", "status"):
                if getattr(mirror, field) != info[field]:
                    setattr(mirror, field, info[field])
                    changed = True
            if changed:
                updated += 1

    now = datetime.now(timezone.utc)
    for key, mirror in list(by_key.items()):
        if key in found:
            continue
        age = (now - _aware(mirror.updated_at)).total_seconds()
        if mirror.status == "open" or age > 7 * 24 * 3600:
            await session.delete(mirror)
            removed += 1

    await session.flush()
    mirrors = (
        (
            await session.execute(
                select(TodoMirror)
                .where(TodoMirror.kb_id == kb_id, TodoMirror.hub_note_id == hub.id)
                .order_by(TodoMirror.title, TodoMirror.source_text)
            )
        )
        .scalars()
        .all()
    )
    open_items = [m for m in mirrors if m.status == "open"]
    done_items = [m for m in mirrors if m.status == "done"]
    for index, mirror in enumerate(open_items):
        mirror.sort_order = index
    body = _render_hub(open_items)
    if hub.body_md != body:
        hub.body_md = body

    # 来源笔记标记：前端可显示「已同步到收件箱」入口（逆向追溯）。
    source_ids = {m.source_note_id for m in mirrors}
    for source_id in source_ids:
        note = await session.get(Note, source_id)
        if note is None:
            continue
        props = dict(note.props_json or {})
        if props.get("todo_hub_note_id") == str(hub.id):
            continue
        props["todo_hub_note_id"] = str(hub.id)
        props["todo_hub_title"] = hub.title
        note.props_json = props

    props = dict(hub.props_json or {})
    props.update(
        {
            "todo_hub": True,
            "todo_auto": True,
            "todo_last_sync_at": now.isoformat(),
            "todo_open_count": len(open_items),
            "todo_done_count": len(done_items),
        }
    )
    hub.props_json = props
    kb.todo_sync_last_at = now
    await session.commit()
    return {
        "ok": True,
        "hub_note_id": str(hub.id),
        "open": len(open_items),
        "done": len(done_items),
        "created": created,
        "updated": updated,
        "removed": removed,
    }


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _set_task_state(
    session: AsyncSession, note: Note, source_ref: str, done: bool
) -> bool:
    match = re.match(r"task:([0-9a-f]{16}):(\d+)$", source_ref)
    if not match:
        return False
    body = _toggle_task_markdown(
        note.body_md or "", match.group(1), int(match.group(2)), done
    )
    if body is None:
        return False
    note.body_md = body
    return True


async def _set_plugin_task_state(
    session: AsyncSession, note: Note, source_ref: str, done: bool
) -> bool:
    body = set_plugin_task_state(note.body_md or "", source_ref, done)
    if body is None:
        return False
    note.body_md = body
    return True


async def _set_row_state(
    session: AsyncSession, database_note: Note, source_ref: str, done: bool
) -> bool:
    row_id_text = source_ref.removeprefix("row:")
    try:
        row_id = uuid.UUID(row_id_text)
    except ValueError:
        return False
    row = await session.get(CollectionRow, row_id)
    if row is None:
        return False
    coll = (
        await session.execute(
            select(NoteCollection).where(NoteCollection.id == row.collection_id)
        )
    ).scalar_one_or_none()
    if coll is None or coll.kb_id != database_note.kb_id:
        return False
    fields = (coll.schema_json or {}).get("fields") or []
    status_field = _status_field(fields)
    if status_field is None:
        return False
    target = _find_done_option(status_field) if done else _find_open_option(status_field)
    if target is None:
        return False
    data = dict(row.data or {})
    data[status_field["id"]] = target.get("id")
    row.data = data
    await sync_row_note_if_exists(session, database_note, coll, row)
    return True


async def apply_hub_checks(session: AsyncSession, hub: Note) -> dict:
    """收件箱中的勾选 → 写回来源（正向同步）。"""
    checked: dict[uuid.UUID, bool] = {}
    for line in (hub.body_md or "").splitlines():
        task = TASK_RE.match(line)
        if not task:
            continue
        link = TODO_LINK_RE.search(line)
        if not link:
            continue
        try:
            mirror_id = uuid.UUID(link.group(1))
        except ValueError:
            continue
        checked[mirror_id] = task.group("state").lower() == "x"
    if not checked:
        return {"updated": 0}

    mirrors = (
        (
            await session.execute(
                select(TodoMirror).where(
                    TodoMirror.id.in_(list(checked)),
                    TodoMirror.kb_id == hub.kb_id,
                    TodoMirror.hub_note_id == hub.id,
                )
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    for mirror in mirrors:
        done = checked[mirror.id]
        if (mirror.status == "done") == done:
            continue
        source_note = await session.get(Note, mirror.source_note_id)
        if source_note is None:
            continue
        if mirror.source_kind == "task":
            changed = await _set_task_state(
                session, source_note, mirror.source_ref, done
            )
        elif mirror.source_kind == "plugin_task":
            changed = await _set_plugin_task_state(
                session, source_note, mirror.source_ref, done
            )
        else:
            changed = await _set_row_state(
                session, source_note, mirror.source_ref, done
            )
        if changed:
            mirror.status = "done" if done else "open"
            updated += 1
    return {"updated": updated}


def schedule_kb_sync(kb_id: uuid.UUID, delay: float = 1.5) -> None:
    """合并短时间内的编辑，延迟刷新收件箱。"""
    existing = _pending.get(kb_id)
    if existing is not None and not existing.done():
        existing.cancel()
    _pending[kb_id] = asyncio.create_task(_run_later(kb_id, delay))


async def _run_later(kb_id: uuid.UUID, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        async with async_session_factory() as session:
            await sync_kb_todos(session, kb_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("知识库 %s 待办同步失败", kb_id)
    finally:
        _pending.pop(kb_id, None)
