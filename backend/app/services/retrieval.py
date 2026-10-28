"""检索与融合：向量召回 + BM25 词法召回 → RRF → 可选重排。

边界安全：kb 过滤在 qdrant 检索边界内强制注入；标签 / 类型 / 时间等
只存在于 PostgreSQL 的筛选条件，先解析成允许的 note_id 集合，再下推到
Qdrant 过滤，避免「先召回后过滤」导致结果被截断。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase, Note, NoteTagLink
from app.services import qdrant_store
from app.services import rerank as rerank_service
from app.services.embedder import embed_one_async, embedding_space, is_disabled
from app.services.lexical import bm25_scores, title_boost, tokenize


@dataclass(slots=True)
class RetrievalFilters:
    """问答 / 检索的附加筛选条件。"""

    note_ids: list[uuid.UUID] = field(default_factory=list)
    note_kinds: list[str] = field(default_factory=list)
    tag_ids: list[uuid.UUID] = field(default_factory=list)
    updated_from: datetime | None = None
    updated_to: datetime | None = None

    @property
    def has_note_constraints(self) -> bool:
        return bool(
            self.note_ids
            or self.note_kinds
            or self.tag_ids
            or self.updated_from
            or self.updated_to
        )


def _hit_key(hit: dict) -> str:
    key = str(hit.get("id") or "")
    if key:
        return key
    payload = hit.get("payload") or {}
    anchor = payload.get("page_id") or payload.get("note_id") or ""
    return f"{hit.get('kb_id', '')}:{anchor}:{payload.get('chunk_index', '')}"


def _rrf(
    ranked_lists: list[list[dict]],
    k: int = 60,
    limit: int = 10,
    weights: list[float] | None = None,
) -> list[dict]:
    """加权 Reciprocal Rank Fusion。

    入参是每路召回的 [hit]；同一 Qdrant point 在向量与词法两路中 id 相同，
    因此天然去重。``weights`` 用于压低词法召回在最终名次中的权重。
    """
    scores: dict[str, dict] = {}
    for list_index, lst in enumerate(ranked_lists):
        weight = weights[list_index] if weights and list_index < len(weights) else 1.0
        for rank, hit in enumerate(lst):
            key = _hit_key(hit)
            if key not in scores:
                scores[key] = {**hit, "_rrf": 0.0, "_ranks": []}
            scores[key]["_rrf"] += weight / (k + rank + 1)
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
        key = _hit_key(h)
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


async def resolve_note_ids(
    db: AsyncSession, kb_ids: list[uuid.UUID], filters: RetrievalFilters
) -> list[str] | None:
    """把标签 / 类型 / 时间 / 指定笔记解析成允许检索的 note_id。

    返回 ``None`` 表示没有笔记级约束；返回空列表表示约束下没有任何笔记。
    """
    if not filters.has_note_constraints:
        return None
    stmt = select(Note.id).where(
        Note.kb_id.in_(kb_ids),
        Note.status == "active",
        Note.lock_hash.is_(None),
    )
    if filters.note_ids:
        stmt = stmt.where(Note.id.in_(filters.note_ids))
    if filters.note_kinds:
        stmt = stmt.where(Note.kind.in_(filters.note_kinds))
    if filters.updated_from:
        stmt = stmt.where(Note.updated_at >= filters.updated_from)
    if filters.updated_to:
        stmt = stmt.where(Note.updated_at <= filters.updated_to)
    if filters.tag_ids:
        tag_ids = list(dict.fromkeys(filters.tag_ids))
        sub = (
            select(NoteTagLink.note_id)
            .where(NoteTagLink.tag_id.in_(tag_ids))
            .group_by(NoteTagLink.note_id)
            .having(func.count(func.distinct(NoteTagLink.tag_id)) == len(tag_ids))
        )
        stmt = stmt.where(Note.id.in_(sub))
    return [str(row) for row in (await db.execute(stmt)).scalars().all()]


def _lexical_text(payload: dict) -> str:
    return "\n".join(
        str(payload.get(key) or "")
        for key in ("title", "heading", "text", "body_head", "slug")
    ).strip()


async def _lexical_hits(
    query: str,
    kb_ids: list[uuid.UUID],
    collection: str,
    models: dict[uuid.UUID, str],
    limit: int,
    allowed_note_ids: list[str] | None,
    filters: RetrievalFilters,
) -> list[dict]:
    """从 Qdrant payload 读取分块并计算 BM25。

    Qdrant 的全文索引对中文分词支持有限，这里直接读取 payload 在应用层
    打分：个人知识库规模下开销可接受，且能保证与向量命中共享 point id，
    从而让 RRF 准确合并同一分块。
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    groups: dict[str, list[uuid.UUID]] = {}
    for kb_id in kb_ids:
        model = models.get(kb_id, settings.embed_model)
        if collection.startswith("wiki"):
            name = qdrant_store.wiki_collection(model)
        elif collection.startswith("note"):
            name = qdrant_store.note_collection(model)
        else:
            name = qdrant_store.raw_collection(model)
        groups.setdefault(name, []).append(kb_id)

    candidates: list[dict] = []
    note_ids_param: list[uuid.UUID | str] | None = None
    if collection.startswith("note"):
        note_ids_param = allowed_note_ids
    for name, group_kb_ids in groups.items():
        points = qdrant_store.scroll_points(
            collection=name,
            kb_id=group_kb_ids,
            limit=settings.retrieval_lexical_limit,
            note_ids=note_ids_param,
            note_kinds=filters.note_kinds if collection.startswith("note") else None,
        )
        if not points:
            continue
        documents = [tokenize(_lexical_text(point["payload"])) for point in points]
        scores = bm25_scores(query_tokens, documents)
        for point, score in zip(points, scores, strict=True):
            payload = point["payload"]
            boosted = score + title_boost(str(payload.get("title") or ""), query_tokens)
            if boosted <= 0:
                continue
            candidates.append(
                {
                    "payload": payload,
                    "id": point["id"],
                    "kb_id": str(payload.get("kb_id") or group_kb_ids[0]),
                    "raw_score": round(boosted, 6),
                    "score": round(boosted, 6),
                }
            )
    candidates.sort(key=lambda hit: hit["raw_score"], reverse=True)
    # 多留一些候选，交给 RRF 与重排决定最终名次。
    return candidates[: max(limit * 4, 20)]


