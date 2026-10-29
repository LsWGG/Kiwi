"""问答会话按知识库隔离：列表与清空带 kb_id 时只看该库可见的会话。"""

from __future__ import annotations

import uuid


async def _create_session(client, scope: dict) -> str:
    resp = await client.post(
        "/api/chat/sessions",
        json={"scope": scope, "intent": "auto"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_list_sessions_filters_by_kb_scope(client):
    kb_a = str(uuid.uuid4())
    kb_b = str(uuid.uuid4())
    ids = {
        "kb_a": await _create_session(
            client, {"scope": "kb", "kb_ids": [kb_a]}
        ),
        "multi": await _create_session(
            client, {"scope": "multi", "kb_ids": [kb_a, kb_b]}
        ),
        "global": await _create_session(client, {"scope": "global", "kb_ids": []}),
        "kb_b": await _create_session(
            client, {"scope": "kb", "kb_ids": [kb_b]}
        ),
    }
    try:
        listed_a = await client.get(f"/api/chat/sessions?kb_id={kb_a}")
        assert listed_a.status_code == 200, listed_a.text
        ids_a = {item["id"] for item in listed_a.json()["items"]}
        assert ids["kb_a"] in ids_a
        assert ids["multi"] in ids_a
        assert ids["global"] in ids_a
        assert ids["kb_b"] not in ids_a

        listed_b = await client.get(f"/api/chat/sessions?kb_id={kb_b}")
        ids_b = {item["id"] for item in listed_b.json()["items"]}
        assert ids["kb_b"] in ids_b
        assert ids["multi"] in ids_b
        assert ids["global"] in ids_b
        assert ids["kb_a"] not in ids_b

        listed_all = await client.get("/api/chat/sessions")
        ids_all = {item["id"] for item in listed_all.json()["items"]}
        assert set(ids.values()) <= ids_all
    finally:
        for session_id in ids.values():
            await client.delete(f"/api/chat/sessions/{session_id}")


async def test_clear_sessions_only_removes_visible_sessions(client):
    kb_a = str(uuid.uuid4())
    kb_b = str(uuid.uuid4())
    ids = {
        "kb_a": await _create_session(
            client, {"scope": "kb", "kb_ids": [kb_a]}
        ),
        "multi": await _create_session(
            client, {"scope": "multi", "kb_ids": [kb_a, kb_b]}
        ),
        "global": await _create_session(client, {"scope": "global", "kb_ids": []}),
        "kb_b": await _create_session(
            client, {"scope": "kb", "kb_ids": [kb_b]}
        ),
    }
    try:
        cleared = await client.delete(f"/api/chat/sessions?kb_id={kb_a}")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["deleted"] >= 3

        remaining = await client.get("/api/chat/sessions")
        ids_left = {item["id"] for item in remaining.json()["items"]}
        assert ids["kb_a"] not in ids_left
        assert ids["multi"] not in ids_left
        assert ids["global"] not in ids_left
        assert ids["kb_b"] in ids_left
    finally:
        await client.delete(f"/api/chat/sessions/{ids['kb_b']}")
