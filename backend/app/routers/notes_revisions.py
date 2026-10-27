"""笔记历史版本与原始文件。"""

import logging
import mimetypes
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    NoteAttachment,
    NoteCollection,
    NoteRevision,
    Source,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    REVISION_MAX_PER_NOTE,
    _get_note,
    _import_props,
    _rebuild_links,
    _reload_tags,
    _require_unlocked,
    _serialize_note,
    _snapshot_revision,
)
from app.schemas.note import (
    NoteOut,
    NoteRevisionOut,
    NoteRevisionSummary,
)
from app.services import (
    audit,
)
from app.services.source_paths import resolve_raw_path

logger = logging.getLogger("kiwi.notes.revisions")

router = APIRouter()

# ---- 历史版本 ----

@router.get("/{note_id}/revisions", response_model=list[NoteRevisionSummary])
async def list_note_revisions(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """按时间倒序返回版本列表（不含正文）。"""
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    _require_unlocked(note, x_note_token, "查看历史版本")
    rows = (
        (
            await session.execute(
                select(NoteRevision)
                .where(NoteRevision.note_id == note_id, NoteRevision.kb_id == kb_id)
                .order_by(NoteRevision.created_at.desc())
                .limit(REVISION_MAX_PER_NOTE)
            )
        )
        .scalars()
        .all()
    )
    return [NoteRevisionSummary.model_validate(row, from_attributes=True) for row in rows]


@router.post("/{note_id}/revisions", response_model=NoteRevisionSummary, status_code=201)
async def create_note_revision(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """手动保存一个检查点。"""
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "创建历史版本")
    revision = await _snapshot_revision(session, note, source="manual", coalesce=False)
    await session.commit()
    await session.refresh(revision)
    return NoteRevisionSummary.model_validate(revision, from_attributes=True)


@router.get("/{note_id}/revisions/{revision_id}", response_model=NoteRevisionOut)
async def get_note_revision(
    note_id: uuid.UUID,
    revision_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    _require_unlocked(note, x_note_token, "查看历史版本")
    revision = await session.get(NoteRevision, revision_id)
    if revision is None or revision.note_id != note_id or revision.kb_id != kb_id:
        raise HTTPException(404, "历史版本不存在")
    return NoteRevisionOut.model_validate(revision, from_attributes=True)


@router.post(
    "/{note_id}/revisions/{revision_id}/restore", response_model=NoteOut
)
async def restore_note_revision(
    note_id: uuid.UUID,
    revision_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """还原到指定版本；当前内容会先保存为「还原前」快照。"""
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    _require_unlocked(note, x_note_token, "还原历史版本")
    revision = await session.get(NoteRevision, revision_id)
    if revision is None or revision.note_id != note_id or revision.kb_id != kb_id:
        raise HTTPException(404, "历史版本不存在")
    if revision.title == note.title and revision.body_md == note.body_md:
        return _serialize_note(note, x_note_token)

    await _snapshot_revision(session, note, source="restore", coalesce=False)
    note.title = revision.title or note.title
    note.body_md = revision.body_md
    # 合并属性：保留版本内容，同时不丢失收藏 / 导入态等当前标记。
    note.props_json = {**(note.props_json or {}), **(revision.props_json or {})}
    await _rebuild_links(session, kb_id, note)
    if note.kind == "database":
        coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == note.id)
            )
        ).scalar_one_or_none()
        if coll is not None:
            coll.name = note.title
    await session.commit()
    await _reload_tags(session, note)
    return _serialize_note(note, x_note_token)


@router.get("/{note_id}/source-file")
async def note_source_file(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """导入笔记的原始文件：内联预览 / 下载（PDF 不再依赖解析结果）。"""
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    _require_unlocked(note, x_note_token, "查看原始文件")
    import_meta = _import_props(note)
    filename = str(import_meta.get("filename") or f"{note.title}")

    if note.source_id is not None:
        source = await session.get(Source, note.source_id)
        if source is not None and source.kb_id == kb_id:
            path = resolve_raw_path(source.raw_path)
            if path.exists() and path.is_file():
                content_type = (
                    mimetypes.guess_type(filename)[0]
                    or mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream"
                )
                return FileResponse(
                    path,
                    media_type=content_type,
                    filename=filename,
                    content_disposition_type="inline",
                )

    # 只读导入没有 Source：回退到附件 / media_url。
    media_url = str(import_meta.get("media_url") or "")
    attachment_id = import_meta.get("attachment_id")
    attachment: NoteAttachment | None = None
    if attachment_id:
        try:
            attachment = await session.get(NoteAttachment, uuid.UUID(str(attachment_id)))
        except (ValueError, TypeError):
            attachment = None
    if attachment is not None and attachment.note_id == note.id:
        path = settings.upload_dir / "media" / attachment.storage_path
        if path.exists() and path.is_file():
            return FileResponse(
                path,
                media_type=attachment.content_type or "application/octet-stream",
                filename=attachment.filename,
                content_disposition_type="inline",
            )
    if media_url.startswith("/media/"):
        rel = media_url[len("/media/") :].lstrip("/")
        path = settings.upload_dir / "media" / rel
        if path.exists() and path.is_file():
            return FileResponse(
                path,
                media_type=str(import_meta.get("content_type") or "application/octet-stream"),
                filename=filename,
                content_disposition_type="inline",
            )
    raise HTTPException(404, "原始文件不存在")


@router.delete("/{note_id}/revisions/{revision_id}", status_code=204)
async def delete_note_revision(
    note_id: uuid.UUID,
    revision_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    _require_unlocked(note, x_note_token, "删除历史版本")
    revision = await session.get(NoteRevision, revision_id)
    if revision is None or revision.note_id != note_id or revision.kb_id != kb_id:
        raise HTTPException(404, "历史版本不存在")
    detail = {
        "title": note.title,
        "revision_id": str(revision_id),
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
    }
    await session.delete(revision)
    await audit.record(
        session,
        "note.revision.delete",
        kb_id=kb_id,
        target_type="note",
        target_id=note_id,
        detail=detail,
        note=f"删除历史版本：{note.title}",
    )
    await session.commit()


