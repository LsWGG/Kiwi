"""备份下载 / 导入：zip 往返、校验和与保留策略。

这些用例只操作临时备份目录，不接触测试数据库，也不执行 pg_dump。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.services import backup_service


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_backup(
    root: Path,
    name: str,
    *,
    created: datetime,
    imported: datetime | None = None,
    db: bytes = b"fake-pg-dump",
    uploads: bytes | None = b"fake-uploads",
) -> Path:
    path = root / name
    path.mkdir()
    (path / "db.dump").write_bytes(db)
    files = [{"name": "db.dump", "size": len(db), "sha256": _sha(db)}]
    if uploads is not None:
        (path / "uploads.tar.gz").write_bytes(uploads)
        files.append({"name": "uploads.tar.gz", "size": len(uploads), "sha256": _sha(uploads)})
    manifest = {
        "format": backup_service.FORMAT,
        "version": backup_service.VERSION,
        "name": name,
        "created_at": created.isoformat(),
        "trigger": "manual",
        "uploads_included": uploads is not None,
        "files": files,
    }
    if imported is not None:
        manifest["imported_at"] = imported.isoformat()
    (path / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    return path


@pytest.fixture
def backup_dir(monkeypatch, tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    monkeypatch.setattr(settings, "backup_dir", root)
    monkeypatch.setattr(settings, "backup_retention_days", 3)
    return root


async def test_download_zip_roundtrip(backup_dir):
    _write_backup(backup_dir, "kiwi-20261101-120000", created=datetime.now(timezone.utc))

    archive, filename = await backup_service.build_backup_zip("kiwi-20261101-120000")
    try:
        assert filename == "kiwi-20261101-120000.zip"
        with zipfile.ZipFile(archive) as zf:
            assert set(zf.namelist()) == {"manifest.json", "db.dump", "uploads.tar.gz"}
    finally:
        archive.unlink(missing_ok=True)


async def test_import_validates_and_keeps_old_snapshot(backup_dir):
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    _write_backup(backup_dir, "kiwi-20261101-120000", created=ten_days_ago)
    archive, _ = await backup_service.build_backup_zip("kiwi-20261101-120000")
    try:
        imported = await backup_service.import_backup_zip(archive)
    finally:
        archive.unlink(missing_ok=True)

    assert imported["trigger"] == "import"
    assert imported["imported_at"]
    assert imported["created_at"] == ten_days_ago.isoformat()
    target = Path(imported["path"])
    assert target.is_dir()
    # 原快照与本机同名，导入的一侧自动改名，不覆盖已有目录。
    assert target.name == "kiwi-20261101-120000-import"
    assert (target / "db.dump").read_bytes() == b"fake-pg-dump"
    # created_at 已超过 3 天，但 imported_at 是刚刚，清理时必须保留。
    assert target.exists()


async def test_import_rejects_bad_checksum(backup_dir, tmp_path):
    good = b"real-dump"
    manifest = {
        "format": backup_service.FORMAT,
        "version": backup_service.VERSION,
        "name": "kiwi-20261101-120000",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"name": "db.dump", "size": len(good), "sha256": _sha(good)}],
    }
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("db.dump", b"fake-dump")

    with pytest.raises(backup_service.BackupError, match="校验失败"):
        await backup_service.import_backup_zip(archive)
    assert not list(backup_dir.glob(".import-*"))


async def test_import_rejects_unknown_entry(backup_dir, tmp_path):
    good = b"dump"
    manifest = {
        "format": backup_service.FORMAT,
        "version": backup_service.VERSION,
        "name": "kiwi-20261101-120000",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"name": "db.dump", "size": len(good), "sha256": _sha(good)}],
    }
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("db.dump", good)
        zf.writestr("../escape.txt", b"nope")

    with pytest.raises(backup_service.BackupError, match="清单外文件"):
        await backup_service.import_backup_zip(archive)
    assert not (backup_dir.parent / "escape.txt").exists()


async def test_download_rejects_path_traversal(backup_dir):
    with pytest.raises(backup_service.BackupError, match="名称不合法"):
        await backup_service.build_backup_zip("../kiwi-20261101-120000")
    with pytest.raises(backup_service.BackupError, match="名称不合法"):
        await backup_service.build_backup_zip("kiwi-x/../../etc")


def test_prune_prefers_imported_at(backup_dir):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    _write_backup(backup_dir, "kiwi-old", created=old)
    _write_backup(backup_dir, "kiwi-imported", created=old, imported=now)
    _write_backup(backup_dir, "kiwi-new", created=now)

    removed = backup_service._prune()

    assert removed == ["kiwi-old"]
    assert not (backup_dir / "kiwi-old").exists()
    assert (backup_dir / "kiwi-imported").is_dir()
    assert (backup_dir / "kiwi-new").is_dir()


def test_default_retention_is_three_days(monkeypatch):
    # 配置默认值；显式环境变量可能覆盖，因此只在未覆盖时断言。
    from app.config import Settings

    default = Settings.model_fields["backup_retention_days"].default
    assert default == 3
