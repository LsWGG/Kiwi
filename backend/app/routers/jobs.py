"""持久化任务查询、取消与重试。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Job
from app.db.session import get_session
from app.schemas.job import JobListOut, JobOut
from app.services import job_queue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobListOut)
async def list_jobs(
    kb_id: uuid.UUID | None = None,
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    conditions = []
    if kb_id is not None:
        conditions.append(Job.kb_id == kb_id)
    if status:
        conditions.append(Job.status == status)
    if kind:
        conditions.append(Job.kind == kind)
    total = (
        await session.execute(select(func.count(Job.id)).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            select(Job)
            .where(*conditions)
            .order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return JobListOut(
        items=[JobOut.model_validate(row) for row in rows],
        total=total,
        retention_days=settings.ops_retention_days,
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return JobOut.model_validate(job)


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, "只有失败或已取消的任务可以重试")
    updated = await job_queue.retry(job_id)
    return JobOut.model_validate(updated)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(409, "任务已结束，无法取消")
    updated = await job_queue.cancel(job_id)
    return JobOut.model_validate(updated)
