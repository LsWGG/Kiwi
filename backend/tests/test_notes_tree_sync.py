"""目录树懒加载、增量刷新与深链定位。"""

from __future__ import annotations

import asyncio
import uuid


async def _folder(client, kb_id: str, name: str, parent_id: str | None = None) -> dict:
    resp = await client.post(
        f"/api/notes/folders?kb_id={kb_id}",
        json={"name": name, "parent_id": parent_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_lazy_tree_children_and_search(client, kb, note_factory):
    root = await note_factory(title="根级笔记")
    folder = await _folder(client, kb["id"], "资料")
    in_folder = await note_factory(title="分组内笔记", folder_id=folder["id"])
    child = await note_factory(title="子笔记", parent_note_id=root["id"])

    tree = await client.get(f"/api/notes/tree?kb_id={kb['id']}&lazy=1")
    assert tree.status_code == 200
    body = tree.json()
    ids = {item["id"] for item in body["notes"]}
    assert body["lazy"] is True
    assert body["total_notes"] == 3
    assert root["id"] in ids
    assert in_folder["id"] not in ids
    assert child["id"] not in ids
    assert body["server_time"]

    children = await client.get(
        f"/api/notes/tree/children?kb_id={kb['id']}"
        f"&ids={folder['id']},{root['id']}"
    )
    assert children.status_code == 200
    child_ids = {item["id"] for item in children.json()["notes"]}
    assert child_ids == {in_folder["id"], child["id"]}

    # 非法 ID 明确报错，避免静默返回空列表掩盖前端拼接错误。
    bad = await client.get(f"/api/notes/tree/children?kb_id={kb['id']}&ids=not-a-uuid")
    assert bad.status_code == 400

    hits = await client.get(f"/api/notes/tree/search?kb_id={kb['id']}&q=分组内")
    assert hits.status_code == 200
    assert [item["id"] for item in hits.json()] == [in_folder["id"]]

    # 默认（非 lazy）仍返回全部笔记，保持旧客户端兼容。
    full = await client.get(f"/api/notes/tree?kb_id={kb['id']}")
    assert {item["id"] for item in full.json()["notes"]} == {
        root["id"],
        in_folder["id"],
        child["id"],
    }


async def test_incremental_refresh_tombstones(client, kb, note_factory):
    folder = await _folder(client, kb["id"], "将被删除的分组")
    note = await note_factory(title="增量笔记", folder_id=folder["id"])

    base = await client.get(f"/api/notes/tree?kb_id={kb['id']}&lazy=1")
    assert base.status_code == 200
    cursor = base.json()["server_time"]

    await asyncio.sleep(0.1)
    added = await note_factory(title="后加的笔记")
    delta = await client.get(
        f"/api/notes/tree?kb_id={kb['id']}&since={cursor}&lazy=1"
    )
    assert delta.status_code == 200
    payload = delta.json()
    assert payload["incremental"] is True
    # 注意：2 秒重叠窗口内刚创建的节点可能重复出现；合并按 ID 幂等。
    assert added["id"] in {item["id"] for item in payload["notes"]}

    cursor = payload["server_time"]
    await asyncio.sleep(0.1)
    moved = await client.delete(f"/api/notes/{added['id']}?kb_id={kb['id']}")
    assert moved.status_code == 204
    delta = await client.get(
        f"/api/notes/tree?kb_id={kb['id']}&since={cursor}&lazy=1"
    )
    assert delta.status_code == 200
    assert added["id"] in delta.json()["deleted_note_ids"]

    # 永久删除写入墓碑，即使原始行已不存在也能通知客户端。
    cursor = delta.json()["server_time"]
    await asyncio.sleep(0.1)
    permanent = await client.delete(
        f"/api/notes/{added['id']}/permanent?kb_id={kb['id']}"
    )
    assert permanent.status_code == 204
    delta = await client.get(
        f"/api/notes/tree?kb_id={kb['id']}&since={cursor}&lazy=1"
    )
    assert added["id"] in delta.json()["deleted_note_ids"]

    # 分组删除同样通过墓碑通知；分组内笔记一并进入回收站。
    cursor = delta.json()["server_time"]
    await asyncio.sleep(0.1)
    removed = await client.delete(
        f"/api/notes/folders/{folder['id']}?kb_id={kb['id']}"
    )
    assert removed.status_code == 204
    delta = (await client.get(
        f"/api/notes/tree?kb_id={kb['id']}&since={cursor}&lazy=1"
    )).json()
    assert folder["id"] in delta["deleted_folder_ids"]
    assert note["id"] in delta["deleted_note_ids"]


async def test_delete_folder_cascades_children_to_trash(client, kb, note_factory):
    """删除父分组：子分组、子分组内笔记和子笔记都进入回收站，均可恢复。"""
    parent = await _folder(client, kb["id"], "父分组")
    child = await _folder(client, kb["id"], "子分组", parent_id=parent["id"])
    in_parent = await note_factory(title="父分组笔记", folder_id=parent["id"])
    in_child = await note_factory(title="子分组笔记", folder_id=child["id"])
    nested = await note_factory(title="子笔记", parent_note_id=in_parent["id"])
    outside = await note_factory(title="外部笔记")

    resp = await client.delete(f"/api/notes/folders/{parent['id']}?kb_id={kb['id']}")
    assert resp.status_code == 204

    tree = (await client.get(f"/api/notes/tree?kb_id={kb['id']}")).json()
    assert {f["id"] for f in tree["folders"]} == set()
    assert {n["id"] for n in tree["notes"]} == {outside["id"]}

    trash = (await client.get(f"/api/notes/trash?kb_id={kb['id']}")).json()
    assert {n["id"] for n in trash["items"]} == {
        in_parent["id"],
        in_child["id"],
        nested["id"],
    }

    # 恢复父分组内的笔记时，随父笔记一起删除的子笔记同步恢复。
    restored = await client.post(
        f"/api/notes/{in_parent['id']}/restore?kb_id={kb['id']}"
    )
    assert restored.status_code == 200
    body = restored.json()
    # 原分组已不存在，恢复到根级。
    assert body["folder_id"] is None
    child_note = (await client.get(f"/api/notes/{nested['id']}?kb_id={kb['id']}")).json()
    assert child_note["status"] == "active"


async def test_tree_node_location_ancestors(client, kb, note_factory):
    folder = await _folder(client, kb["id"], "外层")
    nested = await _folder(client, kb["id"], "内层", parent_id=folder["id"])
    parent_note = await note_factory(title="父笔记", folder_id=nested["id"])
    target = await note_factory(title="目标笔记", parent_note_id=parent_note["id"])

    resp = await client.get(
        f"/api/notes/tree/node/{target['id']}?kb_id={kb['id']}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"]["id"] == target["id"]
    assert {folder["id"], nested["id"], parent_note["id"]} <= set(
        body["ancestor_ids"]
    )

    missing = await client.get(
        f"/api/notes/tree/node/{uuid.uuid4()}?kb_id={kb['id']}"
    )
    assert missing.status_code == 404
