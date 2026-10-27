"""Phase 0：验证 pgserver 在 Windows 上的可用性。

覆盖计划中的退出标准：启动、URI、迁移（建表 / 写入）、pg_dump、重启后数据仍在、
以及含中文与空格的 PostgreSQL 数据目录。
"""

from __future__ import annotations

import faulthandler
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
faulthandler.enable()

OUT = Path(
    os.environ.get("SPIKE_OUT")
    or Path(__file__).resolve().parent / "out" / "pgserver.json"
)
result: dict = {"check": "pgserver", "status": "running", "steps": [], "details": {}}


def flush_result() -> None:
    """每一步后落盘，原生崩溃时也能留下最后完成的步骤。"""
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 - 诊断写入失败不能掩盖主流程
        print(f"[warn] 写入结果失败：{exc}", file=sys.stderr, flush=True)


def step(name: str, fn):
    started = time.time()
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - 需要把失败步骤写进结果
        result["steps"].append(
            {
                "name": name,
                "status": "fail",
                "seconds": round(time.time() - started, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        print(f"[fail] {name}: {type(exc).__name__}: {exc}", flush=True)
        flush_result()
        raise
    result["steps"].append(
        {"name": name, "status": "pass", "seconds": round(time.time() - started, 2)}
    )
    print(f"[pass] {name} -> {value!r}", flush=True)
    flush_result()
    return value


def redact_uri(uri: str) -> str:
    parts = urlsplit(uri)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        user = userinfo.split(":", 1)[0]
        netloc = f"{user}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def short_windows_path(path: Path) -> Path | None:
    """用 8.3 短路径绕开 PostgreSQL initdb 的 ANSI 路径限制。"""
    if os.name != "nt":
        return None
    import ctypes

    buf = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    if 0 < length < len(buf):
        return Path(buf.value)
    return None


def probe_non_ascii_path(pgserver) -> dict:
    """记录非 ASCII 路径的直接结果与短路径规避结果，不影响主检查。"""
    base = Path(tempfile.gettempdir()) / "Kiwi 中文 数据"
    base.mkdir(parents=True, exist_ok=True)
    info: dict = {"data_dir": str(base / "pgdata")}

    def try_start(label: str, data_dir: Path) -> None:
        server = None
        try:
            server = pgserver.get_server(str(data_dir), cleanup_mode="stop")
            info[label] = {
                "status": "pass",
                "query": str(server.psql("SELECT 1")).strip(),
            }
        except Exception as exc:  # noqa: BLE001 - 探测结果需要保留原始错误
            info[label] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if server is not None:
                try:
                    server.cleanup()
                except Exception as exc:  # noqa: BLE001 - 清理失败仅记录
                    info.setdefault("cleanup_warnings", []).append(str(exc))

    try_start("direct", base / "pgdata")
    short_base = short_windows_path(base)
    info["short_base"] = str(short_base) if short_base else None
    if short_base is not None and short_base != base:
        try_start("short_path", short_base / "pgdata")
    return info


def main() -> None:
    import pgserver

    result["details"]["pgserver_version"] = getattr(pgserver, "__version__", "unknown")
    result["details"]["python"] = sys.version
    result["details"]["executable"] = sys.executable
    package_dir = Path(pgserver.__file__).resolve().parent
    embedded_bin = package_dir / "pginstall" / "bin"
    result["details"]["package_dir"] = str(package_dir)
    result["details"]["embedded_bin"] = str(embedded_bin)
    result["details"]["embedded_bin_exists"] = embedded_bin.is_dir()
    if embedded_bin.is_dir():
        result["details"]["embedded_bin_count"] = len(list(embedded_bin.iterdir()))

    # 主流程用纯 ASCII 路径：PostgreSQL 的 Windows 版 initdb 用 ANSI 代码页
    # 处理路径，英文系统上非 ASCII 目录会被转成 "??" 而无法创建。
    data_dir = Path(tempfile.gettempdir()) / "kiwi-pg-spike" / "pgdata"
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    result["details"]["data_dir"] = str(data_dir)

    db = None
    db2 = None
    try:

        def start():
            nonlocal db
            db = pgserver.get_server(str(data_dir), cleanup_mode="stop")
            return "started"

        step("start", start)
        uri = step("get_uri", lambda: db.get_uri())
        result["details"]["uri"] = redact_uri(uri)

        version = step("select_version", lambda: str(db.psql("SELECT version()")))
        result["details"]["version"] = version.strip()[:200]

        step(
            "create_table_and_insert",
            lambda: db.psql(
                "CREATE TABLE IF NOT EXISTS spike (id serial PRIMARY KEY, note text);"
                "INSERT INTO spike(note) VALUES ('中文路径测试 ✓');"
            ),
        )
        rows = step(
            "select_chinese",
            lambda: str(db.psql("SELECT note FROM spike ORDER BY id DESC LIMIT 1")),
        )
        if "中文路径测试" not in rows:
            raise AssertionError(f"中文数据读取不一致：{rows!r}")
        result["details"]["select_output"] = rows.strip()

        bin_dir = Path(
            str(getattr(pgserver, "POSTGRES_BIN_PATH", "") or getattr(pgserver, "pg_bin", ""))
        )
        candidates = [bin_dir / "pg_dump.exe", bin_dir / "pg_dump"]
        candidates.extend(package_dir.rglob("pg_dump.exe"))
        candidates.extend(package_dir.rglob("pg_dump"))
        pg_dump = next((p for p in candidates if p.is_file()), None)
        if pg_dump is None:
            raise FileNotFoundError(f"未找到 pg_dump，候选：{[str(c) for c in candidates]}")

        dump_version = step(
            "pg_dump_version",
            lambda: subprocess.run(
                [str(pg_dump), "--version"], check=True, capture_output=True, text=True
            ).stdout.strip(),
        )
        result["details"]["pg_dump"] = str(pg_dump)
        result["details"]["pg_dump_version"] = dump_version

        dump_path = data_dir.parent / "spike.dump.sql"
        libpq_uri = uri.replace("postgresql+asyncpg://", "postgresql://", 1)
        step(
            "pg_dump",
            lambda: subprocess.run(
                [str(pg_dump), "--dbname", libpq_uri, "--no-owner", "--file", str(dump_path)],
                check=True,
                capture_output=True,
                text=True,
            ).returncode,
        )
        dump_text = dump_path.read_text(encoding="utf-8", errors="replace")
        if "CREATE TABLE" not in dump_text:
            raise AssertionError("pg_dump 输出缺少 CREATE TABLE")
        result["details"]["dump_bytes"] = dump_path.stat().st_size

        step("cleanup_before_restart", lambda: db.cleanup())

        def restart():
            nonlocal db2
            db2 = pgserver.get_server(str(data_dir), cleanup_mode="stop")
            return "restarted"

        step("restart", restart)
        rows_after = step(
            "select_after_restart",
            lambda: str(db2.psql("SELECT note FROM spike ORDER BY id DESC LIMIT 1")),
        )
        if "中文路径测试" not in rows_after:
            raise AssertionError(f"重启后数据丢失：{rows_after!r}")
        result["details"]["restart_ok"] = True
        try:
            result["details"]["non_ascii_path"] = probe_non_ascii_path(pgserver)
        except Exception as exc:  # noqa: BLE001 - 探测失败不影响主结论
            result["details"]["non_ascii_path"] = {
                "error": f"{type(exc).__name__}: {exc}"
            }
        result["status"] = "pass"
        result["summary"] = (
            "pgserver 在 Windows 可用（ASCII 路径下启动、pg_dump、重启均通过）；"
            "非 ASCII 路径结果见 details.non_ascii_path"
        )
    finally:
        for server in (db, db2):
            if server is not None:
                try:
                    server.cleanup()
                except Exception as exc:  # noqa: BLE001 - 清理失败不应覆盖主结果
                    print(f"[warn] cleanup failed: {exc}", flush=True)


if __name__ == "__main__":
    flush_result()
    try:
        main()
    except Exception:  # noqa: BLE001 - 记录完整堆栈到结果文件
        result["error"] = traceback.format_exc()
        print(result["error"], file=sys.stderr, flush=True)
    finally:
        if result["status"] == "running":
            result["status"] = "fail"
        flush_result()
    sys.exit(0 if result["status"] == "pass" else 1)
