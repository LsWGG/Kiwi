"""笔记模板管理与内置模板。"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CollectionRow,
    Note,
    NoteTemplate,
)
from app.db.session import get_session
from app.routers.note_template_data import BUILTIN_TEMPLATE_VERSION, BUILTIN_TEMPLATES
from app.routers.notes_shared import (
    _next_note_sort,
    _rebuild_links,
    _reload_tags,
    _sync_note_tags,
    _validate_folder,
    _validate_note_parent,
)
from app.schemas.note import (
    NoteOut,
    NoteTemplateCreate,
    NoteTemplateOut,
    NoteTemplateUpdate,
    NoteTemplateUseIn,
)
from app.services.note_database import (
    ensure_collection,
    ensure_row_note,
    normalize_row_data,
)

logger = logging.getLogger("kiwi.notes.templates")

router = APIRouter()

async def _ensure_builtin_templates(
    session: AsyncSession, kb_id: uuid.UUID
) -> None:
    """幂等创建 / 升级内置模板。

    内置模板不可由用户编辑，因此按 ``builtin_version`` 安全地整体刷新；
    新版本新增的模板会补齐，已有模板保持原有 id，不影响引用。
    """
    existing = {
        row.name: row
        for row in (
            (
                await session.execute(
                    select(NoteTemplate).where(
                        NoteTemplate.kb_id == kb_id, NoteTemplate.is_builtin.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    changed = False
    for item in BUILTIN_TEMPLATES:
        row = existing.get(item["name"])
        if row is None:
            session.add(
                NoteTemplate(
                    kb_id=kb_id,
                    name=item["name"],
                    description=item["description"],
                    icon=item["icon"],
                    title_pattern=item["title_pattern"],
                    body_md=item["body_md"],
                    tags_json=list(item["tags_json"]),
                    props_json={"builtin_version": BUILTIN_TEMPLATE_VERSION},
                    is_builtin=True,
                    sort_order=item["sort_order"],
                )
            )
            changed = True
            continue
        version = int((row.props_json or {}).get("builtin_version") or 0)
        if version >= BUILTIN_TEMPLATE_VERSION:
            continue
        row.description = item["description"]
        row.icon = item["icon"]
        row.title_pattern = item["title_pattern"]
        row.body_md = item["body_md"]
        row.tags_json = list(item["tags_json"])
        row.sort_order = item["sort_order"]
        row.props_json = {**(row.props_json or {}), "builtin_version": BUILTIN_TEMPLATE_VERSION}
        changed = True
    if changed:
        await session.commit()


def _template_title(template: NoteTemplate, override: str | None) -> str:
    title = (override or "").strip()
    if title:
        return title[:300]
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = (template.title_pattern or template.name or "无标题文档").replace(
        "{{date}}", today
    )
    return pattern.strip()[:300] or "无标题文档"



# ---- 模板 ----

@router.get("/templates", response_model=list[NoteTemplateOut])
async def list_templates(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    await _ensure_builtin_templates(session, kb_id)
    rows = (
        (
            await session.execute(
                select(NoteTemplate)
                .where(NoteTemplate.kb_id == kb_id)
                .order_by(NoteTemplate.is_builtin.desc(), NoteTemplate.sort_order, NoteTemplate.name)
            )
        )
        .scalars()
        .all()
    )
    return [NoteTemplateOut.model_validate(t, from_attributes=True) for t in rows]


@router.post("/templates", response_model=NoteTemplateOut, status_code=201)
async def create_template(
    data: NoteTemplateCreate,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    sort_order = data.sort_order
    if sort_order is None:
        values = (
            (
                await session.execute(
                    select(NoteTemplate.sort_order).where(
                        NoteTemplate.kb_id == kb_id, NoteTemplate.is_builtin.is_(False)
                    )
                )
            )
            .scalars()
            .all()
        )
        sort_order = (max(values) + 1) if values else 100
    template = NoteTemplate(
        kb_id=kb_id,
        name=data.name.strip()[:200],
        description=data.description,
        icon=data.icon,
        title_pattern=data.title_pattern[:300],
        body_md=data.body_md,
        tags_json=[t.strip().lstrip("#") for t in data.tags_json if t.strip()],
        props_json=data.props_json,
        is_builtin=False,
        sort_order=sort_order,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return NoteTemplateOut.model_validate(template, from_attributes=True)


async def _get_template(
    session: AsyncSession, kb_id: uuid.UUID, template_id: uuid.UUID
) -> NoteTemplate:
    template = await session.get(NoteTemplate, template_id)
    if template is None or template.kb_id != kb_id:
        raise HTTPException(404, "模板不存在")
    return template


@router.patch("/templates/{template_id}", response_model=NoteTemplateOut)
async def update_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTemplateUpdate,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    if template.is_builtin:
        raise HTTPException(403, "内置模板不可编辑，可克隆后修改")
    for field in ("name", "description", "icon", "title_pattern", "body_md", "sort_order"):
        if field in data.model_fields_set:
            value = getattr(data, field)
            if value is not None:
                setattr(template, field, value.strip() if field == "name" else value)
    if data.tags_json is not None:
        template.tags_json = [t.strip().lstrip("#") for t in data.tags_json if t.strip()]
    if data.props_json is not None:
        template.props_json = {**(template.props_json or {}), **data.props_json}
    await session.commit()
    await session.refresh(template)
    return NoteTemplateOut.model_validate(template, from_attributes=True)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    if template.is_builtin:
        raise HTTPException(403, "内置模板不可删除")
    await session.delete(template)
    await session.commit()


@router.post("/templates/{template_id}/use", response_model=NoteOut, status_code=201)
async def use_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTemplateUseIn,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    await _validate_folder(session, kb_id, data.folder_id)
    parent = await _validate_note_parent(
        session, kb_id, None, data.parent_note_id
    )
    folder_id = parent.folder_id if parent is not None else data.folder_id
    title = _template_title(template, data.title)
    body = (template.body_md or "").replace("{{date}}", datetime.now().strftime("%Y-%m-%d"))
    template_props = dict(template.props_json or {})

    # 集合模板：直接在目标数据表中创建一行，并套用标题/标签/正文结构
    collection_note_id = template_props.get("collection_note_id")
    if collection_note_id:
        try:
            db_note_id = uuid.UUID(str(collection_note_id))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "模板关联的数据表无效") from e
        db_note = await session.get(Note, db_note_id)
        if db_note is None or db_note.kb_id != kb_id or db_note.kind != "database":
            raise HTTPException(400, "模板关联的数据表不存在")
        coll = await ensure_collection(session, db_note)
        fields = (coll.schema_json or {}).get("fields") or []
        raw_data = dict(template_props.get("collection_data") or {})
        title_field = next(
            (f["id"] for f in fields if f["id"] in ("name", "title")), None
        ) or next(
            (f["id"] for f in fields if f.get("type") in ("text", "long_text", "url")),
            None,
        )
        if title_field and (data.title or template.title_pattern):
            raw_data[title_field] = title
        try:
            row_data = normalize_row_data(raw_data, fields)
        except ValueError as e:
            raise HTTPException(400, f"模板属性不合法：{e}") from e
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
        row = CollectionRow(
            kb_id=kb_id,
            collection_id=coll.id,
            data=row_data,
            sort_order=(max(existing) + 1) if existing else 0,
        )
        session.add(row)
        await session.flush()
        note = await ensure_row_note(session, db_note, coll, row)
        note.body_md = body
        note.view_mode = "edit"
        props = dict(note.props_json or {})
        props.update(
            {
                k: v
                for k, v in template_props.items()
                if k not in ("collection_note_id", "collection_data", "collection_id")
            }
        )
        props["template_id"] = str(template.id)
        note.props_json = props
        await _sync_note_tags(session, note, list(template.tags_json or []))
        await _rebuild_links(session, kb_id, note)
        await session.commit()
        await _reload_tags(session, note)
        return NoteOut.model_validate(note, from_attributes=True)

    note = Note(
        kb_id=kb_id,
        title=title,
        body_md=body,
        kind="doc",
        folder_id=folder_id,
        parent_note_id=data.parent_note_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(
            session, kb_id, folder_id, data.parent_note_id
        ),
        props_json={**(template.props_json or {}), "template_id": str(template.id)},
    )
    session.add(note)
    await session.flush()
    await _sync_note_tags(session, note, list(template.tags_json or []))
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)

