"""自动备份：pg_dump + uploads + manifest，按保留天数清理。

备份目录结构::

    data/backups/kiwi-20261021-120000/
      db.dump          # PostgreSQL custom format
      uploads.tar.gz   # 素材与附件
      manifest.json    # 版本、校验和、文件清单

恢复必须由管理员执行 ``scripts/restore_backup.sh``，应用内不提供一键覆盖
（覆盖数据库属于不可逆操作）。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import tarfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.build_info import APP_VERSION, git_commit
from app.config import settings

logger = logging.getLogger("kiwi.backup")

FORMAT = "kiwi-backup"
VERSION = 1
_lock = asyncio.Lock()
_scheduler_task: asyncio.Task | None = None


class BackupError(Exception):
    pass


def backup_root() -> Path:
    root = settings.backup_dir
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def _db_env() -> dict[str, str]:
    raw = settings.database_url
    # SQLAlchemy 驱动前缀 asyncpg 需要去掉才能被 libpq 识别；这里只取连接参数。
    parsed = urlsplit(raw.replace("postgresql+asyncpg", "postgresql"))
    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname or "localhost"
    env["PGPORT"] = str(parsed.port or 5432)
    env["PGUSER"] = unquote(parsed.username or "kiwi")
    env["PGPASSWORD"] = unquote(parsed.password or "")
    env["PGDATABASE"] = (parsed.path or "/kiwi").lstrip("/") or "kiwi"
    return env


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_uploads(target: Path) -> bool:
    upload_dir = settings.upload_dir
    if not upload_dir.is_absolute():
        upload_dir = Path.cwd() / upload_dir
    if not upload_dir.exists():
        return False
    root = backup_root()
    with tarfile.open(target, "w:gz") as tar:
        for path in sorted(upload_dir.rglob("*")):
            if path.is_dir():
                continue
            if root in path.parents:
                continue
            tar.add(path, arcname=str(path.relative_to(upload_dir)))
    return True


def _prune() -> list[str]:
    """只清理备份目录下形如 kiwi-* 的目录，保留策略按 manifest 时间。"""
    root = backup_root()
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, settings.backup_retention_days))
    removed: list[str] = []
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith("kiwi-"):
            continue
        manifest = child / "manifest.json"
        try:
            data = json.loads(manifest.read_text("utf-8"))
            created = datetime.fromisoformat(str(data["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (OSError, ValueError, KeyError, TypeError):
            try:
                created = datetime.fromtimestamp(child.stat().st_mtime, timezone.utc)
            except OSError:
                continue
        if created < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    if removed:
        logger.info("清理过期备份：%s", ", ".join(removed))
    return removed


async def create_backup(trigger: str = "manual", label: str = "") -> dict:
    """执行一次备份；同一进程内串行，避免 pg_dump 互相争抢。"""
    if _lock.locked():
        raise BackupError("已有备份正在执行")
    async with _lock:
        pg_dump = shutil.which("pg_dump")
        if pg_dump is None:
            raise BackupError(
                "未找到 pg_dump。请安装 postgresql-client，或使用 scripts/backup.sh 在宿主机执行。"
            )
        root = backup_root()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"kiwi-{stamp}"
        if label:
            safe = "".join(c for c in label if c.isalnum() or c in "-_")[:32]
            if safe:
                name = f"{name}-{safe}"
        target = root / name
        suffix = 1
        while target.exists():
            suffix += 1
            target = root / f"{name}-{suffix}"
        tmp = root / f".tmp-{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=False)
        created_at = datetime.now(timezone.utc)
        try:
            db_file = tmp / "db.dump"
            env = _db_env()
            proc = await asyncio.create_subprocess_exec(
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(db_file),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise BackupError(
                    "pg_dump 失败：" + (stderr.decode("utf-8", "ignore").strip()[-500:] or "未知错误")
                )
            uploads_file = tmp / "uploads.tar.gz"
            uploads_included = await asyncio.to_thread(_archive_uploads, uploads_file)
            files = [
                {
                    "name": "db.dump",
                    "size": db_file.stat().st_size,
                    "sha256": await asyncio.to_thread(_sha256, db_file),
                }
            ]
            if uploads_included:
                files.append(
                    {
                        "name": "uploads.tar.gz",
                        "size": uploads_file.stat().st_size,
                        "sha256": await asyncio.to_thread(_sha256, uploads_file),
                    }
                )
            manifest = {
                "format": FORMAT,
                "version": VERSION,
                "name": target.name,
                "created_at": created_at.isoformat(),
                "trigger": trigger,
                "app_version": APP_VERSION,
                "git_commit": git_commit(),
                "database": {
                    "host": env["PGHOST"],
                    "port": env["PGPORT"],
                    "database": env["PGDATABASE"],
                },
                "uploads_included": uploads_included,
                "retention_days": settings.backup_retention_days,
                "files": files,
            }
            (tmp / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
            )
            tmp.rename(target)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        removed = await asyncio.to_thread(_prune)
        logger.info("备份完成：%s（清理 %s 个旧备份）", target.name, len(removed))
        return {**manifest, "path": str(target), "pruned": removed}


def list_backups() -> list[dict]:
    root = backup_root()
    if not root.exists():
        return []
    items: list[dict] = []
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith("kiwi-"):
            continue
        manifest = child / "manifest.json"
        try:
            data = json.loads(manifest.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        data["path"] = str(child)
        items.append(data)
    items.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return items


def latest_backup() -> dict | None:
    items = list_backups()
    return items[0] if items else None


def _due(now: datetime) -> bool:
    if not settings.backup_enabled or settings.backup_interval_hours <= 0:
        return False
    latest = latest_backup()
    if latest is None:
        return True
    try:
        created = datetime.fromisoformat(str(latest["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return True
    return created + timedelta(hours=settings.backup_interval_hours) <= now


async def _loop() -> None:
    # 启动后稍等，避免与迁移、演示库初始化争抢磁盘与数据库。
    await asyncio.sleep(30)
    while True:
        try:
            if _due(datetime.now(timezone.utc)):
                try:
                    await create_backup(trigger="schedule")
                except BackupError as e:
                    logger.warning("定时备份跳过：%s", e)
                except Exception:  # noqa: BLE001
                    logger.exception("定时备份失败")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("备份调度异常")
        await asyncio.sleep(3600)


def start_backup_task() -> asyncio.Task | None:
    global _scheduler_task
    if not settings.backup_enabled:
        logger.info("KIWI_BACKUP_ENABLED=false：自动备份未启动")
        return None
    if _scheduler_task is not None and not _scheduler_task.done():
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_loop(), name="kiwi-backup-scheduler")
    return _scheduler_task


async def stop_backup_task(task: asyncio.Task | None) -> None:
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


__all__ = [
    "BackupError",
    "backup_root",
    "create_backup",
    "latest_backup",
    "list_backups",
    "start_backup_task",
    "stop_backup_task",
]
