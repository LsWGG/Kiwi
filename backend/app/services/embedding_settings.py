"""应用内向量模型配置：读取、落库与运行时生效。

配置存储在 ``embedding_config`` 单行表中；未写入时回退到 ``KIWI_EMBED_*``
环境变量。密钥使用与大模型配置相同的 Fernet 加密。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.embedding_config import EMBEDDING_CONFIG_ID, EmbeddingConfig
from app.services.embedder import (
    EmbeddingRuntimeConfig,
    configure_runtime,
    embedding_space,
    env_runtime_config,
)
from app.services.llm_factory import LLMCrypto

REMOTE_PROVIDERS = {"openai", "remote", "api"}


def normalize_provider(provider: str) -> str:
    """把 openai / remote / api 归一为 openai，其余为 local。"""
    return "openai" if provider.strip().lower() in REMOTE_PROVIDERS else "local"


def is_remote(provider: str) -> bool:
    return normalize_provider(provider) == "openai"


def runtime_from_row(row: EmbeddingConfig) -> EmbeddingRuntimeConfig:
    key = LLMCrypto.decrypt(row.encrypted_api_key) if row.encrypted_api_key else ""
    return EmbeddingRuntimeConfig(
        provider=row.provider,
        api_base=row.api_base,
        api_key=key,
        api_model=row.api_model,
        timeout=row.api_timeout,
        batch_size=row.api_batch_size,
        concurrency=row.api_concurrency,
    )


async def load_runtime(session: AsyncSession) -> EmbeddingConfig | None:
    """启动时加载应用内配置并注入 embedder；无配置则回退环境变量。"""
    row = await session.get(EmbeddingConfig, EMBEDDING_CONFIG_ID)
    if row is None:
        configure_runtime(None)
        return None
    configure_runtime(runtime_from_row(row))
    return row


def apply_row(row: EmbeddingConfig) -> None:
    configure_runtime(runtime_from_row(row))


def active_space() -> str:
    """当前进程实际使用的向量空间（远程模型或默认本地模型）。"""
    return embedding_space(None)


def space_for(provider: str, api_model: str) -> str:
    """按待保存配置计算向量空间，用于保存后的提示。"""
    if is_remote(provider):
        return f"remote:{api_model.strip()}"
    return settings.embed_model


def env_defaults() -> dict:
    env = env_runtime_config()
    return {
        "provider": normalize_provider(env.provider),
        "api_base": env.api_base,
        "api_model": env.api_model,
        "api_timeout": env.timeout,
        "api_batch_size": env.batch_size,
        "api_concurrency": env.concurrency,
        "has_api_key": bool(env.api_key),
    }
