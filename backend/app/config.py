"""Kiwi 应用配置：从 .env / 环境变量加载。"""

from functools import lru_cache
from pathlib import Path

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
    redis_url: str = "redis://localhost:6379/0"

    # --- 安全 ---
    fernet_key: str = "change_me_change_me_change_me_change_me_"
    secret_key: str = "change_me"

    # --- 嵌入 ---
    embed_model: str = "BAAI/bge-small-zh-v1.5"
    embed_dim: int = 512

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
