"""运维接口：备份、构建信息与指标。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.build_info import info as build_info
from app.services import backup_service, job_queue
from app.services.metrics import metrics

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
metrics_router = APIRouter(tags=["maintenance"])


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
