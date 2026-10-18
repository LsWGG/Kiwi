"""大模型配置 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LLMConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = "openai-compatible"
    base_url: str = Field(min_length=1, max_length=300)
    model_name: str = ""
    api_key: str | None = None  # 明文入站，后端加密存储，绝不回读
    is_default: bool = False
    extra_params: dict = {}


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None  # 提供则替换，不提供则保留原值
    is_default: bool | None = None
    extra_params: dict | None = None


class LLMConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    model_name: str
    has_api_key: bool
    is_default: bool
    extra_params: dict
    created_at: datetime
    updated_at: datetime


class ModelInfo(BaseModel):
    id: str
    owned_by: str = ""


class TestConnRequest(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str | None = None
    model_name: str = Field(min_length=1)


class TestConnResult(BaseModel):
    ok: bool
    message: str = ""
    error_type: str | None = None  # invalid_key / rate_limited / not_found / timeout / unknown


class ModelsListRequest(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str | None = None
    config_id: uuid.UUID | None = None  # 传入则复用已存密钥


class LlmResolveRequest(BaseModel):
    """级联解析：页面级 > 知识库 > 全局。"""

    kb_id: uuid.UUID | None = None
    temp_llm_config_id: uuid.UUID | None = None
