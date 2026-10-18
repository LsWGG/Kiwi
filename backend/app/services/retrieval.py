"""检索与融合：单库直比余弦 / 多库 RRF，意图路由。

边界安全：kb 过滤在 qdrant 检索边界内强制注入。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase
from app.services import qdrant_store
from app.services.embedder import embed_one_async, embedding_space


def _rrf(ranked_lists: list[list[dict]], k: int = 60, limit: int = 10) -> list[dict]:
    """Reciprocal Rank Fusion。入参是每库的 [hit]，hit 带 raw_score。"""
    scores: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst):
            key = hit.get("id", "")
            if key not in scores:
                scores[key] = {**hit, "_rrf": 0.0, "_ranks": []}
            scores[key]["_rrf"] += 1.0 / (k + rank + 1)
            scores[key]["_ranks"].append(rank)
    merged = sorted(scores.values(), key=lambda x: x["_rrf"], reverse=True)
    for i, h in enumerate(merged):
        h["score"] = round(h["_rrf"], 6)
        h["rank"] = i + 1
    return merged[:limit]


def _cosine_merge(ranked_lists: list[list[dict]], limit: int = 10) -> list[dict]:
    """同模型多库：直接合并按原始相似度排序。"""
    flat = [h for lst in ranked_lists for h in lst]
    flat.sort(key=lambda x: x.get("raw_score", 0.0), reverse=True)
    dedup: dict[str, dict] = {}
    for h in flat:
        key = h.get("id", "")
        if key not in dedup:
            dedup[key] = h
    result = list(dedup.values())[:limit]
    for i, h in enumerate(result):
        h["score"] = round(h.get("raw_score", 0.0), 6)
        h["rank"] = i + 1
    return result


async def _kb_models(
    db: AsyncSession, kb_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """知识库 id → embedding 模型名。"""
    rows = (
        await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.embedding_model).where(
                KnowledgeBase.id.in_(kb_ids)
            )
        )
    ).all()
    return {row[0]: embedding_space(row[1] or settings.embed_model) for row in rows}


def _normalize_kind(collection: str) -> str:
    """归一化 collection 类型：wiki / note / raw（raw 仅保留给素材检索）。"""
    if collection.startswith("wiki"):
        return "wiki"
    if collection.startswith("note"):
        return "note"
    return "raw"


async def search(
    db: AsyncSession,
    query: str,
    kb_ids: list[uuid.UUID],
    limit: int = 10,
    collection: str = "raw",
) -> list[dict]:
    """跨库检索。按各库 embedding 模型分别编码查询，再融合。

    同模型库可直接比较余弦分数；不同模型库使用 RRF（README §9.3）。
    """
    if not kb_ids or not query.strip():
        return []
    kind = _normalize_kind(collection)
    models = await _kb_models(db, kb_ids)
    vec_cache: dict[str, list[float]] = {}
    per_kb_results: list[list[dict]] = []
    for kb_id in kb_ids:
        model = models.get(kb_id, settings.embed_model)
        if model not in vec_cache:
            try:
                vec_cache[model] = await embed_one_async(query, model)
            except Exception:
                vec_cache[model] = []
        vector = vec_cache[model]
        if not vector:
            per_kb_results.append([])
            continue
        if kind == "wiki":
            name = qdrant_store.wiki_collection(model)
        elif kind == "note":
            name = qdrant_store.note_collection(model)
        else:
            name = qdrant_store.raw_collection(model)
        hits = qdrant_store.search(
            collection=name,
            vector=vector,
            kb_id=kb_id,
            limit=limit,
            # 向量检索总会返回 top-k，即使内容与问题无关；先按相似度过滤，
            # 避免问答把无关分块当作资料并展示成引用来源。
            score_threshold=(
                settings.retrieval_min_score if settings.retrieval_min_score > 0 else None
            ),
        )
        for h in hits:
            h["kb_id"] = str(kb_id)
            h["raw_score"] = h["score"]
            h["id"] = h.get("id", f"{kb_id}-{len(per_kb_results)}")
        per_kb_results.append(hits)

    same_model = len({models.get(k, embedding_space()) for k in kb_ids}) <= 1
    if same_model:
        return _cosine_merge(per_kb_results, limit)
    return _rrf(per_kb_results, limit)


async def hybrid_search(
    db: AsyncSession,
    query: str,
    kb_ids: list[uuid.UUID],
    limit: int = 10,
) -> dict:
    """Wiki + 笔记双检索，返回结构化命中。

    Returns: {
        wiki:  [...],   # 每条 {score, rank, payload, kb_id}
        notes: [...],
    }
    """
    wiki_hits = await search(db, query, kb_ids, limit=limit, collection="wiki")
    note_hits = await search(db, query, kb_ids, limit=limit, collection="note")
    return {"wiki": wiki_hits, "notes": note_hits}


# 兼容旧调用名。
hyrid_search = hybrid_search


def route_intent(query: str) -> str:
    """轻量意图路由：事实/出处类 → 笔记；概念/综合类 → wiki。

    笔记是素材整理后的最终形态，问答不再路由到 raw_chunks。
    """
    q = query.lower()
    wiki_markers = [
        "是什么",
        "什么是",
        "概念",
        "区别",
        "对比",
        "关系",
        "总结",
        "介绍",
        "why",
        "what",
        "how",
        "compare",
        "difference",
    ]
    note_markers = [
        "哪年",
        "数字",
        "版本",
        "条款",
        "第",
        "条",
        "原文",
        "原文说",
        "出处",
        "引用",
        "多少",
        "何时",
        "笔记",
        "记录",
        "quote",
        "citation",
        "number",
        "version",
    ]
    note_score = sum(1 for m in note_markers if m in q)
    wiki_score = sum(1 for m in wiki_markers if m in q)
    if note_score > wiki_score:
        return "note"
    if wiki_score >= note_score and wiki_score > 0:
        return "wiki"
    return "wiki"  # 默认 wiki 优先（设计文档 "Wiki 优先"）
