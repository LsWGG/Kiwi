"""待办双向同步：把知识库内散落的待办汇总到「收件箱」。

来源：
- 笔记正文中的 Markdown 任务项（``- [ ]`` / ``- [x]``）；
- 数据表中带状态字段的行（状态为待办 / 进行中 / 已完成）。

收件箱是一篇自动维护的笔记：每条待办都带来源笔记链接（正向追溯），
勾选状态会写回来源；来源笔记 / 数据表更新后，下一次同步会把状态带回收件箱
（逆向同步）。定时周期由知识库配置 ``todo_sync_interval_hours`` 控制。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from hashlib import sha1
from datetime import datetime, timezone

from sqlalchemy import delete, select
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


def task_items(body: str) -> list[tuple[str, str, bool]]:
    """提取任务项：[(ref, text, checked)]，相同文本按出现顺序编号。"""
    counters: dict[str, int] = {}
    items: list[tuple[str, str, bool]] = []
    for line in (body or "").splitlines():
        match = TASK_RE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        digest = sha1(text.encode("utf-8")).hexdigest()[:16]
        counters[digest] = counters.get(digest, 0) + 1
        items.append(
            (
                _task_ref(text, counters[digest]),
                text,
                match.group("state").lower() == "x",
            )
        )
    return items


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
        body_md=_render_hub([], []),
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


def _render_hub(open_items: list[TodoMirror], done_items: list[TodoMirror]) -> str:
    # 标题由笔记头部展示，正文不再重复一级标题（编辑态会重复显示）。
    lines = [
        "> 由 Kiwi 自动汇总当前知识库中的全部待办。勾选后会同步回来源笔记或数据表；",
        "> 来源中完成后也会在此更新。点击来源标题可回到原始位置。",
        "",
        "## 待办",
        "",
    ]
    # 链接同时带上来源笔记 id：点击标题可直接跳回来源，
    # 老版本收件箱没有 ?note= 时前端会调 /todos/{id} 兜底解析。
    def link(item: TodoMirror) -> str:
        return f"[{item.title}](kiwi://todo/{item.id}?note={item.source_note_id})"

    if open_items:
        for item in open_items:
            lines.append(f"- [ ] {item.source_text} · {link(item)}")
    else:
        lines.append("_暂无待办，去笔记里添加任务或更新数据表状态吧。_")
    if done_items:
        lines += ["", "## 近期完成", ""]
        for item in done_items:
            lines.append(f"- [x] {item.source_text} · {link(item)}")
    lines.append("")
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
    for index, mirror in enumerate(open_items + done_items):
        mirror.sort_order = index
    body = _render_hub(open_items, done_items)
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
    digest, ordinal_text = match.group(1), int(match.group(2))
    counters: dict[str, int] = {}
    lines = (note.body_md or "").splitlines(keepends=True)
    changed = False
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
        if counters[digest] != ordinal_text:
            continue
        checked = task.group("state").lower() == "x"
        if checked == done:
            return False
        newline = "\n" if line.endswith("\n") else ""
        core = line[: -1] if newline else line
        new_state = "x" if done else " "
        lines[index] = TASK_RE.sub(
            lambda m: (
                f"{m.group('quote')}{m.group('indent')}- [{new_state}] {m.group('text')}"
            ),
            core,
        ) + newline
        changed = True
        break
    if changed:
        note.body_md = "".join(lines)
    return changed


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
