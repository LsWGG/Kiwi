"""可选访问令牌与简单限流。

默认不启用（单用户本地应用）。设置 ``KIWI_ACCESS_TOKEN`` 后：

- ``/api/*``、``/media/*`` 与 ``/metrics``（Prometheus）需要 ``X-Access-Token``、
  ``Authorization: Bearer``、登录 Cookie，或媒体 URL 上的 ``?token=``；
- ``/api/health``、``/api/auth/*`` 与前端静态资源保持公开，供健康检查与登录页使用；
- LLM、导入、代码执行接口按分钟限流，返回 429。

限流是单进程内存实现，重启后清零；单用户场景足够，不作为安全边界。
"""

from __future__ import annotations

import json
import secrets
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

PUBLIC_PREFIXES = (
    "/api/health",
    "/api/auth/",
    "/assets/",
    "/portal/",
    "/favicon",
)
PUBLIC_EXACT = {"/", "/docs", "/redoc", "/openapi.json", "/api/auth/status"}


def _extract_token(scope: Scope) -> str:
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    token = headers.get("x-access-token", "").strip()
    if token:
        return token
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie_header = headers.get("cookie", "")
    if cookie_header:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
            value = cookie.get(settings.access_cookie_name)
            if value is not None:
                return value.value
        except Exception:  # noqa: BLE001
            pass
    query = scope.get("query_string", b"").decode("latin-1")
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key == "token" and value:
            from urllib.parse import unquote_plus

            return unquote_plus(value)
    return ""


def is_authenticated(scope: Scope) -> bool:
    token = settings.access_token.strip()
    if not token:
        return True
    supplied = _extract_token(scope)
    return bool(supplied) and secrets.compare_digest(supplied, token)


class AccessControlMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        protected = (
            path.startswith("/api/")
            or path.startswith("/media/")
            or path == "/metrics"
        )
        if settings.access_token.strip() and protected:
            if path not in PUBLIC_EXACT and not path.startswith(PUBLIC_PREFIXES):
                if not is_authenticated(scope):
                    await self._unauthorized(scope, send)
                    return
        await self.app(scope, receive, send)

    @staticmethod
    async def _unauthorized(scope: Scope, send: Send) -> None:
        if scope.get("path", "").startswith("/media/"):
            body = b"Unauthorized"
            headers = [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ]
        else:
            body = json.dumps(
                {"detail": "需要访问令牌", "code": "access_token_required"},
                ensure_ascii=False,
            ).encode()
            headers = [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="kiwi"'),
            ]
        await send(
            {"type": "http.response.start", "status": 401, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """按客户端 IP + 路由组做滑动窗口限流。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    @staticmethod
    def _bucket(path: str) -> tuple[str, int] | None:
        if path.startswith(("/api/chat", "/api/note-editor", "/api/notes/assist")):
            return "llm", settings.rate_limit_llm_per_minute
        if path.startswith(
            ("/api/notes/import", "/api/ingest", "/api/notes/remote")
        ):
            return "import", settings.rate_limit_import_per_minute
        if path.startswith("/api/code-run"):
            return "code", settings.rate_limit_code_per_minute
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        if scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return
        bucket = self._bucket(scope.get("path", ""))
        if bucket is None:
            await self.app(scope, receive, send)
            return
        name, limit = bucket
        if limit <= 0:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        if headers.get("x-forwarded-for"):
            ip = headers["x-forwarded-for"].split(",")[0].strip() or ip
        now = time.monotonic()
        window = self._hits[(ip, name)]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(60 - (now - window[0])))
            body = json.dumps(
                {"detail": f"请求过于频繁，请 {retry_after} 秒后重试", "code": "rate_limited"},
                ensure_ascii=False,
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", str(retry_after).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        window.append(now)
        await self.app(scope, receive, send)


__all__ = ["AccessControlMiddleware", "RateLimitMiddleware", "is_authenticated"]
