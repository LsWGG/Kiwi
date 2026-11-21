"""自动备份：pg_dump + uploads + manifest，按保留天数清理。

备份目录结构::

    data/backups/kiwi-20261021-120000/
      db.dump          # PostgreSQL custom format
      uploads.tar.gz   # 素材与附件
      fernet.key       # 桌面版存在时一并备份，换机恢复后模型密钥仍可解密
      manifest.json    # 版本、校验和、文件清单

    备份包含数据库与可选解密密钥，按敏感数据保管。

支持把整个快照目录打包为 zip 下载，也支持导入已有的 zip 备份包。导入只做
校验并落成一份新快照，不会覆盖当前数据库；恢复仍必须由管理员执行
``scripts/restore_backup.sh``（覆盖数据库属于不可逆操作）。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.build_info import APP_VERSION, git_commit
from app.config import settings

logger = logging.getLogger("kiwi.backup")

FORMAT = "kiwi-backup"
VERSION = 1
# 备份快照内允许出现的文件；下载打包与导入校验都以此为准，避免任意路径落盘。
BACKUP_FILES = ("db.dump", "uploads.tar.gz", "fernet.key")
_NAME_PATTERN = re.compile(r"^kiwi-[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_MANIFEST_LIMIT = 1024 * 1024
# 单个导入包的硬上限，防止误传超大文件把数据卷写满。
MAX_IMPORT_BYTES = 50 * 1024 * 1024 * 1024
_lock = asyncio.Lock()
_scheduler_task: asyncio.Task | None = None


class BackupError(Exception):
    pass


class BackupNotFound(BackupError):
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
    """只清理备份目录下形如 kiwi-* 的目录，保留策略按 manifest 时间。

    导入的备份保留 ``created_at`` 作为原始快照时间，但清理时优先看
    ``imported_at``：否则导入一份几天前的备份会立刻被保留策略删掉。
    """
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
            stamp = data.get("imported_at") or data["created_at"]
            created = datetime.fromisoformat(str(stamp))
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


def _resolve_backup_dir(name: str) -> Path:
    """把外部传入的备份名解析为备份根目录下的真实快照目录。

    只接受 ``kiwi-`` 前缀的扁平名称，并再次校验解析后的父目录，阻断
    ``../`` 与指向目录外的符号链接。
    """
    clean = (name or "").strip()
    if not _NAME_PATTERN.fullmatch(clean):
        raise BackupError("备份名称不合法")
    root = backup_root().resolve()
    target = (root / clean).resolve()
    if target.parent != root or not target.is_dir():
        raise BackupNotFound("备份不存在")
    if not (target / "manifest.json").is_file():
        raise BackupNotFound("备份缺少 manifest.json")
    return target


def _build_backup_zip(path: Path) -> Path:
    """把快照目录中允许的文件打成 zip，写到备份根目录的隐藏临时文件。

    数据库转储与 uploads 本身已压缩，这里用 ``ZIP_STORED`` 避免二次压缩
    浪费 CPU；临时文件在响应结束后由调用方删除。
    """
    root = backup_root()
    root.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".download-", suffix=".zip", dir=root)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            zf.write(path / "manifest.json", "manifest.json")
            for name in BACKUP_FILES:
                candidate = path / name
                if candidate.is_file():
                    zf.write(candidate, name)
        return tmp
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


async def build_backup_zip(name: str) -> tuple[Path, str]:
    """生成下载用 zip，返回 ``(临时文件路径, 建议下载文件名)``。"""
    path = _resolve_backup_dir(name)
    if not (path / "db.dump").is_file():
        raise BackupError("备份缺少 db.dump")
    archive = await asyncio.to_thread(_build_backup_zip, path)
    return archive, f"{path.name}.zip"


def _manifest_files(data: object) -> list[dict]:
    """校验 manifest 的 files 清单，返回规范化后的条目。"""
    if not isinstance(data, dict):
        raise BackupError("备份 manifest 格式不正确")
    if data.get("format") != FORMAT:
        raise BackupError("不是 Kiwi 备份包")
    if data.get("version") != VERSION:
        raise BackupError(f"不支持的备份版本：{data.get('version')}")
    raw_files = data.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise BackupError("备份 manifest 缺少文件清单")
    entries: list[dict] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise BackupError("备份文件清单格式不正确")
        name = raw.get("name")
        size = raw.get("size")
        digest = raw.get("sha256")
        if name not in BACKUP_FILES:
            raise BackupError(f"备份包含不支持的文件：{name}")
        if name in seen:
            raise BackupError(f"备份文件重复：{name}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BackupError(f"{name} 的大小无效")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise BackupError(f"{name} 的校验和无效")
        seen.add(name)
        entries.append({"name": name, "size": size, "sha256": digest.lower()})
    if "db.dump" not in seen:
        raise BackupError("备份缺少 db.dump")
    return entries


def _import_backup_zip(source: Path) -> dict:
    """校验 zip 内容并落成一份新快照；不触碰当前数据库。"""
    root = backup_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile as e:
        raise BackupError("备份包不是有效的 zip 文件") from e
    except OSError as e:
        raise BackupError("无法读取备份包") from e
    with zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        names = {info.filename for info in infos}
        if len(names) != len(infos):
            raise BackupError("备份包包含重名文件")
        if "manifest.json" not in names:
            raise BackupError("备份包缺少 manifest.json")
        manifest_info = zf.getinfo("manifest.json")
        if manifest_info.file_size > _MANIFEST_LIMIT:
            raise BackupError("备份 manifest 过大")
        try:
            manifest_raw = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise BackupError("备份 manifest 无法解析") from e
        entries = _manifest_files(manifest_raw)
        expected = {entry["name"] for entry in entries}
        unknown = names - expected - {"manifest.json"}
        if unknown:
            raise BackupError("备份包包含清单外文件")
        missing = expected - names
        if missing:
            raise BackupError("备份包缺少清单文件：" + "、".join(sorted(missing)))

        staging = root / f".import-{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            for entry in entries:
                name = entry["name"]
                dest = staging / name
                digest = hashlib.sha256()
                total = 0
                with zf.open(name) as src, dest.open("wb") as out:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        total += len(block)
                        if total > entry["size"]:
                            raise BackupError(f"{name} 实际大小超过清单记录")
                        digest.update(block)
                        out.write(block)
                if total != entry["size"]:
                    raise BackupError(f"{name} 大小与清单不一致")
                if digest.hexdigest() != entry["sha256"]:
                    raise BackupError(f"{name} 校验失败，备份包可能已损坏")

            now = datetime.now(timezone.utc)
            original = str(manifest_raw.get("name") or "").strip()
            base = original if _NAME_PATTERN.fullmatch(original) else f"kiwi-{now:%Y%m%d-%H%M%S}"
            target = root / base
            if target.exists():
                base = f"{base}-import"
                target = root / base
            suffix = 1
            while target.exists():
                suffix += 1
                target = root / f"{base}-{suffix}"

            manifest = dict(manifest_raw)
            manifest["name"] = target.name
            manifest["trigger"] = "import"
            manifest["imported_at"] = now.isoformat()
            manifest["original_name"] = original or None
            manifest["retention_days"] = settings.backup_retention_days
            manifest["files"] = entries
            manifest["uploads_included"] = any(e["name"] == "uploads.tar.gz" for e in entries)
            manifest["fernet_key_included"] = any(e["name"] == "fernet.key" for e in entries)
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
            )
            staging.rename(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    removed = _prune()
    logger.info("已导入备份：%s（清理 %s 个旧备份）", target.name, len(removed))
    return {**manifest, "path": str(target), "pruned": removed}


async def import_backup_zip(source: Path) -> dict:
    """异步包装：解压、校验和 sha256 计算都放到线程池，避免阻塞事件循环。"""
    return await asyncio.to_thread(_import_backup_zip, source)


async def create_backup(trigger: str = "manual", label: str = "") -> dict:
    """执行一次备份；同一进程内串行，避免 pg_dump 互相争抢。"""
    if _lock.locked():
        raise BackupError("已有备份正在执行")
    async with _lock:
        # 桌面版把 pgserver 随包的 pg_dump.exe 通过 KIWI_PG_DUMP_PATH 注入，
        # 不依赖系统 PATH；Docker 仍回退到镜像内的 pg_dump。
        pg_dump = (settings.pg_dump_path or "").strip()
        if pg_dump:
            if not Path(pg_dump).is_file():
                raise BackupError(f"配置的 pg_dump 不存在：{pg_dump}")
        else:
            pg_dump = shutil.which("pg_dump") or ""
        if not pg_dump:
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
            # 桌面版把模型 API Key 用本地 Fernet 密钥加密后存进数据库；
            # 备份密钥后，换机恢复仍能解密已有配置（Docker 通常只设置环境变量，无文件）。
            fernet_included = False
            fernet_src = Path(settings.data_dir) / "secrets" / "fernet.key"
            if fernet_src.is_file():
                fernet_dst = tmp / "fernet.key"
                await asyncio.to_thread(shutil.copy2, fernet_src, fernet_dst)
                fernet_included = True
                files.append(
                    {
                        "name": "fernet.key",
                        "size": fernet_dst.stat().st_size,
                        "sha256": await asyncio.to_thread(_sha256, fernet_dst),
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
                "fernet_key_included": fernet_included,
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
    "BACKUP_FILES",
    "MAX_IMPORT_BYTES",
    "BackupError",
    "BackupNotFound",
    "backup_root",
    "build_backup_zip",
    "create_backup",
    "import_backup_zip",
    "latest_backup",
    "list_backups",
    "start_backup_task",
    "stop_backup_task",
]
