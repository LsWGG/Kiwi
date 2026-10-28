"""桌面版本地设置：离线策略与本机执行开关（JSON 原子读写）。

设置存放在用户数据目录，不进入数据库；文件缺失或损坏时一律回到最安全的
默认值，绝不因为解析失败而开启联网或本机执行。Docker 部署不读取该文件。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger("kiwi.desktop.settings")

SETTINGS_VERSION = 1
MIN_CODE_TIMEOUT = 5
MAX_CODE_TIMEOUT = 600
DEFAULT_CODE_TIMEOUT = 60

_lock = threading.Lock()


def settings_path() -> Path:
    return settings.desktop_settings_path or settings.data_dir / "desktop-settings.json"


@dataclass(slots=True)
class DesktopSettings:
    version: int = SETTINGS_VERSION
    allow_online_models: bool = False
    acknowledged_online_models_at: str | None = None
    local_code_execution: bool = False
    acknowledged_local_code_at: str | None = None
    local_code_timeout_seconds: int = DEFAULT_CODE_TIMEOUT
    updated_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_timestamp(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _as_timeout(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_CODE_TIMEOUT
    return max(MIN_CODE_TIMEOUT, min(MAX_CODE_TIMEOUT, value))


def _from_mapping(data: dict) -> DesktopSettings:
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        version = SETTINGS_VERSION
    return DesktopSettings(
        version=version,
        allow_online_models=_as_bool(data.get("allow_online_models"), False),
        acknowledged_online_models_at=_as_timestamp(
            data.get("acknowledged_online_models_at")
        ),
        local_code_execution=_as_bool(data.get("local_code_execution"), False),
        acknowledged_local_code_at=_as_timestamp(
            data.get("acknowledged_local_code_at")
        ),
        local_code_timeout_seconds=_as_timeout(data.get("local_code_timeout_seconds")),
        updated_at=_as_timestamp(data.get("updated_at")),
    )


def _read_unlocked() -> DesktopSettings:
    path = settings_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DesktopSettings()
    except OSError as exc:
        logger.warning("读取桌面设置失败，使用安全默认值：%s", exc)
        return DesktopSettings()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("桌面设置文件损坏，使用安全默认值：%s", path)
        return DesktopSettings()
    if not isinstance(data, dict):
        logger.warning("桌面设置文件结构无效，使用安全默认值：%s", path)
        return DesktopSettings()
    return _from_mapping(data)


def load() -> DesktopSettings:
    with _lock:
        return _read_unlocked()


def online_models_allowed() -> bool:
    """Docker 恒为真；桌面模式读取本地开关（缺失 / 损坏时为 False）。"""
    return not settings.desktop_mode or load().allow_online_models


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            # Windows 由 LocalAppData 的用户 ACL 保护，chmod 语义不同。
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def save(value: DesktopSettings) -> DesktopSettings:
    value.version = SETTINGS_VERSION
    value.local_code_timeout_seconds = _as_timeout(value.local_code_timeout_seconds)
    value.updated_at = _now()
    with _lock:
        _write_atomic(settings_path(), asdict(value))
    return value
