"""知识库列表聚合计数：批量查询结果必须与逐库统计一致。"""

from __future__ import annotations

import uuid


async def test_list_kbs_batches_note_counts(client, kb, note_factory):
    other = await client.post(
        "/api/kbs", json={"name": f"pytest-overview-{uuid.uuid4().hex[:8]}"}
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    try:
        await note_factory(title="overview-a")
        await note_factory(title="overview-b")
        resp = await client.post(
            f"/api/notes?kb_id={other_id}",
            json={"title": "overview-c", "kind": "doc"},
        )
        assert resp.status_code == 201, resp.text

        listing = await client.get("/api/kbs")
        assert listing.status_code == 200, listing.text
        by_id = {item["id"]: item for item in listing.json()}
        assert by_id[kb["id"]]["note_count"] == 2
        assert by_id[other_id]["note_count"] == 1

        single = await client.get(f"/api/kbs/{kb['id']}")
        assert single.status_code == 200, single.text
        assert single.json()["note_count"] == 2
        assert single.json()["last_activity_at"] is not None
    finally:
        await client.delete(f"/api/kbs/{other_id}")
