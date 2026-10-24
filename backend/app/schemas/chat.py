"""检索 / 问答 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchScope(BaseModel):
    """检索范围与内容筛选。"""

    kb_ids: list[uuid.UUID] = []  # 空 = 全局（所有库）
    scope: str = "kb"  # kb / multi / global
    # 笔记级筛选：带任一条件时只检索笔记（Wiki 没有标签 / 类型 / 时间属性）。
    note_kinds: list[str] = []
    tag_ids: list[uuid.UUID] = []
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    # 「问这篇笔记」：只在这些笔记范围内检索。
    note_ids: list[uuid.UUID] = []


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    scope: SearchScope = SearchScope()
    top_k: int = Field(default=8, ge=1, le=50)
    intent: str | None = None  # wiki / raw / auto


class SearchHit(BaseModel):
    kb_id: uuid.UUID
    kb_name: str = ""
    collection: str  # wiki / note / raw
    payload: dict = {}
    score: float = 0.0
    # RRF / 重排后的融合分数，用于跨 collection 排序；score 保留原始相似度。
    fusion_score: float = 0.0
    rank: int = 0


class SearchResponse(BaseModel):
    hits: list[SearchHit] = []
    merged_by: str = "hybrid_rrf"  # cosine / rrf / hybrid_rrf / rerank


class Citation(BaseModel):
    kb_id: uuid.UUID
    kb_name: str = ""
    collection: str  # wiki / note
    title: str
    slug: str | None = None
    chunk_text: str = ""
    target_id: str = ""  # wiki 页面 / 笔记 id，供前端跳转
    kind: str = ""  # 笔记类型（doc/database/canvas/...），Wiki 引用为空
    # 块级锚点：前端跳转后按 quote 精确高亮，heading 作为兜底定位。
    chunk_index: int = 0
    heading: str = ""
    quote: str = ""


class ChatRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)  # [{"role":"user","content":"..."}]
    scope: SearchScope = SearchScope()
    intent: str | None = None  # wiki / raw / auto
    llm_config_id: uuid.UUID | None = None  # 页面级临时指定
    model_override: str | None = Field(default=None, max_length=200)  # 仅本次请求
    stream: bool = True


class ChatEvent(BaseModel):
    type: str  # chunk / citation / done / error / keepalive
    payload: dict = {}
