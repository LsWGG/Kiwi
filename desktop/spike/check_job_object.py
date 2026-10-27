"""Phase 0：验证 Windows Job Object 的 KILL_ON_JOB_CLOSE 与进程树清理。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(
    os.environ.get("SPIKE_OUT")
    or Path(__file__).resolve().parent / "out" / "job-object.json"
)
result: dict = {"check": "job-object", "status": "fail", "details": {}}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
ntdll.NtResumeProcess.argtypes = [wt.HANDLE]
ntdll.NtResumeProcess.restype = ctypes.c_long

CREATE_SUSPENDED = 0x00000004

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
kernel32.CreateJobObjectW.restype = wt.HANDLE
kernel32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
kernel32.SetInformationJobObject.restype = wt.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
kernel32.AssignProcessToJobObject.restype = wt.BOOL
kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
kernel32.TerminateJobObject.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


def last_error() -> str:
    code = ctypes.get_last_error()
    return f"win32 error {code}: {ctypes.FormatError(code)}"


def create_job() -> int:
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(f"CreateJobObjectW 失败：{last_error()}")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    )
    info.BasicLimitInformation.ActiveProcessLimit = 8
    info.ProcessMemoryLimit = 2 * 1024**3
    if not kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise OSError(f"SetInformationJobObject 失败：{last_error()}")
    return job


def make_bat(work: Path) -> Path:
    bat = work / "spawn-tree.bat"
    # start /b 产生孙进程；第二个 ping 让父进程保持存活。
    bat.write_text(
        "@echo off\r\n"
        "start /b cmd /c \"ping -n 300 127.0.0.1 >nul\"\r\n"
        "ping -n 300 127.0.0.1 >nul\r\n",
        encoding="ascii",
    )
    return bat


def spawn_and_assign(job: int, bat: Path) -> subprocess.Popen:
    # 先以挂起状态创建，加入 Job 后再恢复，避免子进程在入 Job 前逃逸。
    proc = subprocess.Popen(
        ["cmd.exe", "/c", str(bat)],
        creationflags=CREATE_SUSPENDED
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # noqa: SLF001
        proc.kill()
        raise OSError(f"AssignProcessToJobObject 失败：{last_error()}")
    status = ntdll.NtResumeProcess(int(proc._handle))  # noqa: SLF001
    if status != 0:
        proc.kill()
        raise OSError(f"NtResumeProcess 失败：NTSTATUS {status:#x}")
    return proc


def descendants(pid: int) -> list[int]:
    import psutil

    try:
        return [child.pid for child in psutil.Process(pid).children(recursive=True)]
    except psutil.Error:
        return []


def alive(pids: list[int]) -> list[int]:
    import psutil

    return [pid for pid in pids if psutil.pid_exists(pid)]


def main() -> None:
    import psutil

    work = Path(tempfile.gettempdir()) / "kiwi-job-spike"
    work.mkdir(parents=True, exist_ok=True)
    bat = make_bat(work)
    result["details"]["psutil"] = psutil.__version__

    jobs: list[int] = []
    procs: list[subprocess.Popen] = []
    try:
        job = create_job()
        jobs.append(job)
        result["details"]["create_and_configure_job"] = "ok"

        proc = spawn_and_assign(job, bat)
        procs.append(proc)
        time.sleep(2)
        tree = descendants(proc.pid)
        result["details"]["root_pid"] = proc.pid
        result["details"]["tree_pids"] = tree
        if len(tree) < 2:
            raise AssertionError(f"未形成进程树，子进程：{tree}")

        if not kernel32.TerminateJobObject(job, 1):
            raise OSError(f"TerminateJobObject 失败：{last_error()}")
        proc.wait(timeout=10)
        time.sleep(1)
        survivors = alive(tree)
        result["details"]["survivors_after_terminate"] = survivors
        if survivors:
            raise AssertionError(f"TerminateJobObject 后仍有进程存活：{survivors}")
        result["details"]["terminate_tree"] = "ok"

        # 单独验证 KILL_ON_JOB_CLOSE：关闭句柄即杀掉进程树。
        job2 = create_job()
        jobs.append(job2)
        proc2 = spawn_and_assign(job2, bat)
        procs.append(proc2)
        time.sleep(2)
        tree2 = descendants(proc2.pid)
        if len(tree2) < 2:
            raise AssertionError(f"第二棵树未形成，子进程：{tree2}")
        if not kernel32.CloseHandle(job2):
            raise OSError(f"CloseHandle 失败：{last_error()}")
        jobs.remove(job2)
        time.sleep(2)
        survivors2 = alive(tree2)
        result["details"]["survivors_after_close"] = survivors2
        if survivors2:
            raise AssertionError(f"关闭 Job 句柄后仍有进程存活：{survivors2}")
        result["details"]["kill_on_close"] = "ok"

        result["status"] = "pass"
        result["summary"] = "Job Object 可限制进程数 / 内存、终止进程树，KILL_ON_JOB_CLOSE 生效"
    finally:
        for proc in procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        for job in jobs:
            try:
                kernel32.CloseHandle(job)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - 结果文件需要保留完整堆栈
        result["error"] = traceback.format_exc()
        print(result["error"], file=sys.stderr, flush=True)
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["status"] == "pass" else 1)
