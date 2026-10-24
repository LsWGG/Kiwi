"""IngestJob 与持久化 Job 的状态对账。

编译页以 ``ingest_jobs`` 为主视图，真正的执行状态在 ``jobs``。历史版本在队列
最终失败时没有回写 ``ingest_jobs``，会留下永远「排队中」的记录；队列记录被
清理或进程重启后也可能出现同样的悬空状态。

这里在读取 / 提交编译前做一次有界对账：只修正 pending / running 且已有明确
终态的行。刚创建不久、可能还没完成入队的任务保持原样，避免与 enqueue 瞬间竞争。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestJob, Job

# 创建后这段时间内不做「队列缺失」判定：提交事务与入队之间存在短暂窗口。
RECONCILE_GRACE_SECONDS = 120


def _age_seconds(value: datetime, now: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (now - value).total_seconds()


async def reconcile_ingest_jobs(
    session: AsyncSession,
    kb_id: uuid.UUID,
    *,
    note_id: uuid.UUID | None = None,
    grace_seconds: int = RECONCILE_GRACE_SECONDS,
) -> int:
    """把悬空的 IngestJob 对齐到持久化队列的真实状态。

    只 flush，不 commit；调用方按自己的事务边界提交。返回修正的行数。
    """
    stmt = select(IngestJob).where(
        IngestJob.kb_id == kb_id,
        IngestJob.status.in_(("pending", "running")),
    )
    if note_id is not None:
        stmt = stmt.where(IngestJob.note_id == note_id)
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return 0

    keys = [f"compile:{row.id}" for row in rows] + [f"ingest:{row.id}" for row in rows]
    durable = {
        row.idempotency_key: row
        for row in (
            await session.execute(select(Job).where(Job.idempotency_key.in_(keys)))
        )
        .scalars()
        .all()
        if row.idempotency_key
    }

    now = datetime.now(timezone.utc)
    changed = 0
    for row in rows:
        job = durable.get(f"compile:{row.id}") or durable.get(f"ingest:{row.id}")
        if job is None:
            if _age_seconds(row.created_at, now) < grace_seconds:
                continue
            row.status = "failed"
            row.error = "未找到对应的后台任务，请重新提交编译"
            changed += 1
            continue
        if job.status == "failed":
            row.status = "failed"
            row.error = (job.error or job.message or "任务未完成")[:2000]
            changed += 1
        elif job.status == "cancelled":
            row.status = "failed"
            row.error = "任务已取消"
            changed += 1
        elif job.status == "succeeded":
            # handler 正常会写回 succeeded；这里兜底处理“队列成功但业务记录未落库”。
            row.status = "succeeded"
            row.progress = 1.0
            touched = (job.result or {}).get("touched_page_ids")
            if isinstance(touched, list) and touched:
                row.touched_page_ids = touched
            changed += 1
    if changed:
        await session.flush()
    return changed
