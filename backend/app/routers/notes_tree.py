"""笔记目录树、分组与工作区列表。"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Note,
    NoteFolder,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_folder,
    _get_parent_note,
    _next_folder_sort,
    _purge_expired_trash,
    _validate_folder,
)
from app.schemas.note import (
    NoteFolderCreate,
    NoteFolderOut,
    NoteFolderUpdate,
    NoteSummary,
    NoteTreeOut,
    ReorderIn,
    TreeReorderIn,
)

logger = logging.getLogger("kiwi.notes.tree")

router = APIRouter()

@router.get("", response_model=list[NoteSummary])
async def list_notes(
    kb_id: uuid.UUID,
    folder_id: uuid.UUID | None = None,
    status: str = "active",
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Note).where(Note.kb_id == kb_id)
    if status == "all":
        stmt = stmt.where(Note.status.in_(["active", "archived"]))
    else:
        stmt = stmt.where(Note.status == status)
    if folder_id is not None:
        stmt = stmt.where(Note.folder_id == folder_id)
    if q:
        stmt = stmt.where(Note.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(Note.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [NoteSummary.model_validate(n, from_attributes=True) for n in rows]


# ---- 目录树 / 分组 / 排序（必须先于 /{note_id} 声明）----


@router.get("/tree", response_model=NoteTreeOut)
async def note_tree(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """一次返回全部分组与笔记，前端自行组树（数据量小，避免递归接口）。"""
    await _purge_expired_trash(session, kb_id)
    folders = (
        (
            await session.execute(
                select(NoteFolder)
                .where(NoteFolder.kb_id == kb_id)
                .order_by(NoteFolder.sort_order, NoteFolder.created_at)
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(Note)
                .where(Note.kb_id == kb_id, Note.status == "active")
                .order_by(Note.sort_order, Note.created_at)
            )
        )
        .scalars()
        .all()
    )
    return NoteTreeOut(
        folders=[NoteFolderOut.model_validate(f, from_attributes=True) for f in folders],
        notes=[NoteSummary.model_validate(n, from_attributes=True) for n in notes],
    )


@router.post("/folders", response_model=NoteFolderOut, status_code=201)
async def create_folder(
    data: NoteFolderCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _validate_folder(session, kb_id, data.parent_id)
    folder = NoteFolder(
        kb_id=kb_id,
        name=data.name.strip(),
        parent_id=data.parent_id,
        sort_order=await _next_folder_sort(session, kb_id, data.parent_id),
    )
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return NoteFolderOut.model_validate(folder, from_attributes=True)


@router.patch("/folders/{folder_id}", response_model=NoteFolderOut)
async def update_folder(
    folder_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteFolderUpdate,
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_folder(session, kb_id, folder_id)
    if data.name is not None:
        folder.name = data.name.strip()
    if data.pinned is not None:
        folder.pinned = data.pinned
    if "parent_id" in data.model_fields_set:
        new_parent = data.parent_id
        if new_parent == folder.id:
            raise HTTPException(400, "不能把分组移入自身")
        await _validate_folder(session, kb_id, new_parent)
        if new_parent is not None:
            # 拒绝移入自身后代（否则成环）
            all_folders = (
                (await session.execute(select(NoteFolder).where(NoteFolder.kb_id == kb_id)))
                .scalars()
                .all()
            )
            parent_of = {f.id: f.parent_id for f in all_folders}
            cursor = new_parent
            while cursor is not None:
                if cursor == folder.id:
                    raise HTTPException(400, "不能把分组移入自身的子分组")
                cursor = parent_of.get(cursor)
            folder.sort_order = await _next_folder_sort(session, kb_id, new_parent)
        folder.parent_id = new_parent
    await session.commit()
    await session.refresh(folder)
    return NoteFolderOut.model_validate(folder, from_attributes=True)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """递归删除分组子树；子树内笔记重挂到被删分组的父级。"""
    folder = await _get_folder(session, kb_id, folder_id)
    all_folders = (
        (await session.execute(select(NoteFolder).where(NoteFolder.kb_id == kb_id)))
        .scalars()
        .all()
    )
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for f in all_folders:
        children.setdefault(f.parent_id, []).append(f.id)
    to_delete: list[uuid.UUID] = []
    stack = [folder.id]
    while stack:
        fid = stack.pop()
        to_delete.append(fid)
        stack.extend(children.get(fid, []))

    await session.execute(
        update(Note)
        .where(Note.kb_id == kb_id, Note.folder_id.in_(to_delete))
        .values(folder_id=folder.parent_id)
    )
    await session.execute(delete(NoteFolder).where(NoteFolder.id.in_(to_delete)))
    await session.commit()


@router.post("/reorder", status_code=204)
async def reorder(
    data: ReorderIn, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """同级批量排序；要求 ordered_ids 恰好是该层级的完整集合。"""
    if data.target == "folder":
        stmt = select(NoteFolder.id).where(NoteFolder.kb_id == kb_id)
        stmt = stmt.where(NoteFolder.parent_id == data.parent_id) if data.parent_id else stmt.where(
            NoteFolder.parent_id.is_(None)
        )
        existing = set((await session.execute(stmt)).scalars().all())
        incoming = set(data.ordered_ids)
        if existing != incoming:
            raise HTTPException(400, "排序列表必须包含该层级全部分组")
        for index, fid in enumerate(data.ordered_ids):
            await session.execute(
                update(NoteFolder).where(NoteFolder.id == fid).values(sort_order=index)
            )
    else:
        stmt = select(Note.id).where(Note.kb_id == kb_id, Note.status == "active")
        if data.parent_note_id is not None:
            parent = await _get_parent_note(session, kb_id, data.parent_note_id)
            stmt = stmt.where(
                Note.folder_id == parent.folder_id,
                Note.parent_note_id == data.parent_note_id,
            )
        else:
            stmt = stmt.where(Note.parent_note_id.is_(None))
            stmt = (
                stmt.where(Note.folder_id == data.parent_id)
                if data.parent_id
                else stmt.where(Note.folder_id.is_(None))
            )
        existing = set((await session.execute(stmt)).scalars().all())
        incoming = set(data.ordered_ids)
        if existing != incoming:
            raise HTTPException(400, "排序列表必须包含该层级全部笔记")
        for index, nid in enumerate(data.ordered_ids):
            await session.execute(update(Note).where(Note.id == nid).values(sort_order=index))
    await session.commit()


@router.post("/tree-reorder", status_code=204)
async def tree_reorder(
    data: TreeReorderIn, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """混合排序：同一层级内分组与笔记共享一个顺序。

    目录树按「分组 + 笔记」混合展示，允许把笔记拖到分组上方。请求必须
    包含该层级全部分组与活跃笔记，避免并发编辑时漏掉节点。
    """
    folder_stmt = select(NoteFolder.id).where(NoteFolder.kb_id == kb_id)
    note_stmt = select(Note.id).where(
        Note.kb_id == kb_id,
        Note.status == "active",
        Note.parent_note_id.is_(None),
    )
    if data.parent_id is None:
        folder_stmt = folder_stmt.where(NoteFolder.parent_id.is_(None))
        note_stmt = note_stmt.where(Note.folder_id.is_(None))
    else:
        folder_stmt = folder_stmt.where(NoteFolder.parent_id == data.parent_id)
        note_stmt = note_stmt.where(Note.folder_id == data.parent_id)

    existing_folders = set((await session.execute(folder_stmt)).scalars().all())
    existing_notes = set((await session.execute(note_stmt)).scalars().all())
    existing = {("folder", fid) for fid in existing_folders} | {
        ("note", nid) for nid in existing_notes
    }
    incoming = [(item.type, item.id) for item in data.items]
    if len(incoming) != len(set(incoming)):
        raise HTTPException(400, "排序列表包含重复节点")
    if set(incoming) != existing:
        raise HTTPException(400, "排序列表必须包含该层级全部分组与笔记")

    for index, (kind, node_id) in enumerate(incoming):
        model = NoteFolder if kind == "folder" else Note
        await session.execute(
            update(model).where(model.id == node_id).values(sort_order=index)
        )
    await session.commit()

