"""历史版本保留上限：每篇笔记最多 60 个。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.models import NoteRevision


async def test_revisions_are_pruned_to_sixty(client, kb, note_factory, db) -> None:
    note = await note_factory()
    note_id = note["id"]
    for _ in range(62):
        resp = await client.post(f"/api/notes/{note_id}/revisions?kb_id={kb['id']}")
        assert resp.status_code == 201, resp.text

    count = (
        await db.execute(
            select(func.count())
            .select_from(NoteRevision)
            .where(NoteRevision.note_id == uuid.UUID(note_id))
        )
    ).scalar_one()
    assert count == 60

    listing = await client.get(f"/api/notes/{note_id}/revisions?kb_id={kb['id']}")
    assert listing.status_code == 200
    assert len(listing.json()) == 60
