"""笔记标签管理。"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Note,
    NoteTag,
    NoteTagLink,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_note,
    _reload_tags,
    _sync_note_tags,
)
from app.schemas.note import (
    NoteOut,
    NoteTagCreate,
    NoteTagOut,
    NoteTagsSet,
    NoteTagUpdate,
)

logger = logging.getLogger("kiwi.notes.tags")

router = APIRouter()

# ---- 标签 ----

@router.get("/tags", response_model=list[NoteTagOut])
async def list_tags(
    kb_id: uuid.UUID,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(
            NoteTag.id,
            NoteTag.name,
            NoteTag.parent_id,
            func.count(Note.id).label("usage_count"),
            func.max(Note.updated_at).label("last_used_at"),
        )
        .outerjoin(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
        .outerjoin(
            Note,
            (Note.id == NoteTagLink.note_id) & (Note.status != "trash"),
        )
        .where(NoteTag.kb_id == kb_id)
        .group_by(NoteTag.id)
        .order_by(func.count(Note.id).desc(), NoteTag.name)
    )
    if q:
        stmt = stmt.where(NoteTag.name.ilike(f"%{q.strip()}%"))
    rows = (await session.execute(stmt)).all()
    return [
        NoteTagOut(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            usage_count=row.usage_count,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.post("/tags", response_model=NoteTagOut, status_code=201)
async def create_tag(
    data: NoteTagCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    name = data.name.strip().lstrip("#").strip()
    if not name:
        raise HTTPException(400, "标签名不能为空")
    parent = None
    if data.parent_id is not None:
        parent = await session.get(NoteTag, data.parent_id)
        if parent is None or parent.kb_id != kb_id:
            raise HTTPException(400, "父标签不存在")
    exists = (
        await session.execute(
            select(NoteTag).where(NoteTag.kb_id == kb_id, NoteTag.name == name)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "同名标签已存在")
    tag = NoteTag(kb_id=kb_id, name=name[:100], parent_id=parent.id if parent else None)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return NoteTagOut(id=tag.id, name=tag.name, parent_id=tag.parent_id, usage_count=0)


@router.patch("/tags/{tag_id}", response_model=NoteTagOut)
async def update_tag(
    tag_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTagUpdate,
    session: AsyncSession = Depends(get_session),
):
    tag = await session.get(NoteTag, tag_id)
    if tag is None or tag.kb_id != kb_id:
        raise HTTPException(404, "标签不存在")
    if data.name is not None:
        name = data.name.strip().lstrip("#").strip()
        if not name:
            raise HTTPException(400, "标签名不能为空")
        clash = (
            await session.execute(
                select(NoteTag).where(
                    NoteTag.kb_id == kb_id, NoteTag.name == name, NoteTag.id != tag.id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(409, "同名标签已存在")
        tag.name = name[:100]
    if "parent_id" in data.model_fields_set:
        if data.parent_id == tag.id:
            raise HTTPException(400, "不能把标签挂到自身")
        if data.parent_id is not None:
            parent = await session.get(NoteTag, data.parent_id)
            if parent is None or parent.kb_id != kb_id:
                raise HTTPException(400, "父标签不存在")
            # 防环
            cursor = parent
            guard = 0
            while cursor is not None and guard < 100:
                if cursor.id == tag.id:
                    raise HTTPException(400, "不能把标签移入自身后代")
                cursor = (
                    await session.get(NoteTag, cursor.parent_id)
                    if cursor.parent_id
                    else None
                )
                guard += 1
        tag.parent_id = data.parent_id
    await session.commit()
    await session.refresh(tag)
    usage = (
        await session.execute(
            select(func.count())
            .select_from(NoteTagLink)
            .join(Note, Note.id == NoteTagLink.note_id)
            .where(NoteTagLink.tag_id == tag.id, Note.status != "trash")
        )
    ).scalar_one()
    return NoteTagOut(
        id=tag.id, name=tag.name, parent_id=tag.parent_id, usage_count=usage
    )


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    tag = await session.get(NoteTag, tag_id)
    if tag is None or tag.kb_id != kb_id:
        raise HTTPException(404, "标签不存在")
    await session.execute(
        update(NoteTag).where(NoteTag.parent_id == tag.id).values(parent_id=tag.parent_id)
    )
    await session.delete(tag)
    await session.commit()


@router.put("/{note_id}/tags", response_model=NoteOut)
async def set_note_tags(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTagsSet,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    await _sync_note_tags(session, note, data.names)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


