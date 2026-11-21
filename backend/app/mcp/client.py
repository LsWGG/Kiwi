"""外部 MCP 服务客户端（Streamable HTTP / JSON-RPC）。

只支持通过 HTTP(S) 连接外部 MCP 服务。出于安全考虑不自动拉起本地 stdio
进程；需要本地工具时可以单独运行一个 MCP 服务，再把 URL 配置进来。

配置来源（按优先级）：

1. ``KIWI_MCP_SERVERS_JSON``：JSON 字符串；
2. ``KIWI_MCP_SERVERS_FILE``：JSON 文件，默认为 ``backend/data/mcp_servers.json``。

格式：
``{"servers": [{"name": "github", "url": "https://host/mcp",
"headers": {"Authorization": "Bearer ..."}, "timeout": 30}]}``
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.mcp.types import ToolDef, ToolError

logger = logging.getLogger("kiwi.mcp.client")

PROTOCOL_VERSION = "2025-06-18"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    url: str
    headers: dict[str, str]
    timeout: float


@dataclass
class _CachedTools:
    expires_at: float
    tools: list[ToolDef]


_cache: dict[str, _CachedTools] = {}
_sessions: dict[str, str] = {}
_locks: dict[str, asyncio.Lock] = {}


def _load_payload() -> Any:
    raw = (settings.mcp_servers_json or "").strip()
    if not raw:
        path = Path(settings.mcp_servers_file)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("无法读取 MCP 配置文件：%s", path)
            return None
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("MCP 配置不是合法 JSON，已忽略")
        return None


def load_server_configs() -> list[MCPServerConfig]:
    payload = _load_payload()
    if payload is None:
        return []
    servers = payload.get("servers") if isinstance(payload, dict) else payload
    if not isinstance(servers, list):
        logger.warning("MCP 配置缺少 servers 数组，已忽略")
        return []
    result: list[MCPServerConfig] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not _NAME_RE.match(name) or name in seen:
            logger.warning("MCP 服务名称不合法或重复：%s", name or "(空)")
            continue
        if not url.startswith(("http://", "https://")):
            logger.warning("MCP 服务 %s 的 url 必须是 http(s)", name)
            continue
        headers = item.get("headers")
        if not isinstance(headers, dict):
            headers = {}
        clean_headers = {
            str(key): str(value)
            for key, value in headers.items()
            if str(key).strip() and value is not None
        }
        try:
            timeout = float(item.get("timeout") or settings.mcp_timeout)
        except (TypeError, ValueError):
            timeout = settings.mcp_timeout
        seen.add(name)
        result.append(
            MCPServerConfig(
                name=name,
                url=url,
                headers=clean_headers,
                timeout=max(1.0, min(timeout, 300.0)),
            )
        )
    return result


def _json_rpc_payload(method: str, params: dict[str, Any], request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def _parse_sse(body: str) -> dict[str, Any] | None:
    """从一个或多个 SSE 帧里找出 JSON-RPC 响应。"""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and ("result" in data or "error" in data):
            return data
    return None


async def _post(
    config: MCPServerConfig,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> tuple[httpx.Response, dict[str, Any] | None]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        **config.headers,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        response = await client.post(config.url, json=payload, headers=headers)
    content_type = response.headers.get("content-type", "")
    data: dict[str, Any] | None = None
    if "text/event-stream" in content_type:
        data = _parse_sse(response.text)
    else:
        try:
            parsed = response.json()
            data = parsed if isinstance(parsed, dict) else None
        except ValueError:
            data = None
    return response, data


def _raise_rpc_error(data: dict[str, Any] | None) -> None:
    if not data:
        return
    error = data.get("error")
    if not isinstance(error, dict):
        return
    message = str(error.get("message") or "MCP 服务返回错误")
    raise ToolError(f"MCP 调用失败：{message}")


async def _initialize(config: MCPServerConfig) -> str | None:
    response, data = await _post(
        config,
        _json_rpc_payload(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "kiwi", "version": "1.0"},
            },
        ),
    )
    if response.status_code >= 400:
        raise ToolError(f"MCP 服务 {config.name} 初始化失败（HTTP {response.status_code}）")
    _raise_rpc_error(data)
    session_id = response.headers.get("mcp-session-id")
    if session_id:
        _sessions[config.name] = session_id
        # 通知不需要响应；部分服务要求先发 initialized 才允许 tools/list。
        try:
            await _post(
                config,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id=session_id,
            )
        except httpx.HTTPError:
            logger.debug("MCP 服务 %s 未接受 initialized 通知", config.name)
    return session_id


def _tool_def(config: MCPServerConfig, raw: dict[str, Any]) -> ToolDef | None:
    remote_name = str(raw.get("name") or "").strip()
    if not remote_name:
        return None
    safe_remote = _TOOL_NAME_RE.sub("_", remote_name).strip("_") or "tool"
    name = f"mcp__{config.name}__{safe_remote}"[:120]
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()
    annotations = raw.get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}
    read_only = annotations.get("readOnlyHint") is True
    destructive = annotations.get("destructiveHint") is True
    schema = raw.get("inputSchema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    properties = schema.get("properties")
    arg_labels: dict[str, str] = {}
    if isinstance(properties, dict):
        for key, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            label = str(prop.get("title") or prop.get("description") or key)
            arg_labels[str(key)] = label[:40]
    label = f"{config.name} · {title or remote_name}"[:80]
    if not description:
        description = f"外部 MCP 服务 {config.name} 提供的工具 {remote_name}。"
    else:
        description = f"[MCP:{config.name}] {description}"
    return ToolDef(
        name=name,
        label=label,
        description=description,
        input_schema=schema,
        read_only=read_only,
        source=config.name,
        destructive=destructive,
        arg_labels=arg_labels,
        summary_template=f"调用 {label}",
        remote_name=remote_name,
    )


async def _list_tools(config: MCPServerConfig) -> list[ToolDef]:
    session_id = _sessions.get(config.name) or await _initialize(config)
    tools: list[ToolDef] = []
    cursor: str | None = None
    for _page in range(10):
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        response, data = await _post(
            config,
            _json_rpc_payload("tools/list", params),
            session_id=session_id,
        )
        if response.status_code == 404 and session_id:
            # 会话过期：重新初始化后重试当前页一次。
            _sessions.pop(config.name, None)
            session_id = await _initialize(config)
            response, data = await _post(
                config,
                _json_rpc_payload("tools/list", params),
                session_id=session_id,
            )
        if response.status_code >= 400:
            raise ToolError(
                f"MCP 服务 {config.name} 返回 HTTP {response.status_code}"
            )
        _raise_rpc_error(data)
        result = (data or {}).get("result")
        if not isinstance(result, dict):
            break
        raw_tools = result.get("tools")
        if isinstance(raw_tools, list):
            for raw in raw_tools:
                if not isinstance(raw, dict):
                    continue
                tool = _tool_def(config, raw)
                if tool is not None:
                    tools.append(tool)
                if len(tools) >= settings.mcp_max_tools:
                    return tools
        next_cursor = result.get("nextCursor")
        cursor = str(next_cursor) if next_cursor else None
        if not cursor:
            break
    return tools


async def external_tools() -> list[ToolDef]:
    """动态发现外部 MCP 工具；单个服务失败不影响内置工具。"""
    tools: list[ToolDef] = []
    now = time.monotonic()
    for config in load_server_configs():
        cached = _cache.get(config.name)
        if cached is not None and cached.expires_at > now:
            tools.extend(cached.tools)
            continue
        lock = _locks.setdefault(config.name, asyncio.Lock())
        async with lock:
            cached = _cache.get(config.name)
            if cached is not None and cached.expires_at > time.monotonic():
                tools.extend(cached.tools)
                continue
            try:
                discovered = await _list_tools(config)
            except (httpx.HTTPError, ToolError) as e:
                logger.warning("MCP 服务 %s 不可用：%s", config.name, e)
                # 短缓存失败结果，避免每个问题都等待超时。
                _cache[config.name] = _CachedTools(
                    expires_at=time.monotonic() + min(60.0, settings.mcp_cache_ttl),
                    tools=[],
                )
                continue
            _cache[config.name] = _CachedTools(
                expires_at=time.monotonic() + settings.mcp_cache_ttl,
                tools=discovered,
            )
            tools.extend(discovered)
    return tools


async def call_external_tool(
    server_name: str, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    config = next(
        (item for item in load_server_configs() if item.name == server_name), None
    )
    if config is None:
        raise ToolError(f"外部 MCP 服务未配置：{server_name}")
    session_id = _sessions.get(server_name)
    if not session_id:
        session_id = await _initialize(config)
    payload = _json_rpc_payload(
        "tools/call", {"name": tool_name, "arguments": args}
    )
    response, data = await _post(config, payload, session_id=session_id)
    if response.status_code == 404 and session_id:
        _sessions.pop(server_name, None)
        session_id = await _initialize(config)
        response, data = await _post(config, payload, session_id=session_id)
    if response.status_code >= 400:
        raise ToolError(f"MCP 服务 {server_name} 返回 HTTP {response.status_code}")
    _raise_rpc_error(data)
    result = (data or {}).get("result")
    if not isinstance(result, dict):
        return {"ok": True}
    return result


def clear_cache() -> None:
    """测试 / 运维辅助：清空工具发现与会话缓存。"""
    _cache.clear()
    _sessions.clear()


__all__ = [
    "MCPServerConfig",
    "call_external_tool",
    "clear_cache",
    "external_tools",
    "load_server_configs",
]
