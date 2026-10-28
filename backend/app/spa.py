"""桌面版 SPA 静态资源服务。

仅当 ``KIWI_FRONTEND_DIST`` 指向打包后的前端目录时启用。Docker / 源码部署
继续由 nginx 或 Vite 提供前端，``/`` 保持原有 JSON 响应，行为不变。

路由注册顺序：API → ``/media`` → ``/assets`` ``/pdfjs`` → 兜底 ``/{path:path}``。
兜底只把「看起来像前端路由」的请求交回 index.html，其余一律 404，避免把
不存在的静态资源或 API 路径误响应成 HTML。
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app.config import settings

logger = logging.getLogger("kiwi.spa")

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
DAILY = "public, max-age=86400"

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "media-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-src 'self' blob: data:; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# 只注入 HTML 文档响应：/media、/assets、/pdfjs 与 API JSON 不带 CSP，
# 避免 PDF / 媒体 iframe 被自身 CSP 拦截。
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# 前端根目录下的固定文件；pack 后由 FastAPI 直出，Docker 仍由 nginx 提供。
ROOT_FILES = {
    "build-info.json": NO_CACHE,
    "sw.js": NO_CACHE,
    "favicon.svg": DAILY,
    "favicon-learn.svg": DAILY,
    "favicon.ico": DAILY,
}

# 这些前缀永远不交给 SPA 兜底：API 404 保持 JSON，静态目录不吞请求。
RESERVED_SEGMENTS = {
    "api",
    "internal",
    "media",
    "metrics",
    "docs",
    "openapi.json",
    "redoc",
    "assets",
    "pdfjs",
}


def configure_mimetypes() -> None:
    """Windows 注册表可能把 .js 映射成 text/plain，显式修正前端资源类型。"""
    for mime_type, suffix in (
        ("text/javascript", ".js"),
        ("text/javascript", ".mjs"),
        ("text/css", ".css"),
        ("application/json", ".json"),
        ("image/svg+xml", ".svg"),
        ("application/wasm", ".wasm"),
        ("font/woff2", ".woff2"),
        ("application/octet-stream", ".bcmap"),
    ):
        mimetypes.add_type(mime_type, suffix)


class CacheControlledStaticFiles(StaticFiles):
    """给 StaticFiles 响应附加缓存策略（Range / 304 响应同样生效）。"""

    def __init__(self, *, cache_control: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cache_control = cache_control

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 206, 304):
            response.headers.setdefault("cache-control", self.cache_control)
        return response


def _apply_security_headers(response):
    if settings.desktop_mode:
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
    return response


def _index_response(root: Path) -> FileResponse:
    response = FileResponse(
        root / "index.html",
        media_type="text/html",
        headers={"Cache-Control": NO_CACHE},
    )
    return _apply_security_headers(response)


def _file_response(
    target: Path, *, cache_control: str, extra_headers: dict[str, str] | None = None
) -> FileResponse:
    headers = {"Cache-Control": cache_control}
    if extra_headers:
        headers.update(extra_headers)
    return FileResponse(target, headers=headers)


def _safe_target(root: Path, path: str) -> Path | None:
    """限制在 dist 目录内，避免 ``..`` 或绝对路径逃逸。"""
    try:
        target = (root / path).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return None
    return target


def _cache_for(path: str) -> str:
    first = path.split("/", 1)[0]
    if first == "assets":
        return IMMUTABLE
    if first == "pdfjs":
        return DAILY
    return NO_CACHE


def _is_reserved(path: str) -> bool:
    return path.split("/", 1)[0] in RESERVED_SEGMENTS


def _root_handler(root: Path, filename: str, cache_control: str):
    def serve() -> FileResponse:
        target = root / filename
        if not target.is_file():
            raise HTTPException(404)
        extra = {"Service-Worker-Allowed": "/"} if filename == "sw.js" else None
        return _file_response(target, cache_control=cache_control, extra_headers=extra)

    return serve


def build_router(root: Path) -> APIRouter:
    router = APIRouter()

    @router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    @router.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
    def index() -> FileResponse:
        return _index_response(root)

    for _name, _cache in ROOT_FILES.items():
        router.add_api_route(
            f"/{_name}",
            _root_handler(root, _name, _cache),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )

    @router.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa_fallback(path: str, request: Request):
        if _is_reserved(path):
            raise HTTPException(404)
        target = _safe_target(root, path)
        if target is not None and target.is_file():
            return _file_response(target, cache_control=_cache_for(path))
        # 带扩展名但文件不存在：多半是资源缺失，不能回退成 index.html。
        if Path(path).suffix:
            raise HTTPException(404)
        if "text/html" not in request.headers.get("accept", "").lower():
            raise HTTPException(404)
        return _index_response(root)

    return router


def setup_spa(app: FastAPI) -> None:
    """挂载前端资源并注册 history fallback；配置错误直接让启动失败。"""
    if settings.frontend_dist is None:
        return
    root = Path(settings.frontend_dist).resolve()
    index_file = root / "index.html"
    if not index_file.is_file():
        raise RuntimeError(
            f"前端资源缺失：{index_file}。请先执行 npm run build，"
            "或用 -SkipFrontend 重新打包。"
        )

    configure_mimetypes()
    for mount, cache_control in (("assets", IMMUTABLE), ("pdfjs", DAILY)):
        directory = root / mount
        if directory.is_dir():
            app.mount(
                f"/{mount}",
                CacheControlledStaticFiles(
                    directory=str(directory),
                    cache_control=cache_control,
                    check_dir=False,
                ),
                name=f"spa-{mount}",
            )
    app.include_router(build_router(root))
    logger.info("桌面 SPA 已启用：%s", root)
