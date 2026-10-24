"""后台任务 API schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    payload: dict
    result: dict
    error: str | None = None
    message: str | None = None
    kb_id: uuid.UUID | None = None
    ref_id: str | None = None
    idempotency_key: str | None = None
    priority: int
    attempts: int
    max_attempts: int
    progress: float
    cancel_requested: bool
    run_after: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    retention_days: int = 14
