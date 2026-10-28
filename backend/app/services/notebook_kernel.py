"""Notebook Python 内核：为每个笔记本维护一个长期运行的 Python 子进程。

* 每个内核都运行在 bubblewrap 安全沙箱内：独立的 PID / 挂载 / IPC / UTS /
  Cgroup 命名空间，仅 ``/work`` 与 ``/tmp`` 可写，项目目录、数据库与密钥不可见；
  Notebook 显式开启网络，以便 ``pip`` / ``uv pip`` 安装依赖；
* 单元格通过 stdin/stdout 的 JSON Lines 协议发送 / 接收，变量在单元格之间保留；
* 每 30 分钟无访问自动回收，最多同时保留 8 个内核；
* 单元格默认 60 秒超时，超时先向沙箱内 Python 发送 SIGINT（可中断纯 Python
  循环），2 秒后仍未退出则终止并重启内核；
* 危险操作（``rm -rf``、格式化磁盘、关机等）在进入沙箱前即被拦截。

每个笔记本拥有 ``/work/.venv`` 可写虚拟环境，通过 ``.pth`` 继承后端只读环境
（pandas、numpy、matplotlib 等），安装的新包在工作目录中持久化。内核同时识别
Jupyter 风格的 ``!命令``、``%pip``、``%uv``、``%cd`` 与 ``%%bash``。
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.sandbox import (
    DangerousCodeError,
    SandboxUnavailable,
    ensure_notebook_venv,
    ensure_safe,
    sandbox_status,
    spawn_sandbox,
)

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 400_000
MAX_KERNELS = 8
IDLE_SECONDS = 30 * 60
MAX_CODE_CHARS = 200_000

_KERNEL_SOURCE = r'''
import ast, base64, contextlib, io, json, os, re, shlex, subprocess, sys, time, traceback

# Windows 桌面版：Job Object 不是文件系统沙箱，因此拒绝 shell / 安装依赖，
# 并把 %cd 限制在当前笔记本工作目录内。Linux 沙箱行为保持不变。
_DESKTOP_WINDOWS = os.name == "nt"
_kernel_root = os.path.realpath(os.getcwd())

sys.path.insert(0, os.getcwd())
_max_text = 400000
_main_stdin = sys.stdin
_namespace = {"__name__": "__main__", "__builtins__": __builtins__}
_display_buffer = []
_shown_figures = set()


def _clip(value):
    try:
        text = str(value)
    except Exception:
        text = "<unprintable>"
    if len(text) > _max_text:
        return text[:_max_text] + "\n…（输出已截断）"
    return text


def _html(value):
    fn = getattr(value, "_repr_html_", None)
    if not callable(fn):
        return ""
    try:
        html = fn()
    except Exception:
        return ""
    return _clip(html) if isinstance(html, str) else ""


def _figure_output(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", dpi=120)
    _shown_figures.add(id(fig))
    return {
        "type": "display_data",
        "image": {
            "mime": "image/png",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        },
    }


def _format(value):
    module = type(value).__module__
    if module.startswith("matplotlib.figure") or module.startswith("matplotlib.axes"):
        fig = getattr(value, "figure", value)
        try:
            return [_figure_output(fig)]
        except Exception:
            pass
    return [{
        "type": "execute_result",
        "text": _clip(repr(value)),
        "html": _html(value),
    }]


def display(*values, **kwargs):
    for value in values:
        _display_buffer.extend(_format(value))


def _drain_figures():
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return []
    outputs = []
    try:
        numbers = list(plt.get_fignums())
    except Exception:
        return []
    for number in numbers:
        try:
            fig = plt.figure(number)
            if id(fig) not in _shown_figures:
                outputs.append(_figure_output(fig))
        except Exception:
            pass
        finally:
            try:
                plt.close(number)
            except Exception:
                pass
    _shown_figures.clear()
    return outputs


_namespace["display"] = display


# ---------- Jupyter 风格命令：!shell、%pip、%uv、%cd 等 ----------
def _exec_command(args, label, shell=False, timeout=280):
    proc = subprocess.Popen(
        args,
        shell=shell,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError("%s 运行超过 %d 秒，已终止。" % (label, timeout))
    except BaseException:
        proc.kill()
        raise
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    if proc.returncode:
        raise RuntimeError("%s 执行失败（退出码 %d）。" % (label, proc.returncode))


def _kiwi_shell(command):
    if _DESKTOP_WINDOWS:
        raise RuntimeError("桌面版 Notebook 已禁用 shell 命令（!命令），只支持 Python 代码。")
    print("$ %s" % command)
    _exec_command(command, command, shell=True)


def _kiwi_pip(args):
    if _DESKTOP_WINDOWS:
        raise RuntimeError("桌面版 Notebook 不支持安装依赖（%pip），请重新安装应用以更新运行包。")
    print("$ pip %s" % args)
    try:
        _exec_command([sys.executable, "-m", "pip", *shlex.split(args)], "pip %s" % args)
    except FileNotFoundError:
        raise RuntimeError("当前环境没有 pip，请先执行 %uv pip install pip 或重启内核。")


def _kiwi_uv(args):
    if _DESKTOP_WINDOWS:
        raise RuntimeError("桌面版 Notebook 不支持安装依赖（%uv），请重新安装应用以更新运行包。")
    print("$ uv %s" % args)
    try:
        _exec_command(["uv", *shlex.split(args)], "uv %s" % args)
    except FileNotFoundError:
        raise RuntimeError("当前沙箱没有 uv，可改用 %pip install 安装依赖。")


def _kiwi_cd(path):
    target = os.path.realpath(os.path.expanduser(path.strip() or _kernel_root))
    if _DESKTOP_WINDOWS:
        try:
            inside = os.path.commonpath([_kernel_root, target]).casefold() == _kernel_root.casefold()
        except ValueError:
            inside = False
        if not inside:
            raise RuntimeError("桌面版 Notebook 只能切换到当前笔记本工作目录内。")
    os.chdir(target)
    print(os.getcwd())


def _kiwi_pwd():
    print(os.getcwd())


def _kiwi_env(value):
    value = value.strip()
    if not value:
        for key in sorted(os.environ):
            print("%s=%s" % (key, os.environ[key]))
        return
    if "=" in value:
        key, _, val = value.partition("=")
        os.environ[key.strip()] = val
        print("%s=%s" % (key.strip(), val))
    else:
        print(os.environ.get(value, ""))


def _kiwi_who(verbose=False):
    for name in sorted(_namespace):
        if name.startswith("__"):
            continue
        value = _namespace[name]
        if verbose:
            print("%-24s %-16s %s" % (name, type(value).__name__, repr(value)[:80]))
        else:
            print(name)


def _kiwi_time(code):
    started = time.time()
    exec(compile(code, "<magic>", "exec"), _namespace)
    print("Wall time: %.3f s" % (time.time() - started))


def _kiwi_unknown_magic(name):
    raise RuntimeError(
        "不支持的行魔法 %%%s。可用：%%pip、%%uv、%%cd、%%pwd、%%env、%%who、%%whos、%%time、%%matplotlib。"
        % name
    )


def _kiwi_whos():
    _kiwi_who(True)


for _helper_name, _helper in {
    "_kiwi_shell": _kiwi_shell,
    "_kiwi_pip": _kiwi_pip,
    "_kiwi_uv": _kiwi_uv,
    "_kiwi_cd": _kiwi_cd,
    "_kiwi_pwd": _kiwi_pwd,
    "_kiwi_env": _kiwi_env,
    "_kiwi_who": _kiwi_who,
    "_kiwi_whos": _kiwi_whos,
    "_kiwi_time": _kiwi_time,
    "_kiwi_unknown_magic": _kiwi_unknown_magic,
}.items():
    _namespace[_helper_name] = _helper


_SHELL_LINE = re.compile(r"^(\s*)!(.*)$")
_MAGIC_LINE = re.compile(r"^(\s*)%([A-Za-z_]\w*)(.*)$")


def _transform_magics(code):
    lines = []
    for line in code.split("\n"):
        match = _SHELL_LINE.match(line)
        if match:
            lines.append("%s_kiwi_shell(%r)" % (match.group(1), match.group(2).strip()))
            continue
        match = _MAGIC_LINE.match(line)
        if match:
            indent, name, rest = match.group(1), match.group(2).lower(), match.group(3).strip()
            if name == "pip":
                lines.append("%s_kiwi_pip(%r)" % (indent, rest))
            elif name == "uv":
                lines.append("%s_kiwi_uv(%r)" % (indent, rest))
            elif name == "cd":
                lines.append("%s_kiwi_cd(%r)" % (indent, rest))
            elif name == "pwd":
                lines.append("%s_kiwi_pwd()" % indent)
            elif name == "env":
                lines.append("%s_kiwi_env(%r)" % (indent, rest))
            elif name == "who":
                lines.append("%s_kiwi_who()" % indent)
            elif name == "whos":
                lines.append("%s_kiwi_whos()" % indent)
            elif name == "time":
                lines.append("%s_kiwi_time(%r)" % (indent, rest))
            elif name in ("matplotlib", "config", "load_ext", "reload_ext", "autoreload"):
                lines.append("%spass" % indent)
            else:
                lines.append("%s_kiwi_unknown_magic(%r)" % (indent, name))
            continue
        lines.append(line)
    return "\n".join(lines)


def _run_cell_magic(code):
    stripped = code.lstrip()
    if not stripped.startswith("%%"):
        return False
    first, _, body = stripped.partition("\n")
    parts = first[2:].strip().split(None, 1)
    name = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    if name in ("bash", "sh", "shell"):
        if _DESKTOP_WINDOWS:
            raise RuntimeError("桌面版 Notebook 已禁用 shell 单元格（%%bash / %%sh）。")
        shell = "/bin/bash" if name == "bash" else "/bin/sh"
        _exec_command([shell, "-c", body], "%%" + name)
        return True
    if name == "writefile":
        target = os.path.realpath(arg or "output.txt")
        if _DESKTOP_WINDOWS:
            try:
                inside = os.path.commonpath([_kernel_root, target]).casefold() == _kernel_root.casefold()
            except ValueError:
                inside = False
            if not inside:
                raise RuntimeError("桌面版 Notebook 只能写入当前笔记本工作目录内的文件。")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(body)
        print("已写入 %s（%d 字节）" % (os.path.abspath(target), len(body.encode("utf-8"))))
        return True
    if name in ("time", "timeit"):
        started = time.time()
        exec(compile(_transform_magics(body), "<cell-magic>", "exec"), _namespace)
        print("Wall time: %.3f s" % (time.time() - started))
        return True
    raise RuntimeError("不支持的单元格魔法：%%%s" % name)


def _run(code):
    global _display_buffer
    _display_buffer = []
    if _run_cell_magic(code):
        outputs = list(_display_buffer)
        outputs.extend(_drain_figures())
        return outputs
    tree = ast.parse(_transform_magics(code), "<cell>", "exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
        ast.fix_missing_locations(last)
    exec(compile(tree, "<cell>", "exec"), _namespace)
    value = eval(compile(last, "<cell>", "eval"), _namespace) if last is not None else None
    outputs = list(_display_buffer)
    if value is not None:
        outputs.extend(_format(value))
    outputs.extend(_drain_figures())
    return outputs


for line in _main_stdin:
    line = line.strip()
    if not line:
        continue
    try:
        request = json.loads(line)
    except Exception:
        continue
    code = str(request.get("code") or "")
    stdout, stderr = io.StringIO(), io.StringIO()
    outputs = []
    ok = True
    old_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            outputs = _run(code)
    except BaseException:
        ok = False
        outputs.append({"type": "error", "text": traceback.format_exc()[:20000]})
    finally:
        sys.stdin = old_stdin
    out_text = stdout.getvalue()
    err_text = stderr.getvalue()
    if out_text:
        outputs.insert(0, {"type": "stream", "name": "stdout", "text": _clip(out_text)})
    if err_text:
        outputs.insert(1 if out_text else 0, {"type": "stream", "name": "stderr", "text": _clip(err_text)})
    sys.stdout.write(json.dumps({"ok": ok, "outputs": outputs}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
'''


@dataclass
class KernelExecution:
    ok: bool
    outputs: list[dict[str, Any]]
    execution_count: int
    duration_ms: int
    timed_out: bool = False
    kernel_restarted: bool = False
    busy: bool = False
    error: str | None = None
    engine: str = "bubblewrap"
    warning: str | None = None


@dataclass
class _Kernel:
    note_id: str
    kb_id: str
    workdir: Path
    proc: subprocess.Popen
    lock: threading.Lock = field(default_factory=threading.Lock)
    execution_count: int = 0
    generation: int = 1
    last_used: float = field(default_factory=time.monotonic)
    stderr_tail: list[str] = field(default_factory=list)
    # Windows Job Object 句柄与输出队列；Linux 分支保持为 None / 未使用。
    job: object | None = None
    windows: bool = False
    stdout_queue: queue.Queue[bytes | None] = field(default_factory=queue.Queue)

    def alive(self) -> bool:
        return self.proc.poll() is None


class NotebookKernelManager:
    """按笔记维护内核进程；线程安全，供 FastAPI 线程池调用。"""

    def __init__(self) -> None:
        self._kernels: dict[str, _Kernel] = {}
        self._guard = threading.Lock()

    # ---------- 生命周期 ----------
    @staticmethod
    def _workdir_path(kb_id: str, note_id: str) -> Path:
        return settings.data_dir / "notebooks" / kb_id / note_id

    def _workdir(self, kb_id: str, note_id: str) -> Path:
        path = self._workdir_path(kb_id, note_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _spawn(self, kb_id: str, note_id: str) -> _Kernel:
        workdir = self._workdir(kb_id, note_id)
        if os.name == "nt" and settings.desktop_mode:
            return self._spawn_windows(kb_id, note_id, workdir)
        python_exe = ensure_notebook_venv(workdir)
        writable_venv = python_exe.startswith("/work/.venv")
        # Notebook 允许联网（pip / uv 安装依赖）；其余命名空间隔离保持不变。
        proc = spawn_sandbox(
            workdir,
            ["-I", "-u", "-c", _KERNEL_SOURCE],
            allow_network=True,
            python_exe=python_exe,
            extra_path="/work/.venv/bin:/run/kiwi-bin" if writable_venv else "/run/kiwi-bin",
            extra_env=(
                {
                    "VIRTUAL_ENV": "/work/.venv",
                    "UV_LINK_MODE": "copy",
                    "UV_CACHE_DIR": "/work/.uv-cache",
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                }
                if writable_venv
                else {}
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        kernel = _Kernel(note_id=note_id, kb_id=kb_id, workdir=workdir, proc=proc)
        self._start_stderr_drain(kernel)
        return kernel

    def _spawn_windows(self, kb_id: str, note_id: str, workdir: Path) -> _Kernel:
        """Windows 桌面：便携 Python + Job Object，用线程读取管道（无 select）。"""
        from app.services.windows_sandbox import (
            runner_environment,
            runner_python,
            spawn_windows_process,
        )

        python = runner_python()
        wrapper = spawn_windows_process(
            [str(python), "-I", "-u", "-c", _KERNEL_SOURCE],
            cwd=workdir,
            env=runner_environment(python, workdir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        kernel = _Kernel(
            note_id=note_id,
            kb_id=kb_id,
            workdir=workdir,
            proc=wrapper.proc,
            job=wrapper.job,
            windows=True,
        )

        def pump_stdout() -> None:
            assert wrapper.proc.stdout is not None
            try:
                for raw in iter(wrapper.proc.stdout.readline, b""):
                    kernel.stdout_queue.put(raw)
            except (OSError, ValueError):
                pass
            finally:
                kernel.stdout_queue.put(None)

        threading.Thread(
            target=pump_stdout, daemon=True, name=f"nb-out-{note_id[:8]}"
        ).start()
        self._start_stderr_drain(kernel)
        return kernel

    @staticmethod
    def _start_stderr_drain(kernel: _Kernel) -> None:
        proc = kernel.proc

        def drain_stderr() -> None:
            assert proc.stderr is not None
            try:
                for raw in iter(proc.stderr.readline, b""):
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    kernel.stderr_tail.append(line)
                    del kernel.stderr_tail[:-20]
            except Exception:
                pass

        threading.Thread(
            target=drain_stderr, daemon=True, name=f"nb-stderr-{kernel.note_id[:8]}"
        ).start()

    @staticmethod
    def _sandbox_child_pid(host_pid: int) -> int | None:
        """定位沙箱内真正执行代码的 Python 进程。

        进程链为 ``bwrap(宿主) -> bwrap(命名空间 init) -> prlimit -> python``，
        只有最末端的 Python 会处理 SIGINT；发给命名空间 init（PID 1）会被忽略。
        """
        queue = [host_pid]
        visited = 0
        while queue and visited < 64:
            current = queue.pop(0)
            visited += 1
            if current != host_pid:
                try:
                    comm = Path(f"/proc/{current}/comm").read_text().strip()
                except OSError:
                    comm = ""
                # bwrap 的 cmdline 里也包含 "python"（它是待执行命令），必须看实际镜像名
                if comm.startswith("python"):
                    return current
            try:
                raw = Path(f"/proc/{current}/task/{current}/children").read_text().strip()
            except OSError:
                continue
            queue.extend(int(token) for token in raw.split() if token.isdigit())
        return None

    @staticmethod
    def _kernel_meta(kernel: _Kernel) -> dict[str, str]:
        if not kernel.windows:
            return {}
        from app.services.windows_sandbox import WINDOWS_ENGINE, WINDOWS_WARNING

        return {"engine": WINDOWS_ENGINE, "warning": WINDOWS_WARNING}

    def _terminate(self, kernel: _Kernel) -> None:
        if kernel.job is not None:
            # TerminateJobObject 会杀掉内核及其启动的整棵进程树。
            try:
                kernel.job.terminate(1)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    kernel.proc.wait(timeout=5)
            finally:
                with contextlib.suppress(Exception):
                    kernel.job.close()
                kernel.job = None
            return
        try:
            if kernel.proc.poll() is None:
                child = self._sandbox_child_pid(kernel.proc.pid)
                if child:
                    try:
                        os.kill(child, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                os.killpg(kernel.proc.pid, signal.SIGTERM)
                try:
                    kernel.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if child:
                        try:
                            os.kill(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    os.killpg(kernel.proc.pid, signal.SIGKILL)
                    kernel.proc.wait(timeout=2)
        except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
            pass

    def _drop(self, note_id: str) -> None:
        with self._guard:
            kernel = self._kernels.pop(note_id, None)
        if kernel is not None:
            self._terminate(kernel)

    def _cleanup_idle(self) -> None:
        now = time.monotonic()
        with self._guard:
            stale = [
                key
                for key, kernel in self._kernels.items()
                if not kernel.lock.locked() and now - kernel.last_used > IDLE_SECONDS
            ]
        for key in stale:
            self._drop(key)

    def _get_or_create(self, kb_id: str, note_id: str) -> _Kernel:
        self._cleanup_idle()
        with self._guard:
            kernel = self._kernels.get(note_id)
            if kernel is not None and kernel.alive():
                if kernel.kb_id != kb_id:
                    self._terminate(kernel)
                    self._kernels.pop(note_id, None)
                    kernel = None
                else:
                    return kernel
            if kernel is not None:
                self._terminate(kernel)
                self._kernels.pop(note_id, None)
            if len(self._kernels) >= MAX_KERNELS:
                oldest = min(self._kernels.values(), key=lambda item: item.last_used)
                if not oldest.lock.locked():
                    self._terminate(oldest)
                    self._kernels.pop(oldest.note_id, None)
            kernel = self._spawn(kb_id, note_id)
            self._kernels[note_id] = kernel
            return kernel

    # ---------- 对外操作 ----------
    def execute(
        self,
        kb_id: str,
        note_id: str,
        code: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> KernelExecution:
        timeout = max(1.0, min(float(timeout), MAX_TIMEOUT_SECONDS))
        code = code[:MAX_CODE_CHARS]
        try:
            ensure_safe(code)
        except DangerousCodeError as exc:
            return KernelExecution(
                ok=False,
                outputs=[{"type": "error", "text": str(exc)}],
                execution_count=0,
                duration_ms=0,
                error=str(exc),
            )
        try:
            kernel = self._get_or_create(kb_id, note_id)
        except SandboxUnavailable as exc:
            return KernelExecution(
                ok=False,
                outputs=[{"type": "error", "text": str(exc)}],
                execution_count=0,
                duration_ms=0,
                error=str(exc),
            )
        meta = self._kernel_meta(kernel)
        if not kernel.lock.acquire(timeout=1.0):
            return KernelExecution(
                ok=False,
                outputs=[],
                execution_count=kernel.execution_count,
                duration_ms=0,
                busy=True,
                error="内核正在执行其他单元格，请等待当前单元格结束。",
                **meta,
            )
        try:
            kernel.last_used = time.monotonic()
            restarted = False
            if not kernel.alive():
                # 内核在获取锁的瞬间退出：清理后让用户重跑，避免持错锁。
                self._drop(note_id)
                return KernelExecution(
                    ok=False,
                    outputs=[
                        {
                            "type": "error",
                            "text": "Python 内核已退出，已自动清理；请重新运行该单元格。",
                        }
                    ],
                    execution_count=0,
                    duration_ms=0,
                    kernel_restarted=True,
                    **meta,
                )
            kernel.execution_count += 1
            count = kernel.execution_count
            started = time.monotonic()
            payload = json.dumps({"code": code}, ensure_ascii=False) + "\n"
            try:
                assert kernel.proc.stdin is not None
                kernel.proc.stdin.write(payload.encode("utf-8"))
                kernel.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._drop(note_id)
                return KernelExecution(
                    ok=False,
                    outputs=[
                        {
                            "type": "error",
                            "text": "Python 内核已退出，已自动清理；请重新运行该单元格。",
                        }
                    ],
                    execution_count=count,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    kernel_restarted=True,
                    **meta,
                )

            timed_out = False
            assert kernel.proc.stdout is not None
            if kernel.windows:
                # Windows 管道不支持 select；stdout 由后台线程写入队列。
                try:
                    line = kernel.stdout_queue.get(timeout=timeout)
                except queue.Empty:
                    self._drop(note_id)
                    return KernelExecution(
                        ok=False,
                        outputs=[
                            {
                                "type": "error",
                                "text": (
                                    f"运行超过 {timeout:g} 秒，已终止并重启内核。"
                                    "变量状态已丢失。"
                                ),
                            }
                        ],
                        execution_count=count,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        timed_out=True,
                        kernel_restarted=True,
                        **meta,
                    )
                if line is None:
                    line = b""
            else:
                ready, _, _ = select.select([kernel.proc.stdout], [], [], timeout)
                if not ready:
                    timed_out = True
                    # 先尝试中断，让纯 Python 循环抛出 KeyboardInterrupt 并返回输出。
                    # 沙箱内 Python 是 bwrap 的子进程，信号必须发给它而不是 bwrap。
                    target = self._sandbox_child_pid(kernel.proc.pid) or kernel.proc.pid
                    try:
                        os.kill(target, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                    ready, _, _ = select.select([kernel.proc.stdout], [], [], 2.0)
                    if not ready:
                        self._drop(note_id)
                        return KernelExecution(
                            ok=False,
                            outputs=[
                                {
                                    "type": "error",
                                    "text": (
                                        f"运行超过 {timeout:g} 秒，内核无法中断，已终止并重启。"
                                        "变量状态已丢失。"
                                    ),
                                }
                            ],
                            execution_count=count,
                            duration_ms=int((time.monotonic() - started) * 1000),
                            timed_out=True,
                            kernel_restarted=True,
                            **meta,
                        )

                line = kernel.proc.stdout.readline()
            if not line:
                self._drop(note_id)
                return KernelExecution(
                    ok=False,
                    outputs=[
                        {
                            "type": "error",
                            "text": "Python 内核意外退出，已自动清理；请重新运行该单元格。",
                        }
                    ],
                    execution_count=count,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    kernel_restarted=True,
                    **meta,
                )
            try:
                data = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                self._drop(note_id)
                return KernelExecution(
                    ok=False,
                    outputs=[
                        {
                            "type": "error",
                            "text": "内核返回了无法解析的输出，已重启内核。",
                        }
                    ],
                    execution_count=count,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    kernel_restarted=True,
                    **meta,
                )
            outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
            outputs = [item for item in outputs if isinstance(item, dict)][:200]
            if timed_out:
                outputs.append(
                    {
                        "type": "error",
                        "text": f"运行超过 {timeout:g} 秒，已发送中断信号。",
                    }
                )
            return KernelExecution(
                ok=bool(data.get("ok")) and not timed_out,
                outputs=outputs,
                execution_count=count,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=timed_out,
                kernel_restarted=restarted,
                **meta,
            )
        finally:
            kernel.last_used = time.monotonic()
            kernel.lock.release()

    @staticmethod
    def _desktop_windows() -> bool:
        return os.name == "nt" and settings.desktop_mode

    def restart(self, kb_id: str, note_id: str) -> dict[str, Any]:
        self._drop(note_id)
        kernel = self._get_or_create(kb_id, note_id)
        return {
            "running": kernel.alive(),
            "execution_count": 0,
            "python_version": sys.version.split()[0],
            "workdir": str(kernel.workdir) if kernel.windows else "/work",
            "generation": kernel.generation,
            "sandbox": sandbox_status(allow_network=not kernel.windows),
        }

    def status(self, kb_id: str, note_id: str) -> dict[str, Any]:
        self._cleanup_idle()
        with self._guard:
            kernel = self._kernels.get(note_id)
        if kernel is None or not kernel.alive():
            windows = kernel.windows if kernel is not None else self._desktop_windows()
            return {
                "running": False,
                "execution_count": 0,
                "python_version": sys.version.split()[0],
                "workdir": (
                    str(self._workdir_path(kb_id, note_id)) if windows else "/work"
                ),
                "sandbox": sandbox_status(allow_network=not windows),
            }
        return {
            "running": True,
            "execution_count": kernel.execution_count,
            "python_version": sys.version.split()[0],
            "workdir": str(kernel.workdir) if kernel.windows else "/work",
            "busy": kernel.lock.locked(),
            "idle_seconds": int(time.monotonic() - kernel.last_used),
            "sandbox": sandbox_status(allow_network=not kernel.windows),
        }

    def terminate(self, note_id: str) -> None:
        self._drop(note_id)

    def purge_note(self, kb_id: str, note_id: str) -> None:
        """永久删除笔记时终止内核并清理沙箱工作目录。"""
        self._drop(note_id)
        shutil.rmtree(self._workdir_path(str(kb_id), str(note_id)), ignore_errors=True)

    def terminate_kb(self, kb_id: str) -> None:
        with self._guard:
            keys = [
                key for key, kernel in self._kernels.items() if kernel.kb_id == str(kb_id)
            ]
        for key in keys:
            self._drop(key)

    def purge_kb(self, kb_id: str) -> None:
        self.terminate_kb(kb_id)
        shutil.rmtree(
            settings.data_dir / "notebooks" / str(kb_id), ignore_errors=True
        )

    def shutdown_all(self) -> None:
        with self._guard:
            keys = list(self._kernels)
        for key in keys:
            self._drop(key)


kernel_manager = NotebookKernelManager()
atexit.register(kernel_manager.shutdown_all)
