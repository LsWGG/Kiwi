"""主题插件对外 schema：列表、当前主题与用户微调覆盖。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.plugin import ThemeSpecIn

# 旧版自定义背景以 data URL 随覆盖值存库；保留 3.5MB 上限兼容历史数据。
# 新上传走 /api/themes/background，文件落 /media/theme-backgrounds/，
# 覆盖值里只保存站内 URL。
MAX_BACKGROUND_CHARS = 3_500_000
MAX_BACKGROUND_URL_CHARS = 2000


class ThemeOverridesIn(BaseModel):
    """对当前主题的局部覆盖：背景、透明度与强调色。

    所有字段为空时表示完全跟随主题包默认值。背景图片支持旧版 data URL、
    http(s) 地址与站内 URL；背景视频只接受 http(s) 或站内 URL，避免把
    100MB 视频塞进数据库。
    """

    background_image: str = Field(default="", max_length=MAX_BACKGROUND_CHARS)
    background_video: str = Field(default="", max_length=MAX_BACKGROUND_URL_CHARS)
    background_size: Literal["cover", "contain", "auto"] | None = None
    background_position: str | None = Field(default=None, max_length=40)
    background_repeat: Literal["no-repeat", "repeat", "repeat-x", "repeat-y"] | None = None
    background_dim: float | None = Field(default=None, ge=0, le=0.9)
    background_blur: float | None = Field(default=None, ge=0, le=40)
    surface_opacity: float | None = Field(default=None, ge=0.35, le=1)
    surface_blur: float | None = Field(default=None, ge=0, le=40)
    # 编辑模式与学习模式各自独立保存强调色；为空表示跟随主题包。
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    learn_accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("background_image")
    @classmethod
    def _check_background(cls, value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        if not (
            text.startswith("data:image/")
            or text.startswith("https://")
            or text.startswith("http://")
            or text.startswith("/")
        ):
            raise ValueError("背景必须是图片 data URL、http(s) 地址或站内路径")
        return text

    @field_validator("background_video")
    @classmethod
    def _check_background_video(cls, value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        if not (
            text.startswith("https://")
            or text.startswith("http://")
            or text.startswith("/")
        ):
            raise ValueError("背景视频必须是 http(s) 地址或站内路径")
        if text.startswith("data:"):
            raise ValueError("背景视频请使用上传接口，不接受 data URL")
        return text


class ThemeOut(BaseModel):
    """主题画廊条目：内置主题与已安装主题共用。"""

    id: str
    key: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    icon: str = "palette"
    homepage: str = ""
    builtin: bool = False
    enabled: bool = True
    active: bool = False
    style_url: str = ""
    preview_url: str = ""
    # 主题内相对资源（背景图 / 字体）的解析前缀；内置主题指向 /api/themes/builtin/。
    asset_base_url: str = ""
    theme: ThemeSpecIn
    assets: list[str] = Field(default_factory=list)


class ThemeActiveOut(BaseModel):
    """启动 / 切换时下发给前端的完整主题。"""

    key: str
    name: str
    builtin: bool = False
    enabled: bool = True
    theme: ThemeSpecIn
    style_url: str = ""
    asset_base_url: str = ""
    overrides: ThemeOverridesIn = Field(default_factory=ThemeOverridesIn)


class ThemeActivateIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    # 不传表示沿用已保存的覆盖；传空对象表示清空覆盖。
    overrides: ThemeOverridesIn | None = None


class ThemeBackgroundOut(BaseModel):
    """自定义背景上传结果：站内 URL 与浏览器可直接使用的媒体类型。"""

    url: str
    kind: Literal["image", "video"]
    content_type: str
    size: int
