"""向量模型配置 schemas。API Key 只入站，绝不回读。"""

from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingConfigUpdate(BaseModel):
    provider: Literal["local", "openai", "remote", "api"] = "local"
    api_base: str = Field("", max_length=300)
    api_key: str | None = Field(None, max_length=500)  # None=保留现有/环境变量，空串=清除
    api_model: str = Field("", max_length=120)
    api_timeout: float = Field(60.0, ge=5.0, le=600.0)
    api_batch_size: int = Field(64, ge=1, le=512)
    api_concurrency: int = Field(4, ge=1, le=16)


class EmbeddingConfigOut(BaseModel):
    provider: str
    api_base: str
    api_model: str
    api_timeout: float
    api_batch_size: int
    api_concurrency: int
    has_api_key: bool
    source: Literal["saved", "env"]
    active_space: str
    env_provider: str
    env_api_base: str
    env_api_model: str
    env_has_api_key: bool


class EmbeddingTestRequest(BaseModel):
    provider: Literal["local", "openai", "remote", "api"] = "openai"
    api_base: str = Field("", max_length=300)
    api_key: str | None = Field(None, max_length=500)
    api_model: str = Field("", max_length=120)
    api_timeout: float = Field(60.0, ge=5.0, le=600.0)


class EmbeddingTestResult(BaseModel):
    ok: bool
    message: str = ""
    dimensions: int | None = None
    latency_ms: float | None = None
