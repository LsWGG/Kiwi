"""Wiki 关联、学习要点、复制与跨库迁移。"""

import logging
import uuid
from copy import deepcopy

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CollectionRow,
    IngestJob,
    KnowledgeBase,
    Note,
    NoteAttachment,
    NoteCollection,
    NoteLink,
    NoteTag,
    NoteTagLink,
    WikiPage,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _collection_child_notes,
    _get_note,
    _next_note_sort,
    _now_iso,
    _rebuild_links,
    _reload_tags,
    _require_unlocked,
    _sync_note_tags,
    _validate_folder,
    _validate_note_parent,
)
from app.schemas.note import (
    NoteCopyIn,
    NoteOut,
    NoteStudyPointOut,
    NoteStudyPointsIn,
    NoteTransferIn,
    NoteWikiLinkIn,
    NoteWikiLinkOut,
)
from app.services import (
    audit,
)
from app.services.note_database import (
    ensure_collection,
    ensure_row_note,
)

logger = logging.getLogger("kiwi.notes.actions")

router = APIRouter()

# ---- 关联 Wiki 页面 ----

@router.get("/{note_id}/wiki", response_model=NoteWikiLinkOut)
async def get_note_wiki(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    page_id = note.wiki_page_id
    if page_id is None:
        return NoteWikiLinkOut()
    page = await session.get(WikiPage, page_id)
    if page is None or page.kb_id != kb_id:
        return NoteWikiLinkOut()
    return NoteWikiLinkOut(wiki_page_id=page.id, slug=page.slug, title=page.title)


@router.put("/{note_id}/wiki", response_model=NoteWikiLinkOut)
async def set_note_wiki(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteWikiLinkIn,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    props = dict(note.props_json or {})
    if data.wiki_page_id is None:
        props.pop("wiki_page_id", None)
        note.props_json = props
        await session.commit()
        return NoteWikiLinkOut()
    page = await session.get(WikiPage, data.wiki_page_id)
    if page is None or page.kb_id != kb_id:
        raise HTTPException(400, "Wiki 页面不存在")
    props["wiki_page_id"] = str(page.id)
    note.props_json = props
    await session.commit()
    return NoteWikiLinkOut(wiki_page_id=page.id, slug=page.slug, title=page.title)


# ---- 学习要点 ----

def _study_points(note: Note) -> list[NoteStudyPointOut]:
    raw = (note.props_json or {}).get("study_points") or []
    out: list[NoteStudyPointOut] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        out.append(
            NoteStudyPointOut(
                id=str(item.get("id") or uuid.uuid4()),
                text=str(item["text"]),
                wiki_slug=item.get("wiki_slug") or None,
                created_at=str(item.get("created_at") or _now_iso()),
            )
        )
    return out


@router.get("/{note_id}/study-points", response_model=list[NoteStudyPointOut])
async def list_study_points(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "查看学习点")
    return _study_points(note)


@router.put("/{note_id}/study-points", response_model=list[NoteStudyPointOut])
async def set_study_points(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteStudyPointsIn,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "编辑学习点")
    existing = {p.id: p for p in _study_points(note)}
    points: list[dict] = []
    for point in data.points:
        point_id = str(uuid.uuid4())
        # 内容未变时沿用原 id，便于前端稳定引用
        for old in existing.values():
            if old.text == point.text and old.wiki_slug == (point.wiki_slug or None):
                point_id = old.id
                break
        points.append(
            {
                "id": point_id,
                "text": point.text.strip(),
                "wiki_slug": point.wiki_slug.strip() if point.wiki_slug else None,
                "created_at": existing.get(point_id).created_at
                if point_id in existing
                else _now_iso(),
            }
        )
    props = dict(note.props_json or {})
    props["study_points"] = points
    note.props_json = props
    await session.commit()
    return _study_points(note)


@router.post("/{note_id}/copy", response_model=NoteOut, status_code=201)
async def copy_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteCopyIn,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """复制笔记到当前知识库；数据表会连同字段、视图和记录一起复制。"""
    src = await _get_note(session, kb_id, note_id)
    _require_unlocked(src, x_note_token, "复制")
    parent_note_id = src.parent_note_id
    if "parent_note_id" in data.model_fields_set:
        parent_note_id = data.parent_note_id
    elif (
        "folder_id" in data.model_fields_set
        and data.folder_id != src.folder_id
    ):
        # 显式换组时副本不再挂在原父笔记下，避免跨组层级。
        parent_note_id = None
    parent = await _validate_note_parent(
        session, kb_id, None, parent_note_id
    )
    folder_id = (
        parent.folder_id
        if parent is not None
        else (
            data.folder_id
            if "folder_id" in data.model_fields_set
            else src.folder_id
        )
    )
    await _validate_folder(session, kb_id, folder_id)
    sort_order = await _next_note_sort(
        session, kb_id, folder_id, parent_note_id
    )
    title = (data.title or f"{src.title} 副本").strip()[:300] or "无标题文档"
    props = deepcopy(src.props_json or {})
    # 置顶状态属于原条目，副本默认不继承
    props.pop("pinned", None)
    if src.kind == "import":
        # 副本不再处于导入流程中，其余元数据（来源、解析质量等）保留
        props.pop("import", None)
    note = Note(
        kb_id=kb_id,
        title=title,
        body_md=src.body_md,
        kind=src.kind,
        folder_id=folder_id,
        parent_note_id=parent_note_id,
        source_id=None,
        status="active",
        view_mode=src.view_mode,
        sort_order=sort_order,
        props_json=props,
    )
    session.add(note)
    await session.flush()

    if src.kind == "database":
        src_coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == src.id)
            )
        ).scalar_one_or_none()
        new_coll = await ensure_collection(session, note)
        if src_coll is not None:
            new_coll.description = src_coll.description
            new_coll.schema_json = deepcopy(src_coll.schema_json or {})
            new_coll.views_json = deepcopy(src_coll.views_json or [])
            rows = (
                (
                    await session.execute(
                        select(CollectionRow)
                        .where(CollectionRow.collection_id == src_coll.id)
                        .order_by(CollectionRow.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                new_row = CollectionRow(
                    kb_id=kb_id,
                    collection_id=new_coll.id,
                    data=deepcopy(row.data or {}),
                    sort_order=row.sort_order,
                )
                session.add(new_row)
                await session.flush()
                # 每行副本同样是完整笔记
                await ensure_row_note(session, note, new_coll, new_row)
            await session.flush()

    await _sync_note_tags(session, note, list(src.tag_names))
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/transfer", response_model=NoteOut)
async def transfer_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTransferIn,
    session: AsyncSession = Depends(get_session),
):
    """把笔记移动到另一个知识库（可指定目标分组）。"""
    note = await _get_note(session, kb_id, note_id)
    if data.target_kb_id == kb_id:
        raise HTTPException(400, "目标知识库与当前知识库相同")
    target = await session.get(KnowledgeBase, data.target_kb_id)
    if target is None:
        raise HTTPException(404, "目标知识库不存在")
    await _validate_folder(session, target.id, data.folder_id)
    # 必须在改 kb_id 前计算，避免本条记录进入目标库排序统计
    sort_order = await _next_note_sort(session, target.id, data.folder_id)
    tag_names = list(note.tag_names)

    # 跨库后原库的入链/出链都失效，清掉后在新库按 [[标题]] 重建出链
    await session.execute(
        delete(NoteLink).where(
            or_(NoteLink.from_note_id == note.id, NoteLink.to_note_id == note.id)
        )
    )
    await session.execute(delete(NoteTagLink).where(NoteTagLink.note_id == note.id))
    note.kb_id = target.id
    note.folder_id = data.folder_id
    note.sort_order = sort_order
    # 子笔记留在原知识库：跨库笔记不能继续挂在已迁走的父级下。
    note.parent_note_id = None
    await session.execute(
        update(Note)
        .where(Note.parent_note_id == note.id)
        .values(parent_note_id=None)
    )
    # 旧库 Source 不再关联，正文已物化在笔记中
    note.source_id = None
    # 关联的 Wiki 页面属于原库，跨库后失效
    props = dict(note.props_json or {})
    props.pop("wiki_page_id", None)
    note.props_json = props
    if tag_names:
        await _sync_note_tags(session, note, tag_names)

    coll = (
        await session.execute(select(NoteCollection).where(NoteCollection.note_id == note.id))
    ).scalar_one_or_none()
    if coll is not None:
        coll.kb_id = target.id
        await session.execute(
            update(CollectionRow)
            .where(CollectionRow.collection_id == coll.id)
            .values(kb_id=target.id)
        )
        # 行笔记是完整笔记，必须随数据表迁移到目标知识库
        for child in await _collection_child_notes(session, note):
            child_tag_names = list(
                (
                    await session.execute(
                        select(NoteTag.name)
                        .join(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
                        .where(NoteTagLink.note_id == child.id)
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(
                delete(NoteLink).where(
                    or_(
                        NoteLink.from_note_id == child.id,
                        NoteLink.to_note_id == child.id,
                    )
                )
            )
            await session.execute(
                delete(NoteTagLink).where(NoteTagLink.note_id == child.id)
            )
            child.kb_id = target.id
            child.folder_id = data.folder_id
            child.source_id = None
            child_props = dict(child.props_json or {})
            child_props.pop("wiki_page_id", None)
            child.props_json = child_props
            if child_tag_names:
                await _sync_note_tags(session, child, child_tag_names)
            await session.execute(
                update(NoteAttachment)
                .where(NoteAttachment.note_id == child.id)
                .values(kb_id=target.id)
            )
            await _rebuild_links(session, target.id, child)
    await session.execute(
        update(NoteAttachment).where(NoteAttachment.note_id == note.id).values(kb_id=target.id)
    )
    await session.execute(
        update(IngestJob).where(IngestJob.note_id == note.id).values(kb_id=target.id)
    )
    await _rebuild_links(session, target.id, note)
    await audit.record(
        session,
        "note.transfer",
        kb_id=kb_id,
        target_type="note",
        target_id=note_id,
        detail={
            "title": note.title,
            "from_kb_id": str(kb_id),
            "to_kb_id": str(target.id),
            "to_kb_name": target.name,
            "folder_id": str(data.folder_id) if data.folder_id else None,
        },
        note=f"跨库迁移：{note.title} → {target.name}",
    )
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)
