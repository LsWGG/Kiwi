"""桌面离线防护：审计钩子、模型端点白名单与联网功能守卫。

审计钩子一旦安装无法移除，因此 socket 行为在子进程中验证；路由守卫与
URL 策略则直接在测试进程内断言。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import (
    desktop_guard,
    desktop_settings,
    ocr_service,
    offline_guard,
    rerank,
    web_research,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "offline_mode", False)
    path = tmp_path / "desktop-settings.json"
    monkeypatch.setattr(settings, "desktop_settings_path", path)
    offline_guard.refresh_policy()
    offline_guard.revoke_endpoints()
    try:
        yield path
    finally:
        offline_guard.refresh_policy()
        offline_guard.revoke_endpoints()


# --------------------------------------------------------------------------- #
# 进程内：路由守卫与模型 URL 策略
# --------------------------------------------------------------------------- #
def test_require_online_feature_blocks_all_desktop_features(desktop):
    for feature in desktop_guard.FEATURE_LABELS:
        with pytest.raises(HTTPException) as exc:
            desktop_guard.require_online_feature(feature)
        assert exc.value.status_code == 409
        assert "桌面版已禁用" in exc.value.detail


def test_guards_are_noop_outside_desktop_mode(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    desktop_guard.require_online_feature("link_fetch")
    desktop_guard.require_local_execution()
    assert (
        desktop_guard.validate_model_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1"
    )


def test_validate_model_url_allows_loopback(desktop):
    for url in (
        "http://127.0.0.1:11434",
        "http://localhost:11434/v1",
        "http://[::1]:8000/v1",
    ):
        assert desktop_guard.validate_model_url(url) == url


def test_validate_model_url_external_requires_ack(desktop):
    with pytest.raises(HTTPException) as exc:
        desktop_guard.validate_model_url("https://api.openai.com/v1")
    assert exc.value.status_code == 400
    assert "允许连接外部模型接口" in exc.value.detail

    desktop_settings.save(desktop_settings.DesktopSettings(allow_online_models=True))
    offline_guard.refresh_policy()
    assert (
        desktop_guard.validate_model_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1"
    )


def test_validate_model_url_rejects_invalid_scheme(desktop):
    for url in ("ftp://example.com/v1", "not-a-url"):
        with pytest.raises(HTTPException) as exc:
            desktop_guard.validate_model_url(url)
        assert exc.value.status_code == 400


def test_require_local_execution_defaults_off(desktop):
    with pytest.raises(HTTPException) as exc:
        desktop_guard.require_local_execution()
    assert exc.value.status_code == 403

    desktop_settings.save(desktop_settings.DesktopSettings(local_code_execution=True))
    desktop_guard.require_local_execution()


def test_offline_services_are_forced_disabled(desktop):
    assert ocr_service.is_available() is False
    with pytest.raises(ocr_service.OcrError, match="桌面版已禁用在线 OCR"):
        ocr_service.ocr_image_bytes(b"fake", config=ocr_service.OcrConfig(enabled=True))
    assert rerank.enabled() is False
    assert web_research.provider_enabled() is False


async def test_online_feature_routes_return_409(client, desktop):
    kb_id = uuid.uuid4()

    resp = await client.post(
        "/api/notes/link/meta", json={"url": "https://example.com/article"}
    )
    assert resp.status_code == 409, resp.text

    resp = await client.post(
        f"/api/notes/import-url?kb_id={kb_id}",
        json={"url": "https://example.com/file.pdf"},
    )
    assert resp.status_code == 409, resp.text

    resp = await client.post("/api/ingest/yuque/repos", json={"token": "token"})
    assert resp.status_code == 409, resp.text

    resp = await client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example.com/subscription/abc",
            "keys": {"p256dh": "x" * 20, "auth": "y" * 10},
        },
    )
    assert resp.status_code == 409, resp.text

    resp = await client.post(
        f"/api/transcribe?kb_id={kb_id}",
        files={"file": ("clip.mp3", b"ID3demo", "audio/mpeg")},
    )
    assert resp.status_code == 409, resp.text

    resp = await client.post("/api/settings/system/ocr/test", json={})
    assert resp.status_code == 409, resp.text


async def test_llm_config_rejects_external_url_until_allowed(client, desktop):
    payload = {
        "name": f"pytest-{uuid.uuid4().hex[:8]}",
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model_name": "demo",
    }
    resp = await client.post("/api/llm/configs", json=payload)
    assert resp.status_code == 400, resp.text

    desktop_settings.save(desktop_settings.DesktopSettings(allow_online_models=True))
    offline_guard.refresh_policy()
    resp = await client.post("/api/llm/configs", json=payload)
    assert resp.status_code == 201, resp.text
    await client.delete(f"/api/llm/configs/{resp.json()['id']}")


# --------------------------------------------------------------------------- #
# 子进程：socket 审计钩子（安装后不可移除）
# --------------------------------------------------------------------------- #
def _write_settings(tmp_path: Path, allow_online: bool) -> Path:
    path = tmp_path / "desktop-settings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "allow_online_models": allow_online,
                "local_code_execution": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_guard_script(code: str, tmp_path: Path, *, allow_online: bool) -> str:
    settings_path = _write_settings(tmp_path, allow_online)
    env = {
        **os.environ,
        "KIWI_OFFLINE_MODE": "true",
        "KIWI_DESKTOP_MODE": "true",
        "KIWI_DESKTOP_SETTINGS_PATH": str(settings_path),
        # install() 应清理这些代理变量。
        "HTTP_PROXY": "http://203.0.113.9:3128",
        "HTTPS_PROXY": "http://203.0.113.9:3128",
        "ALL_PROXY": "http://203.0.113.9:3128",
    }
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    return proc.stdout


OFFLINE_SCRIPT = """
import os
import socket

