"""任务 handler 注册表。

业务模块只负责创建 ``IngestJob`` 并入队 ``Job``；真正的执行逻辑在这里
按需延迟导入，避免 ``routers.notes`` ↔ ``services`` 的循环依赖。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.db.models import IngestJob, Job
from app.db.session import async_session_factory
from app.services.job_queue import JobFailed, register_job

logger = logging.getLogger("kiwi.jobs.handlers")


async def _fail_ingest_job(job_id: str, error: str) -> None:
    """把未完成的业务任务标记为失败，避免编译页永远显示「排队中」。"""
    try:
        row_id = uuid.UUID(job_id)
    except (TypeError, ValueError):
        return
    async with async_session_factory() as db:
        row = await db.get(IngestJob, row_id)
        if row is None or row.status not in ("pending", "running"):
            return
        row.status = "failed"
        row.error = error[:2000]
        await db.commit()


async def _load_ingest_job(job_id: str) -> tuple[IngestJob | None, str, str]:
    async with async_session_factory() as db:
        row = await db.get(IngestJob, uuid.UUID(job_id))
        if row is None:
            return None, "", ""
        return row, row.status, row.error or ""


@register_job("ingest")
async def run_ingest_job(job: Job, payload: dict) -> dict:
    """素材摄入 / 工作区导入 / 重新导入。"""
    from app.services import ingest_service

    ingest_job_id = str(payload["ingest_job_id"])
    mode = str(payload.get("mode") or "ingest")
    use_ocr = bool(payload.get("use_ocr"))
    try:
        if mode == "existing_source":
            await ingest_service._process_note_from_existing_source(
                ingest_job_id,
                uuid.UUID(str(payload["source_id"])),
                uuid.UUID(str(payload["note_id"])),
                use_ocr=use_ocr,
            )
        else:
            await ingest_service._process_ingest(
                ingest_job_id,
                uuid.UUID(str(payload["kb_id"])),
                uuid.UUID(str(payload["source_id"])),
                compile_now=bool(payload.get("compile_now")),
                note_id=(
                    uuid.UUID(str(payload["note_id"])) if payload.get("note_id") else None
                ),
                embed_raw=bool(payload.get("embed_raw", True)),
                use_ocr=use_ocr,
            )
    except Exception as exc:
        # 业务任务记录不能停在「排队中」；交由持久化队列决定是否重试。
        await _fail_ingest_job(ingest_job_id, str(exc) or exc.__class__.__name__)
        raise
    row, status, error = await _load_ingest_job(ingest_job_id)
    if row is None:
        raise JobFailed("摄入任务记录已不存在")
    if status != "succeeded":
        raise JobFailed(error or f"摄入未完成（{status}）")
    return {"ingest_job_id": ingest_job_id, "status": status}


@register_job("note_compile")
async def run_note_compile_job(job: Job, payload: dict) -> dict:
    """笔记 → Wiki 编译；复用已有向量时只编译不重复嵌入。"""
    from app.routers.notes_compile import _link_note_compiled_page
    from app.services import ingest_service

    ingest_job_id = str(payload["job_id"])
    kb_id = uuid.UUID(str(payload["kb_id"]))
    source_id = uuid.UUID(str(payload["source_id"]))
    note_id = uuid.UUID(str(payload["note_id"])) if payload.get("note_id") else None
    try:
        await ingest_service._process_ingest(
            ingest_job_id,
            kb_id,
            source_id,
            compile_now=True,
            note_id=None,
            embed_raw=not bool(payload.get("reused")),
        )
    except Exception as exc:
        await _fail_ingest_job(ingest_job_id, str(exc) or exc.__class__.__name__)
        raise
    row, status, error = await _load_ingest_job(ingest_job_id)
    if row is None:
        raise JobFailed("编译任务记录已不存在")
    if status != "succeeded":
        raise JobFailed(error or f"编译未完成（{status}）")
    if note_id is not None:
        try:
            await _link_note_compiled_page(note_id, kb_id, uuid.UUID(ingest_job_id))
        except Exception:  # noqa: BLE001
            logger.exception("笔记 %s 编译完成但关联 Wiki 页面失败", note_id)
    return {"ingest_job_id": ingest_job_id, "status": status}


@register_job("kb_import")
async def run_kb_import_job(job: Job, payload: dict) -> dict:
    """导入 ``.kiwizip`` 知识库包（大包异步执行）。"""
    from app.services import kb_transfer

    path = Path(str(payload["path"]))
    try:
        async with async_session_factory() as db:
            kb, stats = await kb_transfer.import_package(db, path)
        return {
            "kb_id": str(kb.id),
            "kb_name": kb.name,
            "stats": stats,
        }
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("清理知识库包临时文件失败：%s", path)


@register_job("backup")
async def run_backup_job(job: Job, payload: dict) -> dict:
    from app.services import backup_service

    info = await backup_service.create_backup(trigger="job")
    return info


__all__ = ["run_backup_job", "run_ingest_job", "run_kb_import_job", "run_note_compile_job"]
