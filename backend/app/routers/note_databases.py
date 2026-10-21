"""数据表笔记路由：字段/视图配置 + 行 CRUD。"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionRow, Note, NoteCollection
from app.db.session import get_session
from app.routers.note_guard import require_unlocked_note
from app.schemas.note_database import (
    CollectionContextOut,
    DatabaseOut,
    DatabaseUpdate,
    RowBatchDeleteIn,
    RowCreate,
    RowNoteOut,
    RowNotesCreate,
    RowOut,
    RowUpdate,
)
from app.services import note_lock, todo_sync
from app.services.note_database import (
    default_views_for,
    ensure_collection,
    ensure_row_note,
    normalize_row_data,
    sync_row_note_if_exists,
    validate_fields,
    validate_views,
)

router = APIRouter(
    prefix="/api/notes",
    tags=["note-databases"],
    dependencies=[Depends(require_unlocked_note)],
)


async def _get_database(
    session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID
) -> tuple[Note, NoteCollection]:
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id or note.kind != "database":
        raise HTTPException(404, "数据表不存在")
    coll = await ensure_collection(session, note)
    return note, coll


@router.get("/{note_id}/database", response_model=DatabaseOut)
async def get_database(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note, coll = await _get_database(session, kb_id, note_id)
    await session.commit()
    await session.refresh(coll)
    fields = (coll.schema_json or {}).get("fields") or []
    return DatabaseOut(
        note_id=note_id,
        name=coll.name,
        fields=fields,
        views=coll.views_json or [],
    )


@router.patch("/{note_id}/database", response_model=DatabaseOut)
async def update_database(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: DatabaseUpdate,
    session: AsyncSession = Depends(get_session),
):
    note, coll = await _get_database(session, kb_id, note_id)
    current_fields = (coll.schema_json or {}).get("fields") or []
    try:
        fields = validate_fields(data.fields) if data.fields is not None else current_fields
        if data.views is not None:
            views = validate_views(data.views, fields)
        elif data.fields is not None:
            # 字段变更但未提交视图：引用失效时回退默认视图
            try:
                views = validate_views(coll.views_json or [], fields)
            except ValueError:
                views = default_views_for(fields)
        else:
            views = coll.views_json or []
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    coll.schema_json = {"fields": fields}
    coll.views_json = views
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(400, "名称不能为空")
        coll.name = name
        note.title = name[:300]
    await session.commit()
    await session.refresh(coll)
    return DatabaseOut(
        note_id=note_id,
        name=coll.name,
        fields=coll.schema_json.get("fields", []),
        views=coll.views_json,
    )


@router.get("/{note_id}/collection-context", response_model=CollectionContextOut)
async def get_collection_context(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """行笔记 → 所属集合的属性字段与当前值（供笔记详情面板编辑）。"""
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id:
        raise HTTPException(404, "笔记不存在")
    props = note.props_json or {}
    try:
        db_note_id = uuid.UUID(str(props.get("collection_note_id") or ""))
        row_id = uuid.UUID(str(props.get("collection_row_id") or ""))
    except ValueError as e:
        raise HTTPException(404, "该笔记不属于任何集合") from e
    db_note = await session.get(Note, db_note_id)
    if db_note is None or db_note.kb_id != kb_id or db_note.kind != "database":
        raise HTTPException(404, "所属数据表不存在")
    # 行笔记属性面板会暴露所属数据表的字段与行值；数据表上锁时同样要求解锁。
    if db_note.is_locked and not note_lock.token_is_valid(db_note, x_note_token):
        raise HTTPException(403, "所属数据表已上锁，请先输入密码解锁")
    coll = await ensure_collection(session, db_note)
    row = await session.get(CollectionRow, row_id)
    if row is None or row.collection_id != coll.id or row.kb_id != kb_id:
        raise HTTPException(404, "集合记录不存在")
    fields = (coll.schema_json or {}).get("fields") or []
    title = db_note.title
    await session.commit()
    return CollectionContextOut(
        database_note_id=db_note.id,
        database_title=title,
        row_id=row.id,
        fields=fields,
        data=row.data or {},
        title=note.title,
    )


@router.get("/{note_id}/rows", response_model=list[RowOut])
async def list_rows(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    db_note, coll = await _get_database(session, kb_id, note_id)
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
    return [RowOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/{note_id}/rows", response_model=RowOut, status_code=201)
async def create_row(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: RowCreate,
    session: AsyncSession = Depends(get_session),
):
    _db_note, coll = await _get_database(session, kb_id, note_id)
    fields = (coll.schema_json or {}).get("fields") or []
    try:
        row_data = normalize_row_data(data.data, fields)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    sort_order = data.sort_order
    if sort_order is None:
        existing = (
            (
                await session.execute(
                    select(CollectionRow.sort_order).where(
                        CollectionRow.collection_id == coll.id
                    )
                )
            )
            .scalars()
            .all()
        )
        sort_order = (max(existing) + 1) if existing else 0
    row = CollectionRow(
        kb_id=kb_id,
        collection_id=coll.id,
        data=row_data,
        sort_order=sort_order,
    )
    session.add(row)
    await session.commit()
    todo_sync.schedule_kb_sync(kb_id)
    await session.refresh(row)
    return RowOut.model_validate(row, from_attributes=True)


async def _get_row(
    session: AsyncSession,
    kb_id: uuid.UUID,
    note_id: uuid.UUID,
    row_id: uuid.UUID,
) -> tuple[Note, NoteCollection, CollectionRow]:
    db_note, coll = await _get_database(session, kb_id, note_id)
    row = await session.get(CollectionRow, row_id)
    if row is None or row.collection_id != coll.id or row.kb_id != kb_id:
        raise HTTPException(404, "行不存在")
    return db_note, coll, row


@router.patch("/{note_id}/rows/{row_id}", response_model=RowOut)
async def update_row(
    note_id: uuid.UUID,
    row_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: RowUpdate,
    session: AsyncSession = Depends(get_session),
):
    db_note, coll, row = await _get_row(session, kb_id, note_id, row_id)
    fields = (coll.schema_json or {}).get("fields") or []
    if data.data is not None:
        try:
            row.data = normalize_row_data({**(row.data or {}), **data.data}, fields)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if data.sort_order is not None:
        row.sort_order = data.sort_order
    # 已生成笔记的记录保持标题与集合上下文同步；未生成时不擅自创建
    await sync_row_note_if_exists(session, db_note, coll, row)
    await session.commit()
    todo_sync.schedule_kb_sync(kb_id)
    await session.refresh(row)
    return RowOut.model_validate(row, from_attributes=True)


@router.post("/{note_id}/rows/notes", response_model=list[RowNoteOut])
async def generate_row_notes(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    payload: RowNotesCreate,
    session: AsyncSession = Depends(get_session),
):
    """为选中的一条或多条记录按需生成可编辑笔记。

    导入表格时不再自动为每条记录建笔记；用户在表格中勾选记录后再生成。
    已生成过笔记的行直接复用，不会覆盖笔记正文。
    """
    db_note, coll = await _get_database(session, kb_id, note_id)
    wanted = list(dict.fromkeys(payload.row_ids))
    rows = list(
        (
            await session.execute(
                select(CollectionRow).where(
                    CollectionRow.collection_id == coll.id,
                    CollectionRow.kb_id == kb_id,
                    CollectionRow.id.in_(wanted),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(wanted):
        raise HTTPException(404, "部分记录不存在或不属于该数据表")

    out: list[RowNoteOut] = []
    for row_id in wanted:
        row = by_id[row_id]
        existing = (
            await session.get(Note, row.note_id) if row.note_id is not None else None
        )
        note = await ensure_row_note(session, db_note, coll, row)
        out.append(
            RowNoteOut(
                row_id=row.id,
                note_id=note.id,
                title=note.title,
                created=existing is None,
            )
        )
    await session.commit()
    return out


@router.post("/{note_id}/rows/batch-delete", response_model=dict)
async def delete_rows(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    payload: RowBatchDeleteIn,
    session: AsyncSession = Depends(get_session),
):
    """批量删除记录；每行对应的笔记一并删除（外键级联行）。"""
    _, coll = await _get_database(session, kb_id, note_id)
    rows = list(
        (
            await session.execute(
                select(CollectionRow).where(
                    CollectionRow.collection_id == coll.id,
                    CollectionRow.id.in_(payload.row_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    deleted = 0
    for row in rows:
        note = await session.get(Note, row.note_id) if row.note_id else None
        if note is not None:
            await session.delete(note)
        else:
            await session.delete(row)
        deleted += 1
    await session.commit()
    todo_sync.schedule_kb_sync(kb_id)
    return {"deleted": deleted}


@router.delete("/{note_id}/rows/{row_id}", status_code=204)
async def delete_row(
    note_id: uuid.UUID,
    row_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    _, _, row = await _get_row(session, kb_id, note_id, row_id)
    # 行笔记随行一起删除；外键级联会移除 collection_row
    note = await session.get(Note, row.note_id) if row.note_id else None
    if note is not None:
        await session.delete(note)
    else:
        await session.delete(row)
    await session.commit()
    todo_sync.schedule_kb_sync(kb_id)
