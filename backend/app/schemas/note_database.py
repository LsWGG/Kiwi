"""数据表笔记 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatabaseOut(BaseModel):
    note_id: uuid.UUID
    name: str
    fields: list[dict]
    views: list[dict]


class DatabaseUpdate(BaseModel):
    name: str | None = None
    fields: list[dict] | None = None
    views: list[dict] | None = None


class RowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    # 每行对应的完整笔记（可打开编辑 / 参与链接与标签）
    note_id: uuid.UUID | None = None
    data: dict
    sort_order: int
    created_at: datetime
    updated_at: datetime


class RowCreate(BaseModel):
    data: dict = {}
    sort_order: int | None = None


class RowUpdate(BaseModel):
    data: dict | None = None
    sort_order: int | None = None


class RowBatchDeleteIn(BaseModel):
    row_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RowNotesCreate(BaseModel):
    """为选中的集合记录按需生成可编辑笔记。"""

    row_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RowNoteOut(BaseModel):
    row_id: uuid.UUID
    note_id: uuid.UUID
    title: str
    # False 表示该行此前已生成过笔记，本次直接复用
    created: bool


class CollectionContextOut(BaseModel):
    """笔记作为集合行时的属性上下文（右侧信息面板）。"""

    database_note_id: uuid.UUID
    database_title: str
    row_id: uuid.UUID
    fields: list[dict]
    data: dict
    title: str
