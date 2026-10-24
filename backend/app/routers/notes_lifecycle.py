"""回收站、删除、恢复与归档。"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CollectionRow,
    Note,
    NoteCollection,
    NoteFolder,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    TRASH_RETENTION_DAYS,
    _collection_child_notes,
    _get_note,
    _lifecycle,
    _note_descendant_ids,
    _now_iso,
    _purge_expired_trash,
    _record_tree_tombstones,
    _reload_tags,
    _set_lifecycle,
)
from app.schemas.note import (
    NoteArchiveOut,
    NoteOut,
    NoteSummary,
    NoteTrashOut,
)
from app.services import (
    audit,
)
from app.services.notebook_kernel import kernel_manager

logger = logging.getLogger("kiwi.notes.lifecycle")

router = APIRouter()

# ---- 生命周期 / 回收站 ----

@router.get("/archived", response_model=NoteArchiveOut)
async def archived_notes(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    rows = (
        (
            await session.execute(
                select(Note)
                .options(selectinload(Note.tags))
                .where(Note.kb_id == kb_id, Note.status == "archived")
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return NoteArchiveOut(
        total=len(rows),
        items=[NoteSummary.model_validate(n, from_attributes=True) for n in rows],
    )


@router.get("/trash", response_model=NoteTrashOut)
async def trash_notes(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _purge_expired_trash(session, kb_id)
    rows = (
        (
            await session.execute(
                select(Note)
                .options(selectinload(Note.tags))
                .where(Note.kb_id == kb_id, Note.status == "trash")
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return NoteTrashOut(
        total=len(rows),
        items=[NoteSummary.model_validate(n, from_attributes=True) for n in rows],
        retention_days=TRASH_RETENTION_DAYS,
    )


@router.delete("/trash", status_code=204)
async def empty_trash(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    trashed = (
        await session.execute(
            select(Note.id, Note.title).where(Note.kb_id == kb_id, Note.status == "trash")
        )
    ).all()
    await _record_tree_tombstones(
        session, kb_id, note_ids=[row.id for row in trashed]
    )
    await session.execute(
        delete(Note)
        .where(Note.kb_id == kb_id, Note.status == "trash")
        .execution_options(synchronize_session=False)
    )
    await audit.record(
        session,
        "note.trash.empty",
        kb_id=kb_id,
        target_type="kb",
        target_id=kb_id,
        detail={"count": len(trashed), "titles": [row.title for row in trashed][:20]},
        note=f"清空回收站（{len(trashed)} 篇）",
    )
    await session.commit()



@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """移入回收站：保留 30 天，期间可恢复；不立即删除关联数据。"""
    note = await _get_note(session, kb_id, note_id)
    previous = note.status if note.status in ("active", "archived") else "active"
    _set_lifecycle(note, trashed_at=_now_iso(), status_before_trash=previous)
    note.status = "trash"
    # 子笔记随父笔记一起进入回收站，避免留下无法在目录树中定位的孤立笔记。
    for child_id in await _note_descendant_ids(session, kb_id, note_id):
        child = await session.get(Note, child_id)
        if child is None or child.status not in ("active", "archived"):
            continue
        _set_lifecycle(
            child,
            trashed_at=_now_iso(),
            status_before_trash=child.status,
            trashed_with_parent=True,
        )
        child.status = "trash"
    # 数据表行笔记删除时同步删除对应行，避免留下无法打开的空行
    row_id = (note.props_json or {}).get("collection_row_id")
    if row_id:
        try:
            row = await session.get(CollectionRow, uuid.UUID(str(row_id)))
        except (ValueError, TypeError):
            row = None
        if row is not None and row.note_id == note.id:
            row.note_id = None
            await session.delete(row)
    # 数据表整体移入回收站时，行笔记一并进入回收站
    for child in await _collection_child_notes(session, note):
        if child.status in ("active", "archived"):
            _set_lifecycle(
                child,
                trashed_at=_now_iso(),
                status_before_trash=child.status,
                trashed_with_collection=True,
            )
            child.status = "trash"
    await audit.record(
        session,
        "note.delete",
        kb_id=kb_id,
        target_type="note",
        target_id=note_id,
        detail={"title": note.title, "kind": note.kind, "mode": "trash"},
        note=f"移入回收站：{note.title}",
    )
    await session.commit()
    if note.kind == "notebook":
        kernel_manager.terminate(str(note_id))


@router.delete("/{note_id}/permanent", status_code=204)
async def permanently_delete_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    if note.status != "trash":
        raise HTTPException(400, "只有回收站中的笔记可以永久删除")
    # 数据表集合 / 行 / 附件由外键级联；导入/链接的 Source 保留
    deleted_ids = [note.id]
    if note.kind == "database":
        coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == note.id)
            )
        ).scalar_one_or_none()
        if coll is not None:
            child_ids = (
                (
                    await session.execute(
                        select(CollectionRow.note_id).where(
                            CollectionRow.collection_id == coll.id,
                            CollectionRow.note_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for child_id in child_ids:
                child = await session.get(Note, child_id)
                if child is not None and child.id != note.id:
                    deleted_ids.append(child.id)
                    await session.delete(child)
    detail = {"title": note.title, "kind": note.kind, "mode": "permanent"}
    await _record_tree_tombstones(session, kb_id, note_ids=deleted_ids)
    await session.delete(note)
    await audit.record(
        session,
        "note.delete",
        kb_id=kb_id,
        target_type="note",
        target_id=note_id,
        detail=detail,
        note=f"永久删除：{detail['title']}",
    )
    await session.commit()
    if note.kind == "notebook":
        kernel_manager.purge_note(str(kb_id), str(note_id))


@router.post("/{note_id}/restore", response_model=NoteOut)
async def restore_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    if note.status != "trash":
        raise HTTPException(400, "笔记不在回收站中")
    lifecycle = _lifecycle(note)
    previous = lifecycle.get("status_before_trash")
    note.status = previous if previous in ("active", "archived") else "active"
    _set_lifecycle(note, trashed_at=None, status_before_trash=None, restored_at=_now_iso())
    # 原分组若已被删除，回到根级
    if note.folder_id is not None:
        folder = await session.get(NoteFolder, note.folder_id)
        if folder is None or folder.kb_id != kb_id:
            note.folder_id = None
    # 父笔记仍在回收站 / 已删除时，恢复的笔记提升为当前分组根级。
    if note.parent_note_id is not None:
        parent = await session.get(Note, note.parent_note_id)
        if (
            parent is None
            or parent.kb_id != kb_id
            or parent.status != "active"
        ):
            note.parent_note_id = None
    # 随父笔记一起移入回收站的子笔记同步恢复。
    for child_id in await _note_descendant_ids(session, kb_id, note_id):
        child = await session.get(Note, child_id)
        if child is None or child.status != "trash":
            continue
        child_lifecycle = _lifecycle(child)
        if not child_lifecycle.get("trashed_with_parent"):
            continue
        child_previous = child_lifecycle.get("status_before_trash")
        child.status = (
            child_previous
            if child_previous in ("active", "archived")
            else "active"
        )
        _set_lifecycle(
            child,
            trashed_at=None,
            status_before_trash=None,
            trashed_with_parent=None,
            restored_at=_now_iso(),
        )
    # 行已被删除的行笔记，恢复后降级为普通文档
    row_id = (note.props_json or {}).get("collection_row_id")
    if row_id:
        try:
            row = await session.get(CollectionRow, uuid.UUID(str(row_id)))
        except (ValueError, TypeError):
            row = None
        if row is None or row.note_id is None:
            props = dict(note.props_json or {})
            props.pop("collection_id", None)
            props.pop("collection_note_id", None)
            props.pop("collection_row_id", None)
            note.props_json = props
    # 与数据表一起移入回收站的行笔记一并恢复
    for child in await _collection_child_notes(session, note):
        if child.status == "trash" and _lifecycle(child).get(
            "trashed_with_collection"
        ):
            child_lifecycle = _lifecycle(child)
            child_previous = child_lifecycle.get("status_before_trash")
            child.status = (
                child_previous
                if child_previous in ("active", "archived")
                else "active"
            )
            _set_lifecycle(
                child,
                trashed_at=None,
                status_before_trash=None,
                trashed_with_collection=None,
                restored_at=_now_iso(),
            )
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/archive", response_model=NoteOut)
async def archive_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    note.status = "archived"
    _set_lifecycle(note, archived_at=_now_iso())
    # 子笔记随父笔记一起归档，避免目录树中父级消失后子笔记不可达。
    for child_id in await _note_descendant_ids(session, kb_id, note_id):
        child = await session.get(Note, child_id)
        if child is None or child.status != "active":
            continue
        child.status = "archived"
        _set_lifecycle(
            child, archived_at=_now_iso(), archived_with_parent=True
        )
    # 行笔记随数据表一起归档（仅标记被本次操作改变的行，避免误改独立归档）
    for child in await _collection_child_notes(session, note):
        if child.status == "active":
            child.status = "archived"
            _set_lifecycle(
                child, archived_at=_now_iso(), archived_with_collection=True
            )
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/unarchive", response_model=NoteOut)
async def unarchive_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    if note.status != "archived":
        raise HTTPException(400, "笔记不在归档中")
    note.status = "active"
    _set_lifecycle(note, archived_at=None)
    # 父笔记仍在归档时，取消归档的子笔记提升为分组根级。
    if note.parent_note_id is not None:
        parent = await session.get(Note, note.parent_note_id)
        if parent is None or parent.kb_id != kb_id or parent.status != "active":
            note.parent_note_id = None
    for child_id in await _note_descendant_ids(session, kb_id, note_id):
        child = await session.get(Note, child_id)
        if child is None or child.status != "archived":
            continue
        if not _lifecycle(child).get("archived_with_parent"):
            continue
        child.status = "active"
        _set_lifecycle(
            child, archived_at=None, archived_with_parent=None
        )
    for child in await _collection_child_notes(session, note):
        if child.status == "archived" and _lifecycle(child).get(
            "archived_with_collection"
        ):
            child.status = "active"
            _set_lifecycle(child, archived_at=None, archived_with_collection=None)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


