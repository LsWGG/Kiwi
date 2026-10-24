"""运维数据保留：只清理终态的旧任务与过期审计日志。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.models import AuditLog, Job
from app.db.session import async_session_factory
from app.services.ops_retention import prune_ops_history

KIND = "pytest_retention"
ACTION = "pytest.retention"


def _time(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _cleanup() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Job).where(Job.kind == KIND))
        await db.execute(delete(AuditLog).where(AuditLog.action == ACTION))
        await db.commit()


async def _add_job(status: str, days_ago: int) -> Job:
    job = Job(
        kind=KIND,
        status=status,
        payload={},
        result={},
        idempotency_key=f"pytest-retention:{uuid.uuid4().hex}",
        created_at=_time(days_ago),
    )
    async with async_session_factory() as db:
        db.add(job)
        await db.commit()
    return job


async def _add_audit(days_ago: int) -> AuditLog:
    entry = AuditLog(
        action=ACTION,
        target_type="pytest",
        detail={},
        note="retention test",
        created_at=_time(days_ago),
    )
    async with async_session_factory() as db:
        db.add(entry)
        await db.commit()
    return entry


async def _exists(model, row_id: uuid.UUID) -> bool:
    async with async_session_factory() as db:
        return (await db.get(model, row_id)) is not None


async def test_prune_removes_only_old_finished_records():
    old_jobs = {
        status: await _add_job(status, 20)
        for status in ("succeeded", "failed", "cancelled")
    }
    running = await _add_job("running", 20)
    pending = await _add_job("pending", 20)
    recent = await _add_job("succeeded", 2)
    old_audit = await _add_audit(20)
    recent_audit = await _add_audit(2)
    try:
        result = await prune_ops_history(days=14)

        assert result["jobs"] >= len(old_jobs)
        assert result["audit_logs"] >= 1
        for job in old_jobs.values():
            assert not await _exists(Job, job.id)
        assert await _exists(Job, running.id)
        assert await _exists(Job, pending.id)
        assert await _exists(Job, recent.id)
        assert not await _exists(AuditLog, old_audit.id)
        assert await _exists(AuditLog, recent_audit.id)
    finally:
        await _cleanup()


async def test_prune_disabled_when_days_not_positive():
    job = await _add_job("succeeded", 30)
    entry = await _add_audit(30)
    try:
        assert await prune_ops_history(days=0) == {"jobs": 0, "audit_logs": 0}
        assert await _exists(Job, job.id)
        assert await _exists(AuditLog, entry.id)
    finally:
        await _cleanup()
