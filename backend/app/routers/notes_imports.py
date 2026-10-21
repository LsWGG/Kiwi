"""笔记导入、链接抓取与表格导入。"""

import logging
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    CollectionRow,
    ImportBatch,
    IngestJob,
    KnowledgeBase,
    Note,
    NoteAttachment,
    Source,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_note,
    _import_props,
    _next_note_sort,
    _validate_folder,
    _validate_note_parent,
)
from app.schemas.note import (
    LinkCreate,
    LinkMetaIn,
    LinkMetaOut,
    NoteImportStartOut,
    NoteImportStatusOut,
    NoteOut,
    RemoteFileImportIn,
    TableImportOut,
    TablePreviewOut,
)
from app.services import (
    import_service,
    ingest_service,
    upload_session,
)
from app.services.file_security import (
    MAX_DIRECT_UPLOAD_BYTES,
    FileInspection,
    FileRejected,
    inspect_upload,
)
from app.services.link_fetcher import LinkFetchError, fetch_and_extract, fetch_meta
from app.services.note_database import (
    default_views_for,
    ensure_collection,
)
from app.services.remote_file import SSRFError, fetch_remote_file
from app.services.table_import import (
    MAX_TABLE_BYTES,
    TABLE_EXT,
    ParsedTable,
    TableImportError,
    parse_sheet_workbook,
    parse_table,
    preview_payload,
)

logger = logging.getLogger("kiwi.notes.imports")

router = APIRouter()

# ---- 导入 / 链接（必须先于 /{note_id} 声明）----

ALLOWED_IMPORT_EXT = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".pdf",
    ".docx",
    ".doc",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
}



