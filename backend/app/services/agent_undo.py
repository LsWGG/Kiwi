"""Agent 写操作的一键撤销（进程内、短时有效）。

只支持可逆的常见操作：

- create_note / create_note_from_template → 移入回收站
- update_note / apply_template → 恢复修改前的标题、正文、标签与分组
- delete_note → 从回收站恢复

文件夹与数据表行的复杂变更暂不提供撤销。记录只保存在当前进程内，TTL 15 分钟；
服务重启或过期后返回不可撤销，避免误用旧快照覆盖新内容。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note

UNDO_TTL_SECONDS = 15 * 60
MAX_RECORDS = 200
SUPPORTED = {
    "create_note",
    "create_note_from_template",
    "update_note",
    "apply_template",
    "delete_note",
}

_lock = threading.Lock()
_records: dict[str, "UndoRecord"] = {}


class UndoError(Exception):
    pass


@dataclass
class UndoRecord:
    id: str
    tool: str
    kb_id: uuid.UUID
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    used: bool = False

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label}


def _prune() -> None:
    cutoff = time.time() - UNDO_TTL_SECONDS
    expired = [key for key, record in _records.items() if record.created_at < cutoff]
    for key in expired:
        _records.pop(key, None)
    while len(_records) > MAX_RECORDS:
        oldest = min(_records.items(), key=lambda item: item[1].created_at)[0]
        _records.pop(oldest, None)


async def capture_before(
    session: AsyncSession,
    kb_id: uuid.UUID | None,
    tool: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """在执行写工具前保存恢复所需的最小快照。"""
    if kb_id is None or tool not in SUPPORTED:
        return {}
    note_id = args.get("note_id")
    if tool in ("update_note", "apply_template") and note_id:
        try:
            note = await session.get(Note, uuid.UUID(str(note_id)))
        except (ValueError, TypeError):
            return {}
        if note is None or note.kb_id != kb_id:
            return {}
        return {
            "note_id": str(note.id),
            "title": note.title,
            "body_md": note.body_md,
            "tags": [tag.name for tag in note.tags],
            "folder_id": str(note.folder_id) if note.folder_id else None,
            "parent_note_id": (
                str(note.parent_note_id) if note.parent_note_id else None
            ),
        }
    if tool == "delete_note" and note_id:
        try:
            note = await session.get(Note, uuid.UUID(str(note_id)))
        except (ValueError, TypeError):
            return {}
        if note is None or note.kb_id != kb_id:
            return {}
        return {"note_id": str(note.id), "title": note.title}
    return {}


def register(
    *,
    tool: str,
    kb_id: uuid.UUID,
    label: str,
    snapshot: dict[str, Any],
    result: dict[str, Any],
) -> UndoRecord | None:
    if tool not in SUPPORTED:
        return None
    payload = dict(snapshot)
    note = result.get("note") if isinstance(result, dict) else None
    if isinstance(note, dict) and note.get("id"):
        payload.setdefault("note_id", str(note["id"]))
        payload.setdefault("title", str(note.get("title") or ""))
    if not payload.get("note_id"):
        return None
    record = UndoRecord(
        id=uuid.uuid4().hex,
        tool=tool,
        kb_id=kb_id,
        label=label or tool,
        payload=payload,
    )
    with _lock:
        _prune()
        _records[record.id] = record
    return record


def claim(undo_id: str) -> UndoRecord | None:
    with _lock:
        _prune()
        record = _records.get(undo_id)
        if record is None or record.used:
            return None
        record.used = True
        return record


def release(record: UndoRecord) -> None:
    """撤销执行失败时释放占用，允许用户重试。"""
    with _lock:
        if record.id in _records:
            record.used = False


def clear() -> None:
    with _lock:
        _records.clear()


async def execute(record: UndoRecord, session: AsyncSession) -> str:
    from app.routers.notes_crud import update_note as update_note_route
    from app.routers.notes_lifecycle import delete_note as delete_note_route
    from app.routers.notes_lifecycle import restore_note as restore_note_route
    from app.schemas.note import NoteUpdate

    note_id = uuid.UUID(str(record.payload["note_id"]))
    if record.tool in ("create_note", "create_note_from_template"):
        await delete_note_route(note_id=note_id, kb_id=record.kb_id, session=session)
        return "已把新建的笔记移入回收站"
    if record.tool == "delete_note":
        await restore_note_route(note_id=note_id, kb_id=record.kb_id, session=session)
        return "已从回收站恢复笔记"
    if record.tool in ("update_note", "apply_template"):
        payload = record.payload
        await update_note_route(
            note_id=note_id,
            kb_id=record.kb_id,
            data=NoteUpdate(
                title=payload.get("title"),
                body_md=payload.get("body_md"),
                tags=payload.get("tags") or [],
                folder_id=(
                    uuid.UUID(str(payload["folder_id"]))
                    if payload.get("folder_id")
                    else None
                ),
                parent_note_id=(
                    uuid.UUID(str(payload["parent_note_id"]))
                    if payload.get("parent_note_id")
                    else None
                ),
            ),
            x_note_token=None,
            session=session,
        )
        return "已恢复修改前的笔记内容"
    raise UndoError("该操作暂不支持一键撤销")


__all__ = [
    "UndoError",
    "UndoRecord",
    "capture_before",
    "claim",
    "clear",
    "execute",
    "register",
    "release",
]
