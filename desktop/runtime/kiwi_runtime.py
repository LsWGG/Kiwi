#!/usr/bin/env python3
"""Kiwi 桌面 runtime：编排 PostgreSQL / Qdrant / Alembic / uvicorn。

由 .NET WebView2 宿主启动（也支持在开发机上直接运行）。职责：

1. 在数据目录上加单实例文件锁，创建目录与 Fernet 密钥；
2. 启动 pgserver（PostgreSQL，仅监听 127.0.0.1，随机端口）；
3. 启动随包 Qdrant（仅 loopback；未内置向量模型时失败不阻塞启动）；
4. 预绑定 HTTP socket，取得端口后写入全部 ``KIWI_*`` 环境变量；
5. 安装离线审计钩子、执行 Alembic 迁移、导入 ``app.main``；
6. 以 uvicorn 提供 API 与前端 SPA，持续写 ``runtime.json`` 状态；
7. 收到内部关闭请求 / 父进程退出 / 信号时优雅停止各服务。

``runtime.json`` 只包含状态、阶段、端口、PID 与日志路径，**不写控制令牌**。
控制令牌由宿主生成并通过环境变量传入；本进程只读取、不落盘、不打印。

该文件只在桌面 runtime 中使用；Docker / 源码部署不导入它。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Kiwi"
RUNTIME_VERSION = 1

STATE_POLL_SECONDS = 1.0
PARENT_POLL_SECONDS = 2.0
POSTGRES_START_TIMEOUT = 120.0
QDRANT_START_TIMEOUT = 60.0
HTTP_START_TIMEOUT = 90.0
SERVER_JOIN_TIMEOUT = 15.0
SHUTDOWN_HARD_TIMEOUT = 25.0

_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

logger = logging.getLogger("kiwi.runtime")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict) -> None:
    """原子写 JSON，宿主轮询时不会读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def write_text_atomic(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def http_ok(url: str, *, timeout: float = 1.0) -> bool:
    """用禁用代理的 opener 探测本机服务；只用于 loopback。"""
    try:
        with _HTTP.open(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for_http(
    url: str,
    *,
    timeout: float,
    interval: float = 0.5,
    process: subprocess.Popen | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ok(url):
            return True
        if process is not None and process.poll() is not None:
            return False  # 子进程已退出，无需等到超时
        time.sleep(interval)
    return False


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def create_listen_socket(host: str = "127.0.0.1") -> socket.socket:
    """预绑定 HTTP socket，避免选端口后被其他进程抢占。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(2048)
    sock.setblocking(True)
    return sock


def bundle_root() -> Path:
    """PyInstaller onedir 的 ``_internal``；源码运行时为仓库根目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and getattr(sys, "frozen", False):
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def alembic_directory() -> Path:
    if getattr(sys, "frozen", False):
        return bundle_root() / "alembic"
    return bundle_root() / "backend" / "alembic"


def ensure_app_importable() -> None:
    """源码运行时把 backend/ 加入 sys.path；打包后 app 已在 bundle 内。"""
    if getattr(sys, "frozen", False):
        return
    backend = bundle_root() / "backend"
    if (backend / "app").is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


# --------------------------------------------------------------------------- #
# 状态文件 / 单实例锁 / 日志
# --------------------------------------------------------------------------- #


class RuntimeState:
    """``runtime.json`` 写入器；任何阶段变化都立即落盘。"""

    def __init__(self, path: Path, *, data_dir: Path, log_file: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._payload: dict = {
            "version": RUNTIME_VERSION,
            "status": "starting",
            "stage": "boot",
            "pid": os.getpid(),
            "started_at": now_iso(),
            "data_dir": str(data_dir),
            "log_file": str(log_file),
        }

    def update(self, *, status: str | None = None, stage: str | None = None, **extra) -> None:
        with self._lock:
            if status is not None:
                self._payload["status"] = status
            if stage is not None:
                self._payload["stage"] = stage
            self._payload.update(extra)
            self._payload["updated_at"] = now_iso()
            try:
                write_json_atomic(self.path, self._payload)
            except OSError as exc:  # 状态文件写失败不能终止主流程
                logger.warning("写入 runtime.json 失败：%s", exc)

    @property
    def stage(self) -> str:
        with self._lock:
            return str(self._payload.get("stage", "boot"))

    def fail(self, stage: str, error: str) -> None:
        self.update(status="error", stage=stage, error=error)


class DataDirLock:
    """数据目录单实例锁；进程退出后由操作系统自动释放。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                handle.close()


def configure_logging(log_dir: Path) -> Path:
    """runtime 自己的滚动日志；不记录令牌、密钥与完整环境变量。

    文件 handler 挂在 ``kiwi.runtime`` 上且不向上传播，这样后端导入后
    调用 ``setup_logging()`` 重新配置 root（写 backend.log）时，runtime.log
    不会丢掉启动与关闭阶段的记录。
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "runtime.log"
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers[:] = [console, file_handler]

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        root.addHandler(console)
    for noisy in ("httpx", "httpcore", "qdrant_client", "urllib3", "alembic.runtime.migration"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


# --------------------------------------------------------------------------- #
# 路径 / 密钥 / 子进程
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class RuntimePaths:
    data_dir: Path
    resources: Path
    frontend_dist: Path
    state_file: Path
    log_dir: Path

    @property
    def pgdata(self) -> Path:
        return self.data_dir / "pg"

    @property
    def qdrant_storage(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def fernet_key_file(self) -> Path:
        return self.secrets_dir / "fernet.key"


def prepare_directories(paths: RuntimePaths) -> None:
    for directory in (
        paths.data_dir,
        paths.pgdata,
        paths.qdrant_storage,
        paths.data_dir / "uploads",
        paths.data_dir / "backups",
        paths.data_dir / "notebooks",
        paths.data_dir / "sandbox",
        paths.data_dir / "wiki_schemas",
        paths.data_dir / "models" / "whisper",
        paths.data_dir / "models" / "fastembed",
        paths.secrets_dir,
        paths.log_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def load_or_create_fernet_key(path: Path) -> str:
    """Fernet 密钥只生成一次；损坏时明确报错而不是静默换新。"""
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    write_text_atomic(path, key + "\n", mode=0o600)
    logger.info("已生成桌面数据加密密钥：%s", path)
    return key


def short_windows_path(path: Path) -> Path | None:
    """取得 Windows 8.3 短路径；用于绕开 initdb 的 ANSI 路径限制。"""
    if os.name != "nt":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    if 0 < length < len(buffer):
        short = Path(buffer.value)
        # 未生成 8.3 名称时返回原路径；对非 ASCII 路径没有帮助，视为失败。
        if str(short).casefold() != str(path).casefold():
            return short
    return None


def ensure_pgserver_binaries() -> Path | None:
    """PyInstaller 会把模块放进 PYZ，``__file__`` 可能指向不存在的路径。

    优先使用 pgserver 计算出的 ``POSTGRES_BIN_PATH``；若目录不存在，则在
    bundle 内查找 ``collect_all`` 收集的 ``pginstall/bin`` 并回填模块属性。
    """
    try:
        import pgserver
    except Exception:  # noqa: BLE001 - 未安装时给出统一错误
        return None
    current = Path(str(getattr(pgserver, "POSTGRES_BIN_PATH", "") or ""))
    if current.is_dir():
        return current
    candidates = [
        bundle_root() / "pgserver" / "pginstall" / "bin",
        bundle_root() / "pginstall" / "bin",
    ]
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        with contextlib.suppress(ImportError):
            from pgserver import _commands as commands

            commands.POSTGRES_BIN_PATH = candidate
        with contextlib.suppress(ImportError):
            from pgserver import postgres_server as server_module

            server_module.POSTGRES_BIN_PATH = candidate
        pgserver.POSTGRES_BIN_PATH = candidate
        logger.info("已从 bundle 解析 PostgreSQL 二进制：%s", candidate)
        return candidate
    return None


def find_pg_dump() -> Path | None:
    """优先使用 pgserver 随包的 pg_dump，避免依赖系统 PATH。"""
    try:
        import pgserver
    except Exception:  # noqa: BLE001 - 未安装时由启动流程报错
        return None
    candidates: list[Path] = []
    bin_dir = Path(str(getattr(pgserver, "POSTGRES_BIN_PATH", "") or ""))
    if bin_dir.is_dir():
        candidates.extend([bin_dir / "pg_dump.exe", bin_dir / "pg_dump"])
    package_dir = Path(pgserver.__file__).resolve().parent
    candidates.extend(package_dir.rglob("pg_dump.exe"))
    candidates.extend(package_dir.rglob("pg_dump"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def start_postgres(paths: RuntimePaths) -> tuple[object, str]:
    """启动 pgserver，返回 (server, asyncpg URL)；失败时抛出带日志位置的错误。"""
    if ensure_pgserver_binaries() is None:
        raise RuntimeError(
            "未找到 PostgreSQL 二进制（pgserver / pginstall），"
            f"请检查打包资源：{bundle_root()}"
        )
    import pgserver
    from pgserver.postgres_server import PostgresServer

    pgdata = paths.pgdata
    try:
        server = pgserver.get_server(str(pgdata), cleanup_mode="stop")
    except Exception as exc:  # noqa: BLE001 - 非 ASCII 路径在 Windows 上需要短路径回退
        short_path = short_windows_path(pgdata.parent)
        if os.name != "nt" or short_path is None:
            raise
        logger.warning(
            "PostgreSQL 在 %s 启动失败（%s），改用 8.3 短路径 %s 重试",
            pgdata,
            exc,
            short_path,
        )
        short_pgdata = short_path / pgdata.name
        short_pgdata.mkdir(parents=True, exist_ok=True)
        # 直接构造：get_server 会 resolve() 回非 ASCII 长路径。
        server = PostgresServer(short_pgdata, cleanup_mode="stop")
    uri = server.get_uri()
    db_url = uri
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://") :]
    logger.info("PostgreSQL 已就绪：%s", uri.rsplit("@", 1)[-1])
    return server, db_url


def qdrant_binary(resources: Path) -> Path | None:
    name = "qdrant.exe" if os.name == "nt" else "qdrant"
    candidate = resources / "qdrant" / name
    return candidate if candidate.is_file() else None


def start_qdrant(
    paths: RuntimePaths,
) -> tuple[subprocess.Popen | None, int | None]:
    """启动 Qdrant；二进制缺失或超时只记录警告，不阻塞应用启动。"""
    binary = qdrant_binary(paths.resources)
    if binary is None:
        logger.warning("未找到随包 Qdrant（resources/qdrant），向量服务不可用")
        return None, None
    http_port = free_port()
    grpc_port = free_port()
    while grpc_port == http_port:
        grpc_port = free_port()
    env = {
        **os.environ,
        "QDRANT__SERVICE__HOST": "127.0.0.1",
        "QDRANT__SERVICE__HTTP_PORT": str(http_port),
        "QDRANT__SERVICE__GRPC_PORT": str(grpc_port),
        "QDRANT__STORAGE__STORAGE_PATH": str(paths.qdrant_storage),
        "QDRANT__STORAGE__SNAPSHOTS_PATH": str(paths.qdrant_storage / "snapshots"),
        "QDRANT__TELEMETRY_DISABLED": "true",
    }
    stdout = (paths.log_dir / "qdrant.log").open("a", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(  # noqa: S603 - 固定随包路径，无用户输入
            [str(binary)],
            cwd=str(paths.qdrant_storage),
            env=env,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError as exc:
        stdout.close()
        logger.warning("Qdrant 启动失败：%s", exc)
        return None, None

    if wait_for_http(
        f"http://127.0.0.1:{http_port}/readyz",
        timeout=QDRANT_START_TIMEOUT,
        process=process,
    ):
        logger.info("Qdrant 已就绪：http://127.0.0.1:%s", http_port)
        return process, http_port

    logger.warning(
        "Qdrant 在 %.0f 秒内未就绪，继续启动（向量能力暂不可用），日志：%s",
        QDRANT_START_TIMEOUT,
        paths.log_dir / "qdrant.log",
    )
    terminate_process(process)
    stdout.close()
    return None, None


def portable_python(resources: Path) -> Path | None:
    candidate = resources / "python" / ("python.exe" if os.name == "nt" else "python")
    return candidate if candidate.is_file() else None


def terminate_process(process: subprocess.Popen | None, *, timeout: float = 8.0) -> None:
    if process is None or process.poll() is not None:
        return
    with contextlib.suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5.0)


# --------------------------------------------------------------------------- #
# 应用环境变量
# --------------------------------------------------------------------------- #


def scrub_inherited_env() -> None:
    """清掉宿主进程可能继承的 ``KIWI_*``，避免开发 / 生产配置混入桌面实例。

    控制令牌在调用前已被捕获，稍后单独回填；数据库、密钥、访问令牌等一律
    由 desktop runtime 重新生成。
    """
    for key in [key for key in os.environ if key.upper().startswith("KIWI_")]:
        os.environ.pop(key, None)


def build_app_env(
    *,
    paths: RuntimePaths,
    db_url: str,
    qdrant_url: str,
    http_port: int,
    fernet_key: str,
    pg_dump: Path | None,
    python_path: Path | None,
) -> dict[str, str]:
    """构造后端所需的环境变量；令牌不在此处生成或覆盖。"""
    origin = f"http://127.0.0.1:{http_port}"
    return {
        "KIWI_DATABASE_URL": db_url,
        "KIWI_QDRANT_URL": qdrant_url,
        "KIWI_DATA_DIR": str(paths.data_dir),
        "KIWI_DESKTOP_MODE": "true",
        "KIWI_OFFLINE_MODE": "true",
        "KIWI_FRONTEND_DIST": str(paths.frontend_dist),
        "KIWI_DESKTOP_SETTINGS_PATH": str(paths.data_dir / "desktop-settings.json"),
        "KIWI_UPLOAD_DIR": str(paths.data_dir / "uploads"),
        "KIWI_BACKUP_DIR": str(paths.data_dir / "backups"),
        "KIWI_WHISPER_MODEL_DIR": str(paths.data_dir / "models" / "whisper"),
        "KIWI_WHISPER_ENABLED": "false",
        "KIWI_EMBED_PROVIDER": "none",
        "KIWI_KB_SCHEDULER_ENABLED": "false",
        "KIWI_CORS_ORIGINS": json.dumps([origin]),
        # 桌面只监听 loopback，不需要访问令牌；显式置空防止 .env 继承。
        "KIWI_ACCESS_TOKEN": "",
        "KIWI_FERNET_KEY": fernet_key,
        "KIWI_LOG_FILE": str(paths.log_dir / "backend.log"),
        "KIWI_PG_DUMP_PATH": str(pg_dump) if pg_dump else "",
        "KIWI_DESKTOP_PYTHON": str(python_path) if python_path else "",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "FASTEMBED_CACHE_PATH": str(paths.data_dir / "models" / "fastembed"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
    }


# --------------------------------------------------------------------------- #
# Alembic / uvicorn
# --------------------------------------------------------------------------- #


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    script_location = alembic_directory()
    if not (script_location / "env.py").is_file():
        raise RuntimeError(f"未找到 Alembic 迁移脚本：{script_location}")
    config = Config()
    config.set_main_option("script_location", str(script_location))
    command.upgrade(config, "head")
    logger.info("数据库迁移已完成（head）")


def parent_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 - psutil 不可用时退回系统调用
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def install_exit_signals(shutdown: threading.Event) -> None:
    import signal

    def _handler(signum, _frame):  # noqa: ANN001 - signal handler 签名
        logger.info("收到信号 %s，准备退出", signum)
        shutdown.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _handler)


def hard_exit_after(seconds: float, code: int) -> None:
    """关闭阶段卡住时强制退出，避免宿主 Job Object 超时杀进程。"""

    def _expire() -> None:
        logger.error("关闭超时 %.0f 秒，强制退出", seconds)
        os._exit(code)

    timer = threading.Timer(seconds, _expire)
    timer.daemon = True
    timer.start()


# --------------------------------------------------------------------------- #
# 启动 / 关闭
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kiwi 桌面 runtime")
    parser.add_argument("--data-dir", required=True, help="桌面数据目录（绝对路径）")
    parser.add_argument("--resources", required=True, help="随包资源目录（frontend / qdrant / python）")
    parser.add_argument(
        "--frontend-dist",
        default="",
        help="前端构建目录；默认 <resources>/frontend",
    )
    parser.add_argument(
        "--state-file",
        default="",
        help="runtime.json 路径；默认 <data-dir>/runtime.json",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=0,
        help="宿主进程 PID；退出后 runtime 自动关闭",
    )
    parser.add_argument(
        "--control-token-env",
        default="KIWI_DESKTOP_CONTROL_TOKEN",
        help="控制令牌所在环境变量名（只读取，不落盘）",
    )
    return parser.parse_args(argv)


def resolve_paths(args: argparse.Namespace) -> RuntimePaths:
    data_dir = Path(args.data_dir).expanduser().resolve()
    resources = Path(args.resources).expanduser().resolve()
    frontend_dist = (
        Path(args.frontend_dist).expanduser().resolve()
        if args.frontend_dist
        else resources / "frontend"
    )
    state_file = (
        Path(args.state_file).expanduser().resolve()
        if args.state_file
        else data_dir / "runtime.json"
    )
    return RuntimePaths(
        data_dir=data_dir,
        resources=resources,
        frontend_dist=frontend_dist,
        state_file=state_file,
        log_dir=data_dir / "logs",
    )


def run(args: argparse.Namespace) -> int:
    paths = resolve_paths(args)
    prepare_directories(paths)
    log_file = configure_logging(paths.log_dir)
    state = RuntimeState(paths.state_file, data_dir=paths.data_dir, log_file=log_file)

    lock = DataDirLock(paths.data_dir / "runtime.lock")
    if not lock.acquire():
        # 不能写 runtime.json：该文件属于正在运行的实例，覆盖会让宿主误判状态。
        logger.error("数据目录已被另一个 Kiwi runtime 占用：%s", paths.data_dir)
        return 2

    if not (paths.frontend_dist / "index.html").is_file():
        message = (
            f"前端资源缺失：{paths.frontend_dist / 'index.html'}。"
            "请先运行 npm run build:desktop 并重新打包。"
        )
        logger.error(message)
        state.fail("prepare", message)
        lock.release()
        return 3

    control_token = os.environ.get(args.control_token_env, "")
    scrub_inherited_env()
    if control_token:
        # 只设置到后端读取的变量；不写状态文件、不打印。
        os.environ["KIWI_DESKTOP_CONTROL_TOKEN"] = control_token
    else:
        logger.warning("未收到控制令牌（%s），内部关闭接口将不可用", args.control_token_env)

    pg_server = None
    qdrant_process = None
    http_sock = None
    server_thread = None
    server = None
    shutdown = threading.Event()
    install_exit_signals(shutdown)
    state.update(stage="postgres")

    try:
        fernet_key = load_or_create_fernet_key(paths.fernet_key_file)
        pg_server, db_url = start_postgres(paths)
        pg_dump = find_pg_dump()

        state.update(stage="qdrant")
        qdrant_process, qdrant_port = start_qdrant(paths)
        qdrant_url = (
            f"http://127.0.0.1:{qdrant_port}" if qdrant_port else "http://127.0.0.1:6333"
        )

        http_sock = create_listen_socket()
        http_port = int(http_sock.getsockname()[1])
        state.update(stage="http", http_port=http_port)

        app_env = build_app_env(
            paths=paths,
            db_url=db_url,
            qdrant_url=qdrant_url,
            http_port=http_port,
            fernet_key=fernet_key,
            pg_dump=pg_dump,
            python_path=portable_python(paths.resources),
        )
        os.environ.update(app_env)

        ensure_app_importable()
        # 必须在导入 app.main 前安装：钩子只允许 loopback 与已登记模型端点。
        from app.services import offline_guard

        offline_guard.install()

        state.update(stage="migrate")
        run_migrations()

        state.update(stage="http")
        import uvicorn

        from app.main import app as fastapi_app

        fastapi_app.state.desktop_shutdown_callback = shutdown.set
        config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=http_port,
            log_config=None,
            log_level="info",
            lifespan="on",
            access_log=False,
            proxy_headers=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [http_sock]},
            name="kiwi-uvicorn",
            daemon=True,
        )
        server_thread.start()

        health_url = f"http://127.0.0.1:{http_port}/api/health"
        deadline = time.monotonic() + HTTP_START_TIMEOUT
        while time.monotonic() < deadline:
            if not server_thread.is_alive():
                raise RuntimeError(
                    f"uvicorn 提前退出，请查看日志：{paths.log_dir / 'backend.log'}"
                )
            if http_ok(health_url):
                break
            if shutdown.is_set():
                raise RuntimeError("启动过程中收到退出请求")
            time.sleep(0.5)
        else:
            raise TimeoutError(
                f"后端在 {HTTP_START_TIMEOUT:.0f} 秒内未就绪，请查看日志："
                f"{paths.log_dir / 'backend.log'}"
            )

        state.update(
            status="ready",
            stage="ready",
            http_port=http_port,
            ready_at=now_iso(),
            qdrant_ready=qdrant_port is not None,
        )
        logger.info("Kiwi 已就绪：http://127.0.0.1:%s", http_port)

        while not shutdown.is_set():
            if args.parent_pid and not parent_alive(args.parent_pid):
                logger.info("宿主进程 %s 已退出，runtime 随之关闭", args.parent_pid)
                shutdown.set()
                break
            server_thread.join(timeout=STATE_POLL_SECONDS)
            if not server_thread.is_alive():
                logger.error("uvicorn 意外退出")
                state.fail("http", "uvicorn 意外退出")
                return 1

        state.update(status="stopping", stage="shutdown")
        logger.info("正在关闭 Kiwi runtime…")
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=SERVER_JOIN_TIMEOUT)
            if server_thread.is_alive():
                logger.warning("uvicorn 未在 %.0f 秒内退出", SERVER_JOIN_TIMEOUT)

        # 先停应用与 Qdrant，再写 stopped；最后停 PG，即使 pg_ctl stop 挂起，
        # 宿主也能看到明确的停止状态，并由 Job Object 兜底回收进程树。
        terminate_process(qdrant_process)
        state.update(status="stopped", stage="stopped", stopped_at=now_iso())
        hard_exit_after(SHUTDOWN_HARD_TIMEOUT, 0)
        if pg_server is not None:
            with contextlib.suppress(Exception):
                pg_server.cleanup()
        logger.info("Kiwi runtime 已停止")
        return 0

    except Exception as exc:  # noqa: BLE001 - 统一写入状态并保留堆栈到日志
        logger.error("Kiwi runtime 启动失败：%s", exc)
        logger.error("%s", traceback.format_exc())
        state.fail(state.stage, f"{type(exc).__name__}: {exc}")
        terminate_process(qdrant_process)
        if pg_server is not None:
            with contextlib.suppress(Exception):
                pg_server.cleanup()
        return 1
    finally:
        with contextlib.suppress(OSError):
            if http_sock is not None:
                http_sock.close()
        lock.release()


def main(argv: list[str] | None = None) -> int:
    # PyInstaller 多进程（某些库会 spawn）需要。
    import multiprocessing

    multiprocessing.freeze_support()
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
