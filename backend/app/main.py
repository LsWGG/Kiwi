"""Kiwi 后端入口：FastAPI 应用组装 + lifespan 初始化。"""

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.build_info import APP_VERSION
from app.config import settings
from app.db.session import async_session_factory
from app.observability import RequestContextMiddleware, setup_logging
from app.routers import (
    attachments,
    audit,
    auth,
    chat,
    chat_sessions,
    code_run,
    health,
    ingest,
    jobs,
    kb,
    llm,
    maintenance,
    note_databases,
    note_editor,
    notebooks,
    notes,
    search,
    settings_embedding,
    settings_system,
    sources,
    study,
    wiki,
)
from app.security import AccessControlMiddleware, RateLimitMiddleware
from app.services import (
    backup_service,
    embedding_settings,
    job_queue,
    qdrant_store,
    system_settings,
)
from app.services import job_handlers as _job_handlers  # noqa: F401  注册任务 handler
from app.services.builtin_demo import ensure_builtin_demo, start_vector_seed_task
from app.services.kb_scheduler import start_scheduler_task
from app.services.note_indexer import start_note_index_task
from app.services.notebook_kernel import kernel_manager

setup_logging()
logger = logging.getLogger("kiwi")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化：加载向量模型配置，确保 collection 与租户索引存在。"""
    # 先加载应用内向量模型配置：collection 命名依赖当前向量空间。
    try:
        async with async_session_factory() as db:
            row = await embedding_settings.load_runtime(db)
        if row is not None:
            logger.info("Embedding runtime loaded from app settings (%s)", row.provider)
    except Exception as e:  # noqa: BLE001
        logger.warning("向量模型配置加载失败，回退环境变量：%s", e)

    # 系统设置：品牌信息与线上 OCR 运行时配置
    try:
        async with async_session_factory() as db:
            await system_settings.load_runtime(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("系统设置加载失败，OCR 回退本地 tesseract：%s", e)

    try:
        await asyncio.to_thread(qdrant_store.ensure_collections)
        logger.info("Qdrant collections ready (raw_chunks / wiki_pages, kb_id tenant index)")
    except Exception as e:  # noqa: BLE001
        logger.warning("Qdrant 初始化失败（服务仍启动，摄入时重试）：%s", e)

    builtin_task: asyncio.Task[None] | None = None
    note_index_task: asyncio.Task[None] | None = None
    scheduler_task: asyncio.Task[None] | None = None
    worker_task: asyncio.Task[None] | None = None
    backup_task: asyncio.Task[None] | None = None
    if settings.background_jobs:
        # 内置演示库：幂等确保存在（不自动还原用户主动隐藏的库）。
        try:
            async with async_session_factory() as db:
                await ensure_builtin_demo(db)
            builtin_task = start_vector_seed_task()
        except Exception as e:  # noqa: BLE001
            logger.warning("内置演示库初始化失败（不影响启动）：%s", e)

        # 后台核对笔记索引：只对变更过的笔记重新嵌入。
        note_index_task = start_note_index_task()
        # 知识库定时任务：Wiki 周期编译 + 待办聚合。
        scheduler_task = start_scheduler_task()
        # 持久化任务 worker：导入、编译、知识库包导入、备份。
        worker_task = job_queue.start_worker()
        # 自动备份：pg_dump + uploads + manifest。
        backup_task = backup_service.start_backup_task()
    else:
        logger.info(
            "KIWI_BACKGROUND_JOBS=false：跳过演示库种子、笔记索引巡检、定时任务与任务 worker"
        )

    yield

    await job_queue.stop_worker()
    await backup_service.stop_backup_task(backup_task)
    for task in (builtin_task, note_index_task, scheduler_task, worker_task):
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    kernel_manager.shutdown_all()


app = FastAPI(
    title="Kiwi · 知识编译与检索系统",
    version=APP_VERSION,
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
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AccessControlMiddleware)
app.add_middleware(RequestContextMiddleware)

# 路由注册
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(kb.router)
app.include_router(llm.router)
app.include_router(settings_embedding.router)
app.include_router(settings_system.router)
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
app.include_router(chat_sessions.router)
app.include_router(chat.router)
app.include_router(study.router)
app.include_router(jobs.router)
app.include_router(audit.router)
app.include_router(maintenance.router)
app.include_router(maintenance.metrics_router)


# 附件 / 编辑器内嵌媒体
_media_dir = settings.upload_dir / "media"
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


@app.get("/")
async def root():
    return {"name": "Kiwi", "docs": "/docs", "status": "/api/health"}
