"""桌面 API：模式开关、风险确认、本机执行可用性与状态输出。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.config import settings
from app.routers import desktop
from app.services.notebook_kernel import kernel_manager


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(desktop.router)
    app.include_router(desktop.internal_router)
    return app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    )


@pytest.fixture
async def desktop_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(
        settings, "desktop_settings_path", tmp_path / "desktop-settings.json"
    )
    monkeypatch.setattr(settings, "desktop_python", "")
    async with await _client() as http:
        yield http


async def test_routes_hidden_outside_desktop_mode(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    async with await _client() as http:
        resp = await http.get("/api/desktop/status")
        assert resp.status_code == 404

        resp = await http.get("/api/desktop/settings")
        assert resp.status_code == 404


async def test_internal_shutdown_requires_loopback_and_token(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_control_token", "control-token")
    called: list[bool] = []
    app = _app()
    app.state.desktop_shutdown_callback = lambda: called.append(True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.post("/internal/shutdown")).status_code == 403
        wrong = await http.post(
            "/internal/shutdown", headers={"X-Kiwi-Control-Token": "wrong"}
        )
        assert wrong.status_code == 403

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=app, client=("203.0.113.5", 5000)
            ),
            base_url="http://test",
        ) as remote:
            denied = await remote.post(
                "/internal/shutdown",
                headers={"X-Kiwi-Control-Token": "control-token"},
            )
            assert denied.status_code == 403

        ok = await http.post(
            "/internal/shutdown", headers={"X-Kiwi-Control-Token": "control-token"}
        )
        assert ok.status_code == 200
        assert ok.json() == {"status": "shutting-down"}

    assert called == [True]


async def test_internal_shutdown_requires_runtime_callback(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_control_token", "control-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as http:
        resp = await http.post(
            "/internal/shutdown", headers={"X-Kiwi-Control-Token": "control-token"}
        )
    assert resp.status_code == 503


async def test_internal_shutdown_hidden_outside_desktop_mode(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    monkeypatch.setattr(settings, "desktop_control_token", "control-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as http:
        resp = await http.post(
            "/internal/shutdown", headers={"X-Kiwi-Control-Token": "control-token"}
        )
    assert resp.status_code == 404


async def test_settings_defaults_are_safe(desktop_client):
    resp = await desktop_client.get("/api/desktop/settings")

    assert resp.status_code == 200
    body = resp.json()
    assert body["allow_online_models"] is False
    assert body["local_code_execution"] is False
    assert body["local_code_timeout_seconds"] == 60
    assert body["acknowledged_online_models_at"] is None
    assert body["acknowledged_local_code_at"] is None


async def test_enabling_online_models_requires_fresh_acknowledgement(desktop_client):
    resp = await desktop_client.put(
        "/api/desktop/settings", json={"allow_online_models": True}
    )
    assert resp.status_code == 400

    resp = await desktop_client.put(
        "/api/desktop/settings",
        json={"allow_online_models": True, "acknowledge_risk": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allow_online_models"] is True
    assert body["acknowledged_online_models_at"]

    # 关闭后再次开启，必须重新确认。
    resp = await desktop_client.put(
        "/api/desktop/settings", json={"allow_online_models": False}
    )
    assert resp.status_code == 200
    resp = await desktop_client.put(
        "/api/desktop/settings", json={"allow_online_models": True}
    )
    assert resp.status_code == 400


async def test_local_code_requires_portable_python(desktop_client):
    resp = await desktop_client.put(
        "/api/desktop/settings",
        json={"local_code_execution": True, "acknowledge_risk": True},
    )

    assert resp.status_code == 409
    assert "便携 Python" in resp.json()["detail"]


async def test_local_code_enable_and_disable(desktop_client, monkeypatch, tmp_path):
    portable_python = tmp_path / "resources" / "python.exe"
    portable_python.parent.mkdir(parents=True)
    portable_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "desktop_python", str(portable_python))
    shutdowns: list[bool] = []
    monkeypatch.setattr(
        kernel_manager, "shutdown_all", lambda: shutdowns.append(True)
    )

    resp = await desktop_client.put(
        "/api/desktop/settings",
        json={"local_code_execution": True, "acknowledge_risk": True},
    )
    assert resp.status_code == 200
    assert resp.json()["local_code_execution"] is True
    assert resp.json()["acknowledged_local_code_at"]
    assert shutdowns == []

    status = (await desktop_client.get("/api/desktop/status")).json()
    assert status["local_code"]["enabled"] is True
    assert status["local_code"]["available"] is True
    assert status["capabilities"]["local_code_execution"] is True

    resp = await desktop_client.put(
        "/api/desktop/settings", json={"local_code_execution": False}
    )
    assert resp.status_code == 200
    assert resp.json()["local_code_execution"] is False
    # 关闭开关会立即回收内核。
    assert shutdowns == [True]


async def test_local_code_timeout_bounds(desktop_client):
    for value in (4, 601):
        resp = await desktop_client.put(
            "/api/desktop/settings",
            json={"local_code_timeout_seconds": value},
        )
        assert resp.status_code == 422

    resp = await desktop_client.put(
        "/api/desktop/settings", json={"local_code_timeout_seconds": 120}
    )
    assert resp.status_code == 200
    assert resp.json()["local_code_timeout_seconds"] == 120


async def test_status_reports_capabilities(desktop_client, monkeypatch):
    async def fake_llm_configured() -> bool:
        return True

    monkeypatch.setattr(desktop, "_llm_configured", fake_llm_configured)
    monkeypatch.setattr(
        desktop.embedder,
        "runtime_config",
        lambda: SimpleNamespace(provider="none"),
    )

    resp = await desktop_client.get("/api/desktop/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["desktop"] is True
    assert body["version"]
    assert body["llm"] == {"configured": True, "remote_allowed": False}
    assert body["embedding"] == {
        "enabled": False,
        "provider": "none",
        "state": "disabled",
    }
    assert body["local_code"]["available"] is False
    assert body["capabilities"] == {
        "online_models": False,
        "link_fetch": False,
        "remote_import": False,
        "online_ocr": False,
        "feishu": False,
        "web_push": False,
        "study_web_search": False,
        "youtube_embed": False,
        "external_images": False,
        "local_code_execution": False,
    }
