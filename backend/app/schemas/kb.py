"""知识库 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    description: str = ""
    embedding_model: str | None = None
    llm_config_id: uuid.UUID | None = None
    learning_enabled: bool = True


class KBUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    embedding_model: str | None = None
    llm_config_id: uuid.UUID | None = None
    pinned: bool | None = None
    learning_enabled: bool | None = None


class KBOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    embedding_model: str
    llm_config_id: uuid.UUID | None
    pinned: bool = False
    learning_enabled: bool = True
    is_builtin: bool = False
    builtin_key: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BuiltinKbStatus(BaseModel):
    """内置演示库状态：不存在时前端提供重新创建入口。"""

    key: str
    name: str
    exists: bool
    deleted: bool
    kb_id: uuid.UUID | None = None


class KBOverview(KBOut):
    """知识库概览：附加计数、学习画像状态与最近活动。"""

    source_count: int = 0
    wiki_count: int = 0
    note_count: int = 0
    # 学习画像（只读聚合，来源学习模式）
    onboarded: bool = False
    goal_type: str | None = None
    attempted_topics: int = 0
    mastered_topics: int = 0
    mastery_coverage: float = 0.0
    due_reviews: int = 0
    # 最近活动（笔记 / Wiki / 素材中最新的时间）
    last_activity_at: datetime | None = None
