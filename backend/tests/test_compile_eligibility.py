"""编译资格与「删除全部编译数据」。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import Note, Source
from app.services.compile_eligibility import (
    SKIP_COLLECTION_ROW,
    SKIP_READONLY_IMPORT,
    SKIP_TODO_HUB,
    note_compile_skip_reason,
)


def _note(**props) -> Note:
    return Note(kb_id=uuid.uuid4(), title="测试", props_json=props)


def test_skip_reasons():
    assert note_compile_skip_reason(_note()) is None
    assert note_compile_skip_reason(_note(todo_hub=True)) == SKIP_TODO_HUB
    assert note_compile_skip_reason(_note(todo_hub="true")) == SKIP_TODO_HUB
    assert note_compile_skip_reason(_note(readonly=True)) == SKIP_READONLY_IMPORT
    assert (
        note_compile_skip_reason(_note(**{"import": {"readonly": True}}))
        == SKIP_READONLY_IMPORT
    )
    assert (
        note_compile_skip_reason(_note(collection_row_id=str(uuid.uuid4())))
        == SKIP_COLLECTION_ROW
    )
    # 普通导入（可编辑）仍参与编译。
    assert note_compile_skip_reason(
        _note(**{"import": {"readonly": False}})
    ) is None


async def test_compile_all_skips_system_notes(client, kb, note_factory):
    normal = await note_factory(title="普通文档", body_md="正文")
    await note_factory(title="待办汇总", props_json={"todo_hub": True})
    await note_factory(
        title="只读导入", props_json={"readonly": True}
    )
    await note_factory(
        title="只读链接",
        props_json={"readonly": True, "link": {"url": "https://example.com"}},
    )
    await note_factory(
        title="数据表行笔记", props_json={"collection_row_id": str(uuid.uuid4())}
    )

    resp = await client.post(f"/api/notes/compile-all?kb_id={kb['id']}")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["candidates"] == 1
    assert body["count"] == 1
    assert [job["note_id"] for job in body["jobs"]] == [normal["id"]]


async def test_single_compile_rejects_ineligible(client, kb, note_factory):
    hub = await note_factory(
        title="待办汇总", body_md="有正文", props_json={"todo_hub": True}
    )
    resp = await client.post(f"/api/notes/{hub['id']}/compile?kb_id={kb['id']}")
    assert resp.status_code == 400
    assert "无需编译" in resp.json()["detail"]

    imported = await note_factory(
        title="只读材料", body_md="有正文", props_json={"readonly": True}
    )
    resp = await client.post(f"/api/notes/{imported['id']}/compile?kb_id={kb['id']}")
    assert resp.status_code == 400
    assert "无需编译" in resp.json()["detail"]


async def test_delete_all_compiled_data(client, kb, note_factory, db):
    note = await note_factory(title="保留的笔记", body_md="正文")
    await client.post(f"/api/notes/compile-all?kb_id={kb['id']}")

    page = await client.post(
        f"/api/wiki?kb_id={kb['id']}",
        json={"title": "将被删除的页面", "body_md": "页面正文"},
    )
    assert page.status_code == 201, page.text
    page_id = page.json()["id"]

    # 模拟历史编译留下的软关联。
    row = await db.get(Note, uuid.UUID(note["id"]))
    row.props_json = {
        **(row.props_json or {}),
        "wiki_page_id": page_id,
        "wiki_links": [page_id],
    }
    await db.commit()

    resp = await client.delete(f"/api/wiki/compiled?kb_id={kb['id']}")
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["deleted_pages"] == 1
    assert stats["deleted_snapshots"] >= 1

    assert (await client.get(f"/api/wiki/{page_id}?kb_id={kb['id']}")).status_code == 404

    db.expire_all()
    refreshed = await db.get(Note, uuid.UUID(note["id"]))
    assert refreshed is not None
    assert "wiki_page_id" not in (refreshed.props_json or {})
    assert "wiki_links" not in (refreshed.props_json or {})

    snapshots = (
        (
            await db.execute(
                select(Source).where(
                    Source.kb_id == uuid.UUID(kb["id"]),
                    Source.external_id == f"note:{note['id']}",
                )
            )
        )
        .scalars()
        .all()
    )
    assert snapshots == []
