# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec：Kiwi 桌面 Python runtime。

构建（Windows，仓库根目录）：

    uv run --project backend pyinstaller --noconfirm desktop/kiwi-runtime.spec

产物为 ``dist/kiwi-runtime/kiwi-runtime.exe`` + ``_internal/``。前端、Qdrant
与便携 Python 由 ``build.ps1`` 单独放入 ``resources/``，不打进 runtime bundle。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

spec_dir = Path(SPECPATH).resolve()  # noqa: F821 - PyInstaller 注入
project_root = spec_dir.parent
backend_dir = project_root / "backend"

datas = [
    # Alembic 的 env.py / script.py.mako / versions 在运行时由 script_location 加载。
    (str(backend_dir / "alembic"), "alembic"),
    (
        str(backend_dir / "app" / "services" / "builtin_demo_assets"),
        "app/services/builtin_demo_assets",
    ),
]
datas += collect_data_files("trafilatura")

# pgserver 自带 PostgreSQL 16 二进制（initdb / pg_ctl / postgres / pg_dump）。
pg_datas, pg_binaries, pg_hiddenimports = collect_all("pgserver")
datas += pg_datas
binaries = list(pg_binaries)

hiddenimports = [
    "alembic",
    "alembic.command",
    "alembic.config",
    "alembic.runtime.migration",
    "asyncpg",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "app.db.base",
    "app.db.models",
    "app.db.session",
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "multipart",
    "python_multipart",
    "docx",
    "fitz",
    "pymupdf",
    "PIL",
] + list(pg_hiddenimports)

# 桌面版不内置任何模型运行时；这些包只在 provider=local / whisper 开启时懒加载。
excludes = [
    "fastembed",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "huggingface_hub",
    "torch",
    "transformers",
    "pandas",
    "matplotlib",
    "IPython",
    "jupyter_client",
    "jupyter_core",
    "tkinter",
    "pytest",
    "ruff",
]

a = Analysis(
    [str(spec_dir / "runtime" / "kiwi_runtime.py")],
    pathex=[str(backend_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kiwi-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="kiwi-runtime",
)
