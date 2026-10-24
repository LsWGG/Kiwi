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
    # 检索最低余弦相似度：低于该分数的命中视为与问题无关，不进入问答上下文
    # 与引用列表。设为 0 可关闭过滤。
    retrieval_min_score: float = 0.4
    # 混合检索：向量召回 + BM25 词法召回，再用 RRF 融合。
    retrieval_hybrid_enabled: bool = True
    # 单次词法召回最多读取的分块数；个人库通常远小于该值。
    retrieval_lexical_limit: int = 8000
    retrieval_dense_weight: float = 1.0
    retrieval_lexical_weight: float = 0.8

    # 重排模型（可选）：任意兼容 Cohere / Jina / Xinference 的
    # ``POST {base}/rerank`` 接口。留空表示不启用。
    rerank_api_base: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_timeout: float = 20.0
    rerank_top_n: int = 30

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

    # --- 语音转写（本地 faster-whisper）---
    whisper_enabled: bool = True
    # 模型随首次使用下载到 whisper_model_dir；small 在 CPU 上兼顾速度与中文准确率。
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # auto 表示按音频自动识别语言，也可固定为 zh / en 等。
    whisper_language: str = "auto"
    whisper_model_dir: Path = Path("data/models/whisper")

    # --- 提醒 ---
    # Web Push 的 VAPID 联系地址：浏览器推送服务要求 mailto: 或 https: 开头。
    push_contact: str = "mailto:admin@example.com"

    # --- 后端 ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # 本地实例直连远端数据库时关闭，避免向共享库 / 向量库写入巡检与调度数据。
    background_jobs: bool = True
    # 持久化任务 worker：独立于 background_jobs，关闭自动任务时仍可处理手动导入 / 编译。
    job_worker_enabled: bool = True
    job_concurrency: int = 2
    job_max_attempts: int = 3

    # --- 访问控制（单用户本地应用默认关闭）---
    # 设置后，/api 与 /media 需要 X-Access-Token、Authorization: Bearer
    # 或登录后写入的同名 Cookie。留空表示不启用。
    access_token: str = ""
    access_cookie_name: str = "kiwi_access"
    # 对外分享链接的站点前缀（如 https://share.example.com）。
    # 留空时前端使用当前访问地址；通过 Cloudflare Tunnel 等公网入口
    # 分享时应设置为公开域名，避免在内网创建出 192.168.x.x 链接。
    public_base_url: str = ""
    rate_limit_enabled: bool = True
    rate_limit_llm_per_minute: int = 20
    rate_limit_import_per_minute: int = 10
    rate_limit_code_per_minute: int = 30

    # --- 备份 ---
    backup_enabled: bool = True
    backup_interval_hours: float = 24.0
    backup_retention_days: int = 14
    backup_dir: Path = Path("data/backups")

    # --- 运维数据保留 ---
    # 后台任务与审计日志仅保留最近 N 天；0 表示不自动清理。
    ops_retention_days: int = 14

    # --- 构建信息 ---
    build_commit: str = ""
    build_time: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
