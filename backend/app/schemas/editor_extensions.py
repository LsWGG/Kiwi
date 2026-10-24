"""编辑器内置扩展组件的启停 schemas。"""

from pydantic import BaseModel, Field


class EditorExtensionOut(BaseModel):
    key: str
    label: str
    hint: str
    icon: str
    group: str = "扩展组件"
    enabled: bool
    # 设置页预览使用的示例 Markdown（与编辑器同一套解析规则）。
    preview_markdown: str = ""


class EditorExtensionsOut(BaseModel):
    items: list[EditorExtensionOut]
    enabled: list[str]
    disabled: list[str]


class EditorExtensionsUpdate(BaseModel):
    # 传完整停用集合：新增组件不在集合中则默认启用。
    disabled: list[str] = Field(default_factory=list, max_length=100)
