"""系统设置 schemas。"""

from pydantic import BaseModel, Field


class SystemSettingsOut(BaseModel):
    app_name: str
    app_description: str
    logo_url: str
    theme_color: str
    learn_theme_color: str
    learn_logo_url: str
    learn_description: str
    ocr_enabled: bool
    ocr_provider: str
    ocr_api_base: str
    ocr_api_model: str
    has_ocr_api_key: bool = False
    ocr_timeout: float
    ocr_language: str
    # 语音转写：provider = auto / local / feishu
    transcribe_provider: str = "auto"
    feishu_app_id: str = ""
    feishu_folder_token: str = ""
    feishu_redirect_uri: str = ""
    has_feishu_app_secret: bool = False
    has_feishu_user_token: bool = False
    has_feishu_refresh_token: bool = False
    source: str = "default"


class SystemSettingsUpdate(BaseModel):
    app_name: str | None = Field(default=None, min_length=1, max_length=100)
    app_description: str | None = Field(default=None, max_length=500)
    logo_url: str | None = Field(default=None, max_length=500)
    theme_color: str | None = Field(
        default=None, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    learn_theme_color: str | None = Field(
        default=None, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    learn_logo_url: str | None = Field(default=None, max_length=500)
    learn_description: str | None = Field(default=None, max_length=500)
    ocr_enabled: bool | None = None
    ocr_provider: str | None = Field(default=None, max_length=40)
    ocr_api_base: str | None = Field(default=None, max_length=500)
    ocr_api_model: str | None = Field(default=None, max_length=200)
    # None 保留已保存密钥；空字符串清除。
    ocr_api_key: str | None = None
    ocr_timeout: float | None = Field(default=None, ge=5, le=600)
    ocr_language: str | None = Field(default=None, max_length=40)
    transcribe_provider: str | None = Field(
        default=None, pattern="^(auto|local|feishu)$"
    )
    feishu_app_id: str | None = Field(default=None, max_length=100)
    # None 保留已保存密钥；空字符串清除。
    feishu_app_secret: str | None = None
    feishu_user_token: str | None = None
    feishu_refresh_token: str | None = None
    feishu_folder_token: str | None = Field(default=None, max_length=200)
    feishu_redirect_uri: str | None = Field(default=None, max_length=500)


class OcrTestIn(BaseModel):
    api_base: str | None = Field(default=None, max_length=500)
    api_model: str | None = Field(default=None, max_length=200)
    api_key: str | None = None
    timeout: float | None = Field(default=None, ge=5, le=600)
    language: str | None = Field(default=None, max_length=40)


class OcrTestOut(BaseModel):
    ok: bool
    message: str
    sample_text: str = ""


class LogoUploadOut(BaseModel):
    url: str
