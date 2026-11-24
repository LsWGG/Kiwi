"""运维接口：备份、构建信息与指标。"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.background import BackgroundTask

from app.build_info import info as build_info
from app.services import agent_trace, backup_service, job_queue
from app.services.metrics import metrics

logger = logging.getLogger("kiwi.maintenance")

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
metrics_router = APIRouter(tags=["maintenance"])


def _remove_temp(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("临时备份文件清理失败：%s", path)


@router.get("/agent-traces")
async def recent_agent_traces(
    limit: int = Query(20, ge=1, le=100),
):
    """最近若干轮 Agent 的耗时 / 工具 / 状态轨迹（含脱敏后的输入输出）。"""
    return {"items": agent_trace.recent(limit)}


@router.get("/agent-traces/{trace_id}")
async def agent_trace_detail(trace_id: str):
    """按 ID 取单条轨迹；会话页据此打开某一轮的流转详情。"""
    trace = agent_trace.get(trace_id)
    if trace is None:
        raise HTTPException(404, "该轮轨迹不存在或已被新的轨迹挤出内存")
    return trace


@router.get("/build-info")
async def get_build_info():
    return build_info()


@router.get("/backups")
async def list_backups():
    return {
        "enabled": backup_service.settings.backup_enabled,
        "directory": str(backup_service.backup_root()),
        "retention_days": backup_service.settings.backup_retention_days,
        "interval_hours": backup_service.settings.backup_interval_hours,
        "items": backup_service.list_backups(),
    }


@router.post("/backups", status_code=202)
async def trigger_backup(sync: bool = Query(False, description="同步执行（调试 / CLI 使用）")):
    if sync:
        try:
            return await backup_service.create_backup(trigger="manual")
        except backup_service.BackupError as e:
            raise HTTPException(400, str(e)) from e
    job = await job_queue.enqueue("backup", {"trigger": "manual"}, priority=200)
    return {"job_id": str(job.id), "status": job.status}


@router.get("/backups/{name}/download")
async def download_backup(name: str):
    """把一份快照打包下载；zip 临时文件在响应结束后删除。"""
    try:
        archive, filename = await backup_service.build_backup_zip(name)
    except backup_service.BackupNotFound as e:
        raise HTTPException(404, str(e)) from e
    except backup_service.BackupError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:
        logger.exception("打包备份失败：%s", name)
        raise HTTPException(500, "打包备份失败") from None
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_remove_temp, archive),
    )


@router.post("/backups/import", status_code=201)
async def import_backup(file: UploadFile = File(...)):
    """导入一份 zip 备份快照。

    只做校验与落盘，不覆盖当前数据库；真正的恢复仍由
    ``scripts/restore_backup.sh`` 在停机窗口执行。
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(400, "请选择 .zip 备份包")
    root = backup_service.backup_root()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".upload-{uuid.uuid4().hex[:8]}.zip"
    total = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > backup_service.MAX_IMPORT_BYTES:
                    raise HTTPException(413, "备份包超过 50 GB 上限")
                out.write(chunk)
        if total == 0:
            raise HTTPException(400, "备份包为空")
        return await backup_service.import_backup_zip(tmp)
    except backup_service.BackupError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        await file.close()
        _remove_temp(tmp)


async def _metrics_text() -> str:
    body = metrics.render()
    counts = await job_queue.counts()
    for status, count in sorted(counts.items()):
        body += f'kiwi_jobs_queue{{status="{status}"}} {count}\n'
    return body


@metrics_router.get("/metrics", response_class=PlainTextResponse)
@metrics_router.get("/api/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    return PlainTextResponse(
        await _metrics_text(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
