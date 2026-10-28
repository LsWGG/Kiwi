"""桌面设置 JSON：原子写入、损坏回退与不可信字段收敛。"""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.config import settings
from app.services import desktop_settings


@pytest.fixture
def settings_file(monkeypatch, tmp_path):
    path = tmp_path / "desktop-settings.json"
    monkeypatch.setattr(settings, "desktop_settings_path", path)
    return path


def test_missing_file_uses_safe_defaults(settings_file):
    cfg = desktop_settings.load()

    assert cfg.version == desktop_settings.SETTINGS_VERSION
    assert cfg.allow_online_models is False
    assert cfg.local_code_execution is False
    assert cfg.local_code_timeout_seconds == desktop_settings.DEFAULT_CODE_TIMEOUT
    assert cfg.acknowledged_online_models_at is None
    assert cfg.acknowledged_local_code_at is None
    assert cfg.updated_at is None
    assert not settings_file.exists()


def test_atomic_save_and_reload(settings_file):
    cfg = desktop_settings.load()
    cfg.allow_online_models = True
    cfg.acknowledged_online_models_at = "2026-01-01T00:00:00+00:00"

    saved = desktop_settings.save(cfg)

    assert settings_file.exists()
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["allow_online_models"] is True
    assert data["updated_at"] == saved.updated_at
    # 原子写入不残留临时文件。
    assert [path.name for path in settings_file.parent.iterdir()] == [
        settings_file.name
    ]
    if os.name != "nt":
        assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600

    reloaded = desktop_settings.load()
    assert reloaded.allow_online_models is True
    assert reloaded.acknowledged_online_models_at == "2026-01-01T00:00:00+00:00"


def test_corrupt_file_falls_back_without_rewriting(settings_file):
    settings_file.write_text("{not json", encoding="utf-8")

    cfg = desktop_settings.load()

    assert cfg.allow_online_models is False
    assert cfg.local_code_execution is False
    # 不用默认值覆盖损坏文件，保留现场供用户排查。
    assert settings_file.read_text(encoding="utf-8") == "{not json"


def test_non_object_payload_falls_back(settings_file):
    settings_file.write_text("[]", encoding="utf-8")

    cfg = desktop_settings.load()

    assert cfg.allow_online_models is False
    assert cfg.local_code_execution is False


def test_untrusted_values_are_coerced_to_safe_defaults(settings_file):
    settings_file.write_text(
        json.dumps(
            {
                "version": "2",
                "allow_online_models": "true",
                "local_code_execution": 1,
                "local_code_timeout_seconds": 99999,
                "acknowledged_online_models_at": 123,
                "updated_at": ["x"],
            }
        ),
        encoding="utf-8",
    )

    cfg = desktop_settings.load()

    assert cfg.version == desktop_settings.SETTINGS_VERSION
    # 字符串 "true" 与整数 1 都不能开启风险开关。
    assert cfg.allow_online_models is False
    assert cfg.local_code_execution is False
    assert cfg.local_code_timeout_seconds == desktop_settings.MAX_CODE_TIMEOUT
    assert cfg.acknowledged_online_models_at is None
    assert cfg.updated_at is None


def test_timeout_is_clamped(settings_file):
    cfg = desktop_settings.load()
    cfg.local_code_timeout_seconds = 1

    saved = desktop_settings.save(cfg)

    assert saved.local_code_timeout_seconds == desktop_settings.MIN_CODE_TIMEOUT
