"""问答会话 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatSessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    message_count: int = 0
    scope: dict = {}
    intent: str = "auto"
    llm_config_id: uuid.UUID | None = None
    last_message_at: datetime | None = None
    updated_at: datetime


class ChatSessionOut(ChatSessionSummary):
    messages: list[dict] = []


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    scope: dict = {}
    intent: str = Field(default="auto", max_length=20)
    llm_config_id: uuid.UUID | None = None
    messages: list[dict] = []


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    messages: list[dict] | None = None
    scope: dict | None = None
    intent: str | None = Field(default=None, max_length=20)
    llm_config_id: uuid.UUID | None = None
    clear_llm_config: bool = False


class ChatSessionList(BaseModel):
    items: list[ChatSessionSummary] = []
