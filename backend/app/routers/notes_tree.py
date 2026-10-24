"""笔记目录树、分组与工作区列表。"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Note,
    NoteFolder,
    NoteTreeTombstone,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_folder,
    _get_parent_note,
    _next_folder_sort,
    _note_descendant_ids,
    _now_iso,
    _purge_expired_trash,
    _record_tree_tombstones,
    _set_lifecycle,
    _validate_folder,
)
from app.schemas.note import (
    NoteFolderCreate,
    NoteFolderOut,
    NoteFolderUpdate,
    NoteSummary,
    NoteTreeChildrenOut,
    NoteTreeLocationOut,
    NoteTreeOut,
    ReorderIn,
    TreeReorderIn,
)
from app.services import audit

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


def _pinned_expr():
    """props_json.pinned 为 true 的笔记；兼容历史字符串写法。"""
    return Note.props_json.op("->>")("pinned").in_(("true", "True", "1"))


@router.get("/tree", response_model=NoteTreeOut)
async def note_tree(
    kb_id: uuid.UUID,
    since: datetime | None = None,
    lazy: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """返回目录树数据。

    - 默认返回全部分组与活跃笔记，前端自行组树（兼容旧客户端）。
    - `lazy=1` 只返回全部分组 + 根级 / 置顶笔记，子节点按需通过
      `/tree/children` 拉取，避免大目录首次加载传输全部摘要。
    - `since` 为上次响应的 `server_time`，只返回该时间之后变化的节点
      与删除墓碑；客户端按 ID 合并即可增量刷新。
    """
    await _purge_expired_trash(session, kb_id)
    server_time = datetime.now(timezone.utc)
    total_notes = (
        await session.execute(
            select(func.count())
            .select_from(Note)
            .where(Note.kb_id == kb_id, Note.status == "active")
        )
    ).scalar_one()
    folders_stmt = select(NoteFolder).where(NoteFolder.kb_id == kb_id)
    notes_stmt = select(Note).where(Note.kb_id == kb_id)

    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        # 留 2 秒重叠，避免应用与数据库时钟细微偏差漏掉写入；合并本身幂等。
        since_eff = since - timedelta(seconds=2)
        folders = (
            (
                await session.execute(
                    folders_stmt.where(NoteFolder.updated_at > since_eff).order_by(
                        NoteFolder.sort_order, NoteFolder.created_at
                    )
                )
            )
            .scalars()
            .all()
        )
        changed_notes = (
            (
                await session.execute(
                    notes_stmt.where(
                        Note.updated_at > since_eff, Note.status == "active"
                    ).order_by(Note.sort_order, Note.created_at)
                )
            )
            .scalars()
            .all()
        )
        gone_notes = set(
            (
                await session.execute(
                    select(Note.id).where(
                        Note.kb_id == kb_id,
                        Note.updated_at > since_eff,
                        Note.status != "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        tombstones = (
            await session.execute(
                select(NoteTreeTombstone.item_type, NoteTreeTombstone.item_id).where(
                    NoteTreeTombstone.kb_id == kb_id,
                    NoteTreeTombstone.created_at > since_eff,
                )
            )
        ).all()
        deleted_note_ids = gone_notes | {
            item_id for item_type, item_id in tombstones if item_type == "note"
        }
        deleted_folder_ids = {
            item_id for item_type, item_id in tombstones if item_type == "folder"
        }
        return NoteTreeOut(
            folders=[NoteFolderOut.model_validate(f, from_attributes=True) for f in folders],
            notes=[NoteSummary.model_validate(n, from_attributes=True) for n in changed_notes],
            incremental=True,
            server_time=server_time,
            deleted_note_ids=sorted(deleted_note_ids, key=str),
            deleted_folder_ids=sorted(deleted_folder_ids, key=str),
            lazy=lazy,
            total_notes=total_notes,
        )

    folders = (
        (
            await session.execute(
                folders_stmt.order_by(NoteFolder.sort_order, NoteFolder.created_at)
            )
        )
        .scalars()
        .all()
    )
    notes_stmt = notes_stmt.where(Note.status == "active").order_by(
        Note.sort_order, Note.created_at
    )
    if lazy:
        notes_stmt = notes_stmt.where(
            or_(
                (Note.folder_id.is_(None)) & (Note.parent_note_id.is_(None)),
                _pinned_expr(),
            )
        )
    notes = (await session.execute(notes_stmt)).scalars().all()
    return NoteTreeOut(
        folders=[NoteFolderOut.model_validate(f, from_attributes=True) for f in folders],
        notes=[NoteSummary.model_validate(n, from_attributes=True) for n in notes],
        server_time=server_time,
        lazy=lazy,
        total_notes=total_notes,
    )


@router.get("/tree/children", response_model=NoteTreeChildrenOut)
async def note_tree_children(
    kb_id: uuid.UUID,
    ids: str = Query("", description="父分组 / 父笔记 ID，逗号分隔"),
    limit: int = Query(2000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """按需拉取若干节点（分组或父笔记）的直接子笔记。"""
    try:
        parent_ids = [uuid.UUID(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(400, "ids 包含非法 ID") from None
    if not parent_ids:
        return NoteTreeChildrenOut(notes=[])
    rows = (
        (
            await session.execute(
                select(Note)
                .where(
                    Note.kb_id == kb_id,
                    Note.status == "active",
                    or_(
                        Note.folder_id.in_(parent_ids),
                        Note.parent_note_id.in_(parent_ids),
                    ),
                )
                .order_by(Note.sort_order, Note.created_at)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    truncated = len(rows) > limit
    return NoteTreeChildrenOut(
        notes=[
            NoteSummary.model_validate(n, from_attributes=True) for n in rows[:limit]
        ],
        truncated=truncated,
    )


@router.get("/tree/node/{note_id}", response_model=NoteTreeLocationOut)
async def locate_tree_node(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """返回笔记摘要与祖先链，帮助前端在懒加载目录中展开并定位深链笔记。"""
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id or note.status != "active":
        raise HTTPException(404, "笔记不存在")
    folder_rows = (
        await session.execute(
            select(NoteFolder.id, NoteFolder.parent_id).where(
                NoteFolder.kb_id == kb_id
            )
        )
    ).all()
    folder_parent = {row.id: row.parent_id for row in folder_rows}
    meta_rows = (
        await session.execute(
            select(Note.id, Note.parent_note_id, Note.folder_id).where(
                Note.kb_id == kb_id, Note.status == "active"
            )
        )
    ).all()
    meta = {row.id: (row.parent_note_id, row.folder_id) for row in meta_rows}

    ancestors: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def add_folder_chain(folder_id: uuid.UUID | None) -> None:
        cursor = folder_id
        guard = 0
        while cursor and cursor not in seen and guard < 100:
            seen.add(cursor)
            ancestors.append(cursor)
            cursor = folder_parent.get(cursor)
            guard += 1

    add_folder_chain(note.folder_id)
    cursor = note.parent_note_id
    guard = 0
    while cursor and cursor not in seen and guard < 100:
        seen.add(cursor)
        ancestors.append(cursor)
        parent_parent, parent_folder = meta.get(cursor, (None, None))
        add_folder_chain(parent_folder)
        cursor = parent_parent
        guard += 1

    return NoteTreeLocationOut(
        note=NoteSummary.model_validate(note, from_attributes=True),
        ancestor_ids=ancestors,
    )


@router.get("/tree/search", response_model=list[NoteSummary])
async def search_tree_notes(
    kb_id: uuid.UUID,
    q: str = Query("", max_length=200),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """目录树标题搜索：懒加载模式下不能只搜已加载节点，因此走服务端。"""
    keyword = q.strip()
    if not keyword:
        return []
    escaped = (
        keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    rows = (
        (
            await session.execute(
                select(Note)
                .where(
                    Note.kb_id == kb_id,
                    Note.status == "active",
                    Note.title.ilike(f"%{escaped}%", escape="\\"),
                )
                .order_by(Note.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [NoteSummary.model_validate(n, from_attributes=True) for n in rows]


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
    """递归删除分组子树：子分组与其中的笔记一并移入回收站。

    删除父分组时不能把正文悄悄上移到上一级，否则用户会误以为内容丢失；
    统一走笔记回收站（30 天可恢复），与直接删除笔记保持一致。
    """
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

    notes = list(
        (
            await session.execute(
                select(Note).where(
                    Note.kb_id == kb_id, Note.folder_id.in_(to_delete)
                )
            )
        )
        .scalars()
        .all()
    )
    # 先收集所有子笔记，避免处理顺序影响标记：父笔记可能排在子笔记之后。
    descendant_ids: set[uuid.UUID] = set()
    for note in notes:
        descendant_ids.update(await _note_descendant_ids(session, kb_id, note.id))

    trashed_ids: set[uuid.UUID] = set()
    for note in notes:
        if note.status not in ("active", "archived"):
            continue
        if note.id in descendant_ids:
            # 子笔记随父笔记恢复，避免恢复父笔记后留下不完整的子树。
            _set_lifecycle(
                note,
                trashed_at=_now_iso(),
                status_before_trash=note.status,
                trashed_with_parent=True,
            )
        else:
            # 分组直接包含的笔记：恢复时原分组已不存在，会回到根级。
            _set_lifecycle(
                note,
                trashed_at=_now_iso(),
                status_before_trash=note.status,
                trashed_with_folder=True,
            )
        note.status = "trash"
        trashed_ids.add(note.id)

    await _record_tree_tombstones(
        session, kb_id, folder_ids=to_delete, note_ids=list(trashed_ids)
    )
    await session.execute(delete(NoteFolder).where(NoteFolder.id.in_(to_delete)))
    await audit.record(
        session,
        "folder.delete",
        kb_id=kb_id,
        target_type="folder",
        target_id=folder_id,
        detail={
            "name": folder.name,
            "folders": len(to_delete),
            "notes": len(trashed_ids),
        },
        note=f"删除分组：{folder.name}（{len(to_delete)} 个分组，{len(trashed_ids)} 篇笔记）",
    )
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

