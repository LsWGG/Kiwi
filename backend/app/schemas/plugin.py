"""插件 / 主题 manifest schemas。

插件支持两种形态：

- component：zip 内提供 manifest、入口 ESM 与可选样式；
- theme：zip 内提供 manifest、主题 JSON 与可选样式 / assets 资源。

历史模板插件记录仍可读取，但不再允许创建或导入。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLUGIN_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{1,63}$"
BLOCK_TYPE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
MANIFEST_VERSION = 1
MAX_BLOCKS = 50
MAX_BLOCK_TEMPLATE = 20_000
MAX_MANIFEST_CHARS = 300_000
MAX_DEFAULT_PROPS_CHARS = 20_000

# 主题色彩令牌：与前端 theme/apply.ts 的映射保持一致。省略的令牌由前端
# 内置默认值补齐，因此主题可以只覆盖自己关心的部分。
THEME_COLOR_KEYS = {
    "app.background",
    "surface.background",
    "surface.muted",
    "surface.strong",
    "border.subtle",
    "border.default",
    "border.strong",
    "text.primary",
    "text.strong",
    "text.secondary",
    "text.muted",
    "text.subtle",
    "text.faint",
    "accent",
    "accent.foreground",
}
MAX_THEME_TOKEN_CHARS = 120
MAX_THEME_FONT_CHARS = 160


def _validate_css_value(value: str, label: str) -> str:
    """主题令牌最终会写入 CSS 变量；拒绝能闭合声明 / 规则的字符。"""
    text = value.strip()
    if len(text) > MAX_THEME_TOKEN_CHARS:
        raise ValueError(f"{label}过长")
    if any(char in text for char in ";{}<>"):
        raise ValueError(f"{label}包含非法字符")
    return text


class ThemeBackgroundIn(BaseModel):
    """应用背景层：图片 / 纹理 + 暗化与模糊。"""

    # 主题包内 assets/ 下的相对路径，或 https:// / data: URL。
    image: str = Field(default="", max_length=400)
    size: Literal["cover", "contain", "auto"] = "cover"
    position: str = Field(default="center", max_length=40)
    repeat: Literal["no-repeat", "repeat", "repeat-x", "repeat-y"] = "no-repeat"
    dim: float = Field(default=0.0, ge=0, le=0.9)
    blur: float = Field(default=0.0, ge=0, le=40)

    @field_validator("position")
    @classmethod
    def _strip_position(cls, value: str) -> str:
        return _validate_css_value(value, "背景位置")


class ThemeSurfaceIn(BaseModel):
    """面板表面：透明度 + 毛玻璃 + 圆角。"""

    opacity: float = Field(default=1.0, ge=0.35, le=1.0)
    blur: float = Field(default=0.0, ge=0, le=40)
    radius: float | None = Field(default=None, ge=0, le=40)


class ThemeTypographyIn(BaseModel):
    """字体栈；主题包可通过 style.css 的 @font-face 提供字体文件。"""

    body: str = Field(default="", max_length=MAX_THEME_FONT_CHARS)
    heading: str = Field(default="", max_length=MAX_THEME_FONT_CHARS)
    mono: str = Field(default="", max_length=MAX_THEME_FONT_CHARS)

    @field_validator("body", "heading", "mono")
    @classmethod
    def _strip_font(cls, value: str) -> str:
        return _validate_css_value(value, "字体")


class ThemeSpecIn(BaseModel):
    """主题视觉规格：颜色令牌、背景、表面与字体。"""

    mode: Literal["light", "dark"] = "light"
    colors: dict[str, str] = Field(default_factory=dict)
    background: ThemeBackgroundIn = Field(default_factory=ThemeBackgroundIn)
    surface: ThemeSurfaceIn = Field(default_factory=ThemeSurfaceIn)
    typography: ThemeTypographyIn = Field(default_factory=ThemeTypographyIn)
    # 主题画廊缩略图：assets/ 下的相对路径（可选）。
    preview: str = Field(default="", max_length=400)

    @field_validator("colors")
    @classmethod
    def _validate_colors(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > len(THEME_COLOR_KEYS):
            raise ValueError("颜色令牌数量超出限制")
        normalized: dict[str, str] = {}
        for key, color in value.items():
            if key not in THEME_COLOR_KEYS:
                raise ValueError(f"未知颜色令牌：{key}")
            normalized[key] = _validate_css_value(str(color), f"颜色令牌 {key}")
        return normalized


def _normalize_asset_path(value: str, suffix: tuple[str, ...], label: str) -> str:
    text = value.strip().replace("\\", "/")
    if not text:
        return ""
    if len(text) > 200:
        raise ValueError(f"{label}路径过长")
    if "\x00" in text or text.startswith("/"):
        raise ValueError(f"{label}必须是压缩包内的相对路径")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"{label}不能包含上级目录")
    if not PurePosixPath(parts[-1]).name.lower().endswith(suffix):
        raise ValueError(f"{label}文件类型必须为 {' / '.join(suffix)}")
    return "/".join(parts)


class PluginBlockIn(BaseModel):
    type: str = Field(pattern=BLOCK_TYPE_PATTERN)
    label: str = Field(min_length=1, max_length=80)
    icon: str = Field(default="puzzle", max_length=40)
    description: str = Field(default="", max_length=300)
    category: str = Field(default="插件区块", max_length=40)
    # 历史模板字段：仅为兼容旧记录保留，组件插件不使用。
    template_markdown: str = Field(default="", max_length=MAX_BLOCK_TEMPLATE)
    # 插入时传给组件 / 节点属性的默认值。
    default_props: dict[str, Any] = Field(default_factory=dict)
    # 允许把区块置顶为跨路由浮窗（计时器等全局工具）。
    pinnable: bool = False

    @field_validator("type", "label", "icon", "description", "category")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("template_markdown")
    @classmethod
    def _trim_template(cls, value: str) -> str:
        return value.strip()

    @field_validator("default_props")
    @classmethod
    def _validate_default_props(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            size = len(json.dumps(value, ensure_ascii=False))
        except (TypeError, ValueError):
            raise ValueError("default_props 必须是可序列化的 JSON 对象") from None
        if size > MAX_DEFAULT_PROPS_CHARS:
            raise ValueError("default_props 体积超出限制")
        return value


class PluginManifestIn(BaseModel):
    manifest_version: int = Field(default=MANIFEST_VERSION, ge=1, le=1)
    key: str = Field(pattern=PLUGIN_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(default="1.0.0", pattern=r"^[0-9A-Za-z.+-]{1,32}$")
    description: str = Field(default="", max_length=2000)
    author: str = Field(default="", max_length=100)
    icon: str = Field(default="puzzle", max_length=40)
    homepage: str = Field(default="", max_length=500)
    kind: Literal["component", "theme"] = "component"
    # 组件插件 zip 内的入口脚本 / 两种插件共用的可选样式。
    entry: str = Field(default="", max_length=200)
    style: str = Field(default="", max_length=200)
    blocks: list[PluginBlockIn] = Field(default_factory=list, max_length=MAX_BLOCKS)
    # 主题插件的视觉规格；component 插件必须为空。
    theme: ThemeSpecIn | None = None
    # 预留的插件设置声明；当前版本只保存不解释。
    settings: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    @field_validator("key", "name", "version", "description", "author", "icon", "homepage")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("entry")
    @classmethod
    def _validate_entry(cls, value: str) -> str:
        return _normalize_asset_path(value, (".js", ".mjs"), "入口脚本")

    @field_validator("style")
    @classmethod
    def _validate_style(cls, value: str) -> str:
        return _normalize_asset_path(value, (".css",), "样式文件")

    @model_validator(mode="after")
    def _validate(self) -> PluginManifestIn:
        seen: set[str] = set()
        total = 0
        for block in self.blocks:
            if block.type in seen:
                raise ValueError(f"区块 type 重复：{block.type}")
            seen.add(block.type)
            total += len(block.template_markdown)
        if total > MAX_MANIFEST_CHARS:
            raise ValueError("区块内容总长度超出限制")
        if self.kind == "component":
            if not self.blocks:
                raise ValueError("组件插件至少需要一个区块")
            if self.theme is not None:
                raise ValueError("组件插件不能声明 theme")
        else:
            if self.theme is None:
                raise ValueError("主题插件必须提供 theme 规格")
            if self.entry:
                raise ValueError("主题插件不使用入口脚本，entry 必须为空")
            if self.blocks:
                raise ValueError("主题插件不能声明区块")
        # entry / style 均已通过路径校验，剩余由 zip 解析器确认文件存在。
        return self


class PluginUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    version: str | None = Field(default=None, pattern=r"^[0-9A-Za-z.+-]{1,32}$")
    description: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(default=None, max_length=40)
    homepage: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    blocks: list[PluginBlockIn] | None = Field(default=None, max_length=MAX_BLOCKS)

    @model_validator(mode="after")
    def _validate_blocks(self) -> PluginUpdate:
        if self.blocks is None:
            return self
        seen: set[str] = set()
        total = 0
        for block in self.blocks:
            if block.type in seen:
                raise ValueError(f"区块 type 重复：{block.type}")
            seen.add(block.type)
            total += len(block.template_markdown)
        if total > MAX_MANIFEST_CHARS:
            raise ValueError("区块内容总长度超出限制")
        return self


class PluginBlockOut(BaseModel):
    """拍平后的区块定义，供编辑器斜杠菜单直接消费。"""

    key: str
    plugin_key: str
    plugin_name: str
    plugin_version: str
    type: str
    label: str
    icon: str = "puzzle"
    description: str = ""
    category: str = "插件区块"
    kind: Literal["template", "component"] = "template"
    template_markdown: str = ""
    default_props: dict[str, Any] = Field(default_factory=dict)
    # 编辑器选中区块后可置顶为全局浮窗。
    pinnable: bool = False


class PluginOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    name: str
    version: str
    description: str
    author: str
    icon: str
    homepage: str
    enabled: bool
    kind: Literal["template", "component", "theme"] = "template"
    entry: str = ""
    source: str
    has_script: bool = False
    has_style: bool = False
    script_size: int = 0
    style_size: int = 0
    script_url: str = ""
    style_url: str = ""
    blocks: list[PluginBlockOut] = Field(default_factory=list)
    theme: ThemeSpecIn | None = None
    builtin: bool = False
    asset_count: int = 0
    assets: list[str] = Field(default_factory=list)
    preview_url: str = ""
    created_at: datetime
    updated_at: datetime


class PluginInspectionOut(BaseModel):
    """导入前预检：不落库，供前端提示组件插件的代码执行风险。"""

    kind: Literal["template", "component", "theme"]
    key: str
    name: str
    version: str
    description: str = ""
    entry: str = ""
    style: str = ""
    has_script: bool = False
    has_style: bool = False
    block_count: int = 0
    blocks: list[str] = Field(default_factory=list)
    theme: ThemeSpecIn | None = None
    asset_count: int = 0
    assets: list[str] = Field(default_factory=list)
