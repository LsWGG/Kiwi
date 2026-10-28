"""桌面模式设置与状态 schemas。"""

from pydantic import BaseModel, Field


class DesktopSettingsOut(BaseModel):
    version: int
    allow_online_models: bool
    acknowledged_online_models_at: str | None
    local_code_execution: bool
    acknowledged_local_code_at: str | None
    local_code_timeout_seconds: int
    updated_at: str | None


class DesktopSettingsUpdate(BaseModel):
    allow_online_models: bool | None = None
    local_code_execution: bool | None = None
    # 与 desktop_settings 的上下限保持一致。
    local_code_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    # false → true 时必须同时提交，表示用户已知悉数据离开本机 / 没有文件隔离。
    acknowledge_risk: bool = False


class DesktopEmbeddingOut(BaseModel):
    enabled: bool
    provider: str
    state: str


class DesktopLlmOut(BaseModel):
    configured: bool
    remote_allowed: bool


class DesktopLocalCodeOut(BaseModel):
    enabled: bool
    available: bool
    implementation: str


class DesktopCapabilitiesOut(BaseModel):
    online_models: bool
    link_fetch: bool
    remote_import: bool
    online_ocr: bool
    feishu: bool
    web_push: bool
    study_web_search: bool
    youtube_embed: bool
    external_images: bool
    local_code_execution: bool


class DesktopStatusOut(BaseModel):
    desktop: bool
    version: str
    data_dir: str
    log_dir: str
    embedding: DesktopEmbeddingOut
    llm: DesktopLlmOut
    local_code: DesktopLocalCodeOut
    capabilities: DesktopCapabilitiesOut
