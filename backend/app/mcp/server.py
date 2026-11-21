"""把 Kiwi 的笔记工具暴露成标准 MCP 服务（Streamable HTTP + JSON-RPC）。

端点：``POST /api/mcp?kb_id=<知识库 UUID>``

支持的方法：

- ``initialize`` / ``notifications/initialized`` / ``ping``
- ``tools/list``：返回内置工具的 JSON Schema 与只读注解
- ``tools/call``：执行工具。只读工具直接执行；写工具必须额外携带
  ``X-Kiwi-Write-Approved: true``，避免外部客户端绕过确认直接改数据。

该端点只暴露内置工具，不把外部 MCP 工具再次代理出去，防止递归调用。
所有操作都限定在 ``kb_id`` 指定的知识库内。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.build_info import APP_VERSION
from app.db.session import get_session
from app.mcp.types import Toolbox, ToolError

logger = logging.getLogger("kiwi.mcp.server")

PROTOCOL_VERSION = "2025-06-18"
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(
    request_id: Any, code: int, message: str, data: Any | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _toolbox() -> Toolbox:
    # 延迟导入，避免 app.mcp 包初始化时反向依赖服务层。
    from app.services import agent_tools

    return Toolbox(
        agent_tools.builtin_tools(),
        builtin_executor=agent_tools.call_builtin_tool,
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@router.post("")
async def mcp_endpoint(
    request: Request,
    kb_id: uuid.UUID | None = Query(default=None),
    x_kiwi_write_approved: str | None = Header(
        default=None, alias="X-Kiwi-Write-Approved"
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"))

    if not isinstance(payload, dict):
        return JSONResponse(_error(None, -32600, "Invalid Request"))

    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params")
    if not isinstance(method, str):
        return JSONResponse(_error(request_id, -32600, "Invalid Request"))
    if not isinstance(params, dict):
        params = {}

    # 通知没有 id，不需要响应。客户端初始化完成后会发这条。
    if method.startswith("notifications/"):
        return Response(status_code=202)

    if method == "initialize":
        response = JSONResponse(
            _result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "kiwi", "version": APP_VERSION},
                    "instructions": (
                        "Kiwi 知识库工具。调用工具时通过查询参数 kb_id 指定知识库；"
                        "写工具需要请求头 X-Kiwi-Write-Approved: true。"
                    ),
                },
            )
        )
        # 无状态服务：会话 ID 只用于兼容客户端，服务端不依赖它。
        response.headers["Mcp-Session-Id"] = uuid.uuid4().hex
        return response

    if method == "ping":
        return JSONResponse(_result(request_id, {}))

    if method == "tools/list":
        toolbox = _toolbox()
        return JSONResponse(
            _result(
                request_id,
                {"tools": [tool.mcp_spec() for tool in toolbox.tools]},
            )
        )

    if method == "tools/call":
        return await _call_tool(
            request_id,
            params,
            kb_id=kb_id,
            session=session,
            write_approved=(x_kiwi_write_approved or "").strip().lower()
            in {"1", "true", "yes"},
        )

    return JSONResponse(_error(request_id, -32601, f"Method not found: {method}"))


async def _call_tool(
    request_id: Any,
    params: dict[str, Any],
    *,
    kb_id: uuid.UUID | None,
    session: AsyncSession,
    write_approved: bool,
):
    name = str(params.get("name") or "").strip()
    if not name:
        return JSONResponse(_error(request_id, -32602, "Missing tool name"))
    raw_args = params.get("arguments")
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        return JSONResponse(_error(request_id, -32602, "arguments must be an object"))
    toolbox = _toolbox()
    try:
        definition = toolbox.get(name)
    except ToolError as e:
        return JSONResponse(_error(request_id, -32602, str(e)))
    if kb_id is None:
        return JSONResponse(
            _error(request_id, -32602, "Missing kb_id query parameter")
        )
    if not definition.read_only and not write_approved:
        return JSONResponse(
            _error(
                request_id,
                -32003,
                "写工具需要显式授权：请求头 X-Kiwi-Write-Approved: true",
                data={"tool": name},
            )
        )
    try:
        result = await toolbox.execute(session, kb_id, name, raw_args)
    except ToolError as e:
        text = str(e)
        return JSONResponse(
            _result(
                request_id,
                {"content": [{"type": "text", "text": text}], "isError": True},
            )
        )
    except Exception:  # noqa: BLE001 —— 不让单个工具异常打断 MCP 连接
        logger.exception("MCP 工具执行失败：%s", name)
        return JSONResponse(
            _result(
                request_id,
                {
                    "content": [{"type": "text", "text": "工具执行失败"}],
                    "isError": True,
                },
            )
        )
    return JSONResponse(
        _result(
            request_id,
            {
                "content": [{"type": "text", "text": _json_text(result)}],
                "structuredContent": result if isinstance(result, dict) else {},
                "isError": False,
            },
        )
    )


@router.get("")
async def mcp_get():
    """Streamable HTTP 的 GET 用于服务端推送；Kiwi 不提供该能力。"""
    return Response(status_code=405)


__all__ = ["router"]
