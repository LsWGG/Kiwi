"""操作审计写入。

审计与业务写入共用同一个事务：业务失败回滚时不会留下“已执行”的假记录；
需要独立留痕的场景（如后台任务）使用 ``record_standalone``。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.db.session import async_session_factory
from app.observability import current_client_ip, current_request_id


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _build(
    action: str,
    *,
    kb_id: uuid.UUID | None,
    target_type: str,
    target_id: str | None,
    detail: dict | None,
    note: str,
    actor: str,
) -> AuditLog:
    return AuditLog(
        kb_id=kb_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=_jsonable(detail or {}),
        note=note,
        actor=actor,
        ip=current_client_ip() or None,
        request_id=current_request_id(),
    )


async def record(
    session: AsyncSession,
    action: str,
    *,
    kb_id: uuid.UUID | None = None,
    target_type: str = "",
    target_id: str | uuid.UUID | None = None,
    detail: dict | None = None,
    note: str = "",
    actor: str = "local",
) -> AuditLog:
    """在调用方事务内写入审计记录（不 commit）。"""
    entry = _build(
        action,
        kb_id=kb_id,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
        note=note,
        actor=actor,
    )
    session.add(entry)
    return entry


async def record_standalone(action: str, **kwargs) -> AuditLog:
    """后台任务 / 无请求上下文时使用，独立提交。"""
    async with async_session_factory() as db:
        entry = await record(db, action, **kwargs)
        await db.commit()
        await db.refresh(entry)
        return entry
