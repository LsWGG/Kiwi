"""Windows 桌面本机执行：Job Object 资源限制 + 随包便携 Python。

这不是安全沙箱。Job Object 只保证超时或关闭开关时能杀掉整棵进程树，并限制
进程数、内存与输出体积；**代码仍然可以读取当前用户可访问的文件**。因此桌面
版本机执行默认关闭，只有用户在设置中显式确认风险后才启用，且只应运行可信
代码。

Linux / Docker 继续使用 :mod:`app.services.sandbox` 的 bubblewrap 实现；本模块
只在 ``os.name == "nt"`` 且 ``desktop_mode=true`` 时被调用。
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.services.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    SandboxResult,
    SandboxUnavailable,
    ensure_safe,
)

WINDOWS_ENGINE = "windows-job"
WINDOWS_WARNING = (
    "本机执行不具备文件系统隔离：代码可以读取当前用户可访问的文件，"
    "只应运行可信代码。"
)
MAX_OUTPUT_BYTES = 400 * 1024
MAX_PROCESS_MEMORY = 2 * 1024**3
MAX_JOB_MEMORY = 4 * 1024**3
MAX_ACTIVE_PROCESSES = 16
STDERR_TAIL_LINES = 20

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32First.restype = wintypes.BOOL
    _kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32Next.restype = wintypes.BOOL
    _kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenThread.restype = wintypes.HANDLE
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
else:  # pragma: no cover - Linux/macOS 不应调用本模块
    _kernel32 = None


@dataclass
class WindowsJob:
    """Job Object 句柄；关闭句柄会按 KILL_ON_JOB_CLOSE 杀掉整棵进程树。"""

    handle: int

    def terminate(self, exit_code: int = 1) -> None:
        if not self.handle or _kernel32 is None:
            return
        _kernel32.TerminateJobObject(wintypes.HANDLE(self.handle), exit_code)

    def close(self) -> None:
        if not self.handle or _kernel32 is None:
            return
        _kernel32.CloseHandle(wintypes.HANDLE(self.handle))
        self.handle = 0


@dataclass
class WindowsProcess:
    proc: subprocess.Popen
    job: WindowsJob

    def terminate(self) -> None:
        self.job.terminate()

    def close(self) -> None:
        self.job.close()


def _last_error() -> int:
    return int(ctypes.get_last_error()) if os.name == "nt" else 0


def _portable_python() -> Path | None:
    raw = settings.desktop_python.strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def runner_python() -> Path:
    """返回随包便携 Python；缺失时给出可操作的错误。"""
    if os.name != "nt":
        raise SandboxUnavailable("Windows 本机执行仅在 Windows 上可用。")
    path = _portable_python()
    if path is None:
        raise SandboxUnavailable(
            "未找到桌面版便携 Python，请重新安装应用后再运行本机代码。"
        )
    return path


def runner_environment(python: Path, workdir: Path) -> dict[str, str]:
    """只保留解释器运行必需变量；不传入任何 ``KIWI_*``、数据库或密钥。"""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = str(Path(system_root) / "System32")
    env = {
        "PATH": os.pathsep.join([str(python.parent), system32, system_root]),
        "SystemRoot": system_root,
        "WINDIR": os.environ.get("WINDIR", system_root),
        "COMSPEC": os.environ.get("COMSPEC", str(Path(system32) / "cmd.exe")),
        "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
        "TEMP": str(workdir),
        "TMP": str(workdir),
        "HOME": str(workdir),
        "USERPROFILE": str(workdir),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(workdir / ".matplotlib"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    return env


def create_job() -> WindowsJob:
    if _kernel32 is None:
        raise SandboxUnavailable("Windows 本机执行仅在 Windows 上可用。")
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise SandboxUnavailable(f"创建 Job Object 失败（WinError {_last_error()}）。")
    job = WindowsJob(handle=int(handle))
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info.BasicLimitInformation.ActiveProcessLimit = MAX_ACTIVE_PROCESSES
    info.ProcessMemoryLimit = MAX_PROCESS_MEMORY
    info.JobMemoryLimit = MAX_JOB_MEMORY
    ok = _kernel32.SetInformationJobObject(
        wintypes.HANDLE(job.handle),
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        error = _last_error()
        job.close()
        raise SandboxUnavailable(f"配置 Job Object 失败（WinError {error}）。")
    return job


def _resume_process(pid: int) -> None:
    """恢复 CREATE_SUSPENDED 进程；Popen 不暴露线程句柄，只能按 PID 枚举。"""
    assert _kernel32 is not None
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or ctypes.c_void_p(snapshot).value == ctypes.c_void_p(-1).value:
        raise SandboxUnavailable(f"无法枚举进程线程（WinError {_last_error()}）。")
    entry = _THREADENTRY32()
    entry.dwSize = ctypes.sizeof(_THREADENTRY32)
    resumed = 0
    try:
        has_entry = _kernel32.Thread32First(
            wintypes.HANDLE(snapshot), ctypes.byref(entry)
        )
        while has_entry:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                )
                if thread:
                    try:
                        if _kernel32.ResumeThread(wintypes.HANDLE(thread)) != 0xFFFFFFFF:
                            resumed += 1
                    finally:
                        _kernel32.CloseHandle(wintypes.HANDLE(thread))
            has_entry = _kernel32.Thread32Next(
                wintypes.HANDLE(snapshot), ctypes.byref(entry)
            )
    finally:
        _kernel32.CloseHandle(wintypes.HANDLE(snapshot))
    if resumed == 0:
        raise SandboxUnavailable("无法恢复被挂起的本机执行进程。")


def spawn_windows_process(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdin: int | None = subprocess.PIPE,
    stdout: int | None = subprocess.PIPE,
    stderr: int | None = subprocess.PIPE,
    bufsize: int = 0,
) -> WindowsProcess:
    """以挂起状态启动进程，加入 Job Object 后再恢复，避免逃逸。"""
    if os.name != "nt" or _kernel32 is None:
        raise SandboxUnavailable("Windows 本机执行仅在 Windows 上可用。")
    job = create_job()
    try:
        proc = subprocess.Popen(  # noqa: S603 - 命令由固定解释器与常量代码组成
            args,
            cwd=str(cwd),
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            bufsize=bufsize,
            creationflags=_CREATE_SUSPENDED | _CREATE_NO_WINDOW,
        )
    except OSError as exc:
        job.close()
        raise SandboxUnavailable(f"无法启动便携 Python：{exc}") from exc
    try:
        if not _kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(job.handle), wintypes.HANDLE(int(proc._handle))
        ):
            raise SandboxUnavailable(
                f"将本机执行进程加入 Job Object 失败（WinError {_last_error()}）。"
            )
        _resume_process(proc.pid)
    except BaseException:
        job.terminate(1)
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait(timeout=5)
        job.close()
        raise
    return WindowsProcess(proc=proc, job=job)


def _read_limited(
    stream,
    buffer: bytearray,
    lock: threading.Lock,
    overflow: threading.Event,
    process: WindowsProcess,
) -> None:
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            with lock:
                remaining = MAX_OUTPUT_BYTES - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
            if overflow.is_set():
                process.job.terminate(1)
                break
    except (OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


def _write_stdin(stream, data: bytes) -> None:
    try:
        stream.write(data)
        stream.close()
    except (OSError, ValueError):
        pass


def _decode(buffer: bytearray, truncated: bool) -> str:
    text = bytes(buffer).decode("utf-8", errors="replace")
    if truncated:
        text = (text + "\n…（输出已截断）").strip()
    return text


def run_once_windows(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    workdir: Path | None = None,
) -> SandboxResult:
    """在便携 Python + Job Object 中执行一次性代码。"""
    ensure_safe(code)
    python = runner_python()
    owns_workdir = workdir is None
    if workdir is None:
        base = settings.data_dir / "sandbox"
        base.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    else:
        workdir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    wrapper: WindowsProcess | None = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    lock = threading.Lock()
    overflow = threading.Event()
    timed_out = False
    try:
        wrapper = spawn_windows_process(
            [str(python), "-I", "-u", "-"],
            cwd=workdir,
            env=runner_environment(python, workdir),
        )
        proc = wrapper.proc
        threads = [
            threading.Thread(
                target=_read_limited,
                args=(proc.stdout, buffers["stdout"], lock, overflow, wrapper),
                daemon=True,
                name="kiwi-win-out",
            ),
            threading.Thread(
                target=_read_limited,
                args=(proc.stderr, buffers["stderr"], lock, overflow, wrapper),
                daemon=True,
                name="kiwi-win-err",
            ),
            threading.Thread(
                target=_write_stdin,
                args=(proc.stdin, code.encode("utf-8")),
                daemon=True,
                name="kiwi-win-in",
            ),
        ]
        for thread in threads:
            thread.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            wrapper.job.terminate(1)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=5)

        truncated = overflow.is_set()
        stdout = _decode(buffers["stdout"], truncated)
        stderr = _decode(buffers["stderr"], truncated)
        if timed_out:
            stderr = (stderr + f"\n运行超过 {timeout:g} 秒，已终止进程树。").strip()
        elif truncated:
            stderr = (stderr + "\n输出超过 400 KB，已终止进程树。").strip()
        return SandboxResult(
            ok=not timed_out and not truncated and proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=None if (timed_out or truncated) else proc.returncode,
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            truncated=truncated,
            sandboxed=False,
            engine=WINDOWS_ENGINE,
            warning=WINDOWS_WARNING,
        )
    finally:
        if wrapper is not None:
            wrapper.close()
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def windows_sandbox_status() -> dict:
    available = _portable_python() is not None
    python = _portable_python()
    return {
        "available": available,
        "engine": WINDOWS_ENGINE,
        "network": False,
        "sandboxed": False,
        "warning": WINDOWS_WARNING,
        "writable_paths": [str(settings.data_dir / "sandbox")],
        "venv": str(python.parent) if python else "",
        "project_venv": "",
        "package_managers": [],
        "uv": False,
        "python_version": sys.version.split()[0],
    }
