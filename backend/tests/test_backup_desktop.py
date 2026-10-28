"""桌面版备份路径。

桌面 runtime 通过 ``KIWI_PG_DUMP_PATH`` 指向 pgserver 随包的 ``pg_dump``，
不能只依赖安装目录是否在系统 PATH 中。这里验证配置优先且缺失时明确报错。
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import backup_service


async def test_backup_uses_configured_pg_dump(monkeypatch, tmp_path):
    missing = tmp_path / "pg_dump.exe"
    monkeypatch.setattr(settings, "pg_dump_path", str(missing))

    with pytest.raises(backup_service.BackupError, match="配置的 pg_dump 不存在"):
        await backup_service.create_backup()
