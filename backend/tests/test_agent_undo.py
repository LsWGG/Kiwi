"""Agent 写操作撤销：创建 → 回收站、更新 → 恢复旧内容、删除 → 从回收站恢复。"""

from __future__ import annotations

import uuid

from app.db.models import Note
from app.services import agent_undo


async def _create_note(client, kb_id, *, title: str, body: str) -> str:
    resp = await client.post(
        f"/api/notes?kb_id={kb_id}",
        json={"title": title, "kind": "doc", "body_md": body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_undo_create_moves_note_to_trash(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    note_id = await _create_note(client, kb_id, title="撤销新建", body="正文")
    record = agent_undo.register(
        tool="create_note",
        kb_id=kb_id,
        label="新建笔记",
        snapshot={},
        result={"ok": True, "note": {"id": note_id, "title": "撤销新建"}},
    )
    assert record is not None
    message = await agent_undo.execute(record, db)
    assert "回收站" in message
    note = await db.get(Note, uuid.UUID(note_id))
    assert note is not None and note.status == "trash"


async def test_undo_update_restores_previous_fields(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    note_id = await _create_note(client, kb_id, title="旧标题", body="旧正文")
    snapshot = await agent_undo.capture_before(
        db, kb_id, "update_note", {"note_id": note_id}
    )
    assert snapshot["body_md"] == "旧正文"

    resp = await client.patch(
        f"/api/notes/{note_id}?kb_id={kb_id}",
        json={"title": "新标题", "body_md": "新正文"},
    )
    assert resp.status_code == 200, resp.text
    record = agent_undo.register(
        tool="update_note",
        kb_id=kb_id,
        label="修改笔记",
        snapshot=snapshot,
        result={"ok": True, "note": {"id": note_id, "title": "新标题"}},
    )
    assert record is not None
    db.expire_all()
    await agent_undo.execute(record, db)

    detail = await client.get(f"/api/notes/{note_id}?kb_id={kb_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "旧标题"
    assert body["body_md"] == "旧正文"


async def test_undo_delete_restores_from_trash(client, kb, db):
    kb_id = uuid.UUID(kb["id"])
    note_id = await _create_note(client, kb_id, title="撤销删除", body="正文")
    snapshot = await agent_undo.capture_before(
        db, kb_id, "delete_note", {"note_id": note_id}
    )
    resp = await client.delete(f"/api/notes/{note_id}?kb_id={kb_id}")
    assert resp.status_code == 204, resp.text

    record = agent_undo.register(
        tool="delete_note",
        kb_id=kb_id,
        label="移入回收站",
        snapshot=snapshot,
        result={"ok": True, "note_id": note_id, "status": "trash"},
    )
    assert record is not None
    db.expire_all()
    message = await agent_undo.execute(record, db)
    assert "恢复" in message
    db.expire_all()
    note = await db.get(Note, uuid.UUID(note_id))
    assert note is not None and note.status == "active"
