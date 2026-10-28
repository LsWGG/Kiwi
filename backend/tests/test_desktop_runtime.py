"""桌面 runtime 的纯逻辑：路径、状态文件、单实例锁与环境变量。

不启动 PostgreSQL / Qdrant / uvicorn；这些由 Windows 冒烟覆盖。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from cryptography.fernet import Fernet

RUNTIME_PATH = Path(__file__).resolve().parents[2] / "desktop" / "runtime" / "kiwi_runtime.py"


@pytest.fixture(scope="module")
def runtime():
    spec = importlib.util.spec_from_file_location("kiwi_desktop_runtime", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses 需要能从 sys.modules 找到模块的全局命名空间。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _paths(runtime, tmp_path):
    return runtime.RuntimePaths(
        data_dir=tmp_path / "data",
        resources=tmp_path / "resources",
        frontend_dist=tmp_path / "resources" / "frontend",
        state_file=tmp_path / "data" / "runtime.json",
        log_dir=tmp_path / "data" / "logs",
    )


def test_resolve_paths_defaults(runtime, tmp_path):
    args = SimpleNamespace(
        data_dir=str(tmp_path / "data"),
        resources=str(tmp_path / "resources"),
        frontend_dist="",
        state_file="",
        parent_pid=0,
        control_token_env="KIWI_DESKTOP_CONTROL_TOKEN",
    )
    paths = runtime.resolve_paths(args)
    assert paths.data_dir == (tmp_path / "data").resolve()
    assert paths.frontend_dist == (tmp_path / "resources" / "frontend").resolve()
    assert paths.state_file == (tmp_path / "data" / "runtime.json").resolve()
    assert paths.pgdata == paths.data_dir / "pg"
    assert paths.fernet_key_file == paths.data_dir / "secrets" / "fernet.key"


def test_prepare_directories_and_fernet_key(runtime, tmp_path):
    paths = _paths(runtime, tmp_path)
    runtime.prepare_directories(paths)
    for directory in (
        paths.pgdata,
        paths.qdrant_storage,
        paths.data_dir / "uploads",
        paths.data_dir / "backups",
        paths.data_dir / "notebooks",
        paths.data_dir / "sandbox",
        paths.data_dir / "wiki_schemas",
        paths.secrets_dir,
        paths.log_dir,
    ):
        assert directory.is_dir(), directory

    key = runtime.load_or_create_fernet_key(paths.fernet_key_file)
    assert runtime.load_or_create_fernet_key(paths.fernet_key_file) == key
    Fernet(key.encode())  # 验证是可用的 Fernet 密钥
    assert paths.fernet_key_file.read_text(encoding="utf-8").strip() == key


def test_runtime_state_atomic_and_no_secrets(runtime, tmp_path):
    state_path = tmp_path / "runtime.json"
    state = runtime.RuntimeState(
        state_path, data_dir=tmp_path / "data", log_file=tmp_path / "runtime.log"
    )
    state.update(stage="postgres")
    state.update(status="ready", stage="ready", http_port=4567)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["stage"] == "ready"
    assert payload["http_port"] == 4567
    assert payload["pid"] == os.getpid()
    assert "token" not in json.dumps(payload).lower()
    # 原子写不留下临时文件
    assert list(tmp_path.glob(".runtime.json.*.tmp")) == []

    state.fail("migrate", "RuntimeError: boom")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["stage"] == "migrate"
    assert payload["error"] == "RuntimeError: boom"


def test_data_dir_lock_is_exclusive(runtime, tmp_path):
    lock_path = tmp_path / "runtime.lock"
    first = runtime.DataDirLock(lock_path)
    second = runtime.DataDirLock(lock_path)
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_build_app_env_desktop_defaults(runtime, tmp_path):
    paths = _paths(runtime, tmp_path)
    env = runtime.build_app_env(
        paths=paths,
        db_url="postgresql+asyncpg://postgres:@127.0.0.1:5432/postgres",
        qdrant_url="http://127.0.0.1:6333",
        http_port=4567,
        fernet_key="test-key",
        pg_dump=None,
        python_path=None,
    )
    assert env["KIWI_DESKTOP_MODE"] == "true"
    assert env["KIWI_OFFLINE_MODE"] == "true"
    assert env["KIWI_EMBED_PROVIDER"] == "none"
    assert env["KIWI_WHISPER_ENABLED"] == "false"
    assert env["KIWI_KB_SCHEDULER_ENABLED"] == "false"
    assert env["KIWI_ACCESS_TOKEN"] == ""
    assert json.loads(env["KIWI_CORS_ORIGINS"]) == ["http://127.0.0.1:4567"]
    assert env["KIWI_DATA_DIR"] == str(paths.data_dir)
    assert env["KIWI_BACKUP_DIR"] == str(paths.data_dir / "backups")
    assert env["KIWI_LOG_FILE"] == str(paths.log_dir / "backend.log")
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["KIWI_PG_DUMP_PATH"] == ""
    assert env["KIWI_DESKTOP_PYTHON"] == ""
    assert "KIWI_DESKTOP_CONTROL_TOKEN" not in env


def test_scrub_inherited_env(runtime):
    with mock.patch.dict(
        os.environ,
        {"KIWI_ACCESS_TOKEN": "secret", "Kiwi_Database_Url": "x", "PATH": "/bin"},
        clear=True,
    ):
        runtime.scrub_inherited_env()
        assert "KIWI_ACCESS_TOKEN" not in os.environ
        assert "Kiwi_Database_Url" not in os.environ
        assert os.environ["PATH"] == "/bin"


def test_short_windows_path_only_on_windows(runtime, tmp_path):
    if os.name == "nt":
        pytest.skip("Windows 上由共享文件夹路径行为决定，不在此断言")
    assert runtime.short_windows_path(tmp_path) is None
