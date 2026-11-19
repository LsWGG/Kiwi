"""只读导入文件进入问答上下文：显式 @ 时不依赖向量命中。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.routers import chat
from app.schemas.chat import ChatRequest, SearchScope

CONTENT = "Elasticsearch 是一个分布式搜索和分析引擎。\n它支持近实时检索。"


async def test_mentioned_readonly_import_is_read_into_context(
    client, db, kb, monkeypatch
):
    resp = await client.post(
        f"/api/notes/import?kb_id={kb['id']}",
        files={"file": ("guide.txt", CONTENT.encode("utf-8"), "text/plain")},
        data={"readonly": "true", "title": "只读导入资料"},
    )
    assert resp.status_code == 202, resp.text
    note = resp.json()["note"]
    assert note["props_json"]["import"]["readonly"] is True

    async def fake_resolve_llm(session, kb_id, temp_cfg_id):
        return (
            SimpleNamespace(
                model_name="test-model",
                extra_params={},
                base_url="http://127.0.0.1:9",
            ),
            "test-key",
        )

    async def fake_search_many(*args, **kwargs):
        # 只读文件没有向量分块：模拟检索完全不命中。
        return [], ""

    async def fake_index(kb_ids):
        return None

    monkeypatch.setattr(chat, "resolve_llm", fake_resolve_llm)
    monkeypatch.setattr(
        chat.llm_factory,
        "get_client",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(chat, "_safe_search_many", fake_search_many)
    monkeypatch.setattr(chat, "ensure_notes_indexed", fake_index)

    stages: list[tuple[str, str, str, str]] = []
    data = ChatRequest(
        messages=[{"role": "user", "content": "这份资料的要点是什么？"}],
        scope=SearchScope(
            kb_ids=[uuid.UUID(kb["id"])],
            scope="kb",
            note_ids=[uuid.UUID(note["id"])],
        ),
        intent="note",
    )
    prepared = await chat._prepare_chat(
        db, data, "这份资料的要点是什么？", "note", lambda *args: stages.append(args)
    )

    joined = "\n\n".join(str(item.get("content") or "") for item in prepared.openai_msgs)
    assert "分布式搜索和分析引擎" in joined
    assert "导入文件正文" in joined
    cited = [item for item in prepared.citations if item.target_id == note["id"]]
    assert cited and cited[0].kind == "import"
    assert "分布式搜索" in cited[0].chunk_text
    assert not any("无法读取正文" in notice for notice in prepared.notices)
    assert any(stage[0] == "files" and "1 个附件" in stage[2] for stage in stages)
