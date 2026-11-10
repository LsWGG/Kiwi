"""附件 / 内嵌媒体：上传、列表、删除，文件经 /media 静态目录提供。"""

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Note, NoteAttachment
from app.db.session import get_session
from app.schemas.attachment import AttachmentOut, MdBundleOut
from app.services import md_bundle
from app.services.file_security import MAX_UPLOAD_BYTES

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

# 附件不设大小上限：文件流式落盘，避免大文件占用进程内存。
UPLOAD_CHUNK_BYTES = 1024 * 1024
# 图片与常见文档；不收 SVG（同源内联脚本风险）
ALLOWED_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".avif",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".zip",
}


def media_dir() -> Path:
    path = settings.upload_dir / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachment_out(att: NoteAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=att.id,
        kb_id=att.kb_id,
        note_id=att.note_id,
        filename=att.filename,
        content_type=att.content_type,
        size=att.size,
        url=f"/media/{att.storage_path}",
        created_at=att.created_at,
    )


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    kb_id: uuid.UUID,
    note_id: uuid.UUID | None = None,
    file: UploadFile = File(...),
    any_type: bool = False,
    session: AsyncSession = Depends(get_session),
):
    filename = (file.filename or "attachment.bin").strip() or "attachment.bin"
    # 扩展名只保留安全字符，避免拼进存储路径时引入异常字符
    ext = re.sub(r"[^a-z0-9.]", "", Path(filename).suffix.lower())[:16]
    if not any_type and ext not in ALLOWED_EXT:
        raise HTTPException(
            415, f"不支持的文件类型 {ext or '(无扩展名)'}，允许：{', '.join(sorted(ALLOWED_EXT))}"
        )

    if note_id is not None:
        note = await session.get(Note, note_id)
        if note is None or note.kb_id != kb_id:
            raise HTTPException(404, "笔记不存在")

    storage_dir = media_dir() / str(kb_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = storage_dir / stored_name
    partial = storage_dir / f".{stored_name}.part"
    size = 0
    try:
        with partial.open("wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "空文件")
        partial.replace(target)
    except HTTPException:
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise HTTPException(500, "附件写入失败，请检查磁盘空间") from exc
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    content_type = (file.content_type or "").split(";")[0].strip()
    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    att = NoteAttachment(
        kb_id=kb_id,
        note_id=note_id,
        filename=filename[:300],
        content_type=content_type[:120],
        size=size,
        storage_path=f"{kb_id}/{stored_name}",
    )
    session.add(att)
    await session.commit()
    await session.refresh(att)
    return attachment_out(att)


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    kb_id: uuid.UUID,
    note_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(NoteAttachment).where(NoteAttachment.kb_id == kb_id)
    if note_id is not None:
        stmt = stmt.where(NoteAttachment.note_id == note_id)
    rows = (
        (await session.execute(stmt.order_by(NoteAttachment.created_at.desc())))
        .scalars()
        .all()
    )
    return [attachment_out(a) for a in rows]


@router.post("/md-bundle", response_model=MdBundleOut)
async def import_md_bundle(
    kb_id: uuid.UUID,
    note_id: uuid.UUID | None = None,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """把「md + 图片 / 附件目录」压缩包解析进当前笔记。

    编辑器「插入附件」上传 `.zip` 时调用：包内资源落盘为附件并重写正文引用，
    返回可直接插入的 Markdown；包内没有 Markdown 时返回 ``found=false``，
    前端回退为普通附件上传。
    """
    filename = (file.filename or "bundle.zip").strip() or "bundle.zip"
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(415, "请上传 .zip 压缩包")
    if note_id is not None:
        note = await session.get(Note, note_id)
        if note is None or note.kb_id != kb_id:
            raise HTTPException(404, "笔记不存在")

    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"压缩包超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限"
        )

    try:
        bundle = await md_bundle.import_md_bundle(
            session,
            kb_id=kb_id,
            note_id=note_id,
            content=content,
            filename=filename,
            require_markdown=False,
        )
    except md_bundle.MdBundleError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    if bundle is None:
        # 普通附件压缩包：不落任何数据，交给前端按文件卡片插入。
        return MdBundleOut(found=False)

    await session.commit()
    return MdBundleOut(
        found=True,
        title=bundle.title,
        markdown=bundle.markdown,
        main_entry=bundle.main_entry,
        attachments=[attachment_out(a) for a in bundle.attachments],
        warnings=bundle.warnings,
        rewritten_refs=bundle.rewritten_refs,
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    att = await session.get(NoteAttachment, attachment_id)
    if att is None or att.kb_id != kb_id:
        raise HTTPException(404, "附件不存在")
    storage_path = att.storage_path
    await session.delete(att)
    await session.commit()
    # 尽力删除磁盘文件（失败不阻塞）
    try:
        target = (media_dir() / storage_path).resolve()
        if target.is_relative_to(media_dir().resolve()):
            target.unlink(missing_ok=True)
    except OSError:
        pass
