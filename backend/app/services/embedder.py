"""Embedding 服务：本地 fastembed 或远程 OpenAI 兼容接口。

默认在本地运行 fastembed（首次使用时下载 ONNX 模型，可通过 HF_ENDPOINT 换镜像）。
部署环境无法运行本地模型时，可在「设置 → 向量模型」中切换到线上接口，
也可以用环境变量兜底：

    KIWI_EMBED_PROVIDER=openai
    KIWI_EMBED_API_BASE=https://api.openai.com/v1
    KIWI_EMBED_API_KEY=sk-...
    KIWI_EMBED_API_MODEL=text-embedding-3-small

应用内配置由 ``configure_runtime()`` 注入，优先于环境变量；未保存应用内配置时
使用环境变量。远程模式下所有知识库共享同一向量空间，``embedding_model`` 参数
会被忽略；Qdrant collection 名通过 ``embedding_space()`` 与本地模型隔离，
避免维度冲突。
"""

import asyncio
import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from app.config import settings

_executor = ThreadPoolExecutor(max_workers=2)
_embedders: dict[str, object] = {}
_embedder_lock = threading.Lock()

_REMOTE_RETRY_STATUS = {429, 500, 502, 503, 504}
_REMOTE_MAX_ATTEMPTS = 3
_REMOTE_PROVIDERS = {"openai", "remote", "api"}


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """当前生效的向量化配置。"""

    provider: str
    api_base: str
    api_key: str
    api_model: str
    timeout: float
    batch_size: int
    concurrency: int


def env_runtime_config() -> EmbeddingRuntimeConfig:
    """环境变量中的兜底配置。"""
    return EmbeddingRuntimeConfig(
        provider=settings.embed_provider,
        api_base=settings.embed_api_base,
        api_key=settings.embed_api_key,
        api_model=settings.embed_api_model,
        timeout=settings.embed_api_timeout,
        batch_size=settings.embed_api_batch_size,
        concurrency=settings.embed_api_concurrency,
    )


_runtime_override: EmbeddingRuntimeConfig | None = None


def configure_runtime(config: EmbeddingRuntimeConfig | None) -> None:
    """注入应用内配置；传 None 表示回退到环境变量。"""
    global _runtime_override
    _runtime_override = config


def runtime_config() -> EmbeddingRuntimeConfig:
    """当前生效配置：应用内配置优先，否则环境变量。"""
    return _runtime_override or env_runtime_config()


def is_remote_provider() -> bool:
    """是否使用远程 embedding 接口。"""
    return runtime_config().provider.strip().lower() in _REMOTE_PROVIDERS


def embedding_space(model: str | None = None) -> str:
    """向量空间标识：用于 Qdrant collection 命名与同空间判断。

    远程模式下只取决于线上模型名，与知识库本地模型配置无关；
    本地模式沿用原有模型名。
    """
    if is_remote_provider():
        return f"remote:{runtime_config().api_model.strip()}"
    return model or settings.embed_model


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
    """返回文本向量。

    - ``provider=local``（默认）：在线程池运行 fastembed。
    - ``provider=openai``：调用 OpenAI 兼容的 ``/embeddings`` 接口。

    model 为空时使用系统默认模型；远程模式下该参数被忽略。
    """
    if not texts:
        return []
    if is_remote_provider():
        return await _embed_texts_remote(texts)
    target = model or settings.embed_model
    offload = functools.partial(_embed_texts_sync, texts, target)
    return await asyncio.get_running_loop().run_in_executor(_executor, offload)


def _embed_texts_sync(texts: list[str], model: str) -> list[list[float]]:
    emb = _load_embedder(model)
    return [list(map(float, v)) for v in emb.embed(texts)]


async def embed_one_async(text: str, model: str | None = None) -> list[float]:
    res = await embed_texts_async([text], model)
    return res[0] if res else []


