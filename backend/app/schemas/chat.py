"""检索 / 问答 schemas。"""

import uuid

from pydantic import BaseModel, Field


class SearchScope(BaseModel):
    """检索范围。"""

    kb_ids: list[uuid.UUID] = []  # 空 = 全局（所有库）
    scope: str = "kb"  # kb / multi / global


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    scope: SearchScope = SearchScope()
    top_k: int = Field(default=8, ge=1, le=50)
    intent: str | None = None  # wiki / raw / auto


class SearchHit(BaseModel):
    kb_id: uuid.UUID
    kb_name: str = ""
    collection: str  # wiki or raw
    payload: dict = {}
    score: float = 0.0
    rank: int = 0


class SearchResponse(BaseModel):
    hits: list[SearchHit] = []
    merged_by: str = "cosine"  # or "rrf"


class Citation(BaseModel):
    kb_id: uuid.UUID
    kb_name: str = ""
    collection: str
    title: str
    slug: str | None = None
    chunk_text: str = ""
    target_id: str = ""  # source/wiki id，供前端跳转


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
