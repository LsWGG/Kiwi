"""Qdrant 封装：collection 准备、租户过滤、读写。

关键：kb_id 关键字索引必须用 KeywordIndexParams(is_tenant=True)，
过滤在检索边界内执行（不做"先召回后过滤"）。
"""

import hashlib
import threading
import uuid

from qdrant_client import QdrantClient, models

from app.config import settings

EMBED_DIM = settings.embed_dim
DEFAULT_EMBED_MODEL = settings.embed_model

# 默认模型沿用历史 collection 名，已有向量无需迁移；
# 其他模型按模型名哈希分 collection，避免不同向量空间/维度混写。
RAW_COLLECTION = "raw_chunks"
WIKI_COLLECTION = "wiki_pages"
_MODEL_PREFIX_RAW = "raw_chunks__"
_MODEL_PREFIX_WIKI = "wiki_pages__"

_ensured: set[str] = set()
_ensure_lock = threading.Lock()


def get_client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=30,
    )


def collection_names(model: str | None = None) -> tuple[str, str]:
    """(raw, wiki) collection 名；默认模型使用历史名称。"""
    model = model or DEFAULT_EMBED_MODEL
    if model == DEFAULT_EMBED_MODEL:
        return RAW_COLLECTION, WIKI_COLLECTION
    suffix = hashlib.sha1(model.encode("utf-8")).hexdigest()[:12]
    return f"{_MODEL_PREFIX_RAW}{suffix}", f"{_MODEL_PREFIX_WIKI}{suffix}"


def raw_collection(model: str | None = None) -> str:
    return collection_names(model)[0]


def wiki_collection(model: str | None = None) -> str:
    return collection_names(model)[1]


def _ensure_named(client: QdrantClient, name: str, dim: int) -> None:
    """幂等创建指定 collection + kb_id 租户索引。"""
    if name in _ensured:
        return
    with _ensure_lock:
        if name in _ensured:
            return
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                ),
            )
        schema = client.get_collection(name).payload_schema or {}
        if "kb_id" not in schema:
            client.create_payload_index(
                collection_name=name,
                field_name="kb_id",
                field_schema=models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD,
                    is_tenant=True,
                ),
            )
        _ensured.add(name)


def ensure_collections(client: QdrantClient | None = None) -> None:
    """幂等创建默认模型的两个 collection + kb_id 租户索引。"""
    client = client or get_client()
    for name in (RAW_COLLECTION, WIKI_COLLECTION):
        _ensure_named(client, name, EMBED_DIM)


def _kb_filter(kb_id: uuid.UUID | list[uuid.UUID]) -> models.Filter:
    """构造 kb_id 过滤条件。"""
    if isinstance(kb_id, list):
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="kb_id",
                    match=models.MatchAny(any=[str(k) for k in kb_id]),
                )
            ]
        )
    return models.Filter(
        must=[
            models.FieldCondition(
                key="kb_id",
                match=models.MatchValue(value=str(kb_id)),
            )
        ]
    )


def upsert_chunks(
    kb_id: uuid.UUID, points: list[dict], model: str | None = None
) -> None:
    """upsert raw chunks（写入该知识库 embedding 模型对应的 collection）。"""
    if not points:
        return
    client = get_client()
    name = raw_collection(model)
    _ensure_named(client, name, len(points[0]["vector"]))
    client.upsert(
        collection_name=name,
        points=[
            models.PointStruct(
                id=uuid.uuid4(),
                vector=p["vector"],
                payload={**p.get("payload", {}), "kb_id": str(kb_id)},
            )
            for p in points
        ],
    )


def upsert_wiki_pages(
    kb_id: uuid.UUID, points: list[dict], model: str | None = None
) -> None:
    """upsert wiki page 向量。"""
    if not points:
        return
    client = get_client()
    name = wiki_collection(model)
    _ensure_named(client, name, len(points[0]["vector"]))
    client.upsert(
        collection_name=name,
        points=[
            models.PointStruct(
                id=uuid.uuid4(),
                vector=p["vector"],
                payload={**p.get("payload", {}), "kb_id": str(kb_id)},
            )
            for p in points
        ],
    )


def search(
    collection: str,
    vector: list[float],
    kb_id: uuid.UUID | list[uuid.UUID],
    limit: int = 10,
    score_threshold: float | None = None,
) -> list[dict]:
    """检索，kb 过滤强制注入检索边界。返回 [{payload, score}]。"""
    client = get_client()
    if not vector:
        return []
    if not client.collection_exists(collection):
        return []
    res = client.query_points(
        collection_name=collection,
        query=models.NearestQuery(nearest=vector),
        query_filter=_kb_filter(kb_id),
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )
    return [
        {
            "payload": hit.payload or {},
            "score": float(hit.score),
            "id": str(hit.id),
        }
        for hit in res.points
    ]


def scroll_chunks(
    kb_id: uuid.UUID, limit: int = 40, model: str | None = None
) -> list[dict]:
    """按租户读取 raw chunk（用于尚未编译成 Wiki 的素材出题）。"""
    client = get_client()
    name = raw_collection(model)
    if not client.collection_exists(name):
        return []
    points, _ = client.scroll(
        collection_name=name,
        scroll_filter=_kb_filter(kb_id),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [p.payload or {} for p in points]


def delete_source_chunks(source_id: uuid.UUID, model: str | None = None) -> None:
    """删除某素材的 raw chunks（源内容更新时先清旧向量）。"""
    client = get_client()
    name = raw_collection(model)
    if not client.collection_exists(name):
        return
    client.delete(
        collection_name=name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_id", match=models.MatchValue(value=str(source_id))
                    )
                ]
            )
        ),
    )


def delete_wiki_page(
    kb_id: uuid.UUID, page_id: uuid.UUID | str, model: str | None = None
) -> None:
    """删除某 Wiki 页面的向量（按知识库的模型 collection）。"""
    client = get_client()
    name = wiki_collection(model)
    if not client.collection_exists(name):
        return
    client.delete(
        collection_name=name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="kb_id", match=models.MatchValue(value=str(kb_id))
                    ),
                    models.FieldCondition(
                        key="page_id", match=models.MatchValue(value=str(page_id))
                    ),
                ]
            )
        ),
    )


def count_collection(name: str) -> int:
    """统计 collection 内点数（探活用）。"""
    client = get_client()
    return client.count(collection_name=name).count


def list_vector_collections() -> list[str]:
    """全部 raw/wiki collection（含各 embedding 模型的分区）。"""
    client = get_client()
    names = [c.name for c in client.get_collections().collections]
    return [
        n
        for n in names
        if n == RAW_COLLECTION
        or n == WIKI_COLLECTION
        or n.startswith(_MODEL_PREFIX_RAW)
        or n.startswith(_MODEL_PREFIX_WIKI)
    ]


def purge_kb(kb_id: uuid.UUID) -> None:
    """删除某 kb 在全部模型 collection 中的向量。"""
    client = get_client()
    for col in list_vector_collections():
        client.delete(
            collection_name=col,
            points_selector=models.FilterSelector(filter=_kb_filter(kb_id)),
        )


def count_raw_points() -> int:
    """统计全部 raw collection 的点数（健康检查）。"""
    return sum(count_collection(name) for name in list_vector_collections() if "raw" in name)
