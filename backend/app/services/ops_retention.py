"""运维数据保留：后台任务与审计日志仅保留最近 N 天。

已完成的任务与审计记录只用于排查近期问题，长期堆积会拖慢列表查询。
清理按 ``created_at`` 判断，且只删除已结束的任务，避免误删排队 / 运行中的任务。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.config import settings
from app.db.models import AuditLog, Job
from app.db.session import async_session_factory

logger = logging.getLogger("kiwi.retention")

# 每天检查数次即可；清理是幂等的。
CHECK_INTERVAL_SECONDS = 6 * 3600
FINISHED_JOB_STATUSES = ("succeeded", "failed", "cancelled")

_task: asyncio.Task | None = None


async def prune_ops_history(days: int | None = None) -> dict[str, int]:
    """删除 ``days`` 天前的已结束任务与审计日志；返回删除条数。"""
    days = settings.ops_retention_days if days is None else days
    if days <= 0:
        return {"jobs": 0, "audit_logs": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session_factory() as db:
        jobs = await db.execute(
            delete(Job).where(
                Job.created_at < cutoff,
                Job.status.in_(FINISHED_JOB_STATUSES),
            )
        )
        audit_logs = await db.execute(
            delete(AuditLog).where(AuditLog.created_at < cutoff)
        )
        await db.commit()

    result = {
        "jobs": jobs.rowcount or 0,
        "audit_logs": audit_logs.rowcount or 0,
    }
    if result["jobs"] or result["audit_logs"]:
        logger.info("清理 %s 天前的运维数据：%s", days, result)
    return result


async def _loop() -> None:
    while True:
        try:
            await prune_ops_history()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("清理过期运维数据失败")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_retention_task() -> asyncio.Task | None:
    global _task
    if settings.ops_retention_days <= 0:
        logger.info("KIWI_OPS_RETENTION_DAYS<=0：不自动清理后台任务与审计日志")
        return None
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(_loop(), name="kiwi-ops-retention")
    return _task


async def stop_retention_task(task: asyncio.Task | None) -> None:
    global _task
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _task = None
