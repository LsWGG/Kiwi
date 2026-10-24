"""插件 / 区块 manifest schemas。

插件仅支持组件插件：zip 内提供 manifest、入口 ESM 与可选样式。
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
    kind: Literal["component"] = "component"
    # 组件插件 zip 内的入口脚本 / 可选样式。
    entry: str = Field(default="", max_length=200)
    style: str = Field(default="", max_length=200)
    blocks: list[PluginBlockIn] = Field(default_factory=list, max_length=MAX_BLOCKS)
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
        if not self.blocks:
            raise ValueError("组件插件至少需要一个区块")
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
    kind: Literal["template", "component"] = "template"
    entry: str = ""
    source: str
    has_script: bool = False
    has_style: bool = False
    script_size: int = 0
    style_size: int = 0
    script_url: str = ""
    style_url: str = ""
    blocks: list[PluginBlockOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PluginInspectionOut(BaseModel):
    """导入前预检：不落库，供前端提示组件插件的代码执行风险。"""

    kind: Literal["template", "component"]
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