def _remote_endpoint(config: EmbeddingRuntimeConfig | None = None) -> str:
    cfg = config or runtime_config()
    base = cfg.api_base.strip().rstrip("/")
    if not base:
        raise RuntimeError("已启用远程嵌入，但未配置接口地址（API Base）")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def _remote_headers(config: EmbeddingRuntimeConfig | None = None) -> dict[str, str]:
    cfg = config or runtime_config()
    headers = {"Content-Type": "application/json"}
    key = cfg.api_key.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def _request_embeddings(
    client: httpx.AsyncClient,
    url: str,
    batch: list[str],
    config: EmbeddingRuntimeConfig | None = None,
) -> list[list[float]]:
    """请求单个批次，失败时对 429/5xx 做有限重试。"""
    cfg = config or runtime_config()
    model = cfg.api_model.strip()
    if not model:
        raise RuntimeError("已启用远程嵌入，但未配置模型名")
    payload = {"model": model, "input": batch}
    last_error = ""
    for attempt in range(_REMOTE_MAX_ATTEMPTS):
        try:
            resp = await client.post(url, json=payload, headers=_remote_headers(cfg))
            if resp.status_code in _REMOTE_RETRY_STATUS and attempt + 1 < _REMOTE_MAX_ATTEMPTS:
                await asyncio.sleep(0.8 * (2**attempt))
                continue
            if resp.status_code >= 400:
                detail = resp.text[:300].replace("\n", " ")
                raise RuntimeError(
                    f"嵌入接口返回 {resp.status_code}：{detail or resp.reason_phrase}"
                )
            data = resp.json()
            items = data.get("data")
            if not isinstance(items, list) or len(items) != len(batch):
                raise RuntimeError(
                    f"嵌入接口返回数量异常：期望 {len(batch)} 条，实际 {len(items or [])} 条"
                )
            # 部分兼容实现不返回 index，此时保持响应顺序。
            if all(isinstance(item, dict) and "index" in item for item in items):
                items = sorted(items, key=lambda item: int(item["index"]))
            vectors: list[list[float]] = []
            for item in items:
                vector = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("嵌入接口返回了空向量")
                vectors.append([float(v) for v in vector])
            return vectors
        except httpx.HTTPError as exc:
            last_error = str(exc)
            if attempt + 1 >= _REMOTE_MAX_ATTEMPTS:
                break
            await asyncio.sleep(0.8 * (2**attempt))
    raise RuntimeError(f"无法连接嵌入接口 {url}：{last_error or '未知网络错误'}")


async def _embed_texts_remote(
    texts: list[str], config: EmbeddingRuntimeConfig | None = None
) -> list[list[float]]:
    """调用线上 OpenAI 兼容 embedding 接口，按批次并发请求。"""
    cfg = config or runtime_config()
    url = _remote_endpoint(cfg)
    batch_size = max(1, cfg.batch_size)
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    timeout = httpx.Timeout(max(5.0, cfg.timeout))
    semaphore = asyncio.Semaphore(max(1, cfg.concurrency))

    async def limited(batch: list[str]) -> list[list[float]]:
        async with semaphore:
            return await _request_embeddings(client, url, batch, cfg)

    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(*(limited(batch) for batch in batches))
    return [vector for batch_result in results for vector in batch_result]


async def test_remote_connection(
    api_base: str,
    api_key: str,
    api_model: str,
    timeout: float = 60.0,
) -> tuple[int, float]:
    """用一条短文本验证线上接口，返回 (向量维度, 耗时毫秒)。"""
    cfg = EmbeddingRuntimeConfig(
        provider="openai",
        api_base=api_base,
        api_key=api_key,
        api_model=api_model,
        timeout=timeout,
        batch_size=1,
        concurrency=1,
    )
    url = _remote_endpoint(cfg)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(max(5.0, timeout))) as client:
        vectors = await _request_embeddings(client, url, ["Kiwi 向量接口连通性测试"], cfg)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not vectors:
        raise RuntimeError("嵌入接口未返回向量")
    return len(vectors[0]), round(elapsed_ms, 1)
