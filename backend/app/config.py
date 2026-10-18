"""Kiwi 应用配置：从 .env / 环境变量加载。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    """全局配置。所有值可由 .env 或环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT.parent / ".env", env_prefix="KIWI_", extra="ignore"
    )

    # --- 存储 ---
    database_url: str = "postgresql+asyncpg://kiwi:kiwi@localhost:5432/kiwi"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # --- 安全 ---
    fernet_key: str = "change_me_change_me_change_me_change_me_"

    # --- 嵌入 ---
    # provider=local 使用 fastembed 本地模型；openai 调用 OpenAI 兼容的线上接口。
    embed_provider: Literal["local", "openai", "remote", "api"] = "local"
    embed_model: str = "BAAI/bge-small-zh-v1.5"
    embed_dim: int = 512
    # 线上接口：base 形如 https://api.openai.com/v1（也兼容 Ollama /v1）。
    embed_api_base: str = ""
    embed_api_key: str = ""
    embed_api_model: str = "text-embedding-3-small"
    embed_api_timeout: float = 60.0
    embed_api_batch_size: int = 64
    embed_api_concurrency: int = 4

    # --- LLM ---
    # 本地大模型（Ollama 等）冷启动与长文编译可能远超 60s，默认放宽到 10 分钟。
    llm_timeout: float = 600.0

    # --- 上传 ---
    upload_dir: Path = Path("data/uploads")

    # --- 学习模式联网核查（可选）---
    # 取值：disabled / duckduckgo / searxng / tavily
    study_search_provider: str = "disabled"
    study_search_base_url: str = "https://html.duckduckgo.com/html/"
    study_search_api_key: str = ""

    # --- 后端 ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