def _link_props(result, url: str, prev: dict | None = None) -> dict:
    props = dict(prev or {})
    props.update(
        {
            "url": url,
            "final_url": result.final_url if result else url,
            "site": result.site if result else "",
            "favicon": result.favicon if result else "",
            "excerpt": result.excerpt if result else "",
            "fetch_status": result.fetch_status if result else "failed",
            "fetch_error": result.error if result else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return props


@router.post("/import", response_model=NoteImportStartOut, status_code=202)
async def import_file(
    kb_id: uuid.UUID,
    file: UploadFile | None = File(None),
    upload_id: str | None = Form(None),
    batch_id: uuid.UUID | None = Form(None),
    folder_id: uuid.UUID | None = Form(None),
    parent_note_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    compile_now: bool = Form(False),
    readonly: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """导入文件 → 创建导入笔记 + 后台解析。

    小文件直接 multipart 上传；大文件先走 /api/ingest/uploads 分片上传，
    完成后把 upload_id 传到这里，避免重复传输。
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, folder_id)

    session_upload: upload_session.UploadSession | None = None
    if upload_id:
        try:
            session_upload = upload_session.load_session(upload_id)
            if session_upload.kb_id != str(kb_id):
                raise upload_session.UploadError("上传会话不存在", 404)
            content = upload_session.assemble(session_upload)
        except upload_session.UploadError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        filename = session_upload.filename
    elif file is not None:
        filename = file.filename or "upload.md"
        content = await file.read()
        if not content:
            raise HTTPException(400, "空文件")
        if len(content) > MAX_DIRECT_UPLOAD_BYTES:
            raise HTTPException(
                413, f"文件超过 {MAX_DIRECT_UPLOAD_BYTES // (1024 * 1024)}MB，请使用分片上传"
            )
    else:
        raise HTTPException(400, "缺少文件或 upload_id")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMPORT_EXT:
        raise HTTPException(
            415, f"不支持的文件类型 {ext}，允许：{', '.join(sorted(ALLOWED_IMPORT_EXT))}"
        )
    try:
        inspection = inspect_upload(content, filename)
    except FileRejected as exc:
        if session_upload is not None:
            upload_session.abort_session(session_upload)
        raise HTTPException(exc.status_code, exc.message) from exc

    try:
        return await _start_import(
            session,
            kb,
            filename=filename,
            content=content,
            folder_id=folder_id,
            parent_note_id=parent_note_id,
            title=title,
            compile_now=compile_now,
            batch_id=batch_id,
            readonly=readonly,
            inspection=inspection,
        )
    finally:
        if session_upload is not None:
            upload_session.abort_session(session_upload)


async def _create_readonly_file_note(
    session: AsyncSession,
    kb: KnowledgeBase,
    *,
    filename: str,
    content: bytes,
    folder_id: uuid.UUID | None,
    parent_note_id: uuid.UUID | None,
    title: str | None,
    inspection: FileInspection,
    import_meta: dict | None,
    batch_id: uuid.UUID | None,
    provider: str,
) -> NoteImportStartOut:
    """只读导入：保留原始文件，不解析、不编译、不索引。"""
    kb_id = kb.id
    user_title = (title or "").strip()
    safe_ext = re.sub(r"[^a-z0-9.]", "", Path(filename).suffix.lower())[:16]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    note = Note(
        kb_id=kb_id,
        title=(user_title or Path(filename).stem.strip() or "只读文档")[:300],
        kind="import",
        body_md="",
        folder_id=folder_id,
        parent_note_id=parent_note_id,
        status="active",
        view_mode="read",
        sort_order=await _next_note_sort(
            session, kb_id, folder_id, parent_note_id
        ),
        props_json={"readonly": True},
    )
    session.add(note)
    await session.flush()

    storage_dir = settings.upload_dir / "media" / str(kb_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{safe_ext}"
    (storage_dir / stored_name).write_bytes(content)
    attachment = NoteAttachment(
        kb_id=kb_id,
        note_id=note.id,
        filename=filename[:300],
        content_type=content_type[:120],
        size=len(content),
        storage_path=f"{kb_id}/{stored_name}",
    )
    session.add(attachment)
    await session.flush()

    note.props_json = {
        "readonly": True,
        "import": {
            "status": "ready",
            "progress": 1.0,
            "readonly": True,
            "filename": filename,
            "content_type": content_type,
            "size": len(content),
            "media_url": f"/media/{kb_id}/{stored_name}",
            "attachment_id": str(attachment.id),
            "scan_status": inspection.scan_status,
            "scan_detail": inspection.scan_detail,
            "warnings": inspection.warnings,
            **(import_meta or {}),
        },
    }
    await session.flush()

    created_batch = False
    if batch_id is not None:
        batch = await session.get(ImportBatch, batch_id)
        if batch is None or batch.kb_id != kb_id:
            await session.rollback()
            raise HTTPException(404, "导入批次不存在")
    else:
        batch = await import_service.create_batch(
            kb_id, provider=provider, label=filename, expected_count=1
        )
        created_batch = True
    await import_service.record_item(
        batch.id,
        title=note.title,
        status="ready",
        warnings=inspection.warnings,
    )
    if created_batch:
        await import_service.mark_closed(batch.id)

    await session.commit()
    await session.refresh(note)
    return NoteImportStartOut(
        note=NoteOut.model_validate(note, from_attributes=True), job_id=None
    )


async def _start_import(
    session: AsyncSession,
    kb: KnowledgeBase,
    *,
    filename: str,
    content: bytes,
    folder_id: uuid.UUID | None,
    parent_note_id: uuid.UUID | None,
    title: str | None,
    compile_now: bool,
    batch_id: uuid.UUID | None,
    inspection: FileInspection,
    import_meta: dict | None = None,
    provider: str = "upload",
    readonly: bool = False,
) -> NoteImportStartOut:
    """创建导入笔记并启动后台解析（文件上传与线上文件共用）。

    ``readonly=True`` 时跳过解析与向量化：原始文件作为附件保留，笔记只提供
    阅读与下载，不转成可编辑文档。
    """
    kb_id = kb.id
    user_title = (title or "").strip()
    parent = await _validate_note_parent(
        session, kb_id, None, parent_note_id
    )
    if parent is not None:
        folder_id = parent.folder_id
    if readonly:
        return await _create_readonly_file_note(
            session,
            kb,
            filename=filename,
            content=content,
            folder_id=folder_id,
            parent_note_id=parent_note_id,
            title=title,
            inspection=inspection,
            import_meta=import_meta,
            batch_id=batch_id,
            provider=provider,
        )
    note = Note(
        kb_id=kb_id,
        title=(user_title or Path(filename).stem.strip() or "未命名文档")[:300],
        kind="import",
        body_md="",
        folder_id=folder_id,
        parent_note_id=parent_note_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(
            session, kb_id, folder_id, parent_note_id
        ),
        props_json={
            "import": {
                "status": "parsing",
                "progress": 0.0,
                "filename": filename,
                "title_source": "user" if user_title else "auto",
                "scan_status": inspection.scan_status,
                "scan_detail": inspection.scan_detail,
                "warnings": inspection.warnings,
                **(import_meta or {}),
            }
        },
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    await session.refresh(kb)

    created_batch = False
    if batch_id is not None:
        batch = await session.get(ImportBatch, batch_id)
        if batch is None or batch.kb_id != kb_id:
            raise HTTPException(404, "导入批次不存在")
        if batch.status != "running":
            raise HTTPException(409, "批次已结束，无法继续导入")
    else:
        batch = await import_service.create_batch(
            kb_id, provider=provider, label=filename, expected_count=1
        )
        created_batch = True

    try:
        job_id = await ingest_service.run_ingest(
            content,
            filename,
            kb,
            compile_now=compile_now,
            note_id=note.id,
            batch_id=str(batch.id),
            scan_status=inspection.scan_status,
            scan_detail=inspection.scan_detail,
            source_type=inspection.source_type,
            title=note.title,
        )
        job = await session.get(IngestJob, job_id)
        await import_service.record_item(
            batch.id,
            title=note.title,
            status="submitted",
            source_id=job.source_id if job else None,
            job_id=job_id,
            warnings=inspection.warnings,
        )
    except Exception as e:  # noqa: BLE001
        await import_service.record_item(
            batch.id,
            title=note.title,
            status="failed",
            error=f"启动导入失败：{e}",
            warnings=inspection.warnings,
        )
        note.props_json = {
            **(note.props_json or {}),
            "import": {**_import_props(note), "status": "failed", "error": f"启动导入失败：{e}"},
        }
        await session.commit()
        if created_batch:
            await import_service.mark_closed(batch.id)
        raise HTTPException(500, f"启动导入失败：{e}") from e

    if created_batch:
        await import_service.mark_closed(batch.id)
    return NoteImportStartOut(
        note=NoteOut.model_validate(note, from_attributes=True), job_id=job_id
    )


@router.post("/import-url", response_model=NoteImportStartOut, status_code=202)
async def import_remote_file(
    payload: RemoteFileImportIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """按 URL 下载线上文件 → 创建导入笔记 + 后台解析。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, payload.folder_id)

    try:
        remote = await fetch_remote_file(payload.url)
    except SSRFError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LinkFetchError as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        inspection = inspect_upload(remote.content, remote.filename)
    except FileRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    return await _start_import(
        session,
        kb,
        filename=remote.filename,
        content=remote.content,
        folder_id=payload.folder_id,
        parent_note_id=payload.parent_note_id,
        title=payload.title,
        compile_now=payload.compile_now,
        batch_id=payload.batch_id,
        readonly=payload.readonly,
        inspection=inspection,
        import_meta={
            "remote_url": remote.url,
            "final_url": remote.final_url,
            "content_type": remote.content_type,
        },
        provider="url",
    )


async def _load_table_bytes(file: UploadFile | None) -> tuple[str, bytes]:
    if file is None:
        raise HTTPException(400, "请选择表格文件")
    filename = file.filename or "table.csv"
    ext = Path(filename).suffix.lower()
    if ext not in TABLE_EXT:
        raise HTTPException(
            415, f"不支持的表格类型 {ext or '（无扩展名）'}，允许：.csv、.xlsx、.xls"
        )
    content = await file.read()
    if not content:
        raise HTTPException(400, "表格文件为空")
    if len(content) > MAX_TABLE_BYTES:
        raise HTTPException(413, "表格文件超过 20MB 上限")
    return filename, content


async def _load_table_upload(
    file: UploadFile | None, sheet: str | None, has_header: bool
) -> tuple[str, bytes, ParsedTable]:
    filename, content = await _load_table_bytes(file)
    try:
        table = parse_table(
            content, filename, sheet=(sheet or "").strip() or None, has_header=has_header
        )
    except TableImportError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return filename, content, table


@router.post("/table-preview", response_model=TablePreviewOut)
async def preview_table_file(
    file: UploadFile = File(...),
    sheet: str | None = Form(None),
    has_header: bool = Form(True),
):
    """解析表格预览：工作表列表、推断字段与样例行。"""
    _, _, table = await _load_table_upload(file, sheet, has_header)
    return TablePreviewOut(**preview_payload(table))


@router.post("/import-table", response_model=TableImportOut, status_code=201)
async def import_table_file(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    folder_id: uuid.UUID | None = Form(None),
    parent_note_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    sheet: str | None = Form(None),
    has_header: bool = Form(True),
    # database = 多视图数据表；sheet = Excel 风格表格笔记（保留多工作表与公式）
    target: str = Form("database"),
    session: AsyncSession = Depends(get_session),
):
    """把 CSV / Excel 转换成数据表或 Excel 风格表格笔记。"""
    if target not in ("database", "sheet"):
        raise HTTPException(400, "target 只能是 database 或 sheet")
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, folder_id)
    parent = await _validate_note_parent(
        session, kb_id, None, parent_note_id
    )
    if parent is not None:
        folder_id = parent.folder_id

    filename, content, table = await _load_table_upload(file, sheet, has_header)
    if not table.rows:
        raise HTTPException(422, "表格没有可导入的数据行")

    base_title = (title or "").strip() or Path(filename).stem.strip() or "导入数据表"
    note_title = base_title[:300]

    if target == "sheet":
        try:
            workbook, truncated = parse_sheet_workbook(
                content, filename, has_header=has_header
            )
        except TableImportError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        note = Note(
            kb_id=kb_id,
            title=note_title,
            kind="sheet",
            body_md="",
            folder_id=folder_id,
            parent_note_id=parent_note_id,
            status="active",
            view_mode="edit",
            sort_order=await _next_note_sort(
                session, kb_id, folder_id, parent_note_id
            ),
            props_json={
                "sheet": workbook,
                "table_import": {
                    "filename": filename,
                    "sheet_count": len(workbook["sheets"]),
                    "row_count": sum(
                        len(item.get("cells") or {})
                        for item in workbook["sheets"]
                    ),
                    "truncated": truncated,
                },
            },
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return TableImportOut(
            note=NoteOut.model_validate(note, from_attributes=True),
            sheet=table.sheet,
            fields=table.fields,
            row_count=len(table.rows),
            truncated=table.truncated or truncated,
        )

    if len(table.sheets) > 1:
        note_title = f"{base_title} · {table.sheet}"[:300]

    note = Note(
        kb_id=kb_id,
        title=note_title,
        kind="database",
        body_md="",
        folder_id=folder_id,
        parent_note_id=parent_note_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(
            session, kb_id, folder_id, parent_note_id
        ),
        props_json={
            "table_import": {
                "filename": filename,
                "sheet": table.sheet,
                "row_count": len(table.rows),
                "truncated": table.truncated,
            }
        },
    )
    session.add(note)
    await session.flush()

    coll = await ensure_collection(session, note)
    coll.name = note_title[:200]
    coll.schema_json = {"fields": table.fields}
    coll.views_json = default_views_for(table.fields)
    coll.description = (
        f"由 {filename} 导入"
        + (f"（工作表「{table.sheet}」）" if len(table.sheets) > 1 else "")
    )[:500]
    await session.flush()

    session.add_all(
        [
            CollectionRow(
                kb_id=kb_id,
                collection_id=coll.id,
                data=data,
                sort_order=index,
            )
            for index, data in enumerate(table.rows)
        ]
    )

    await session.commit()
    await session.refresh(note)
    return TableImportOut(
        note=NoteOut.model_validate(note, from_attributes=True),
        sheet=table.sheet,
        fields=table.fields,
        row_count=len(table.rows),
        truncated=table.truncated,
    )


@router.get("/{note_id}/import", response_model=NoteImportStatusOut)
async def import_status(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """导入进度（前端 1.5s 轮询）：状态、进度、来源与正文是否可读。"""
    note = await _get_note(session, kb_id, note_id)
    if note.kind != "import":
        raise HTTPException(404, "不是导入笔记")
    imp = _import_props(note)
    job = (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.note_id == note.id)
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    source = None
    if job is not None:
        source = await session.get(Source, job.source_id)
    elif note.source_id:
        source = await session.get(Source, note.source_id)

    status = imp.get("status")
    if status not in ("importing", "ready", "failed"):
        if job is not None:
            if job.status == "failed":
                status = "failed"
            elif job.status == "succeeded":
                status = "ready"
            else:
                status = "importing"
        else:
            status = "ready" if (note.body_md or "").strip() else "importing"

    progress = imp.get("progress")
    if progress is None:
        progress = job.progress if job is not None else (1.0 if status == "ready" else 0.0)

    return NoteImportStatusOut(
        status=status,
        progress=float(progress or 0.0),
        error=imp.get("error") or (job.error if job is not None else None),
        source_id=source.id if source is not None else note.source_id,
        job_id=job.id if job is not None else None,
        source_status=source.status if source is not None else None,
        parse_quality=(source.parse_quality if source is not None else None)
        or imp.get("parse_quality"),
        parse_engine=source.parse_engine if source is not None else None,
        scan_status=(source.scan_status if source is not None else None)
        or imp.get("scan_status"),
        scan_detail=(source.scan_detail if source is not None else None)
        or imp.get("scan_detail"),
        quality_report=(source.quality_report if source is not None else None) or {},
        warnings=((source.quality_report or {}).get("warnings") if source else None)
        or list(imp.get("warnings") or []),
        body_ready=bool((note.body_md or "").strip()),
    )


@router.post("/link/meta", response_model=LinkMetaOut)
async def link_meta(data: LinkMetaIn):
    """只读取网页元信息（标题 / 站点 / 摘要），供编辑器插入链接卡片。"""
    try:
        result = await fetch_meta(data.url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e
    return LinkMetaOut(
        url=result.url,
        final_url=result.final_url,
        title=result.title,
        site=result.site,
        excerpt=result.excerpt,
        favicon=result.favicon,
        fetch_status=result.fetch_status,  # type: ignore[arg-type]
        error=result.error,
    )


@router.post("/link", response_model=NoteOut, status_code=201)
async def create_link(
    data: LinkCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """服务端抓取网页正文生成链接笔记；抓取失败降级为书签卡片。

    ``readonly=True`` 时只抓取标题 / 摘要，保留为只读书签，不生成正文，
    也不参与编译与可编辑文档。
    """
    await _validate_folder(session, kb_id, data.folder_id)
    parent = await _validate_note_parent(
        session, kb_id, None, data.parent_note_id
    )
    folder_id = parent.folder_id if parent is not None else data.folder_id
    if data.readonly:
        try:
            meta = await fetch_meta(data.url)
        except LinkFetchError as e:
            raise HTTPException(400, str(e)) from e
        note = Note(
            kb_id=kb_id,
            title=(data.title or meta.title or meta.site or meta.url)[:300],
            body_md="",
            kind="link",
            folder_id=folder_id,
            parent_note_id=data.parent_note_id,
            status="active",
            view_mode="read",
            sort_order=await _next_note_sort(
                session, kb_id, folder_id, data.parent_note_id
            ),
            props_json={
                "readonly": True,
                "link": _link_props(meta, meta.url),
            },
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return NoteOut.model_validate(note, from_attributes=True)

    try:
        result = await fetch_and_extract(data.url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e

    note = Note(
        kb_id=kb_id,
        title=(data.title or result.title or result.site or result.url)[:300],
        body_md=result.markdown,
        kind="link",
        folder_id=folder_id,
        parent_note_id=data.parent_note_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(
            session, kb_id, folder_id, data.parent_note_id
        ),
        props_json={"link": _link_props(result, result.url)},
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/link/refresh", response_model=NoteOut)
async def refresh_link(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    if note.kind != "link":
        raise HTTPException(404, "不是链接笔记")
    link = (note.props_json or {}).get("link") or {}
    url = link.get("url") or link.get("final_url")
    if not url:
        raise HTTPException(400, "链接缺少原始地址")
    try:
        result = await fetch_and_extract(url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e
    if result.fetch_status == "ok" and result.markdown:
        note.body_md = result.markdown
    note.props_json = {**(note.props_json or {}), "link": _link_props(result, url, link)}
    await session.commit()
    await session.refresh(note)
    return NoteOut.model_validate(note, from_attributes=True)

