"""Phase 0：确认后端依赖可在 Windows 安装，并且 app.main 可以导入。"""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
import traceback
from pathlib import Path

OUT = Path(
    os.environ.get("SPIKE_OUT")
    or Path(__file__).resolve().parent / "out" / "backend-deps.json"
)
result: dict = {"check": "backend-deps", "status": "fail", "details": {}}

PACKAGES = [
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "pydantic",
    "qdrant-client",
    "fastembed",
    "openai",
    "pymupdf",
    "python-docx",
    "pandas",
    "matplotlib",
    "faster-whisper",
    "pywebpush",
    "trafilatura",
    "lxml",
]

try:
    import app.main  # noqa: F401 - 导入即验证所有路由与服务的依赖

    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None

    result["details"] = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable": sys.executable,
        "packages": versions,
        "app_main": "imported",
    }
    result["status"] = "pass"
    result["summary"] = "后端依赖在 Windows 安装成功，app.main 可导入"
except Exception:  # noqa: BLE001 - 结果文件需要保留完整堆栈
    result["error"] = traceback.format_exc()
    print(result["error"], file=sys.stderr)
finally:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

sys.exit(0 if result["status"] == "pass" else 1)
