"""只读分享链接：有效期、访问密码、媒体签名与撤销。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import update

from app.config import settings


def _write_media(rel: str, content: bytes) -> Path:
    root = Path(settings.upload_dir) / "media"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


async def _create_share(client, kb_id: str, note_id: str, **payload) -> dict:
    resp = await client.post(
        f"/api/notes/{note_id}/shares?kb_id={kb_id}",
        json={"expires_in_hours": 24, **payload},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_share_lifecycle_public_content_and_media(client, kb, note_factory):
    rel = f"pytest-share/{uuid.uuid4().hex}.png"
    media_path = _write_media(rel, b"\x89PNG\r\n\x1a\nshare")
    note = await note_factory(
        title="分享验证",
        body_md=f"# 分享验证\n\n这是公开段落。\n\n![示意图](/media/{rel})",
    )
    try:
        share = await _create_share(client, kb["id"], note["id"])
        assert share["active"] is True
        assert share["has_password"] is False
        assert share["path"] == f"/share/{share['token']}"

        resp = await client.get(f"/api/share/{share['token']}")
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"] == "no-store"
        data = resp.json()
        assert data["title"] == "分享验证"
        # 分享页单独展示标题，正文不再重复一级标题
        assert not data["body_md"].startswith("# 分享验证")
        assert "这是公开段落。" in data["body_md"]

        match = re.search(r"!\[示意图\]\(([^)]+)\)", data["body_md"])
        assert match, data["body_md"]
        media_url = match.group(1)
        assert f"/api/share/{share['token']}/media/{rel}" in media_url
        media = await client.get(media_url)
        assert media.status_code == 200, media.text
        assert media.content.startswith(b"\x89PNG")

        tail = media_url[:-1] + ("0" if media_url[-1] != "0" else "1")
        tampered = await client.get(tail)
        assert tampered.status_code == 404

        listed = await client.get(f"/api/notes/{note['id']}/shares?kb_id={kb['id']}")
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["view_count"] == 1

        revoked = await client.delete(
            f"/api/notes/{note['id']}/shares/{share['id']}?kb_id={kb['id']}"
        )
        assert revoked.status_code == 204, revoked.text
        expired = await client.get(f"/api/share/{share['token']}")
        assert expired.status_code == 404
        assert expired.json()["detail"]["code"] == "share_revoked"
        listed = await client.get(f"/api/notes/{note['id']}/shares?kb_id={kb['id']}")
        assert listed.json() == []
    finally:
        media_path.unlink(missing_ok=True)


async def test_share_password_and_expiry(client, kb, note_factory):
    note = await note_factory(title="密码分享", body_md="机密内容")
    share = await _create_share(client, kb["id"], note["id"], password="open-sesame")

    missing = await client.get(f"/api/share/{share['token']}")
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "share_password_required"

    wrong = await client.get(
        f"/api/share/{share['token']}", headers={"X-Share-Password": "wrong"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "share_password_invalid"

    ok = await client.get(
        f"/api/share/{share['token']}", headers={"X-Share-Password": "open-sesame"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["body_md"] == "机密内容"
    assert ok.json()["has_password"] is True

    # 手工把有效期改到过去，公开接口应返回 410。
    from app.db.models import NoteShare
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            update(NoteShare)
            .where(NoteShare.id == uuid.UUID(share["id"]))
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()
    expired = await client.get(
        f"/api/share/{share['token']}", headers={"X-Share-Password": "open-sesame"}
    )
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "share_expired"


async def test_locked_note_cannot_be_shared(client, kb, note_factory):
    note = await note_factory(title="上锁笔记", body_md="正文")
    locked = await client.post(
        f"/api/notes/{note['id']}/lock?kb_id={kb['id']}", json={"password": "1234"}
    )
    assert locked.status_code == 200, locked.text

    resp = await client.post(
        f"/api/notes/{note['id']}/shares?kb_id={kb['id']}",
        json={"expires_in_hours": 24},
    )
    assert resp.status_code == 400
    assert "上锁" in resp.json()["detail"]


async def test_share_url_uses_public_base_url(client, kb, note_factory, monkeypatch):
    note = await note_factory(title="公网分享", body_md="正文")
    monkeypatch.setattr(settings, "public_base_url", "https://share.example.com/")
    share = await _create_share(client, kb["id"], note["id"])
    assert share["url"] == f"https://share.example.com/share/{share['token']}"

    # 未配置公网域名时返回 null，由前端回退到当前访问地址。
    monkeypatch.setattr(settings, "public_base_url", "")
    listed = await client.get(f"/api/notes/{note['id']}/shares?kb_id={kb['id']}")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["url"] is None
