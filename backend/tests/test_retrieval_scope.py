"""@ 目录 / 笔记检索范围：目录展开子树，且与指定笔记取并集。"""

from __future__ import annotations

import uuid

from app.services.retrieval import (
    RetrievalFilters,
    folder_subtree_ids,
    resolve_note_ids,
)


async def _create_folder(client, kb_id: str, name: str, parent_id: str | None = None) -> str:
    resp = await client.post(
        f"/api/notes/folders?kb_id={kb_id}",
        json={"name": name, "parent_id": parent_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_folder_subtree_and_note_union(client, db, kb, note_factory):
    root = await _create_folder(client, kb["id"], "root")
    child = await _create_folder(client, kb["id"], "child", root)
    grandchild = await _create_folder(client, kb["id"], "grandchild", child)
    other = await _create_folder(client, kb["id"], "other")

    root_note = await note_factory(folder_id=root)
    child_note = await note_factory(folder_id=child)
    # 更深层的子目录同样命中。
    deep_note = await note_factory(folder_id=grandchild)
    other_note = await note_factory(folder_id=other)
    loose_note = await note_factory()

    kb_uuid = uuid.UUID(kb["id"])
    subtree = set(
        await folder_subtree_ids(db, [kb_uuid], [uuid.UUID(root)])
    )
    assert subtree == {
        uuid.UUID(root),
        uuid.UUID(child),
        uuid.UUID(grandchild),
    }

    resolved = await resolve_note_ids(
        db,
        [kb_uuid],
        RetrievalFilters(
            folder_ids=[uuid.UUID(root)],
            note_ids=[uuid.UUID(other_note["id"])],
        ),
    )
    assert resolved is not None
    assert set(resolved) == {
        root_note["id"],
        child_note["id"],
        deep_note["id"],
        other_note["id"],
    }
    assert loose_note["id"] not in resolved

    # 目录与笔记并集后，仍与其他筛选条件（类型）取交集。
    narrowed = await resolve_note_ids(
        db,
        [kb_uuid],
        RetrievalFilters(folder_ids=[uuid.UUID(root)], note_kinds=["canvas"]),
    )
    assert narrowed == []


async def test_no_scope_returns_none(db, kb):
    resolved = await resolve_note_ids(db, [uuid.UUID(kb["id"])], RetrievalFilters())
    assert resolved is None
