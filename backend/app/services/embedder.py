"""Embedding 服务：fastembed 懒加载 + 按知识库模型缓存。

首次使用某模型时下载 ONNX 模型（HF，可达时自动），可用 HF_ENDPOINT 换镜像。
每个知识库可配置独立 embedding 模型，因此按模型名维护多个实例。
用线程池执行嵌入，避免阻塞事件循环。
"""

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import settings

_executor = ThreadPoolExecutor(max_workers=2)
_embedders: dict[str, object] = {}
_embedder_lock = threading.Lock()


def _load_embedder(model: str):
    """懒加载指定模型的 fastembed TextEmbedding（线程安全）。"""
    with _embedder_lock:
        existing = _embedders.get(model)
        if existing is not None:
            return existing
        from fastembed import TextEmbedding

        # fastembed 0.9 的模型名可能是 "BAAI/bge-small-zh-v1.5"
        instance = TextEmbedding(model_name=model)
        _embedders[model] = instance
        return instance


async def embed_texts_async(texts: list[str], model: str | None = None) -> list[list[float]]:
    """async 入口：在专用线程执行 fastembed，返回向量列表。

    model 为空时使用系统默认模型；调用方传入 kb.embedding_model 即可按库隔离。
    """
    if not texts:
        return []
    target = model or settings.embed_model
    offload = functools.partial(_embed_texts_sync, texts, target)
    return await asyncio.get_running_loop().run_in_executor(_executor, offload)


def _embed_texts_sync(texts: list[str], model: str) -> list[list[float]]:
    emb = _load_embedder(model)
    return [list(map(float, v)) for v in emb.embed(texts)]


async def embed_one_async(text: str, model: str | None = None) -> list[float]:
    res = await embed_texts_async([text], model)
    return res[0] if res else []
