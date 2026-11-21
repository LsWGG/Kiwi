"""与传输方式无关的工具定义与工具箱。

设计目标：

- 工具来自注册表（内置工具 + 外部 MCP 服务），Agent 循环里不再出现
  ``if tool == "..."`` 这样的枚举分发；
- 每个工具都携带 JSON Schema、读写属性、来源与参数标签，既供 LLM 选择，
  也供前端审批卡片展示；
- 外部 MCP 工具默认按「写操作」处理，必须经用户确认，避免未知工具绕过
  危险操作确认。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


class ToolError(Exception):
    """可直接展示给模型 / 用户的工具错误。"""


RemoteExecutor = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
BuiltinExecutor = Callable[
    [AsyncSession | None, uuid.UUID | None, str, dict[str, Any]], Awaitable[dict[str, Any]]
]


@dataclass
class ToolDef:
    """一个可被 Agent 调用的工具。

    ``source`` 为 ``kiwi`` 表示内置工具；其他值是对外 MCP 服务的名称。
    """

    name: str
    label: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    source: str = "kiwi"
    destructive: bool = False
    # 是否必须在某个知识库上下文中执行；联网读网页等工具不需要。
    requires_kb: bool = True
    args_model: type[BaseModel] | None = None
    arg_labels: dict[str, str] = field(default_factory=dict)
    summary_template: str = ""
    # 外部 MCP 工具的原始名称（不含 mcp__server__ 前缀）。
    remote_name: str | None = None

    @property
    def external(self) -> bool:
        return self.source != "kiwi"

    def prompt_spec(self) -> dict[str, Any]:
        """给模型看的精简说明；input_schema 就是调用参数契约。"""
        return {
            "name": self.name,
            "description": self.description,
            "read_only": self.read_only,
            "source": self.source,
            "input_schema": self.input_schema,
        }

    def mcp_spec(self) -> dict[str, Any]:
        """MCP ``tools/list`` 返回的标准结构。"""
        return {
            "name": self.name,
            "title": self.label,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": False,
            },
            "_meta": {"kiwi/source": self.source},
        }


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _validate_external(schema: dict[str, Any], args: dict[str, Any]) -> None:
    """外部 MCP 工具的最小 JSON Schema 校验。

    完整校验交给 MCP 服务；这里只拦截明显的类型 / 必填错误，避免把无效参数
    发给远端后才报错。复杂关键字（oneOf / anyOf 等）不在这里处理。
    """
    if not isinstance(args, dict):
        raise ToolError("工具参数必须是 JSON 对象")
    if not schema:
        return
    required = schema.get("required") or []
    missing = [str(key) for key in required if key not in args]
    if missing:
        raise ToolError(f"缺少必填参数：{', '.join(missing)}")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
        "null": type(None),
    }
    for key, value in args.items():
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue
        allowed = prop.get("type")
        if isinstance(allowed, list):
            expected = tuple(
                type_map[item] for item in allowed if item in type_map
            )
            if expected and not isinstance(value, expected):
                raise ToolError(f"参数 {key} 类型不正确，期望 {' / '.join(allowed)}")
        elif isinstance(allowed, str) and allowed in type_map:
            if allowed in ("integer", "number") and isinstance(value, bool):
                raise ToolError(f"参数 {key} 类型不正确，期望 {allowed}")
            if not isinstance(value, type_map[allowed]):
                raise ToolError(f"参数 {key} 类型不正确，期望 {allowed}")
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolError(f"参数 {key} 只能是：{', '.join(map(str, enum))}")


def field_labels(model: type[BaseModel]) -> dict[str, str]:
    """参数名到中文标签；用于审批卡片展示。"""
    labels: dict[str, str] = {}
    for name, info in model.model_fields.items():
        label = info.title or name
        labels[name] = str(label)[:40]
    return labels


class _DefaultEmpty(dict):
    """format_map 时缺失的占位符按空字符串处理。"""

    def __missing__(self, key: str) -> str:
        return ""


class Toolbox:
    """一次问答可见的工具集合。"""

    def __init__(
        self,
        tools: list[ToolDef],
        *,
        builtin_executor: BuiltinExecutor | None = None,
        remote_executor: RemoteExecutor | None = None,
    ):
        self._tools = {tool.name: tool for tool in tools}
        self._builtin_executor = builtin_executor
        self._remote_executor = remote_executor

    @property
    def tools(self) -> list[ToolDef]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDef:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "（无）"
            raise ToolError(f"未知工具：{name}。可用工具：{available}")
        return tool

    def with_tools(self, extra: list[ToolDef]) -> "Toolbox":
        merged = list(self._tools.values()) + [
            tool for tool in extra if tool.name not in self._tools
        ]
        return Toolbox(
            merged,
            builtin_executor=self._builtin_executor,
            remote_executor=self._remote_executor,
        )

    def prompt(self) -> str:
        specs = [tool.prompt_spec() for tool in self._tools.values()]
        lines = [
            "你可以调用下列工具读取网页或操作当前知识库。读工具会自动执行；写工具会先请求用户确认，"
            "在用户确认前不要声称操作已完成。",
            "工具名以 mcp__ 开头的是外部 MCP 服务提供的工具；它们的读写属性由服务声明，"
            "未声明为只读的工具一律按写操作处理。",
            "工具清单（JSON）：",
            json.dumps(specs, ensure_ascii=False),
        ]
        return "\n".join(lines)

    def prepare_call(
        self,
        tool: str,
        args: dict[str, Any] | None,
        summary: str,
        *,
        can_write: bool,
    ) -> tuple[dict[str, Any], str, str, dict[str, str]]:
        definition = self.get(tool)
        if not definition.read_only and not can_write:
            raise ToolError(
                "当前为多库 / 全局问答范围，写操作不可用；请切换到单个知识库后再试。"
            )
        raw_args = args if isinstance(args, dict) else {}
        if definition.args_model is not None:
            try:
                model = definition.args_model.model_validate(raw_args)
            except ValidationError as e:
                first = e.errors()[0] if e.errors() else {}
                field_name = ".".join(str(part) for part in first.get("loc", ()))
                message = first.get("msg", "参数不正确")
                raise ToolError(
                    f"{tool} 参数错误：{field_name} {message}".strip()
                ) from e
            normalized = model.model_dump(mode="json", exclude_unset=True)
            labels = definition.arg_labels or field_labels(definition.args_model)
        else:
            _validate_external(definition.input_schema, raw_args)
            normalized = dict(raw_args)
            labels = definition.arg_labels
        clean_summary = " ".join(str(summary or "").split())[:300]
        if not clean_summary and definition.summary_template:
            try:
                clean_summary = definition.summary_template.format_map(
                    _DefaultEmpty(normalized)
                )[:300]
            except (KeyError, ValueError):
                clean_summary = ""
        return (
            normalized,
            definition.label,
            clean_summary or definition.label,
            labels,
        )

    async def execute(
        self,
        session: AsyncSession | None,
        kb_id: uuid.UUID | None,
        tool: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        definition = self.get(tool)
        if definition.external:
            if self._remote_executor is None:
                raise ToolError("外部 MCP 工具未配置执行器")
            result = await self._remote_executor(
                definition.source, definition.remote_name or tool, args
            )
            error = bool(result.get("isError"))
            content = _content_text(result)
            if error:
                raise ToolError(content or "外部 MCP 工具执行失败")
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                return structured
            if content:
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        return parsed
                except ValueError:
                    pass
                return {"text": content}
            return {"ok": True}
        if self._builtin_executor is None:
            raise ToolError("内置工具未配置执行器")
        return await self._builtin_executor(session, kb_id, tool, args)


def _content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


__all__ = [
    "BuiltinExecutor",
    "RemoteExecutor",
    "ToolDef",
    "ToolError",
    "Toolbox",
    "field_labels",
]
