"""可选的重排模型接入。

支持任意兼容 ``POST {base}/rerank`` 的服务（Jina / Cohere / Xinference 等）。
未配置或调用失败时原样返回融合结果：重排只改变名次，不能阻断检索。
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("kiwi.retrieval.rerank")


def _document(hit: dict) -> str:
    payload = hit.get("payload") or {}
    title = str(payload.get("title") or "")
    body = str(
        payload.get("text")
        or payload.get("body_head")
        or payload.get("chunk_text")
        or ""
    )
    return f"{title}\n{body}".strip()[:3000]


def enabled() -> bool:
    return bool(settings.rerank_api_base.strip())


async def rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
    """调用重排接口；无配置、无命中或失败时返回原始顺序。"""
    if not enabled() or not hits:
        return hits[:top_k]
    documents = [_document(hit) for hit in hits]
    headers = {"Content-Type": "application/json"}
    if settings.rerank_api_key:
        headers["Authorization"] = f"Bearer {settings.rerank_api_key}"
    payload = {
        "model": settings.rerank_model,
        "query": query,
        "documents": documents,
        "top_n": min(top_k, len(documents)),
    }
    url = settings.rerank_api_base.rstrip("/") + "/rerank"
    try:
        async with httpx.AsyncClient(timeout=settings.rerank_timeout) as client:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
    except Exception:  # noqa: BLE001 —— 重排不可用时降级为融合排序
        logger.warning("重排服务调用失败，回退到 RRF 排序", exc_info=True)
        return hits[:top_k]

    entries = data.get("results") or data.get("data") or []
    ranked: list[tuple[float, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(hits):
            continue
        raw_score = entry.get("relevance_score", entry.get("score", 0.0))
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        ranked.append((score, index))
    if not ranked:
        return hits[:top_k]

    ranked.sort(key=lambda item: item[0], reverse=True)
    out: list[dict] = []
    for rank, (score, index) in enumerate(ranked[:top_k]):
        hit = {**hits[index]}
        hit["fusion_score"] = hit.get("score", 0.0)
        hit["rerank_score"] = round(score, 6)
        hit["score"] = round(score, 6)
        hit["rank"] = rank + 1
        out.append(hit)
    return out
