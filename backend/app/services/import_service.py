"""导入批次编排：统一提交、状态聚合、报告生成。

批次是导入的审计单元：文件上传、语雀令牌、语雀导出包都归入同一张
import_batches 表；素材与摄入任务通过 import_batch_id 关联。
后台 watcher 在批次关闭且任务全部结束后生成解析报告。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import ImportBatch, IngestJob, KnowledgeBase, Note, NoteFolder, Source
from app.db.session import async_session_factory
from app.services import ingest_service
from app.services.file_security import scan_bytes
from app.services.yuque_importer import (
    ImportItem,
    YuqueError,
    fetch_repo_documents,
    read_export_zip,
)

logger = logging.getLogger(__name__)

_TERMINAL = {"succeeded", "failed"}
_watchers: dict[str, asyncio.Task] = {}
FINALIZE_IDLE_SECONDS = 60
WATCH_LIMIT_SECONDS = 6 * 60 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


async def create_batch(
    kb_id: uuid.UUID,
    *,
    provider: str = "upload",
    label: str = "",
    expected_count: int = 0,
    closed: bool = False,
) -> ImportBatch:
    """创建批次并启动后台聚合器。"""
    async with async_session_factory() as db:
        batch = ImportBatch(
            kb_id=kb_id,
            provider=provider,
            status="running",
            total_sources=0,
            report_json={
                "label": label,
                "provider": provider,
                "expected_count": expected_count,
                "closed": closed,
                "items": [],
                "created_at": _iso(),
                "last_activity_at": _iso(),
            },
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
    _ensure_watcher(batch.id)
    return batch


async def get_batch(batch_id: uuid.UUID) -> ImportBatch | None:
    async with async_session_factory() as db:
        return await db.get(ImportBatch, batch_id)


async def list_batches(kb_id: uuid.UUID, limit: int = 50) -> list[ImportBatch]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(ImportBatch)
                .where(ImportBatch.kb_id == kb_id)
                .order_by(ImportBatch.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return list(rows.all())


async def record_item(
    batch_id: uuid.UUID,
    *,
    title: str,
    status: str = "submitted",
    source_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    error: str = "",
    warnings: list[str] | None = None,
    external_id: str = "",
    note_id: uuid.UUID | None = None,
) -> None:
    """登记一个 Import Item 的提交结果（submitted / skipped / failed）。"""
    async with async_session_factory() as db:
        batch = await db.get(ImportBatch, batch_id)
        if batch is None:
            return
        report = dict(batch.report_json or {})
        items = list(report.get("items") or [])
        items.append(
            {
                "title": title,
                "status": status,
                "source_id": str(source_id) if source_id else None,
                "job_id": str(job_id) if job_id else None,
                "note_id": str(note_id) if note_id else None,
                "error": error,
                "warnings": warnings or [],
                "external_id": external_id,
                "submitted_at": _iso(),
            }
        )
        report["items"] = items
        report["last_activity_at"] = _iso()
        batch.report_json = report
        batch.total_sources = len(items)
        if status == "skipped":
            batch.skipped_count += 1
        await db.commit()


async def mark_closed(batch_id: uuid.UUID, *, error: str = "") -> None:
    """声明批次不再接收新条目，触发收尾。"""
    async with async_session_factory() as db:
        batch = await db.get(ImportBatch, batch_id)
        if batch is None:
            return
        report = dict(batch.report_json or {})
        report["closed"] = True
        report["last_activity_at"] = _iso()
        batch.report_json = report
        if error:
            batch.error = error
        await db.commit()
    _ensure_watcher(batch_id)


def _ensure_watcher(batch_id: uuid.UUID) -> None:
    key = str(batch_id)
    task = _watchers.get(key)
    if task is not None and not task.done():
        return
    _watchers[key] = asyncio.create_task(_watch_batch(key), name=f"import-batch:{key}")


async def _watch_batch(batch_id: str) -> None:
    """等待批次内所有摄入任务结束，然后生成报告。"""
    bid = uuid.UUID(batch_id)
    started = asyncio.get_event_loop().time()
    try:
        while True:
            await asyncio.sleep(2)
            if asyncio.get_event_loop().time() - started > WATCH_LIMIT_SECONDS:
                await _finish_with_timeout(bid)
                return
            async with async_session_factory() as db:
                batch = await db.get(ImportBatch, bid)
                if batch is None or batch.status != "running":
                    return
                report = dict(batch.report_json or {})
                closed = bool(report.get("closed"))
                last_at = report.get("last_activity_at")
                try:
                    idle = (_now() - datetime.fromisoformat(last_at)).total_seconds()
                except (TypeError, ValueError):
                    idle = FINALIZE_IDLE_SECONDS + 1
                active = (
                    await db.execute(
                        select(func.count())
                        .select_from(IngestJob)
                        .where(
                            IngestJob.import_batch_id == batch_id,
                            IngestJob.status.in_(("pending", "running")),
                        )
                    )
                ).scalar_one()
                source_count = (
                    await db.execute(
                        select(func.count())
                        .select_from(Source)
                        .where(Source.import_batch_id == batch_id)
                    )
                ).scalar_one()
            if active:
                continue
            # 显式关闭；或已有素材、任务全部结束且静默足够久（兜底）
            if closed or (source_count > 0 and idle >= FINALIZE_IDLE_SECONDS):
                await finalize_batch(bid)
                return
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("import batch watcher %s failed", batch_id)
        await _finish_with_timeout(bid)
    finally:
        _watchers.pop(batch_id, None)


async def _finish_with_timeout(batch_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        batch = await db.get(ImportBatch, batch_id)
        if batch is None or batch.status != "running":
            return
        batch.status = "partial"
        batch.error = batch.error or "导入任务超时未完成"
        batch.finished_at = _now()
        await db.commit()


def _dist(counter: dict[str, int], key: str) -> dict[str, int]:
    counter[key] = counter.get(key, 0) + 1
    return counter


async def finalize_batch(batch_id: uuid.UUID) -> ImportBatch | None:
    """聚合素材 / 任务状态并生成导入报告。"""
    async with async_session_factory() as db:
        batch = await db.get(ImportBatch, batch_id)
        if batch is None:
            return None
        if batch.status != "running":
            return batch
        sources = list(
            (
                await db.execute(
                    select(Source).where(Source.import_batch_id == str(batch_id))
                )
            )
            .scalars()
            .all()
        )
        jobs = list(
            (
                await db.execute(
                    select(IngestJob).where(
                        IngestJob.import_batch_id == str(batch_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        if any(job.status not in _TERMINAL for job in jobs):
            return batch

        job_by_source = {job.source_id: job for job in jobs}
        report = dict(batch.report_json or {})
        submitted = list(report.get("items") or [])

        quality: dict[str, int] = {}
        types: dict[str, int] = {}
        scans: dict[str, int] = {}
        engines: dict[str, int] = {}
        warnings: list[dict] = []
        failures: list[dict] = []
        compiled = 0
        succeeded_ids: set[uuid.UUID] = set()

        for source in sources:
            job = job_by_source.get(source.id)
            if job is not None and job.status == "succeeded":
                succeeded_ids.add(source.id)
            quality = _dist(quality, source.parse_quality or "unknown")
            types = _dist(types, source.type or "unknown")
            scans = _dist(scans, source.scan_status or "unavailable")
            engines = _dist(engines, source.parse_engine or "native")
            if source.status == "compiled":
                compiled += 1
            src_warnings = (source.quality_report or {}).get("warnings") or []
            if src_warnings:
                warnings.append({"title": source.title, "warnings": src_warnings})
            if source.status == "failed" or (
                job is not None and job.status == "failed"
            ):
                failures.append(
                    {
                        "title": source.title,
                        "error": (job.error if job and job.error else "解析失败"),
                    }
                )

        # 提交阶段就失败/跳过的条目（没有生成 Source）
        for item in submitted:
            if item.get("status") == "failed" and not item.get("source_id"):
                failures.append(
                    {"title": item.get("title") or "未命名文档", "error": item.get("error") or "提交失败"}
                )

        processed = len(succeeded_ids)
        failed = len({(f["title"], f["error"]) for f in failures})
        skipped = int(batch.skipped_count or 0)
        total = max(len(submitted), len(sources) + skipped)
        batch.total_sources = total
        batch.processed_count = processed
        batch.failed_count = failed

        now = _now()
        if total == 0:
            batch.status = "failed"
            batch.error = batch.error or "没有可导入的文档"
        elif failed and not processed:
            batch.status = "failed"
        elif failed:
            batch.status = "partial"
        else:
            batch.status = "completed"

        try:
            created_at = datetime.fromisoformat(report.get("created_at") or _iso(now))
        except (TypeError, ValueError):
            created_at = now
        report.update(
            {
                "closed": True,
                "generated_at": _iso(now),
                "duration_seconds": round((now - created_at).total_seconds(), 1),
                "summary": {
                    "total": total,
                    "processed": processed,
                    "failed": failed,
                    "skipped": skipped,
                    "compiled": compiled,
                },
                "quality": quality,
                "types": types,
                "scan": scans,
                "engines": engines,
                "warnings": warnings,
                "failures": failures,
                "sources": [
                    {
                        "id": str(s.id),
                        "title": s.title,
                        "type": s.type,
                        "status": s.status,
                        "parse_quality": s.parse_quality,
                        "parse_engine": s.parse_engine,
                        "scan_status": s.scan_status,
                        "source_url": s.source_url,
                        "external_id": s.external_id,
                        "chars": (s.quality_report or {}).get("chars", 0),
                        "warnings": (s.quality_report or {}).get("warnings") or [],
                    }
                    for s in sources
                ],
            }
        )
        # 保留提交条目的原始错误信息
        report["items"] = submitted
        batch.report_json = report
        batch.finished_at = now
        await db.commit()
        await db.refresh(batch)
    logger.info(
        "import batch %s finalized: %s (%s/%s)",
        batch_id,
        batch.status,
        batch.processed_count,
        batch.total_sources,
    )
    return batch


# --------------------------------------------------------------------------- #
# 统一提交入口
# --------------------------------------------------------------------------- #
async def submit_bytes(
    kb: KnowledgeBase,
    batch_id: uuid.UUID,
    *,
    content: bytes,
    filename: str,
    source_type: str,
    title: str | None = None,
    compile_now: bool = False,
    scan_status: str = "unavailable",
    scan_detail: str = "",
    external_id: str | None = None,
    source_url: str = "",
    content_updated_at=None,
    warnings: list[str] | None = None,
    note_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, str]:
    """提交单个文件；返回 (job_id, status/错误信息)。"""
    display_title = title or filename
    try:
        job_id = await ingest_service.run_ingest(
            content,
            filename,
            kb,
            compile_now=compile_now,
            note_id=note_id,
            external_id=external_id,
            source_url=source_url,
            content_updated_at=content_updated_at,
            batch_id=str(batch_id),
            scan_status=scan_status,
            scan_detail=scan_detail,
            source_type=source_type,
            title=title,
        )
    except FileExistsError as exc:
        await record_item(
            batch_id,
            title=display_title,
            status="skipped",
            error=str(exc),
            external_id=external_id or "",
            note_id=note_id,
        )
        return None, "skipped"
    except Exception as exc:  # noqa: BLE001
        logger.exception("submit import item failed: %s", filename)
        await record_item(
            batch_id,
            title=display_title,
            status="failed",
            error=str(exc),
            external_id=external_id or "",
            note_id=note_id,
        )
        return None, str(exc)

    async with async_session_factory() as db:
        from sqlalchemy import select

        job = (
            await db.execute(select(IngestJob).where(IngestJob.id == job_id))
        ).scalar_one()
        source_id = job.source_id
    await record_item(
        batch_id,
        title=display_title,
        status="submitted",
        source_id=source_id,
        job_id=job_id,
        warnings=warnings,
        external_id=external_id or "",
        note_id=note_id,
    )
    return job_id, "submitted"


async def _find_source_by_external(
    kb_id: uuid.UUID, external_id: str
) -> Source | None:
    async with async_session_factory() as db:
        return (
            await db.execute(
                select(Source).where(
                    Source.kb_id == kb_id, Source.external_id == external_id
                )
            )
        ).scalars().first()


async def _note_for_source(kb_id: uuid.UUID, source_id: uuid.UUID) -> Note | None:
    async with async_session_factory() as db:
        return (
            await db.execute(
                select(Note).where(
                    Note.kb_id == kb_id, Note.source_id == source_id
                )
            )
        ).scalars().first()


async def create_import_note(
    kb_id: uuid.UUID,
    *,
    title: str,
    folder_id: uuid.UUID | None,
    filename: str,
    source_id: uuid.UUID | None = None,
    external_id: str = "",
    source_url: str = "",
    scan_status: str = "",
    scan_detail: str = "",
    warnings: list[str] | None = None,
) -> uuid.UUID:
    """为语雀等来源创建可编辑的导入笔记。"""
    async with async_session_factory() as db:
        max_sort = (
            await db.execute(
                select(func.max(Note.sort_order)).where(
                    Note.kb_id == kb_id, Note.folder_id == folder_id
                )
            )
        ).scalar() or 0
        note = Note(
            kb_id=kb_id,
            title=(title or "未命名文档")[:300],
            kind="import",
            body_md="",
            folder_id=folder_id,
            status="active",
            view_mode="edit",
            sort_order=int(max_sort) + 1,
            source_id=source_id,
            props_json={
                "import": {
                    "status": "parsing",
                    "progress": 0.0,
                    "filename": filename,
                    "title_source": "auto",
                    "external_id": external_id,
                    "source_url": source_url,
                    "scan_status": scan_status,
                    "scan_detail": scan_detail,
                    "warnings": warnings or [],
                }
            },
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


async def _fail_note(note_id: uuid.UUID, message: str) -> None:
    async with async_session_factory() as db:
        note = await db.get(Note, note_id)
        if note is None:
            return
        props = dict(note.props_json or {})
        imp = dict(props.get("import") or {})
        imp.update({"status": "failed", "error": message})
        props["import"] = imp
        note.props_json = props
        await db.commit()


async def _ensure_folder_path(
    kb_id: uuid.UUID,
    root_folder_id: uuid.UUID | None,
    parts: tuple[str, ...],
    cache: dict[tuple[str, ...], uuid.UUID | None],
) -> uuid.UUID | None:
    """按语雀目录树路径找到/创建笔记分组，返回最深层 folder_id。"""
    normalized = tuple(part.strip()[:200] for part in parts if part.strip())
    if not normalized:
        return root_folder_id
    cache_key = (str(root_folder_id or ""), *normalized)
    if cache_key in cache:
        return cache[cache_key]
    parent = root_folder_id
    async with async_session_factory() as db:
        for name in normalized:
            stmt = select(NoteFolder).where(
                NoteFolder.kb_id == kb_id, NoteFolder.name == name
            )
            stmt = stmt.where(
                NoteFolder.parent_id.is_(None)
                if parent is None
                else NoteFolder.parent_id == parent
            )
            folder = (await db.execute(stmt)).scalars().first()
            if folder is None:
                max_sort = (
                    await db.execute(
                        select(func.max(NoteFolder.sort_order)).where(
                            NoteFolder.kb_id == kb_id,
                            NoteFolder.parent_id.is_(None)
                            if parent is None
                            else NoteFolder.parent_id == parent,
                        )
                    )
                ).scalar() or 0
                folder = NoteFolder(
                    kb_id=kb_id,
                    name=name,
                    parent_id=parent,
                    sort_order=int(max_sort) + 1,
                )
                db.add(folder)
                await db.flush()
            parent = folder.id
        await db.commit()
        cache[cache_key] = parent
        return parent


async def import_items(
    kb: KnowledgeBase,
    batch_id: uuid.UUID,
    items: list[ImportItem],
    *,
    compile_now: bool,
    folder_id: uuid.UUID | None = None,
    create_notes: bool = True,
) -> None:
    """提交一组语雀 Import Item；单条失败不中断整批。"""
    from hashlib import sha256

    folder_cache: dict[tuple[str, ...], uuid.UUID | None] = {}
    for item in items:
        content = item.as_bytes()
        item_folder_id = await _ensure_folder_path(
            kb.id, folder_id, item.folder_path, folder_cache
        )
        fingerprint = sha256(content).hexdigest()
        scan_status, scan_detail = scan_bytes(content)
        if scan_status in ("infected", "error"):
            note_id = None
            if create_notes:
                note_id = await create_import_note(
                    kb.id,
                    title=item.title,
                    folder_id=item_folder_id,
                    filename=item.filename(),
                    external_id=item.external_id,
                    source_url=item.source_url,
                    scan_status=scan_status,
                    scan_detail=scan_detail,
                    warnings=item.warnings,
                )
                await _fail_note(note_id, f"安全扫描未通过：{scan_detail}")
            await record_item(
                batch_id,
                title=item.title,
                status="failed",
                error=f"安全扫描未通过：{scan_detail}",
                external_id=item.external_id,
                note_id=note_id,
            )
            continue

        existing = await _find_source_by_external(kb.id, item.external_id)
        if (
            existing is not None
            and existing.sha256 == fingerprint
            and existing.status in ("parsed", "compiled")
        ):
            # 内容未变化：不重复解析，也不重复创建笔记
            await record_item(
                batch_id,
                title=item.title,
                status="skipped",
                error=f"外部文档内容未变化（{existing.title}），已跳过",
                external_id=item.external_id,
            )
            continue

        note_id: uuid.UUID | None = None
        if create_notes:
            reused = (
                await _note_for_source(kb.id, existing.id)
                if existing is not None
                else None
            )
            if reused is not None:
                note_id = reused.id
            else:
                note_id = await create_import_note(
                    kb.id,
                    title=item.title,
                    folder_id=item_folder_id,
                    filename=item.filename(),
                    source_id=existing.id if existing else None,
                    external_id=item.external_id,
                    source_url=item.source_url,
                    scan_status=scan_status,
                    scan_detail=scan_detail,
                    warnings=item.warnings,
                )

        job_id, status = await submit_bytes(
            kb,
            batch_id,
            content=content,
            filename=item.filename(),
            source_type="md",
            title=item.title,
            compile_now=compile_now,
            scan_status=scan_status,
            scan_detail=scan_detail,
            external_id=item.external_id,
            source_url=item.source_url,
            content_updated_at=item.content_updated_at,
            warnings=item.warnings,
            note_id=note_id,
        )
        if note_id is not None and status != "submitted":
            await _fail_note(note_id, status)


async def run_yuque_token_import(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    token: str,
    repo: str,
    *,
    compile_now: bool,
    folder_id: uuid.UUID | None = None,
    create_notes: bool = True,
) -> None:
    """后台拉取语雀文档并逐条入库。"""
    bid = uuid.UUID(str(batch_id))
    try:
        items, errors = await fetch_repo_documents(token, repo)
        async with async_session_factory() as db:
            batch = await db.get(ImportBatch, bid)
            if batch is None:
                return
            report = dict(batch.report_json or {})
            report["fetch_errors"] = errors
            report["last_activity_at"] = _iso()
            batch.report_json = report
            await db.commit()

        for message in errors:
            title, _, detail = message.partition("：")
            await record_item(
                bid,
                title=title or message,
                status="failed",
                error=detail or message,
            )
        if not items and not errors:
            await record_item(
                bid,
                title="语雀知识库",
                status="failed",
                error="知识库中没有文档",
            )

        async with async_session_factory() as db:
            kb = await db.get(KnowledgeBase, kb_id)
            if kb is None:
                return
            await import_items(
                kb,
                bid,
                items,
                compile_now=compile_now,
                folder_id=folder_id,
                create_notes=create_notes,
            )
        await mark_closed(bid)
    except YuqueError as exc:
        logger.warning("yuque import %s failed: %s", batch_id, exc)
        await mark_closed(bid, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("yuque import %s unexpected error", batch_id)
        await mark_closed(bid, error=f"语雀导入异常：{exc}")


async def start_yuque_token_import(
    kb: KnowledgeBase,
    token: str,
    repo: str,
    *,
    compile_now: bool,
    folder_id: uuid.UUID | None = None,
    create_notes: bool = True,
) -> ImportBatch:
    batch = await create_batch(
        kb.id, provider="yuque_token", label=f"语雀 · {repo}", expected_count=0
    )
    asyncio.create_task(
        run_yuque_token_import(
            batch.id,
            kb.id,
            token,
            repo,
            compile_now=compile_now,
            folder_id=folder_id,
            create_notes=create_notes,
        ),
        name=f"yuque-import:{batch.id}",
    )
    return batch


async def start_yuque_zip_import(
    kb: KnowledgeBase,
    content: bytes,
    filename: str,
    *,
    compile_now: bool,
    folder_id: uuid.UUID | None = None,
    create_notes: bool = True,
) -> ImportBatch:
    """解析导出包并入库（解析同步完成，摄入异步）。"""
    import io
    import zipfile

    batch = await create_batch(
        kb.id, provider="yuque_zip", label=f"语雀导出包 · {filename}"
    )
    from app.config import settings

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            items, errors = read_export_zip(
                zf, media_dir=Path(settings.media_dir), kb_id=str(kb.id)
            )
    except (zipfile.BadZipFile, OSError) as exc:
        await mark_closed(batch.id, error=f"导出包解析失败：{exc}")
        return await get_batch(batch.id) or batch

    for message in errors:
        title, _, detail = message.partition("：")
        await record_item(
            batch.id,
            title=title or message,
            status="failed",
            error=detail or message,
        )
    asyncio.create_task(
        _run_zip_items(batch.id, kb.id, items, compile_now, folder_id, create_notes),
        name=f"yuque-zip:{batch.id}",
    )
    return batch


async def _run_zip_items(
    batch_id: uuid.UUID,
    kb_id: uuid.UUID,
    items: list[ImportItem],
    compile_now: bool,
    folder_id: uuid.UUID | None = None,
    create_notes: bool = True,
) -> None:
    try:
        async with async_session_factory() as db:
            kb = await db.get(KnowledgeBase, kb_id)
            if kb is None:
                return
            await import_items(
                kb,
                batch_id,
                items,
                compile_now=compile_now,
                folder_id=folder_id,
                create_notes=create_notes,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("yuque zip import %s failed", batch_id)
        await mark_closed(batch_id, error=f"导出包导入异常：{exc}")
        return
    await mark_closed(batch_id)


async def cleanup_upload_session(upload_id: uuid.UUID) -> None:
    """删除分片上传的临时目录（保留在完成/中止时调用）。"""
    from app.config import settings

    root = Path(settings.upload_dir) / "chunks" / str(upload_id)
    if not root.exists():
        return
    for path in sorted(root.glob("**/*"), reverse=True):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
