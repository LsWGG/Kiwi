"""会话自动标题：长问题按固定字数裁剪，不把整段提问写进侧栏。"""

from __future__ import annotations

import uuid


async def _create(client, content: str) -> dict:
    resp = await client.post(
        "/api/chat/sessions",
        json={
            "scope": {"scope": "global", "kb_ids": [str(uuid.uuid4())]},
            "intent": "auto",
            "messages": [{"role": "user", "content": content}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_auto_title_trims_long_first_question(client):
    question = (
        "请帮我规划一个从北京出发去天津的三天旅游行程，包含交通、住宿、餐饮和景点预约，"
        "并整理成一篇结构完整的旅游规划笔记放到知识库根目录下"
    )
    created = await _create(client, question)
    try:
        title = created["title"]
        assert title.endswith("…")
        assert len(title) <= 25
        assert title.rstrip("…") in question
    finally:
        await client.delete(f"/api/chat/sessions/{created['id']}")


async def test_session_keeps_agent_progress_metadata(client):
    steps = [
        {
            "id": "tool-1",
            "message": "读取网页完成",
            "detail": "网页正文",
            "status": "done",
        }
    ]
    plan = [{"id": "p1", "title": "读取网页", "status": "done"}]
    resp = await client.post(
        "/api/chat/sessions",
        json={
            "scope": {"scope": "global", "kb_ids": [str(uuid.uuid4())]},
            "intent": "auto",
            "messages": [
                {
                    "role": "assistant",
                    "content": "已完成。",
                    "steps": steps,
                    "plan": plan,
                    "trace_id": "trace-abc-123",
                    "started_at": 1000,
                    "finished_at": 26000,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    try:
        detail = await client.get(f"/api/chat/sessions/{session_id}")
        message = detail.json()["messages"][0]
        assert message["steps"] == steps
        assert message["plan"] == plan
        assert message["trace_id"] == "trace-abc-123"
        assert message["started_at"] == 1000
        assert message["finished_at"] == 26000
    finally:
        await client.delete(f"/api/chat/sessions/{session_id}")


async def test_auto_title_keeps_short_question(client):
    created = await _create(client, "你好")
    try:
        assert created["title"] == "你好"
    finally:
        await client.delete(f"/api/chat/sessions/{created['id']}")
