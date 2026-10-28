"""桌面模式配置默认值回归：Docker / 源码部署行为保持不变。"""

from __future__ import annotations

from app.config import PROJECT_ROOT, Settings

_DESKTOP_ENV = (
    "KIWI_DESKTOP_MODE",
    "KIWI_OFFLINE_MODE",
    "KIWI_FRONTEND_DIST",
    "KIWI_DATA_DIR",
    "KIWI_DESKTOP_SETTINGS_PATH",
    "KIWI_DESKTOP_CONTROL_TOKEN",
    "KIWI_DESKTOP_PYTHON",
    "KIWI_PG_DUMP_PATH",
    "KIWI_LOG_FILE",
    "KIWI_KB_SCHEDULER_ENABLED",
    "KIWI_EMBED_PROVIDER",
    "KIWI_WHISPER_ENABLED",
)


def _clean_env(monkeypatch) -> None:
    for key in _DESKTOP_ENV:
        monkeypatch.delenv(key, raising=False)


def test_desktop_defaults_preserve_existing_behavior(monkeypatch):
    _clean_env(monkeypatch)
    cfg = Settings(_env_file=None)

    assert cfg.desktop_mode is False
    assert cfg.offline_mode is False
    assert cfg.frontend_dist is None
    assert cfg.data_dir == PROJECT_ROOT / "data"
    assert cfg.desktop_settings_path is None
    assert cfg.desktop_control_token == ""
    assert cfg.desktop_python == ""
    assert cfg.pg_dump_path == ""
    assert cfg.log_file is None
    assert cfg.kb_scheduler_enabled is True
    # Docker 主线依赖的默认值不变。
    assert cfg.embed_provider == "local"
    assert cfg.whisper_enabled is True


def test_relative_desktop_paths_resolve_against_project_root(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("KIWI_DATA_DIR", "desktop-data")
    monkeypatch.setenv("KIWI_FRONTEND_DIST", "desktop/frontend")
    monkeypatch.setenv("KIWI_DESKTOP_SETTINGS_PATH", "desktop/desktop-settings.json")
    monkeypatch.setenv("KIWI_LOG_FILE", "desktop/logs/runtime.log")

    cfg = Settings(_env_file=None)

    assert cfg.data_dir == (PROJECT_ROOT / "desktop-data").resolve()
    assert cfg.frontend_dist == (PROJECT_ROOT / "desktop/frontend").resolve()
    assert (
        cfg.desktop_settings_path
        == (PROJECT_ROOT / "desktop/desktop-settings.json").resolve()
    )
    assert cfg.log_file == (PROJECT_ROOT / "desktop/logs/runtime.log").resolve()


def test_blank_optional_paths_are_none(monkeypatch):
    _clean_env(monkeypatch)
    for key in (
        "KIWI_FRONTEND_DIST",
        "KIWI_DESKTOP_SETTINGS_PATH",
        "KIWI_LOG_FILE",
    ):
        monkeypatch.setenv(key, "")

    cfg = Settings(_env_file=None)

    assert cfg.frontend_dist is None
    assert cfg.desktop_settings_path is None
    assert cfg.log_file is None
