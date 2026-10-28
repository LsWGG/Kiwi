"""Windows 桌面本机执行：Job Object runner、便携 Python 站点钩子与路由守卫。

Job Object 只能在 Windows 上验证，相关用例在 Linux / macOS 自动跳过；
sitecustomize 的 socket 限制在子进程中验证，避免审计钩子污染测试进程。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import desktop_guard, desktop_settings, windows_sandbox
from app.services.sandbox import DangerousCodeError

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="需要 Windows Job Object")
BACKEND_DIR = Path(__file__).resolve().parents[1]
SITECUSTOMIZE_DIR = BACKEND_DIR.parent / "desktop" / "runtime"


@pytest.fixture
def desktop_settings_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "desktop_mode", True)
    path = tmp_path / "desktop-settings.json"
    monkeypatch.setattr(settings, "desktop_settings_path", path)
    return path


def test_require_local_execution_defaults_off(desktop_settings_file):
    with pytest.raises(HTTPException) as exc:
        desktop_guard.require_local_execution()
    assert exc.value.status_code == 403
    assert "本机代码执行默认关闭" in exc.value.detail


@WINDOWS_ONLY
def test_require_local_execution_checks_portable_python(
    desktop_settings_file, monkeypatch, tmp_path
):
    desktop_settings.save(
        desktop_settings.DesktopSettings(local_code_execution=True)
    )
    monkeypatch.setattr(settings, "desktop_python", str(tmp_path / "missing.exe"))
    with pytest.raises(HTTPException) as exc:
        desktop_guard.require_local_execution()
    assert exc.value.status_code == 503
    assert "便携 Python" in exc.value.detail


@pytest.mark.skipif(os.name == "nt", reason="验证非 Windows 上的明确失败路径")
def test_runner_rejects_non_windows():
    with pytest.raises(windows_sandbox.SandboxUnavailable):
        windows_sandbox.runner_python()
    with pytest.raises(windows_sandbox.SandboxUnavailable):
        windows_sandbox.create_job()


def test_status_reports_windows_engine_without_running(monkeypatch, tmp_path):
    python = tmp_path / "resources" / "python" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "desktop_python", str(python))
    status = windows_sandbox.windows_sandbox_status()
    assert status["engine"] == "windows-job"
    assert status["available"] is True
    assert status["sandboxed"] is False
    assert status["network"] is False
    assert status["warning"]


def _run_with_sitecustomize(tmp_path: Path, body: str) -> dict:
    """在全新解释器中导入 sitecustomize，验证 socket 限制。"""
    script = (
        "import json, socket\n"
        "results = {}\n"
        "def attempt(name, fn):\n"
        "    try:\n"
        "        fn()\n"
        "        results[name] = 'allowed'\n"
        "    except PermissionError as exc:\n"
        "        results[name] = 'blocked'\n"
        "    except OSError as exc:\n"
        "        results[name] = 'oserror'\n"
        f"{body}\n"
        "print(json.dumps(results))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SITECUSTOMIZE_DIR)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_sitecustomize_blocks_external_network(tmp_path):
    results = _run_with_sitecustomize(
        tmp_path,
        "attempt('dns', lambda: socket.getaddrinfo('example.com', 80))\n"
        "attempt('connect', lambda: socket.socket().connect(('192.0.2.1', 80)))\n"
        "attempt('gethostbyname', lambda: socket.gethostbyname('example.com'))\n"
        "attempt('loopback_dns', lambda: socket.getaddrinfo('localhost', 80))\n"
        "attempt('loopback_connect', lambda: socket.socket().connect(('127.0.0.1', 9)))\n",
    )
    assert results["dns"] == "blocked"
    assert results["connect"] == "blocked"
    assert results["gethostbyname"] == "blocked"
    assert results["loopback_dns"] == "allowed"
    # 127.0.0.1:9 大概率没有服务；关键是审计钩子放行而不是 PermissionError。
    assert results["loopback_connect"] in {"allowed", "oserror"}


# --------------------------------------------------------------------------- #
# Windows：Job Object + 便携 Python 行为
# --------------------------------------------------------------------------- #
@pytest.fixture
def windows_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_python", sys.executable)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return windows_sandbox


@WINDOWS_ONLY
def test_run_once_windows_result_and_env(windows_runner):
    result = windows_runner.run_once_windows(
        "import os\nprint(os.environ.get('KIWI_DATABASE_URL'))\nprint(6 * 7)\n",
        timeout=30,
    )
    assert result.ok
    assert result.engine == "windows-job"
    assert result.sandboxed is False
    assert result.warning
    assert "None" in result.stdout
    assert "42" in result.stdout


@WINDOWS_ONLY
def test_run_once_windows_timeout_kills_tree(windows_runner):
    result = windows_runner.run_once_windows(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n",
        timeout=1,
    )
    assert result.timed_out
    assert result.exit_code is None
    assert "运行超过" in result.stderr


@WINDOWS_ONLY
def test_run_once_windows_truncates_output(windows_runner):
    result = windows_runner.run_once_windows(
        "print('x' * (500 * 1024))", timeout=30
    )
    assert result.truncated
    assert "输出已截断" in result.stdout


@WINDOWS_ONLY
def test_run_once_windows_rejects_dangerous_code(windows_runner):
    with pytest.raises(DangerousCodeError):
        windows_runner.run_once_windows("import os; os.system('format C:')")
