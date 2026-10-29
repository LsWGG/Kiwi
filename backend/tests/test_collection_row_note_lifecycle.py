"""数据表记录与行笔记解耦：删行保留笔记，删笔记不丢整条记录。"""

from __future__ import annotations


async def _create_row_note(client, kb_id: str, database_id: str) -> tuple[str, str]:
    row_resp = await client.post(
        f"/api/notes/{database_id}/rows?kb_id={kb_id}",
        json={"data": {"name": "记录一"}},
    )
    assert row_resp.status_code == 201, row_resp.text
    row = row_resp.json()

    notes_resp = await client.post(
        f"/api/notes/{database_id}/rows/notes?kb_id={kb_id}",
        json={"row_ids": [row["id"]]},
    )
    assert notes_resp.status_code == 200, notes_resp.text
    note = notes_resp.json()[0]
    return row["id"], note["note_id"]


async def test_delete_row_keeps_note_as_plain_doc(client, kb, note_factory):
    database = await note_factory(kind="database", title="测试数据表")
    row_id, note_id = await _create_row_note(client, kb["id"], database["id"])

    deleted = await client.delete(
        f"/api/notes/{database['id']}/rows/{row_id}?kb_id={kb['id']}"
    )
    assert deleted.status_code == 204, deleted.text

    rows = await client.get(f"/api/notes/{database['id']}/rows?kb_id={kb['id']}")
    assert rows.status_code == 200, rows.text
    assert rows.json() == []

    note = await client.get(f"/api/notes/{note_id}?kb_id={kb['id']}")
    assert note.status_code == 200, note.text
    props = note.json()["props_json"]
    assert "collection_row_id" not in props
    assert "collection_note_id" not in props
    assert "collection_id" not in props


async def test_batch_delete_rows_keeps_notes(client, kb, note_factory):
    database = await note_factory(kind="database", title="批量数据表")
    first_row, first_note = await _create_row_note(client, kb["id"], database["id"])
    second_row, second_note = await _create_row_note(client, kb["id"], database["id"])

    resp = await client.post(
        f"/api/notes/{database['id']}/rows/batch-delete?kb_id={kb['id']}",
        json={"row_ids": [first_row, second_row]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 2, "notes_kept": 2}

    for note_id in (first_note, second_note):
        note = await client.get(f"/api/notes/{note_id}?kb_id={kb['id']}")
        assert note.status_code == 200, note.text
        assert "collection_row_id" not in note.json()["props_json"]


async def test_trash_and_restore_rebind_row_note(client, kb, note_factory):
    database = await note_factory(kind="database", title="回收站数据表")
    row_id, note_id = await _create_row_note(client, kb["id"], database["id"])

    trashed = await client.delete(f"/api/notes/{note_id}?kb_id={kb['id']}")
    assert trashed.status_code == 204, trashed.text
    rows = await client.get(f"/api/notes/{database['id']}/rows?kb_id={kb['id']}")
    row = next(item for item in rows.json() if item["id"] == row_id)
    assert row["note_id"] is None

    restored = await client.post(f"/api/notes/{note_id}/restore?kb_id={kb['id']}")
    assert restored.status_code == 200, restored.text
    rows = await client.get(f"/api/notes/{database['id']}/rows?kb_id={kb['id']}")
    row = next(item for item in rows.json() if item["id"] == row_id)
    assert row["note_id"] == note_id


async def test_permanent_delete_row_note_keeps_row(client, kb, note_factory):
    database = await note_factory(kind="database", title="永久删除数据表")
    row_id, note_id = await _create_row_note(client, kb["id"], database["id"])

    await client.delete(f"/api/notes/{note_id}?kb_id={kb['id']}")
    purged = await client.delete(
        f"/api/notes/{note_id}/permanent?kb_id={kb['id']}"
    )
    assert purged.status_code == 204, purged.text

    rows = await client.get(f"/api/notes/{database['id']}/rows?kb_id={kb['id']}")
    assert any(item["id"] == row_id for item in rows.json())
    gone = await client.get(f"/api/notes/{note_id}?kb_id={kb['id']}")
    assert gone.status_code == 404
