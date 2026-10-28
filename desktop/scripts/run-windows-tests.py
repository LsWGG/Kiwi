"""Windows CI：用随包 PostgreSQL 16 运行 Windows 专项测试。

GitHub 的 windows-latest 自带 PostgreSQL 14，与生产/打包的 16 不一致。
这里直接用 pgserver 启动同一份 PostgreSQL 16 二进制，建一个临时测试库，
再运行 ``pytest tests/test_windows_runner.py``；结束后清理集群。

用法（在 backend 目录、已安装 pgserver 的虚拟环境中）：

    python ../desktop/scripts/run-windows-tests.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

TEST_DATABASE = "kiwi_windows_test"


def main() -> int:
    if os.name != "nt":
        print("该脚本只用于 Windows CI。", file=sys.stderr)
        return 2

    import pgserver

    base = Path(tempfile.gettempdir()) / "kiwi-windows-tests"
    base.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(base / "pgdata"), cleanup_mode="stop")
    try:
        uri = server.get_uri()
        parsed = urllib.parse.urlsplit(uri)
        try:
            server.psql(f'CREATE DATABASE "{TEST_DATABASE}"')
        except Exception:  # noqa: BLE001 - 重复运行时库已存在
            pass

        userinfo = ""
        if parsed.username:
            userinfo = urllib.parse.quote(parsed.username, safe="")
            if parsed.password:
                userinfo += ":" + urllib.parse.quote(parsed.password, safe="")
            userinfo += "@"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        url = f"postgresql+asyncpg://{userinfo}{host}:{port}/{TEST_DATABASE}"

        env = {
            **os.environ,
            "KIWI_TEST_DATABASE_URL": url,
            "KIWI_QDRANT_URL": os.environ.get(
                "KIWI_QDRANT_URL", "http://127.0.0.1:6333"
            ),
            "KIWI_RATE_LIMIT_ENABLED": "false",
            "KIWI_ACCESS_TOKEN": "",
            "KIWI_BACKGROUND_JOBS": "false",
            "KIWI_KB_SCHEDULER_ENABLED": "false",
            "KIWI_JOB_WORKER_ENABLED": "false",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        print(f"测试数据库：{host}:{port}/{TEST_DATABASE}", flush=True)
        return subprocess.call(
            [sys.executable, "-m", "pytest", "-q", "tests/test_windows_runner.py"],
            env=env,
        )
    finally:
        try:
            server.cleanup()
        except Exception as exc:  # noqa: BLE001 - 清理失败不掩盖测试结果
            print(f"[warn] 清理 PostgreSQL 失败：{exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
