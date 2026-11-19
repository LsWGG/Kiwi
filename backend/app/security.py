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
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

PUBLIC_PREFIXES = (
    "/api/health",
    "/api/auth/",
    # 飞书 OAuth 回调由浏览器 302 进入，没有自定义请求头；用 state 校验防伪。
    "/api/transcribe/feishu/oauth/callback",
    # 公开只读分享页：凭随机 token + 可选密码访问，不要求登录。
    "/api/share/",
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


__all__ = ["AccessControlMiddleware", "is_authenticated"]
