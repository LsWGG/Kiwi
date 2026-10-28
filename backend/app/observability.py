"""请求上下文、结构化日志与 HTTP 指标。

- 每个请求生成 / 透传 ``X-Request-ID``，写入日志与审计记录；
- 记录方法、路由、状态码与耗时；
- 通过 ``KIWI_LOG_JSON=true`` 可切换为 JSON 行日志，便于外部采集。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.metrics import metrics

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")

REQUEST_ID_HEADER = "x-request-id"


def current_request_id() -> str:
    return request_id_var.get()


def current_client_ip() -> str:
    return client_ip_var.get()


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _log_file_path() -> Path | None:
    """桌面 runtime 通过 ``KIWI_LOG_FILE`` 指定滚动日志；Docker 不设置。"""
    from app.config import settings

    return settings.log_file


def setup_logging() -> None:
    """安装统一日志格式；保留 uvicorn 自己的 access log。

    ``KIWI_LOG_FILE`` 非空时额外写滚动文件（桌面版）；文件不可写时退回
    控制台日志，不影响启动。Docker 未设置该变量，行为与之前一致。
    """
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdLogFilter())
    if os.environ.get("KIWI_LOG_JSON", "").lower() in ("1", "true", "yes"):
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
            )
        )
    handlers: list[logging.Handler] = [handler]
    log_file = _log_file_path()
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
        except OSError as exc:
            logging.getLogger("kiwi.logging").warning(
                "无法写入日志文件 %s：%s", log_file, exc
            )
        else:
            file_handler.addFilter(RequestIdLogFilter())
            file_handler.setFormatter(handler.formatter)
            handlers.append(file_handler)
    root.handlers[:] = handlers
    root.setLevel(logging.INFO)
    # 这些库的 INFO 日志过于嘈杂，统一降级；错误仍会输出。
    for noisy in ("httpx", "httpcore", "qdrant_client", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _route_label(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path or scope.get("path", "unknown")


class RequestContextMiddleware:
    """纯 ASGI 中间件：SSE 等流式响应不会被缓冲。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("kiwi.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = (headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex)[:64]
        client = scope.get("client")
        client_ip = client[0] if client else ""
        forwarded = headers.get("x-forwarded-for", "")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(client_ip)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                raw_headers = list(message.get("headers", []))
                raw_headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - started
            method = scope.get("method", "?")
            path = _route_label(scope)
            metrics.inc(
                "kiwi_http_requests_total",
                {"method": method, "status": str(status_code), "route": path},
            )
            metrics.observe(
                "kiwi_http_request_duration_seconds",
                elapsed,
                {"method": method, "route": path},
            )
            level = logging.WARNING if status_code >= 500 else logging.INFO
            if not path.startswith(("/media", "/assets")):
                self.logger.log(
                    level,
                    "%s %s %s %.1fms",
                    method,
                    path,
                    status_code,
                    elapsed * 1000,
                )
            request_id_var.reset(token)
            client_ip_var.reset(ip_token)
