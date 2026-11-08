"""Windows CI：用随包 PostgreSQL 16 运行 Windows 专项测试。

GitHub 的 windows-latest 自带 PostgreSQL 14，与生产/打包的 16 不一致。
这里直接用 pgserver 启动同一份 PostgreSQL 16 二进制，建一个临时测试库，
再运行 ``pytest tests/test_windows_runner.py``；结束后清理集群。

用法（在 backend 目录、已安装 pgserver 的虚拟环境中）：

    python ../desktop/scripts/run-windows-tests.py
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

TEST_DATABASE = "kiwi_windows_test"
# Windows 托管 runner 首次启动 PostgreSQL 时可能被 Defender 扫描拖慢，
# pgserver 0.1.4 在 Windows 分支把 pg_ctl 超时写死为 10 秒，CI 上会误判失败。
PG_CTL_TIMEOUT_SECONDS = 180


def _patch_pg_ctl_timeout() -> None:
    """放宽 pgserver 的 pg_ctl 超时，并保留调用方显式传入的值。"""
    from pgserver import postgres_server

    original = postgres_server.pg_ctl

    def pg_ctl_with_timeout(*args, **kwargs):
        # pgserver 0.1.4 自己传了 timeout=10，必须覆盖而不是 setdefault。
        kwargs["timeout"] = PG_CTL_TIMEOUT_SECONDS
        return original(*args, **kwargs)

    postgres_server.pg_ctl = pg_ctl_with_timeout


def _print_pg_log(pgdata: Path) -> None:
    log = pgdata / "log"
    if not log.is_file():
        print(f"[warn] 未找到 PostgreSQL 日志：{log}", file=sys.stderr)
        return
    print(f"--- PostgreSQL 日志 {log} ---", file=sys.stderr)
    try:
        print(log.read_text(encoding="utf-8", errors="replace")[-20000:], file=sys.stderr)
    except OSError as exc:
        print(f"[warn] 读取 PostgreSQL 日志失败：{exc}", file=sys.stderr)


def main() -> int:
    if os.name != "nt":
        print("该脚本只用于 Windows CI。", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    import pgserver

    _patch_pg_ctl_timeout()

    base = Path(tempfile.gettempdir()) / "kiwi-windows-tests"
    base.mkdir(parents=True, exist_ok=True)
    pgdata = base / "pgdata"
    try:
        server = pgserver.get_server(str(pgdata), cleanup_mode="stop")
    except Exception:
        _print_pg_log(pgdata)
        raise
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
