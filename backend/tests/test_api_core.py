"""API 契约集成测试：真实 PostgreSQL，覆盖健康、笔记树、审计与加密锁。"""

from __future__ import annotations

import uuid

from app.db.models import Note


async def test_health_version_and_metrics(client):
    health = await client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    version = await client.get("/api/health/version")
    assert version.status_code == 200
    assert version.json()["version"]
    assert "commit" in version.json()

    detail = await client.get("/api/health/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["postgres"] == "up"
    assert body["version"]["name"] == "Kiwi"

    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "kiwi_http_requests_total" in metrics.text
    assert metrics.headers.get("x-request-id")


async def test_tree_reorder_and_note_crud(client, kb, note_factory):
    first = await note_factory(title="排序一")
    second = await note_factory(title="排序二")

    tree = await client.get(f"/api/notes/tree?kb_id={kb['id']}")
    assert tree.status_code == 200
    titles = [item["title"] for item in tree.json()["notes"]]
    assert titles == ["排序一", "排序二"]

    resp = await client.post(
        f"/api/notes/reorder?kb_id={kb['id']}",
        json={"target": "note", "ordered_ids": [second["id"], first["id"]]},
    )
    assert resp.status_code == 204

    tree = await client.get(f"/api/notes/tree?kb_id={kb['id']}")
    assert [item["title"] for item in tree.json()["notes"]] == ["排序二", "排序一"]

    folder = await client.post(
        f"/api/notes/folders?kb_id={kb['id']}", json={"name": "测试分组"}
    )
    assert folder.status_code == 201
    folder_id = folder.json()["id"]

    patched = await client.patch(
        f"/api/notes/{first['id']}?kb_id={kb['id']}",
        json={"title": "排序一（改）", "folder_id": folder_id},
    )
    assert patched.status_code == 200
    assert patched.json()["folder_id"] == folder_id

    deleted = await client.delete(f"/api/notes/{first['id']}?kb_id={kb['id']}")
    assert deleted.status_code == 204
    trash = await client.get(f"/api/notes/trash?kb_id={kb['id']}")
    assert trash.status_code == 200
    assert any(item["id"] == first["id"] for item in trash.json()["items"])

    emptied = await client.delete(f"/api/notes/trash?kb_id={kb['id']}")
    assert emptied.status_code == 204


async def test_audit_tracks_trash_empty_and_csv(client, kb, note_factory):
    note = await note_factory(title="审计目标")
    assert (await client.delete(f"/api/notes/{note['id']}?kb_id={kb['id']}")).status_code == 204
    assert (await client.delete(f"/api/notes/trash?kb_id={kb['id']}")).status_code == 204

    audit = await client.get(f"/api/audit?kb_id={kb['id']}")
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "note.delete" in actions
    assert "note.trash.empty" in actions
    entry = next(item for item in audit.json()["items"] if item["action"] == "note.trash.empty")
    assert entry["detail"]["count"] == 1
    assert entry["request_id"]

    csv = await client.get(f"/api/audit/export.csv?kb_id={kb['id']}")
    assert csv.status_code == 200
    assert csv.content.startswith(b"\xef\xbb\xbf")
    assert "note.trash.empty" in csv.text


async def test_encrypted_note_lock_and_unlock(client, kb, note_factory, db):
    note = await note_factory(title="加密笔记", body_md="机密正文 alpha")
    lock = await client.post(
        f"/api/notes/{note['id']}/lock?kb_id={kb['id']}",
        json={"password": "test1234", "hint": "测试", "encrypt": True},
    )
    assert lock.status_code == 200, lock.text
    lock_body = lock.json()
    assert lock_body["encrypted"] is True
    token = lock_body["token"]

    locked = await client.get(f"/api/notes/{note['id']}?kb_id={kb['id']}")
    assert locked.status_code == 200
    assert locked.json()["is_locked"] is True
    assert locked.json()["encrypted"] is True
    assert locked.json()["body_md"] == ""

    unlocked = await client.get(
        f"/api/notes/{note['id']}?kb_id={kb['id']}",
        headers={"X-Note-Token": token},
    )
    assert unlocked.json()["body_md"] == "机密正文 alpha"

    wrong = await client.post(
        f"/api/notes/{note['id']}/unlock?kb_id={kb['id']}",
        json={"password": "wrong"},
    )
    assert wrong.status_code == 401

    stored = await db.get(Note, uuid.UUID(note["id"]))
    await db.refresh(stored)
    assert stored.body_md == ""
    assert stored.body_enc
    assert stored.lock_encrypted is True
    assert stored.lock_enc_salt

    removed = await client.request(
        "DELETE",
        f"/api/notes/{note['id']}/lock?kb_id={kb['id']}",
        json={"password": "test1234"},
    )
    assert removed.status_code == 204
    reopened = await client.get(f"/api/notes/{note['id']}?kb_id={kb['id']}")
    assert reopened.json()["body_md"] == "机密正文 alpha"
    assert reopened.json()["encrypted"] is False


async def test_jobs_api_and_cancel(client):
    created = await client.post("/api/maintenance/backups")
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    listing = await client.get("/api/jobs?limit=20&kind=backup")
    assert listing.status_code == 200
    assert any(item["id"] == job_id for item in listing.json()["items"])

    cancelled = await client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_build_info_and_backup_listing(client):
    build = await client.get("/api/maintenance/build-info")
    assert build.status_code == 200
    assert build.json()["version"]

    backups = await client.get("/api/maintenance/backups")
    assert backups.status_code == 200
    assert "items" in backups.json()
    assert "retention_days" in backups.json()
