"""ClawBot 渠道设置、计划预览与定时任务请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WeChatSettingsUpdate(BaseModel):
    enabled: bool | None = None
    # 支持多选知识库；default_kb_id 仅为旧客户端兼容。
    default_kb_ids: list[str] | None = None
    default_kb_id: str | None = None
    allow_write: bool | None = None


class WeChatScheduleCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    # cron 与自然语言二选一；time 为旧版 HH:MM 兼容字段。
    cron: str | None = Field(default=None, max_length=120)
    schedule_text: str | None = Field(default=None, max_length=200)
    time: str | None = Field(default=None, max_length=5)
    days: str = Field(default="daily", max_length=20)
    kb_ids: list[str] | None = None
    kb_id: str | None = None
    sender: str | None = None


class WeChatSchedulePreview(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class WeChatScheduleUpdate(BaseModel):
    enabled: bool


class WeChatTestPush(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


__all__ = [
    "WeChatScheduleCreate",
    "WeChatSchedulePreview",
    "WeChatScheduleUpdate",
    "WeChatSettingsUpdate",
    "WeChatTestPush",
]
