"""Kiwi 的 MCP（Model Context Protocol）支持。

- ``types``：与传输方式无关的工具注册表 / 工具箱。
- ``server``：把 Kiwi 笔记能力暴露成标准 MCP 服务（HTTP JSON-RPC）。
- ``client``：让问答 Agent 动态发现并调用外部 MCP 服务。

工具不再写死在 Agent 循环里；内置工具与外部 MCP 工具都通过注册表
提供名称、JSON Schema 与权限信息。
"""

from app.mcp.types import Toolbox, ToolDef, ToolError

__all__ = ["ToolDef", "ToolError", "Toolbox"]
