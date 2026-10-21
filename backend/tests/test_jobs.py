"""持久化任务队列：幂等、重试、重启恢复与取消。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.db.models import Job
from app.db.session import async_session_factory
from app.services import job_queue


async def _failing_handler(job, payload):
    raise RuntimeError("expected test failure")


job_queue.register_job("pytest_fail")(_failing_handler)


async def _load(job_id: uuid.UUID) -> Job:
    async with async_session_factory() as db:
        return await db.get(Job, job_id)


async def _cleanup(kind: str) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Job).where(Job.kind == kind))
        await db.commit()


async def test_enqueue_is_idempotent():
    key = f"pytest:{uuid.uuid4().hex}"
    first = await job_queue.enqueue("pytest_fail", {"value": 1}, idempotency_key=key)
    second = await job_queue.enqueue("pytest_fail", {"value": 2}, idempotency_key=key)
    try:
        assert first.id == second.id
        assert second.payload == {"value": 1}
    finally:
        await _cleanup("pytest_fail")


async def test_retry_then_final_failure():
    job = await job_queue.enqueue(
        "pytest_fail", {}, idempotency_key=f"pytest:{uuid.uuid4().hex}", max_attempts=2
    )
    try:
        await job_queue.run_once()
        row = await _load(job.id)
        assert row.status == "pending"
        assert row.attempts == 1
        assert "expected test failure" in (row.error or "")

        async with async_session_factory() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(run_after=datetime.now(timezone.utc))
            )
            await db.commit()

        await job_queue.run_once()
        row = await _load(job.id)
        assert row.status == "failed"
        assert row.attempts == 2
        assert "已重试 2 次" in (row.message or "")
    finally:
        await _cleanup("pytest_fail")


async def test_recovery_requeues_running_job():
    job = await job_queue.enqueue(
        "pytest_fail", {}, idempotency_key=f"pytest:{uuid.uuid4().hex}"
    )
    try:
        async with async_session_factory() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(status="running", attempts=1, worker_id="dead-worker")
            )
            await db.commit()
        await job_queue._recover()
        row = await _load(job.id)
        assert row.status == "pending"
        assert row.worker_id is None
    finally:
        await _cleanup("pytest_fail")


async def test_cancel_pending_job():
    job = await job_queue.enqueue(
        "pytest_fail", {}, idempotency_key=f"pytest:{uuid.uuid4().hex}"
    )
    try:
        await job_queue.cancel(job.id)
        row = await _load(job.id)
        assert row.status == "cancelled"
        assert row.cancel_requested is True
    finally:
        await _cleanup("pytest_fail")


async def test_pending_jobs_survive_new_session():
    """任务落库，而不是存在进程内列表里。"""
    job = await job_queue.enqueue(
        "pytest_fail", {"persisted": True}, idempotency_key=f"pytest:{uuid.uuid4().hex}"
    )
    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(Job).where(Job.id == job.id))
            ).scalar_one()
        assert row.status == "pending"
        assert row.payload == {"persisted": True}
    finally:
        await _cleanup("pytest_fail")