async def search(
    db: AsyncSession,
    query: str,
    kb_ids: list[uuid.UUID],
    limit: int = 10,
    collection: str = "raw",
    filters: RetrievalFilters | None = None,
) -> list[dict]:
    """跨库混合检索：向量召回 + BM25 → RRF → 可选重排。

    同模型库可直接比较余弦分数；不同模型库使用 RRF。词法召回始终按
    知识库各自的 collection 读取，最后与向量结果按 point id 融合。
    """
    filters = filters or RetrievalFilters()
    if not kb_ids or not query.strip():
        return []
    if is_disabled():
        # 无向量模型时没有任何语义召回；调用方应改用笔记全文搜索或提示配置模型。
        return []
    kind = _normalize_kind(collection)
    models = await _kb_models(db, kb_ids)
    allowed_note_ids = (
        await resolve_note_ids(db, kb_ids, filters) if kind == "note" else None
    )
    if kind == "note" and allowed_note_ids == []:
        return []

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
            note_ids=allowed_note_ids if kind == "note" else None,
            note_kinds=filters.note_kinds if kind == "note" else None,
        )
        for h in hits:
            h["kb_id"] = str(kb_id)
            h["raw_score"] = h["score"]
            h["id"] = h.get("id", f"{kb_id}-{len(per_kb_results)}")
        per_kb_results.append(hits)

    same_model = len({models.get(k, embedding_space()) for k in kb_ids}) <= 1
    if same_model:
        dense = _cosine_merge(per_kb_results, limit * 2)
    else:
        dense = _rrf(per_kb_results, limit=limit * 2)

    lexical: list[dict] = []
    if settings.retrieval_hybrid_enabled and kind in ("wiki", "note"):
        try:
            lexical = await _lexical_hits(
                query,
                kb_ids,
                collection,
                models,
                limit,
                allowed_note_ids,
                filters,
            )
        except Exception:  # noqa: BLE001 —— 词法召回失败时保留纯向量结果
            from logging import getLogger

            getLogger("kiwi.retrieval").warning(
                "BM25 词法召回失败，回退到向量检索", exc_info=True
            )

    if lexical:
        fused = _rrf(
            [dense, lexical],
            limit=limit * 2,
            weights=[settings.retrieval_dense_weight, settings.retrieval_lexical_weight],
        )
        for hit in fused:
            hit["merged_by"] = "hybrid_rrf"
    else:
        fused = dense
        for hit in fused:
            hit["merged_by"] = "rrf" if not same_model else "cosine"

    # RRF 分数只用于排序（数值很小），对外保留原始余弦 / BM25 分数，
    # 让「最低相关度」阈值与调试接口仍能按原有语义理解。
    for hit in fused:
        hit["fusion_score"] = hit.get("score", 0.0)
        if hit.get("raw_score") is not None:
            hit["score"] = round(float(hit["raw_score"]), 6)

    if rerank_service.enabled() and fused:
        return await rerank_service.rerank(query, fused, limit)
    return fused[:limit]


async def hybrid_search(
    db: AsyncSession,
    query: str,
    kb_ids: list[uuid.UUID],
    limit: int = 10,
    filters: RetrievalFilters | None = None,
) -> dict:
    """Wiki + 笔记双检索，返回结构化命中。

    带笔记级筛选（标签 / 类型 / 时间 / 指定笔记）时只查笔记：Wiki 没有
    这些属性，混入结果会让筛选显得无效。
    """
    filters = filters or RetrievalFilters()
    wiki_hits: list[dict] = []
    if not filters.has_note_constraints:
        wiki_hits = await search(db, query, kb_ids, limit=limit, collection="wiki")
    note_hits = await search(
        db, query, kb_ids, limit=limit, collection="note", filters=filters
    )
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
