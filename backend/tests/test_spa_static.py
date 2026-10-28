"""桌面版 SPA 静态服务：回退、MIME、缓存与安全头。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from app.config import settings
from app.spa import setup_spa

INDEX_HTML = "<!doctype html><html><body><div id=app>SPA</div></body></html>"


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "pdfjs").mkdir()
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "sw.js").write_text("self.addEventListener('install', () => {})", encoding="utf-8")
    (dist / "build-info.json").write_text('{"version":"test"}', encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (dist / "pdfjs" / "a.bcmap").write_bytes(b"\x00\x01")
    return dist


@pytest.fixture
def spa_client(monkeypatch, tmp_path):
    dist = _make_dist(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    (media / "demo.txt").write_text("media-content", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist", dist)
    monkeypatch.setattr(settings, "desktop_mode", True)

    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    # 与 main.py 一致：media 在 SPA 之前挂载。
    app.mount("/media", StaticFiles(directory=str(media)), name="media")
    setup_spa(app)
    return app


async def _get(app: FastAPI, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path, **kwargs)


async def test_root_serves_index_with_security_headers(spa_client):
    resp = await _get(spa_client, "/")
    assert resp.status_code == 200
    assert "SPA" in resp.text
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in resp.headers["permissions-policy"]


async def test_deep_link_history_fallback_requires_html_accept(spa_client):
    resp = await _get(spa_client, "/wiki/abc/notes", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "SPA" in resp.text

    bare = await _get(spa_client, "/wiki/abc/notes")
    assert bare.status_code == 404


async def test_missing_asset_is_404_not_index(spa_client):
    resp = await _get(spa_client, "/assets/missing.js", headers={"Accept": "text/html"})
    assert resp.status_code == 404
    assert "SPA" not in resp.text


async def test_api_paths_are_never_swallowed(spa_client):
    ok = await _get(spa_client, "/api/ping", headers={"Accept": "text/html"})
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}

    missing = await _get(spa_client, "/api/missing", headers={"Accept": "text/html"})
    assert missing.status_code == 404
    assert "SPA" not in missing.text


async def test_asset_mime_and_immutable_cache(spa_client):
    resp = await _get(spa_client, "/assets/app.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "content-security-policy" not in resp.headers


async def test_pdfjs_assets_have_daily_cache_and_bcmap_mime(spa_client):
    resp = await _get(spa_client, "/pdfjs/a.bcmap")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert resp.headers["content-type"].startswith("application/octet-stream")


async def test_root_and_service_worker_files(spa_client):
    build = await _get(spa_client, "/build-info.json")
    assert build.status_code == 200
    assert build.headers["content-type"].startswith("application/json")
    assert build.headers["cache-control"] == "no-cache"
    assert build.json() == {"version": "test"}

    sw = await _get(spa_client, "/sw.js")
    assert sw.status_code == 200
    assert sw.headers["service-worker-allowed"] == "/"
    assert sw.headers["cache-control"] == "no-cache"
    assert sw.headers["content-type"].startswith("text/javascript")

    icon = await _get(spa_client, "/favicon.svg")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")


async def test_media_range_and_no_csp(spa_client):
    resp = await _get(spa_client, "/media/demo.txt", headers={"Range": "bytes=0-4"})
    assert resp.status_code == 206
    assert resp.text == "media"
    assert resp.headers["content-range"].startswith("bytes 0-4/")
    assert "content-security-policy" not in resp.headers


async def test_head_request(spa_client):
    transport = httpx.ASGITransport(app=spa_client)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.head("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


async def test_security_headers_only_in_desktop_mode(monkeypatch, tmp_path):
    dist = _make_dist(tmp_path)
    monkeypatch.setattr(settings, "frontend_dist", dist)
    monkeypatch.setattr(settings, "desktop_mode", False)
    app = FastAPI()
    setup_spa(app)

    resp = await _get(app, "/")
    assert resp.status_code == 200
    assert "SPA" in resp.text
    assert "content-security-policy" not in resp.headers


def test_missing_index_fails_fast(monkeypatch, tmp_path):
    empty = tmp_path / "empty-dist"
    empty.mkdir()
    monkeypatch.setattr(settings, "frontend_dist", empty)
    monkeypatch.setattr(settings, "desktop_mode", True)
    with pytest.raises(RuntimeError, match="前端资源缺失"):
        setup_spa(FastAPI())


async def test_docker_root_remains_json(client):
    """未设置 frontend_dist 时 `/` 仍是 JSON 探针（Docker 回归）。"""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Kiwi"
    assert data["status"] == "/api/health"
