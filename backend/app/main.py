"""Kiwi 后端入口：FastAPI 应用组装 + lifespan 初始化。"""

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import (
    attachments,
    chat,
    code_run,
    health,
    ingest,
    kb,
    llm,
    note_databases,
    note_editor,
    notebooks,
    notes,
    search,
    sources,
    study,
    wiki,
)
from app.db.session import async_session_factory
from app.services import qdrant_store
from app.services.builtin_demo import ensure_builtin_demo, start_vector_seed_task
from app.services.notebook_kernel import kernel_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kiwi")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化：确保向量 collection 与租户索引存在。"""
    try:
        await asyncio.to_thread(qdrant_store.ensure_collections)
        logger.info("Qdrant collections ready (raw_chunks / wiki_pages, kb_id tenant index)")
    except Exception as e:  # noqa: BLE001
        logger.warning("Qdrant 初始化失败（服务仍启动，摄入时重试）：%s", e)

    # 内置演示库：幂等确保存在（不自动还原用户主动隐藏的库）。
    builtin_task: asyncio.Task[None] | None = None
    try:
        async with async_session_factory() as db:
            await ensure_builtin_demo(db)
        builtin_task = start_vector_seed_task()
    except Exception as e:  # noqa: BLE001
        logger.warning("内置演示库初始化失败（不影响启动）：%s", e)

    yield

    if builtin_task is not None and not builtin_task.done():
        builtin_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await builtin_task
    kernel_manager.shutdown_all()


app = FastAPI(
    title="Kiwi · 知识编译与检索系统",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(health.router)
app.include_router(kb.router)
app.include_router(llm.router)
app.include_router(notes.router)
app.include_router(note_databases.router)
app.include_router(note_editor.router)
app.include_router(notebooks.router)
app.include_router(code_run.router)
app.include_router(attachments.router)
app.include_router(sources.router)
app.include_router(ingest.router)
app.include_router(wiki.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(study.router)


# 附件 / 编辑器内嵌媒体
_media_dir = settings.upload_dir / "media"
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


@app.get("/")
async def root():
    return {"name": "Kiwi", "docs": "/docs", "status": "/api/health"}
