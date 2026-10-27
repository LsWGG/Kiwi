"""素材原文件路径回归：相对 raw_path 解析与重复导入自愈。"""

from __future__ import annotations

import uuid
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.models import Source
from app.db.session import async_session_factory
from app.services.source_paths import resolve_raw_path


def test_upload_dir_is_absolute():
    assert Path(settings.upload_dir).is_absolute()


def test_resolve_legacy_relative_path():
    kb_id = uuid.uuid4()
    path = resolve_raw_path(f"data/uploads/{kb_id}/abc.md")
    assert path.is_absolute()
    assert path.parent.name == str(kb_id)
    assert path.name == "abc.md"


def test_resolve_plain_relative_path():
    assert resolve_raw_path("media/x.png") == Path(settings.upload_dir) / "media" / "x.png"


async def test_reimport_rewrites_stale_relative_source(client, kb):
    """共享数据库里的旧 Source 指向别的环境时，重新上传应自愈。"""
    content = "# 路径回归\n\n重复导入应重新落盘。\n".encode()
    files = {"file": ("legacy.md", content, "text/markdown")}

    first = await client.post(f"/api/notes/import?kb_id={kb['id']}", files=files)
    assert first.status_code == 202, first.text

    fingerprint = sha256(content).hexdigest()
    async with async_session_factory() as db:
        source = (
            await db.execute(
                select(Source).where(
                    Source.kb_id == uuid.UUID(kb["id"]),
                    Source.sha256 == fingerprint,
                )
            )
        ).scalar_one()
        canonical = Path(source.raw_path)
        assert canonical.is_absolute() and canonical.exists()
        # 模拟另一环境留下的记录：相对路径，且文件不在当前目录下。
        source.raw_path = f"data/uploads/{kb['id']}/{canonical.name}"
        await db.commit()
        source_id = source.id
    canonical.unlink()

    second = await client.post(f"/api/notes/import?kb_id={kb['id']}", files=files)
    assert second.status_code == 202, second.text

    async with async_session_factory() as db:
        source = await db.get(Source, source_id)
        assert source is not None
        resolved = Path(source.raw_path)
        assert resolved.is_absolute()
        assert resolved.exists()
        assert resolved.read_bytes() == content
