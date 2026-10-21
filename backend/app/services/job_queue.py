"""持久化任务队列：单进程 worker + PostgreSQL 行锁。

设计取舍：
- 任务状态全部落库，进程重启后 ``running`` 任务重新入队；
- ``SELECT … FOR UPDATE SKIP LOCKED`` 领取任务，为将来多进程留出空间；
- 幂等键由调用方提供（如 ``ingest:<job_id>``），重复提交返回已有任务；
- 失败按指数退避重试，可在任务页手动重试或取消。

本模块不导入任何业务路由；handler 在 ``job_handlers`` 中注册，并按需延迟导入。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import Job
from app.db.session import async_session_factory
from app.services.metrics import metrics

logger = logging.getLogger("kiwi.jobs")

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
HEARTBEAT_SECONDS = 20
IDLE_SLEEP_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 300

JobHandler = Callable[[Job, dict], Awaitable[dict | None]]
_handlers: dict[str, JobHandler] = {}
_running_tasks: dict[uuid.UUID, asyncio.Task] = {}
_worker_task: asyncio.Task | None = None
_stop_event = asyncio.Event()


class JobCancelled(Exception):
    """handler 主动检查到取消请求时可抛出。"""


class JobFailed(Exception):
    """handler 判定业务失败（需要重试或最终失败）。"""


def register_job(kind: str):
    def decorator(func: JobHandler) -> JobHandler:
        _handlers[kind] = func
        return func

    return decorator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


async def enqueue(
    kind: str,
    payload: dict | None = None,
    *,
    kb_id: uuid.UUID | None = None,
    ref_id: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
) -> Job:
    """创建任务；幂等键命中时直接返回已有任务。"""
    async with async_session_factory() as db:
        if idempotency_key:
            existing = (
                await db.execute(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        job = Job(
            kind=kind,
            status="pending",
            payload=_jsonable(payload or {}),
            result={},
            kb_id=kb_id,
            ref_id=ref_id,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts or settings.job_max_attempts,
            priority=priority,
            run_after=run_after or _now(),
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if not idempotency_key:
                raise
            existing = (
                await db.execute(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
            ).scalar_one()
            return existing
        await db.refresh(job)
        logger.info("任务入队 %s kind=%s id=%s", job.id, kind, idempotency_key or "-")
        return job


async def _claim_one() -> Job | None:
    async with async_session_factory() as db:
        now = _now()
        job = (
            await db.execute(
                select(Job)
                .where(Job.status == "pending", Job.run_after <= now)
                .order_by(Job.priority.asc(), Job.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        if job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = now
            job.message = "已取消"
            await db.commit()
            return None
        job.status = "running"
        job.attempts += 1
        job.started_at = now
        job.heartbeat_at = now
        job.worker_id = WORKER_ID
        job.error = None
        job.message = "执行中"
        await db.commit()
        await db.refresh(job)
        return job


async def _heartbeat(job_id: uuid.UUID, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            async with async_session_factory() as db:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "running")
                    .values(heartbeat_at=_now())
                )
                await db.commit()


async def _finish(
    job_id: uuid.UUID,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    message: str | None = None,
    retry_in: float | None = None,
) -> None:
    async with async_session_factory() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        # 取消优先：执行期间收到取消请求时，不再把任务标成成功。
        if job.cancel_requested and status != "cancelled":
            status = "cancelled"
            message = "已取消"
        job.status = status
        job.result = _jsonable(result or {})
        job.error = error
        job.message = message
        if status in ("succeeded", "failed", "cancelled"):
            job.finished_at = _now()
            job.progress = 1.0 if status == "succeeded" else job.progress
        elif status == "pending" and retry_in is not None:
            job.run_after = _now() + timedelta(seconds=max(1.0, retry_in))
        await db.commit()


async def _run_job(job_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        kind = job.kind
        attempts = job.attempts
        max_attempts = job.max_attempts
        payload = dict(job.payload or {})
    handler = _handlers.get(kind)
    if handler is None:
        await _finish(
            job_id,
            status="failed",
            error=f"未注册的任务类型：{kind}",
            message="handler 缺失",
        )
        metrics.inc("kiwi_jobs_total", {"kind": kind, "outcome": "failed"})
        return

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(job_id, stop), name=f"job-heartbeat:{job_id}")
    started = _now()
    try:
        result = await handler(job, payload)
        await _finish(job_id, status="succeeded", result=result or {}, message="完成")
        metrics.inc("kiwi_jobs_total", {"kind": kind, "outcome": "succeeded"})
    except asyncio.CancelledError:
        await _finish(job_id, status="cancelled", message="已取消")
        metrics.inc("kiwi_jobs_total", {"kind": kind, "outcome": "cancelled"})
        raise
    except (JobFailed, Exception) as exc:  # noqa: BLE001
        message = str(exc) or exc.__class__.__name__
        logger.exception("任务失败 %s kind=%s attempt=%s", job_id, kind, attempts)
        if attempts < max_attempts:
            backoff = min(MAX_BACKOFF_SECONDS, 10 * (2 ** max(0, attempts - 1)))
            await _finish(
                job_id,
                status="pending",
                error=message,
                message=f"第 {attempts} 次失败，{backoff}s 后重试",
                retry_in=backoff,
            )
            metrics.inc("kiwi_jobs_retry_total", {"kind": kind})
        else:
            await _finish(
                job_id,
                status="failed",
                error=message,
                message=f"已重试 {attempts} 次",
            )
            metrics.inc("kiwi_jobs_total", {"kind": kind, "outcome": "failed"})
    finally:
        stop.set()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        _running_tasks.pop(job_id, None)
        metrics.observe(
            "kiwi_job_duration_seconds",
            (_now() - started).total_seconds(),
            {"kind": kind},
        )
        # payload 只在本地日志里出现 id，不打印正文，避免敏感内容落日志。
        logger.info("任务结束 %s kind=%s", job_id, kind)


async def run_once() -> uuid.UUID | None:
    """测试 / 手动驱动：领取并执行一个任务。"""
    job = await _claim_one()
    if job is None:
        return None
    await _run_job(job.id)
    return job.id


async def _recover() -> None:
    """启动时把本进程遗留的 running 任务重新排队。"""
    async with async_session_factory() as db:
        rows = (
            await db.execute(select(Job).where(Job.status == "running"))
        ).scalars().all()
        for job in rows:
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.finished_at = _now()
                job.error = "进程重启，任务未完成且已达最大重试次数"
                job.message = "进程重启"
            else:
                job.status = "pending"
                job.run_after = _now()
                job.worker_id = None
                job.message = "进程重启，任务重新排队"
        await db.commit()
        if rows:
            logger.warning("恢复 %s 个未完成的后台任务", len(rows))


async def _worker_loop() -> None:
    await _recover()
    logger.info(
        "任务 worker 已启动 id=%s concurrency=%s", WORKER_ID, settings.job_concurrency
    )
    semaphore = asyncio.Semaphore(max(1, settings.job_concurrency))
    while not _stop_event.is_set():
        try:
            job = await _claim_one()
            if job is None:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue
            await semaphore.acquire()

            async def run_one(job_id: uuid.UUID) -> None:
                try:
                    await _run_job(job_id)
                finally:
                    semaphore.release()

            task = asyncio.create_task(run_one(job.id), name=f"job:{job.id}")
            _running_tasks[job.id] = task
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("任务 worker 异常")
            await asyncio.sleep(IDLE_SLEEP_SECONDS)
    for task in list(_running_tasks.values()):
        task.cancel()
    if _running_tasks:
        await asyncio.gather(*_running_tasks.values(), return_exceptions=True)


def start_worker() -> asyncio.Task | None:
    global _worker_task
    if not settings.job_worker_enabled:
        logger.info("KIWI_JOB_WORKER_ENABLED=false：任务 worker 未启动")
        return None
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    _stop_event.clear()
    _worker_task = asyncio.create_task(_worker_loop(), name="kiwi-job-worker")
    return _worker_task


async def stop_worker() -> None:
    global _worker_task
    _stop_event.set()
    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task
    _worker_task = None


async def cancel(job_id: uuid.UUID) -> Job | None:
    async with async_session_factory() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return None
        if job.status == "pending":
            job.status = "cancelled"
            job.cancel_requested = True
            job.finished_at = _now()
            job.message = "已取消"
        elif job.status == "running":
            job.cancel_requested = True
            job.message = "取消请求已提交"
        await db.commit()
        await db.refresh(job)
    task = _running_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
    return job


async def retry(job_id: uuid.UUID) -> Job | None:
    async with async_session_factory() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return None
        if job.status not in ("failed", "cancelled"):
            return job
        job.status = "pending"
        job.attempts = 0
        job.cancel_requested = False
        job.error = None
        job.message = "手动重试"
        job.result = {}
        job.run_after = _now()
        job.started_at = None
        job.finished_at = None
        await db.commit()
        await db.refresh(job)
        return job


async def counts() -> dict[str, int]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
        ).all()
    return {status: int(count) for status, count in rows}


__all__ = [
    "JobCancelled",
    "JobFailed",
    "cancel",
    "counts",
    "enqueue",
    "register_job",
    "retry",
    "run_once",
    "start_worker",
    "stop_worker",
]
