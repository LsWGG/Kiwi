"""导入路由：安全校验、批次管理、分片上传、语雀接入、SSE 进度。"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ImportBatch,
    IngestJob,
    Job,
    KnowledgeBase,
    Note,
    NoteFolder,
    Source,
    WikiPage,
)
from app.db.session import get_session
from app.event_hub import hub
from app.schemas.source import (
    BatchCreateRequest,
    ChunkCompleteRequest,
    ChunkInitRequest,
    CompileRequest,
    ImportBatchOut,
    IngestJobOut,
    SourceOut,
    YuqueReposRequest,
    YuqueTokenRequest,
)
from app.services import import_service, ingest_service, upload_session
from app.services.file_security import (
    MAX_DIRECT_UPLOAD_BYTES,
    FileRejected,
    inspect_archive,
    inspect_upload,
)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

DIRECT_UPLOAD_LIMIT = MAX_DIRECT_UPLOAD_BYTES


async def _get_kb(session: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    return kb


def _reject(exc: FileRejected) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


def _upload_error(exc: upload_session.UploadError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


async def _validate_folder(
    session: AsyncSession, kb_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    if folder_id is None:
        return
    folder = await session.get(NoteFolder, folder_id)
    if folder is None or folder.kb_id != kb_id:
        raise HTTPException(404, "目标分组不存在")


async def _get_batch(
    session: AsyncSession, batch_id: uuid.UUID, kb_id: uuid.UUID
) -> ImportBatch:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None or batch.kb_id != kb_id:
        raise HTTPException(404, "导入批次不存在")
    return batch


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")
    if len(content) > limit:
        raise HTTPException(413, f"文件超过 {limit // (1024 * 1024)}MB 上限")
    return content


# --------------------------------------------------------------------------- #
# 兼容接口：单文件直传
# --------------------------------------------------------------------------- #
@router.post("/upload", response_model=IngestJobOut, status_code=202)
async def upload_file(
    kb_id: uuid.UUID,
    compile_now: bool = Form(False),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """小文件直传（≤20MB）。自动创建并关闭批次，供报告追溯。"""
    kb = await _get_kb(session, kb_id)
    content = await _read_limited(file, DIRECT_UPLOAD_LIMIT)
    filename = file.filename or "upload.bin"
    try:
        inspection = inspect_upload(content, filename, DIRECT_UPLOAD_LIMIT)
    except FileRejected as exc:
        raise _reject(exc)

    batch = await import_service.create_batch(
        kb.id, provider="upload", label=filename, expected_count=1
    )
    job_id, status = await import_service.submit_bytes(
        kb,
        batch.id,
        content=content,
        filename=filename,
        source_type=inspection.source_type,
        compile_now=compile_now,
        scan_status=inspection.scan_status,
        scan_detail=inspection.scan_detail,
    )
    await import_service.mark_closed(batch.id)
    if job_id is None:
        raise HTTPException(409 if status == "skipped" else 400, status)

    job = (await session.execute(select(IngestJob).where(IngestJob.id == job_id))).scalar_one()
    return IngestJobOut.model_validate(job, from_attributes=True)


# --------------------------------------------------------------------------- #
# 批次
# --------------------------------------------------------------------------- #
@router.post("/batches", response_model=ImportBatchOut, status_code=201)
async def create_batch(
    data: BatchCreateRequest,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_kb(session, kb_id)
    if data.provider not in ("upload", "yuque_token", "yuque_zip"):
        raise HTTPException(400, "provider 应为 upload / yuque_token / yuque_zip")
    batch = await import_service.create_batch(
        kb_id,
        provider=data.provider,
        label=data.label,
        expected_count=max(0, data.expected_count),
    )
    return ImportBatchOut.model_validate(batch, from_attributes=True)


@router.get("/batches", response_model=list[ImportBatchOut])
async def list_batches(
    kb_id: uuid.UUID,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    await _get_kb(session, kb_id)
    rows = await import_service.list_batches(kb_id, limit=min(max(limit, 1), 200))
    return [ImportBatchOut.model_validate(b, from_attributes=True) for b in rows]


@router.get("/batches/{batch_id}", response_model=ImportBatchOut)
async def get_batch(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    batch = await _get_batch(session, batch_id, kb_id)
    return ImportBatchOut.model_validate(batch, from_attributes=True)


@router.post("/batches/{batch_id}/files", status_code=202)
async def upload_batch_file(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    compile_now: bool = Form(False),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """向已创建批次追加一个文件（≤20MB）。"""
    kb = await _get_kb(session, kb_id)
    batch = await _get_batch(session, batch_id, kb_id)
    if batch.status != "running":
        raise HTTPException(409, "批次已结束，无法继续上传")
    content = await _read_limited(file, DIRECT_UPLOAD_LIMIT)
    filename = file.filename or "upload.bin"
    try:
        inspection = inspect_upload(content, filename, DIRECT_UPLOAD_LIMIT)
    except FileRejected as exc:
        raise _reject(exc)
    job_id, status = await import_service.submit_bytes(
        kb,
        batch.id,
        content=content,
        filename=filename,
        source_type=inspection.source_type,
        compile_now=compile_now,
        scan_status=inspection.scan_status,
        scan_detail=inspection.scan_detail,
    )
    await session.refresh(batch)
    return {
        "batch": ImportBatchOut.model_validate(batch, from_attributes=True).model_dump(),
        "job_id": str(job_id) if job_id else None,
        "status": status,
        "warnings": inspection.warnings,
    }


@router.post("/batches/{batch_id}/close", response_model=ImportBatchOut)
async def close_batch(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_batch(session, batch_id, kb_id)
    await import_service.mark_closed(batch_id)
    batch = await _get_batch(session, batch_id, kb_id)
    await session.refresh(batch)
    return ImportBatchOut.model_validate(batch, from_attributes=True)


@router.post("/batches/{batch_id}/cancel", response_model=ImportBatchOut)
async def cancel_batch(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    batch = await _get_batch(session, batch_id, kb_id)
    jobs = (
        (
            await session.execute(
                select(IngestJob).where(
                    IngestJob.import_batch_id == str(batch.id),
                    IngestJob.status.in_(("pending", "running")),
                )
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        await ingest_service.cancel_job(str(job.id))
    await import_service.mark_closed(batch.id, error="用户取消导入")
    await session.refresh(batch)
    return ImportBatchOut.model_validate(batch, from_attributes=True)


# --------------------------------------------------------------------------- #
# 分片上传（大文件 + 断点续传）
# --------------------------------------------------------------------------- #
@router.post("/uploads/init")
async def init_chunked_upload(
    data: ChunkInitRequest,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_kb(session, kb_id)
    try:
        item = upload_session.init_session(kb_id, data.filename, data.size, data.sha256)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    return item.public()


@router.get("/uploads/{upload_id}")
async def get_chunked_upload(upload_id: str):
    try:
        item = upload_session.load_session(upload_id)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    return item.public()


@router.put("/uploads/{upload_id}/chunks/{index}")
async def put_chunk(upload_id: str, index: int, request: Request):
    try:
        item = upload_session.load_session(upload_id)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    body = await request.body()
    try:
        return upload_session.write_chunk(item, index, body)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)


@router.post("/uploads/{upload_id}/complete", status_code=202)
async def complete_chunked_upload(
    upload_id: str,
    data: ChunkCompleteRequest,
    kb_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
):
    kb = await _get_kb(session, kb_id)
    try:
        item = upload_session.load_session(upload_id)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    if item.kb_id != str(kb_id):
        raise HTTPException(404, "上传会话不存在")
    try:
        content = upload_session.assemble(item)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    try:
        inspection = inspect_upload(content, item.filename)
    except FileRejected as exc:
        upload_session.abort_session(item)
        raise _reject(exc)

    created_batch = False
    if batch_id is not None:
        batch = await _get_batch(session, batch_id, kb_id)
        if batch.status != "running":
            raise HTTPException(409, "批次已结束，无法继续上传")
    else:
        batch = await import_service.create_batch(
            kb.id, provider="upload", label=item.filename, expected_count=1
        )
        created_batch = True

    job_id, status = await import_service.submit_bytes(
        kb,
        batch.id,
        content=content,
        filename=item.filename,
        source_type=inspection.source_type,
        title=data.title,
        compile_now=data.compile_now,
        scan_status=inspection.scan_status,
        scan_detail=inspection.scan_detail,
    )
    upload_session.abort_session(item)
    if created_batch:
        await import_service.mark_closed(batch.id)
    batch = await session.get(ImportBatch, batch.id)
    await session.refresh(batch)
    return {
        "batch": ImportBatchOut.model_validate(batch, from_attributes=True).model_dump(),
        "job_id": str(job_id) if job_id else None,
        "status": status,
        "warnings": inspection.warnings,
        "upload_id": upload_id,
    }


@router.delete("/uploads/{upload_id}", status_code=204)
async def abort_chunked_upload(upload_id: str):
    try:
        item = upload_session.load_session(upload_id)
    except upload_session.UploadError as exc:
        raise _upload_error(exc)
    upload_session.abort_session(item)


# --------------------------------------------------------------------------- #
# 语雀
# --------------------------------------------------------------------------- #
@router.post("/yuque/repos")
async def list_yuque_repos(data: YuqueReposRequest):
    """用令牌拉取可访问的知识库列表（个人 + 团队）。"""
    from app.services.yuque_importer import YuqueError, fetch_user_repos

    try:
        return await fetch_user_repos(data.token)
    except YuqueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/yuque/token", response_model=ImportBatchOut, status_code=202)
async def import_from_yuque_token(
    data: YuqueTokenRequest,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """令牌直连：后台串行拉取目录与正文，逐条入库。"""
    kb = await _get_kb(session, kb_id)
    if not data.token.strip():
        raise HTTPException(400, "请填写语雀访问令牌")
    await _validate_folder(session, kb_id, data.folder_id)
    batch = await import_service.start_yuque_token_import(
        kb,
        data.token.strip(),
        data.repo.strip(),
        compile_now=data.compile_now,
        folder_id=data.folder_id,
        create_notes=data.create_notes,
    )
    return ImportBatchOut.model_validate(batch, from_attributes=True)


@router.post("/yuque/zip", response_model=ImportBatchOut, status_code=202)
async def import_from_yuque_zip(
    kb_id: uuid.UUID,
    compile_now: bool = Form(False),
    folder_id: uuid.UUID | None = Form(None),
    create_notes: bool = Form(True),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """导出包兜底：解压 Markdown 并复用统一摄入流水线。"""
    kb = await _get_kb(session, kb_id)
    await _validate_folder(session, kb_id, folder_id)
    content = await _read_limited(file, 200 * 1024 * 1024)
    try:
        zf = inspect_archive(content, file.filename or "yuque.zip")
        zf.close()
    except FileRejected as exc:
        raise _reject(exc)
    batch = await import_service.start_yuque_zip_import(
        kb,
        content,
        file.filename or "yuque.zip",
        compile_now=compile_now,
        folder_id=folder_id,
        create_notes=create_notes,
    )
    return ImportBatchOut.model_validate(batch, from_attributes=True)


# --------------------------------------------------------------------------- #
# 任务 / 编译
# --------------------------------------------------------------------------- #
def _job_page_ids(job: IngestJob) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for raw in job.touched_page_ids or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    return ids


async def _jobs_out(session: AsyncSession, jobs: list[IngestJob]) -> list[IngestJobOut]:
    """补齐任务详情所需的素材标题、笔记标题与受影响 Wiki 页面。"""
    if not jobs:
        return []
    source_ids = {job.source_id for job in jobs}
    note_ids = {job.note_id for job in jobs if job.note_id}
    page_ids = {page_id for job in jobs for page_id in _job_page_ids(job)}

    sources = {
        item.id: item
        for item in (
            await session.execute(select(Source).where(Source.id.in_(source_ids)))
        ).scalars()
    }
    notes = {}
    if note_ids:
        notes = {
            item.id: item
            for item in (
                await session.execute(select(Note).where(Note.id.in_(note_ids)))
            ).scalars()
        }
    pages = {}
    if page_ids:
        pages = {
            item.id: item
            for item in (
                await session.execute(select(WikiPage).where(WikiPage.id.in_(page_ids)))
            ).scalars()
        }

    # 关联持久化队列任务：编译页可以就地取消 / 重试，不必跳到运维页。
    durable: dict[str, Job] = {}
    keys = [f"compile:{job.id}" for job in jobs] + [f"ingest:{job.id}" for job in jobs]
    for row in (
        await session.execute(select(Job).where(Job.idempotency_key.in_(keys)))
    ).scalars():
        if row.idempotency_key:
            durable[row.idempotency_key] = row

    out: list[IngestJobOut] = []
    for job in jobs:
        item = IngestJobOut.model_validate(job, from_attributes=True)
        linked = durable.get(f"compile:{job.id}") or durable.get(f"ingest:{job.id}")
        if linked is not None:
            item.durable_job_id = linked.id
        source = sources.get(job.source_id)
        if source is not None:
            item.source_title = source.title
            item.source_type = source.type
        if job.note_id is not None:
            note = notes.get(job.note_id)
            if note is not None:
                item.note_title = note.title
        item.touched_pages = [
            {
                "id": str(page.id),
                "title": page.title,
                "slug": page.slug,
                "page_type": page.page_type,
            }
            for page_id in _job_page_ids(job)
            if (page := pages.get(page_id)) is not None
        ]
        out.append(item)
    return out


@router.get("/jobs", response_model=list[IngestJobOut])
async def list_jobs(
    kb_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(IngestJob).where(IngestJob.kb_id == kb_id)
    if batch_id is not None:
        stmt = stmt.where(IngestJob.import_batch_id == str(batch_id))
    if kind:
        stmt = stmt.where(IngestJob.kind == kind)
    rows = list(
        (
            await session.execute(
                stmt.order_by(IngestJob.created_at.desc()).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return await _jobs_out(session, rows)


@router.get("/jobs/{job_id}", response_model=IngestJobOut, include_in_schema=False)
@router.get("/{job_id}", response_model=IngestJobOut)
async def get_job(
    job_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(IngestJob, job_id)
    if job is None or job.kb_id != kb_id:
        raise HTTPException(404, "任务不存在")
    return (await _jobs_out(session, [job]))[0]


@router.get("/{job_id}/events")
async def ingest_events(job_id: uuid.UUID):
    """SSE 进度事件流。事件：parse_progress/chunk_done/embed_progress/compile_start/
    compile_page/compile_done/done/error/keepalive。"""
    key = str(job_id)
    return StreamingResponse(
        hub.stream(key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{job_id}/cancel", status_code=204)
async def cancel_job(job_id: uuid.UUID):
    await ingest_service.cancel_job(str(job_id))


@router.post("/compile", response_model=dict, status_code=202)
async def trigger_compile(
    data: CompileRequest,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """触发对素材的（重）编译。source_ids 为空则全部未编译素材。"""
    from app.db.models import Source

    if data.source_ids:
        stmt = select(Source).where(Source.kb_id == kb_id, Source.id.in_(data.source_ids))
    else:
        # 笔记编译使用 /notes/compile-all 从笔记正文重新生成，不复用内部 Source。
        stmt = select(Source).where(
            Source.kb_id == kb_id, Source.status == "parsed", Source.type != "note"
        )
    sources = (await session.execute(stmt)).scalars().all()
    if not sources:
        raise HTTPException(400, "没有可编译的素材（需先导入并完成解析）")

    selected = list(sources[:20])
    jobs = []
    for src in selected:
        job = IngestJob(kb_id=kb_id, source_id=src.id, kind="compile", status="pending")
        session.add(job)
        await session.flush()

        async def _run(sid=src.id, jid=job.id):
            await ingest_service._process_ingest(
                str(jid), kb_id, sid, compile_now=True, embed_raw=False
            )

        ingest_service._running[str(job.id)] = asyncio.create_task(
            _run(), name=f"compile:{job.id}"
        )
        jobs.append({"job_id": str(job.id), "source_id": str(src.id)})
    await session.commit()
    return {
        "jobs": jobs,
        "count": len(jobs),
        "requested": len(sources),
        "skipped": max(0, len(sources) - len(selected)),
    }


@router.get("/sources/{source_id}/status", response_model=SourceOut)
async def source_status(
    source_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    from app.db.models import Source

    source = await session.get(Source, source_id)
    if source is None or source.kb_id != kb_id:
        raise HTTPException(404, "素材不存在")
    return SourceOut.model_validate(source, from_attributes=True)
