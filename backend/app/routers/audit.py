"""审计日志查询与导出。"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AuditLog
from app.db.session import get_session
from app.schemas.audit import AuditLogOut, AuditPageOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _conditions(kb_id: uuid.UUID | None, action: str | None):
    conditions = []
    if kb_id is not None:
        conditions.append(AuditLog.kb_id == kb_id)
    if action:
        conditions.append(AuditLog.action == action)
    return conditions


@router.get("", response_model=AuditPageOut)
async def list_audit(
    kb_id: uuid.UUID | None = None,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    conditions = _conditions(kb_id, action)
    total = (
        await session.execute(select(func.count(AuditLog.id)).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return AuditPageOut(
        items=[AuditLogOut.model_validate(row) for row in rows],
        total=total,
        retention_days=settings.ops_retention_days,
    )


@router.get("/export.csv")
async def export_audit(
    kb_id: uuid.UUID | None = None,
    action: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(AuditLog)
            .where(*_conditions(kb_id, action))
            .order_by(AuditLog.created_at.desc())
            .limit(20000)
        )
    ).scalars().all()
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(
        ["时间", "动作", "知识库", "对象类型", "对象", "摘要", "操作者", "IP", "请求 ID"]
    )
    for row in rows:
        writer.writerow(
            [
                row.created_at.isoformat() if row.created_at else "",
                row.action,
                str(row.kb_id or ""),
                row.target_type,
                row.target_id or "",
                row.note,
                row.actor,
                row.ip or "",
                row.request_id or "",
            ]
        )
    filename = "kiwi-audit.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
