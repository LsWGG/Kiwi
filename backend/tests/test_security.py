"""可选访问令牌与限流中间件的 ASGI 级测试。"""

from __future__ import annotations

import asyncio
import json

from app.config import settings
from app.security import AccessControlMiddleware, RateLimitMiddleware


async def ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def call(middleware, path: str, *, method: str = "GET", headers=None, query: str = ""):
    sent: list[dict] = []

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query.encode(),
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 12345),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return status, body, sent


def run(middleware, path, **kwargs):
    # 不用 asyncio.run()：它在退出时会把当前事件循环置空，
    # 导致同一进程里后续的 pytest-asyncio（session 级 loop）用例拿不到事件循环。
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(call(middleware, path, **kwargs))
    finally:
        loop.close()


def test_access_control_disabled_allows_everything(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "")
    status, _, _ = run(AccessControlMiddleware(ok_app), "/api/kbs")
    assert status == 200


def test_access_control_blocks_private_paths(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "s3cret")
    mw = AccessControlMiddleware(ok_app)

    status, body, _ = run(mw, "/api/kbs")
    assert status == 401
    assert json.loads(body)["code"] == "access_token_required"

    status, _, _ = run(mw, "/media/a.png")
    assert status == 401

    # Prometheus 指标同样受保护，抓取端需携带令牌。
    status, _, _ = run(mw, "/metrics")
    assert status == 401
    status, _, _ = run(mw, "/metrics", headers={"X-Access-Token": "s3cret"})
    assert status == 200

    status, _, _ = run(mw, "/api/kbs", headers={"X-Access-Token": "s3cret"})
    assert status == 200

    status, _, _ = run(mw, "/api/kbs", headers={"Authorization": "Bearer s3cret"})
    assert status == 200


def test_access_control_keeps_public_paths_open(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "s3cret")
    mw = AccessControlMiddleware(ok_app)
    for path in ("/api/health", "/api/health/detail", "/api/auth/status", "/"):
        status, _, _ = run(mw, path)
        assert status == 200, path


def test_media_query_token(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "s3cret")
    mw = AccessControlMiddleware(ok_app)
    status, _, _ = run(mw, "/media/a.png", query="token=s3cret")
    assert status == 200
    status, _, _ = run(mw, "/media/a.png", query="token=wrong")
    assert status == 401


def test_options_is_never_blocked(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "s3cret")
    status, _, _ = run(AccessControlMiddleware(ok_app), "/api/kbs", method="OPTIONS")
    assert status == 200


def test_rate_limit_bucket_returns_429(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_llm_per_minute", 2)
    mw = RateLimitMiddleware(ok_app)
    assert run(mw, "/api/chat/stream", method="POST")[0] == 200
    assert run(mw, "/api/chat/stream", method="POST")[0] == 200
    status, body, messages = run(mw, "/api/chat/stream", method="POST")
    assert status == 429
    headers = dict(
        (key.decode(), value.decode())
        for key, value in next(
            m["headers"] for m in messages if m["type"] == "http.response.start"
        )
    )
    assert "retry-after" in headers
    assert json.loads(body)["code"] == "rate_limited"
