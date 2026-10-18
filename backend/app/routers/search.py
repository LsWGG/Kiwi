"""检索路由（非流式，供调试/嵌入）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase
from app.db.session import get_session
from app.schemas.chat import SearchHit, SearchRequest, SearchResponse
from app.services.retrieval import search

router = APIRouter(prefix="/api/search", tags=["search"])


async def _resolve_kb_ids(
    session: AsyncSession, kb_ids: list[uuid.UUID], scope: str
) -> list[uuid.UUID]:
    """根据 scope 解析有效知识库 id 列表，强制边界。"""
    if kb_ids:
        return list(dict.fromkeys(kb_ids))
    if scope == "global":
        rows = (await session.execute(select(KnowledgeBase.id))).scalars().all()
        return list(rows)
    raise HTTPException(400, "未指定 kb_ids，且非 global scope")


@router.post("", response_model=SearchResponse)
async def do_search(data: SearchRequest, session: AsyncSession = Depends(get_session)):
    if not data.query.strip():
        raise HTTPException(422, "查询不能为空")
    kb_ids = await _resolve_kb_ids(session, data.scope.kb_ids, data.scope.scope)

    # Wiki + 笔记双 collection 检索 + 融合（笔记是素材整理后的最终形态）
    results = []
    for collection, weight in (("wiki", 1.0), ("note", 0.9)):
        hits = await search(session, data.query, kb_ids, limit=data.top_k, collection=collection)
        kb_info = {}
        for h in hits:
            kb_id = h.get("kb_id", "")
            if kb_id and kb_id not in kb_info:
                kb_row = await session.get(KnowledgeBase, uuid.UUID(kb_id))
                kb_info[kb_id] = kb_row.name if kb_row else ""
            results.append(
                SearchHit(
                    kb_id=uuid.UUID(kb_id) if kb_id else uuid.UUID(int=0),
                    kb_name=kb_info.get(kb_id, ""),
                    collection=collection,
                    payload=h["payload"],
                    score=h["score"] * weight,
                    rank=len(results) + 1,
                )
            )

    results.sort(key=lambda x: x.score, reverse=True)
    for i, r in enumerate(results):
        r.rank = i + 1
    return SearchResponse(hits=results[: data.top_k], merged_by="weighted")
