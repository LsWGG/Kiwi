"""微信 ClawBot 渠道设置与定时任务请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WeChatSettingsUpdate(BaseModel):
    enabled: bool | None = None
    default_kb_id: str | None = None
    allow_write: bool | None = None
    allowed_users: list[str] | None = None


class WeChatScheduleCreate(BaseModel):
    time: str = Field(
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
        description="每天推送时间，HH:MM",
    )
    prompt: str = Field(min_length=1, max_length=2000)
    kb_id: str | None = None
    sender: str | None = None
    days: str = "daily"


class WeChatScheduleUpdate(BaseModel):
    enabled: bool


class WeChatTestPush(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


__all__ = [
    "WeChatScheduleCreate",
    "WeChatScheduleUpdate",
    "WeChatSettingsUpdate",
    "WeChatTestPush",
]
