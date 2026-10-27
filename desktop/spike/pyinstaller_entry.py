"""PyInstaller 探针：冻结后端核心依赖，启动一个本地 HTTP 服务并自测。"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(os.environ.get("SPIKE_OUT", "desktop/spike/out/pyinstaller-runtime.json"))
result: dict = {"check": "pyinstaller-runtime", "status": "fail", "details": {}}


def main() -> None:
    import alembic
    import asyncpg
    import fastapi
    import openai
    import pydantic
    import qdrant_client
    import sqlalchemy
    import uvicorn
    import uvicorn.protocols.http.h11_impl  # noqa: F401 - 验证协议模块被冻结
    import uvicorn.server  # noqa: F401

    versions = {
        "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "fastapi": getattr(fastapi, "__version__", "unknown"),
        "uvicorn": getattr(uvicorn, "__version__", "unknown"),
        "sqlalchemy": getattr(sqlalchemy, "__version__", "unknown"),
        "asyncpg": getattr(asyncpg, "__version__", "unknown"),
        "alembic": getattr(alembic, "__version__", "unknown"),
        "qdrant_client": getattr(qdrant_client, "__version__", "unknown"),
        "openai": getattr(openai, "__version__", "unknown"),
        "pydantic": getattr(pydantic, "__version__", "unknown"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
            body = json.dumps({"ok": True, "frozen": versions["frozen"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as resp:
            payload = json.loads(resp.read())
    finally:
        server.shutdown()
        server.server_close()
    if not payload.get("ok"):
        raise AssertionError(f"自测响应异常：{payload}")

    result["details"] = versions
    result["details"]["http_port"] = port
    result["status"] = "pass"
    result["summary"] = "PyInstaller onedir 可导入后端核心依赖并启动本地 HTTP 服务"


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - 结果文件需要保留完整堆栈
        result["error"] = traceback.format_exc()
        print(result["error"], file=sys.stderr)
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["status"] == "pass" else 1)
