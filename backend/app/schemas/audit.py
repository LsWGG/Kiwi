"""审计日志 API schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID | None = None
    action: str
    target_type: str
    target_id: str | None = None
    detail: dict
    actor: str
    ip: str | None = None
    request_id: str | None = None
    note: str
    created_at: datetime


class AuditPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    retention_days: int = 14
