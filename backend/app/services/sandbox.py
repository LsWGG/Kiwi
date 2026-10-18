"""代码执行安全沙箱：bubblewrap 命名空间隔离 + 危险操作静态拦截。

隔离边界（bubblewrap）：

* 只读挂载系统运行库、项目虚拟环境（`/venv`）与 uv Python 运行时；
* 仅工作目录 `/work` 与 `/tmp` 可写，宿主项目目录、数据库、`.env` 均不可见；
* 独立 PID / IPC / UTS / Cgroup 命名空间；默认**无网络**，Notebook 内核显式开启网络；
* 丢弃全部 capabilities，禁止在沙箱内继续创建用户命名空间；
* 资源限制：2GB 地址空间、100MB 文件、256 进程，超时强制终止。

Notebook 内核在 `/work` 下拥有独立虚拟环境（`/work/.venv`），通过 `.pth`
继承项目依赖，同时可以用 ``pip`` / ``uv pip`` 安装新包；安装结果随工作目录保留。
沙箱不可用时**拒绝执行**，绝不回退到宿主直跑。
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import PROJECT_ROOT

BWRAP = shutil.which("bwrap")
PRLIMIT = shutil.which("prlimit")
UV_BIN = shutil.which("uv")
UV_MOUNT_DIR = "/run/kiwi-bin"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 64 * 1024

RLIMIT_AS = 2 * 1024**3
RLIMIT_FSIZE = 100 * 1024**2
RLIMIT_NPROC = 256

_SYSTEM_MOUNTS: tuple[tuple[str, str], ...] = (
    ("/usr", "/usr"),
    ("/etc/fonts", "/etc/fonts"),
    ("/etc/ssl", "/etc/ssl"),
    ("/etc/ca-certificates", "/etc/ca-certificates"),
    ("/etc/ld.so.cache", "/etc/ld.so.cache"),
    ("/etc/ld.so.conf", "/etc/ld.so.conf"),
    ("/etc/ld.so.conf.d", "/etc/ld.so.conf.d"),
    ("/etc/localtime", "/etc/localtime"),
    ("/etc/passwd", "/etc/passwd"),
    ("/etc/group", "/etc/group"),
    ("/etc/nsswitch.conf", "/etc/nsswitch.conf"),
    ("/etc/hosts", "/etc/hosts"),
    ("/etc/resolv.conf", "/etc/resolv.conf"),
    ("/etc/mime.types", "/etc/mime.types"),
)


class SandboxUnavailable(RuntimeError):
    """当前环境没有可用的隔离工具，调用方应拒绝执行。"""


class DangerousCodeError(ValueError):
    """代码中包含明确禁止的危险操作。"""


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    sandboxed: bool = True


def _venv_root() -> Path:
    """项目虚拟环境根目录（解释器位于 <venv>/bin/python）。

    ``.venv/bin/python`` 通常是指向 uv 运行时的符号链接，直接 resolve 会把沙箱里
    的 ``/venv`` 错绑成运行时目录；优先用 ``sys.prefix`` 并校验 pyvenv.cfg。
    """
    candidates = [
        Path(sys.prefix),
        Path(sys.executable).parent.parent,
        Path(sys.executable).resolve().parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "pyvenv.cfg").exists():
            return candidate
    return Path(sys.prefix)


def _uv_python_mount() -> tuple[str, str] | None:
    """定位 uv 管理的 Python 运行时；venv 的 pyvenv.cfg 会引用它。"""
    resolved = Path(sys.executable).resolve()
    for parent in resolved.parents:
        if parent.name == "python" and parent.parent.name == "uv":
            return (str(parent), str(parent))
    if str(resolved).startswith("/usr/"):
        # 常规系统 Python：随 /usr 一起挂载，无需额外绑定
        return None
    # 兜底：把解释器所在运行时目录只读挂载
    root = resolved.parent.parent
    return (str(root), str(root))


def _limit_prefix(command: list[str], *, cpu_seconds: int | None) -> list[str]:
    """用 prlimit 在沙箱内施加资源限制，避免在宿主线程中 fork 时设置。"""
    if not PRLIMIT:
        return command
    args = [
        PRLIMIT,
        f"--as={RLIMIT_AS}",
        f"--fsize={RLIMIT_FSIZE}",
        "--core=0",
        f"--nproc={RLIMIT_NPROC}",
    ]
    if cpu_seconds:
        args.append(f"--cpu={cpu_seconds}")
    return [*args, "--", *command]


def _host_preexec(cpu_seconds: int | None):
    """prlimit 缺失时的兜底（仅在非线程环境安全）。"""

    def apply() -> None:
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_AS, (RLIMIT_AS, RLIMIT_AS))
            resource.setrlimit(resource.RLIMIT_FSIZE, (RLIMIT_FSIZE, RLIMIT_FSIZE))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if cpu_seconds:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except Exception:  # pragma: no cover - 受限环境
            pass

    return apply


def bwrap_args(
    workdir: Path,
    command: list[str],
    *,
    allow_network: bool = False,
    extra_path: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """构造 bubblewrap 启动参数；调用前必须确保沙箱可用。

    ``allow_network`` 为 True 时不创建网络命名空间，其余隔离保持不变；
    ``extra_path`` 会前置到 PATH（Notebook 用来优先使用 `/work/.venv/bin`）。
    """
    if not BWRAP:
        raise SandboxUnavailable("安全沙箱不可用（缺少 bubblewrap），已拒绝执行代码。")
    args: list[str] = [
        BWRAP,
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/sbin",
        "/sbin",
    ]
    for src, dest in _SYSTEM_MOUNTS:
        if Path(src).exists():
            args += ["--ro-bind", src, dest]
    uv_mount = _uv_python_mount()
    if uv_mount:
        args += ["--ro-bind", uv_mount[0], uv_mount[1]]
    args += [
        "--ro-bind",
        str(_venv_root()),
        "/venv",
        "--bind",
        str(workdir),
        "/work",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
    ]
    # uv 可执行文件挂到 /run 下的临时挂载点（/usr 只读，不能直接写 /usr/local/bin）。
    if UV_BIN:
        args += ["--dir", UV_MOUNT_DIR, "--ro-bind", UV_BIN, f"{UV_MOUNT_DIR}/uv"]
    env: dict[str, str] = {
        "PATH": (
            f"{extra_path}:/venv/bin:/usr/bin:/bin"
            if extra_path
            else "/venv/bin:/usr/bin:/bin"
        ),
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MPLBACKEND": "Agg",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    args += ["--clearenv"]
    for key, value in env.items():
        args += ["--setenv", key, value]
    args += [
        "--chdir",
        "/work",
        "--die-with-parent",
        "--new-session",
        "--hostname",
        "kiwi-sandbox",
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-cgroup",
        "--disable-userns",
        "--cap-drop",
        "ALL",
    ]
    if not allow_network:
        args.append("--unshare-net")
    args += ["--", *command]
    return args


def spawn_sandbox(
    workdir: Path,
    python_args: list[str],
    *,
    cpu_seconds: int | None = None,
    allow_network: bool = False,
    python_exe: str = "/venv/bin/python",
    extra_path: str | None = None,
    extra_env: dict[str, str] | None = None,
    **popen_kwargs,
) -> subprocess.Popen:
    """启动沙箱进程；stdin/stdout/stderr 由调用方指定。"""
    if not BWRAP:
        raise SandboxUnavailable("安全沙箱不可用（缺少 bubblewrap），已拒绝执行代码。")
    command = _limit_prefix([python_exe, *python_args], cpu_seconds=cpu_seconds)
    args = bwrap_args(
        workdir,
        command,
        allow_network=allow_network,
        extra_path=extra_path,
        extra_env=extra_env,
    )
    if PRLIMIT:
        return subprocess.Popen(args, env={}, start_new_session=True, **popen_kwargs)
    return subprocess.Popen(
        args,
        env={},
        start_new_session=True,
        preexec_fn=_host_preexec(cpu_seconds),
        **popen_kwargs,
    )


def _project_site_packages() -> str:
    """项目虚拟环境 site-packages 在沙箱内的路径（/venv 挂载点）。"""
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return f"/venv/lib/{version}/site-packages"


def ensure_notebook_venv(workdir: Path) -> str:
    """确保笔记本拥有可写虚拟环境，返回沙箱内解释器路径。

    虚拟环境建在 ``/work/.venv``，并通过 ``.pth`` 继承项目只读依赖：
    既能 ``import pandas``，也能用 ``pip`` / ``uv pip`` 安装新包，安装结果
    随笔记本工作目录持久化。失败时回退到只读项目环境。
    """
    venv = workdir / ".venv"
    python = venv / "bin" / "python"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = venv / "lib" / version / "site-packages"
    pth = site_packages / "kiwi-project.pth"
    if python.exists() and site_packages.exists():
        if not pth.exists():
            pth.write_text(f"{_project_site_packages()}\n", encoding="utf-8")
        return "/work/.venv/bin/python"

    base_python = _venv_root() / "bin" / "python"
    try:
        subprocess.run(
            [str(base_python), "-m", "venv", str(venv)],
            check=True,
            timeout=120,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        site_packages.mkdir(parents=True, exist_ok=True)
        pth.write_text(f"{_project_site_packages()}\n", encoding="utf-8")
        if python.exists():
            return "/work/.venv/bin/python"
    except (OSError, subprocess.SubprocessError):
        pass
    return "/venv/bin/python"


_DANGEROUS_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmkfs(?:\.\w+)?\b", re.I), "格式化文件系统（mkfs）"),
    (
        re.compile(r"\bdd\b[^\n;&|]*\bof\s*=\s*/dev/", re.I),
        "向块设备写入数据（dd of=/dev/…）",
    ),
    (re.compile(r"\b(?:shutdown|reboot|poweroff|halt)\b", re.I), "关机 / 重启系统"),
    (re.compile(r"\bwipefs\b|\bshred\b", re.I), "擦除磁盘数据"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/(?:\s|$)", re.I), "递归修改根目录权限"),
    (re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:", re.S), "fork 炸弹"),
    (
        re.compile(
            r"shutil\.rmtree\s*\(\s*['\"]/(?:etc|usr|home|data|var|boot|root|opt|srv|sys|proc)?['\"]",
            re.I,
        ),
        "递归删除系统目录（shutil.rmtree）",
    ),
    (
        re.compile(
            r"os\.(?:remove|unlink|rmdir)\s*\(\s*['\"]/(?:etc|usr|home|data|var|boot|root|opt|srv|sys|proc)",
            re.I,
        ),
        "删除系统路径（os.remove）",
    ),
)


def _rm_recursive_force(code: str) -> str | None:
    """识别 shell / 列表形式的 `rm -rf`（含 -r -f、-fr、--recursive --force）。"""
    normalized = re.sub(r"[\"'\[\](),]", " ", code)
    for match in re.finditer(r"\brm\b([^\n;&|]*)", normalized):
        tail = match.group(1)
        if not tail.strip():
            continue
        has_recursive = bool(
            re.search(r"(?:^|\s)(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive)(?=\s|$)", tail)
        )
        has_force = bool(
            re.search(r"(?:^|\s)(?:-[A-Za-z]*[fF][A-Za-z]*|--force)(?=\s|$)", tail)
        )
        if has_recursive and has_force:
            return "递归强制删除（rm -rf）"
    return None


def inspect_code(code: str) -> str | None:
    """返回危险操作说明；None 表示放行。"""
    reason = _rm_recursive_force(code)
    if reason:
        return reason
    for pattern, label in _DANGEROUS_RULES:
        if pattern.search(code):
            return label
    return None


def ensure_safe(code: str) -> None:
    reason = inspect_code(code)
    if reason:
        raise DangerousCodeError(
            f"检测到危险操作：{reason}。沙箱已拒绝执行该代码；"
            "代码只允许读写 /work 与 /tmp。"
        )


def _trim(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > MAX_OUTPUT_BYTES
    if truncated:
        data = data[:MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def run_once(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    workdir: Path | None = None,
) -> SandboxResult:
    """在一次性沙箱中执行 Python 代码（无持久状态）。"""
    ensure_safe(code)
    if not BWRAP:
        raise SandboxUnavailable("安全沙箱不可用（缺少 bubblewrap），已拒绝执行代码。")

    owns_workdir = workdir is None
    if workdir is None:
        base = PROJECT_ROOT / "data" / "sandbox"
        base.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    started = time.monotonic()
    timed_out = False
    try:
        proc = spawn_sandbox(
            workdir,
            ["-I", "-u", "-"],
            cpu_seconds=int(timeout) + 1,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = proc.communicate(input=code.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        out_text, out_cut = _trim(stdout)
        err_text, err_cut = _trim(stderr)
        if timed_out:
            err_text = (err_text + f"\n运行超过 {int(timeout)} 秒，已终止。").strip()
        return SandboxResult(
            ok=not timed_out and proc.returncode == 0,
            stdout=out_text,
            stderr=err_text,
            exit_code=None if timed_out else proc.returncode,
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            truncated=out_cut or err_cut,
        )
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def sandbox_status(allow_network: bool = False) -> dict:
    """供健康检查 / 前端展示的沙箱信息。"""
    return {
        "available": bool(BWRAP),
        "engine": "bubblewrap" if BWRAP else None,
        "network": bool(allow_network),
        "writable_paths": ["/work", "/tmp"],
        "venv": "/work/.venv" if allow_network else "/venv",
        "project_venv": "/venv",
        "package_managers": (
            (["pip"] + (["uv"] if UV_BIN else [])) if allow_network else []
        ),
        "uv": bool(UV_BIN),
        "python_version": sys.version.split()[0],
    }