from app.services import offline_guard

assert offline_guard.install() is True
assert offline_guard.is_installed() is True

# loopback：TCP connect 与 DNS 均放行。
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
client = socket.socket()
client.connect(listener.getsockname())
client.close()
conn, _ = listener.accept()
conn.close()
listener.close()
socket.getaddrinfo("localhost", 80)
print("LOOPBACK_OK")

# 未登记的外部 DNS / IP 一律阻断。
try:
    socket.getaddrinfo("example.com", 443)
except offline_guard.OfflineNetworkBlocked:
    print("DNS_BLOCKED")
else:
    raise SystemExit("DNS_NOT_BLOCKED")

try:
    probe = socket.socket()
    probe.settimeout(1.0)
    probe.connect(("203.0.113.5", 443))
except offline_guard.OfflineNetworkBlocked:
    print("CONNECT_BLOCKED")
except OSError:
    raise SystemExit("CONNECT_NOT_BLOCKED")
else:
    raise SystemExit("CONNECT_NOT_BLOCKED")

# 未开启 allow_online_models 时，登记外部模型端点直接失败。
try:
    offline_guard.register_endpoint("http://203.0.113.5:8080")
except offline_guard.OnlineModelsDisabled:
    print("ONLINE_DISABLED")
else:
    raise SystemExit("ONLINE_NOT_DISABLED")

print(
    "PROXY",
    os.environ.get("HTTP_PROXY"),
    os.environ.get("HTTPS_PROXY"),
    os.environ.get("ALL_PROXY"),
    os.environ.get("NO_PROXY"),
)
"""


ALLOWED_SCRIPT = """
import socket
import time

from app.services import offline_guard

assert offline_guard.install() is True

offline_guard.register_endpoint("http://203.0.113.5:8080", ttl=30)
try:
    socket.getaddrinfo("203.0.113.5", 8080)
except offline_guard.OfflineNetworkBlocked:
    raise SystemExit("REGISTERED_BLOCKED")
print("REGISTERED_OK")

offline_guard.register_endpoint("http://203.0.113.6:8080", ttl=0.05)
time.sleep(0.2)
try:
    socket.getaddrinfo("203.0.113.6", 8080)
except offline_guard.OfflineNetworkBlocked:
    print("EXPIRED_BLOCKED")
else:
    raise SystemExit("EXPIRED_NOT_BLOCKED")
"""


def test_audit_hook_blocks_external_and_allows_loopback(tmp_path):
    stdout = _run_guard_script(OFFLINE_SCRIPT, tmp_path, allow_online=False)
    assert "LOOPBACK_OK" in stdout
    assert "DNS_BLOCKED" in stdout
    assert "CONNECT_BLOCKED" in stdout
    assert "ONLINE_DISABLED" in stdout
    # 代理变量被清空，NO_PROXY 指向本机。
    proxy_line = next(line for line in stdout.splitlines() if line.startswith("PROXY "))
    assert proxy_line.split()[1:4] == ["None", "None", "None"]
    assert "127.0.0.1" in proxy_line
    assert "localhost" in proxy_line


def test_registered_endpoint_allowed_until_ttl_expires(tmp_path):
    stdout = _run_guard_script(ALLOWED_SCRIPT, tmp_path, allow_online=True)
    assert "REGISTERED_OK" in stdout
    assert "EXPIRED_BLOCKED" in stdout
