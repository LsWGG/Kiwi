"""工具注册表与 MCP 端点：动态 schema、只读自动执行、写操作显式授权。"""

from __future__ import annotations

import uuid

from app.mcp.client import MCPServerConfig, _tool_def
from app.services import agent_tools


async def _rpc(client, kb_id, method, params=None, *, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = await client.post(f"/api/mcp?kb_id={kb_id}", json=body, headers=headers or {})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_registry_drives_tool_metadata():
    tools = agent_tools.builtin_tools()
    assert len(tools) >= 15
    assert agent_tools.READ_ONLY_TOOLS == {
        tool.name for tool in tools if tool.read_only
    }
    for tool in tools:
        assert tool.label
        assert tool.description
        assert tool.input_schema.get("type") == "object"
        if tool.args_model is not None and tool.args_model.model_fields:
            # 审批卡片使用 Field.title，不再依赖前端硬编码参数名。
            assert set(tool.arg_labels) == set(tool.args_model.model_fields)
        assert agent_tools.TOOL_LABELS[tool.name] == tool.label


def test_external_tool_without_readonly_hint_is_treated_as_write():
    config = MCPServerConfig(
        name="demo", url="https://example.com/mcp", headers={}, timeout=5
    )
    read_tool = _tool_def(
        config,
        {
            "name": "lookup",
            "description": "查资料",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        },
    )
    write_tool = _tool_def(config, {"name": "mutate"})
    assert read_tool is not None and read_tool.read_only
    assert read_tool.name == "mcp__demo__lookup"
    assert read_tool.remote_name == "lookup"
    assert write_tool is not None and not write_tool.read_only


async def test_mcp_list_and_read_tool(client, kb):
    kb_id = uuid.UUID(kb["id"])
    listed = await _rpc(client, kb_id, "tools/list")
    tools = listed["result"]["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    assert "search_notes" in by_name
    assert by_name["search_notes"]["annotations"]["readOnlyHint"] is True
    assert by_name["create_note"]["annotations"]["readOnlyHint"] is False
    assert by_name["search_notes"]["inputSchema"]["type"] == "object"

    called = await _rpc(
        client,
        kb_id,
        "tools/call",
        {"name": "list_folders", "arguments": {}},
    )
    result = called["result"]
    assert result["isError"] is False
    assert "items" in result["structuredContent"]


async def test_mcp_write_requires_explicit_approval_header(client, kb):
    kb_id = uuid.UUID(kb["id"])
    denied = await _rpc(
        client,
        kb_id,
        "tools/call",
        {"name": "create_folder", "arguments": {"name": "MCP 分组"}},
    )
    assert denied["error"]["code"] == -32003

    allowed = await _rpc(
        client,
        kb_id,
        "tools/call",
        {"name": "create_folder", "arguments": {"name": "MCP 分组"}},
        headers={"X-Kiwi-Write-Approved": "true"},
    )
    assert allowed["result"]["isError"] is False
    folder_id = allowed["result"]["structuredContent"]["folder"]["id"]

    listed = await _rpc(
        client, kb_id, "tools/call", {"name": "list_folders", "arguments": {}}
    )
    assert any(
        item["id"] == folder_id and item["name"] == "MCP 分组"
        for item in listed["result"]["structuredContent"]["items"]
    )


async def test_mcp_unknown_tool_and_missing_kb(client, kb):
    kb_id = uuid.UUID(kb["id"])
    unknown = await _rpc(
        client, kb_id, "tools/call", {"name": "not_a_tool", "arguments": {}}
    )
    assert unknown["error"]["code"] == -32602

    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "list_folders", "arguments": {}},
    }
    resp = await client.post("/api/mcp", json=body)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32602
