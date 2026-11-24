"""Agent 工具真正落库：笔记 / 分组 / 数据表记录的 CRUD 与上锁保护。"""

from __future__ import annotations

import uuid

import pytest

from app.services import agent_tools
from app.services.link_fetcher import LinkFetchResult, SSRFError


async def test_agent_note_crud_and_search(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    created = await agent_tools.execute_tool(
        db,
        kb_id,
        "create_note",
        {"title": "Agent 笔记", "body_md": "第一版正文", "tags": ["agent"]},
    )
    note_id = created["note"]["id"]

    fetched = await agent_tools.execute_tool(
        db, kb_id, "get_note", {"note_id": note_id}
    )
    assert fetched["title"] == "Agent 笔记"
    assert fetched["body_md"] == "第一版正文"
    assert fetched["tags"] == ["agent"]

    searched = await agent_tools.execute_tool(
        db, kb_id, "search_notes", {"query": "Agent"}
    )
    assert any(item["id"] == note_id for item in searched["items"])

    updated = await agent_tools.execute_tool(
        db,
        kb_id,
        "update_note",
        {"note_id": note_id, "title": "Agent 笔记（改）", "body_md": "第二版正文"},
    )
    assert updated["note"]["title"] == "Agent 笔记（改）"
    fetched = await agent_tools.execute_tool(
        db, kb_id, "get_note", {"note_id": note_id}
    )
    assert fetched["body_md"] == "第二版正文"

    deleted = await agent_tools.execute_tool(
        db, kb_id, "delete_note", {"note_id": note_id}
    )
    assert deleted["status"] == "trash"
    with pytest.raises(agent_tools.ToolError, match="回收站"):
        await agent_tools.execute_tool(db, kb_id, "get_note", {"note_id": note_id})


async def test_agent_reads_note_templates(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    body = "# 旅游规划\n\n## 行程时间\n\n## 行前准备\n"
    created = await client.post(
        f"/api/notes/templates?kb_id={kb_id}",
        json={
            "name": "旅游规划",
            "description": "按天整理行程、交通与预约信息",
            "title_pattern": "{{date}} 旅游规划",
            "body_md": body,
            "tags_json": ["旅行"],
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    listed = await agent_tools.execute_tool(
        db, kb_id, "list_templates", {"query": "旅游"}
    )
    item = next(item for item in listed["items"] if item["name"] == "旅游规划")
    assert item["id"] == template_id
    assert item["title_pattern"] == "{{date}} 旅游规划"
    assert "行程时间" in item["body_preview"]

    fetched = await agent_tools.execute_tool(
        db, kb_id, "get_template", {"name": "旅游规划"}
    )
    assert fetched["body_md"] == body
    assert fetched["tags"] == ["旅行"]

    by_id = await agent_tools.execute_tool(
        db, kb_id, "get_template", {"template_id": template_id}
    )
    assert by_id["name"] == "旅游规划"

    with pytest.raises(agent_tools.ToolError, match="没有找到"):
        await agent_tools.execute_tool(
            db, kb_id, "get_template", {"name": "不存在的模板"}
        )


async def test_agent_folder_crud(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    created = await agent_tools.execute_tool(
        db, kb_id, "create_folder", {"name": "Agent 分组"}
    )
    folder_id = created["folder"]["id"]

    renamed = await agent_tools.execute_tool(
        db,
        kb_id,
        "update_folder",
        {"folder_id": folder_id, "name": "Agent 分组（改）"},
    )
    assert renamed["folder"]["name"] == "Agent 分组（改）"
    listed = await agent_tools.execute_tool(db, kb_id, "list_folders", {})
    assert any(
        item["id"] == folder_id and item["name"] == "Agent 分组（改）"
        for item in listed["items"]
    )

    await agent_tools.execute_tool(
        db, kb_id, "delete_folder", {"folder_id": folder_id}
    )
    listed = await agent_tools.execute_tool(db, kb_id, "list_folders", {})
    assert all(item["id"] != folder_id for item in listed["items"])


async def test_agent_database_row_crud(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    created = await agent_tools.execute_tool(
        db, kb_id, "create_note", {"title": "Agent 数据表", "kind": "database"}
    )
    database_id = created["note"]["id"]

    databases = await agent_tools.execute_tool(db, kb_id, "list_databases", {})
    assert any(item["id"] == database_id for item in databases["items"])

    row = await agent_tools.execute_tool(
        db,
        kb_id,
        "create_database_row",
        {"note_id": database_id, "data": {"name": "记录一"}},
    )
    row_id = row["row"]["id"]
    rows = await agent_tools.execute_tool(
        db, kb_id, "query_database_rows", {"note_id": database_id}
    )
    assert any(item["id"] == row_id for item in rows["items"])

    updated = await agent_tools.execute_tool(
        db,
        kb_id,
        "update_database_row",
        {"note_id": database_id, "row_id": row_id, "data": {"name": "记录二"}},
    )
    assert updated["row"]["data"]["name"] == "记录二"

    await agent_tools.execute_tool(
        db,
        kb_id,
        "delete_database_row",
        {"note_id": database_id, "row_id": row_id},
    )
    rows = await agent_tools.execute_tool(
        db, kb_id, "query_database_rows", {"note_id": database_id}
    )
    assert all(item["id"] != row_id for item in rows["items"])


async def test_agent_refuses_locked_note(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    note = await client.post(
        f"/api/notes?kb_id={kb_id}",
        json={"title": "上锁笔记", "kind": "doc"},
    )
    assert note.status_code == 201, note.text
    note_id = note.json()["id"]
    locked = await client.post(
        f"/api/notes/{note_id}/lock?kb_id={kb_id}",
        json={"password": "test-pass", "hint": ""},
    )
    assert locked.status_code in (200, 204), locked.text

    with pytest.raises(agent_tools.ToolError, match="上锁"):
        await agent_tools.execute_tool(db, kb_id, "get_note", {"note_id": note_id})
    with pytest.raises(agent_tools.ToolError, match="上锁"):
        await agent_tools.execute_tool(
            db, kb_id, "update_note", {"note_id": note_id, "title": "不该成功"}
        )


def _fetch_result(url: str, **overrides) -> LinkFetchResult:
    payload = {
        "url": url,
        "final_url": url,
        "title": "古诗文网 · 关雎",
        "markdown": "# 关雎\n\n关关雎鸠，在河之洲。",
        "site": "古诗文网",
        "excerpt": "诗经",
        "favicon": "",
        "fetch_status": "ok",
        "error": None,
    }
    payload.update(overrides)
    return LinkFetchResult(**payload)


async def test_agent_fetch_url_is_read_only_without_kb(monkeypatch):
    async def fake_fetch(url: str) -> LinkFetchResult:
        return _fetch_result(url)

    monkeypatch.setattr(agent_tools, "fetch_and_extract", fake_fetch)
    assert "fetch_url" in agent_tools.READ_ONLY_TOOLS

    # 全局问答没有 kb_id / 数据库会话，也应能读取网页。
    result = await agent_tools.execute_tool(
        None, None, "fetch_url", {"url": "https://www.guwendao.net/shiwenv_45.aspx"}
    )
    assert result["title"] == "古诗文网 · 关雎"
    # 摘要不在正文里时补在开头；正文保持原样。
    assert result["markdown"].startswith("> 页面摘要：诗经\n\n# 关雎")
    assert result["summary_added"] is True
    assert result["markdown_truncated"] is False

    with pytest.raises(agent_tools.ToolError, match="无法执行工具"):
        await agent_tools.execute_tool(None, None, "list_folders", {})


async def test_agent_fetch_url_reports_fetch_failure(monkeypatch):
    async def fake_fetch(url: str) -> LinkFetchResult:
        return _fetch_result(url, markdown="", fetch_status="failed", error="连接超时")

    monkeypatch.setattr(agent_tools, "fetch_and_extract", fake_fetch)
    with pytest.raises(agent_tools.ToolError, match="连接超时"):
        await agent_tools.execute_tool(
            None, None, "fetch_url", {"url": "https://example.com/slow"}
        )


async def test_agent_fetch_url_rejects_private_address(monkeypatch):
    async def fake_fetch(url: str) -> LinkFetchResult:
        raise SSRFError("拒绝访问内网地址 127.0.0.1")

    monkeypatch.setattr(agent_tools, "fetch_and_extract", fake_fetch)
    with pytest.raises(agent_tools.ToolError, match="内网"):
        await agent_tools.execute_tool(
            None, None, "fetch_url", {"url": "http://127.0.0.1/secret"}
        )


async def test_agent_fetch_url_skips_duplicate_summary(monkeypatch):
    async def fake_fetch(url: str) -> LinkFetchResult:
        return _fetch_result(url, markdown="# 关雎\n\n诗经", excerpt="诗经")

    monkeypatch.setattr(agent_tools, "fetch_and_extract", fake_fetch)
    result = await agent_tools.execute_tool(
        None, None, "fetch_url", {"url": "https://example.com/dupe"}
    )
    assert result["summary_added"] is False
    assert result["markdown"] == "# 关雎\n\n诗经"


async def test_agent_fetch_url_marks_truncated_body(monkeypatch):
    long_body = "正文" * (agent_tools.MAX_RESULT_WEB_BODY // 2 + 10)

    async def fake_fetch(url: str) -> LinkFetchResult:
        return _fetch_result(url, markdown=long_body)

    monkeypatch.setattr(agent_tools, "fetch_and_extract", fake_fetch)
    result = await agent_tools.execute_tool(
        None, None, "fetch_url", {"url": "https://example.com/long"}
    )
    assert len(result["markdown"]) == agent_tools.MAX_RESULT_WEB_BODY
    assert result["markdown_truncated"] is True
