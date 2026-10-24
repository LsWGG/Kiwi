"""Web Push 提醒的请求 / 响应模型。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=16, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: PushKeys
    user_agent: str = Field(default="", max_length=300)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


class PushSettingsIn(BaseModel):
    enabled: bool | None = None
    reminder_hour: int | None = Field(default=None, ge=0, le=23)
    weekly_report: bool | None = None


class PushDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint: str
    user_agent: str
    created_at: datetime
    last_success_at: datetime | None
    failure_count: int


class PushStatusOut(BaseModel):
    enabled: bool
    reminder_hour: int
    weekly_report: bool
    public_key: str
    contact: str
    subscriptions: list[PushDeviceOut]
    last_daily_date: date | None
    last_weekly_date: date | None


class PushResultOut(BaseModel):
    sent: int
    failed: int
    removed: int = 0
