"""知识库定时任务：Wiki 自动编译与待办聚合。

每 60 秒检查一次到期知识库：

- ``wiki_compile_interval_hours``：把自上次编译以来更新的笔记送入 Wiki 编译；
- ``todo_sync_interval_hours``：刷新收件箱并同步双向状态。

任务进程内运行，重启后按 ``last_at`` 继续到期判断，不会重复堆积。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import KnowledgeBase, Note
from app.db.session import async_session_factory
from app.services import todo_sync

logger = logging.getLogger("kiwi.scheduler")

CHECK_INTERVAL_SECONDS = 60
MAX_COMPILE_PER_RUN = 50


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _due(last: datetime | None, interval_hours: int, now: datetime) -> bool:
    if interval_hours <= 0:
        return False
    last = _aware(last)
    return last is None or last + timedelta(hours=interval_hours) <= now


async def _run_wiki_compile(
    session, kb: KnowledgeBase, now: datetime
) -> dict:
    """把更新过的笔记送入编译流水线；必须在独立 session 中调用。"""
    # 延迟导入，避免 routers.notes ↔ services 的循环依赖。
    from app.routers.notes import _prepare_note_compile, _schedule_note_compile

    last = _aware(kb.wiki_compile_last_at)
    stmt = select(Note).where(Note.kb_id == kb.id, Note.status == "active")
    if last is not None:
        stmt = stmt.where(Note.updated_at > last)
    notes = (await session.execute(stmt.order_by(Note.updated_at))).scalars().all()
    candidates = [
        note
        for note in notes
        if not (note.props_json or {}).get("collection_row_id")
        and not (note.props_json or {}).get("todo_hub")
    ]

    jobs = 0
    busy = 0
    empty = 0
    failed = 0
    for note in candidates[:MAX_COMPILE_PER_RUN]:
        try:
            prepared = await _prepare_note_compile(session, kb.id, note)
        except Exception:  # noqa: BLE001
            logger.exception("定时编译准备失败：笔记 %s", note.id)
            failed += 1
            continue
        if prepared is None:
            busy += 1
            continue
        job, source, reused = prepared
        await session.commit()
        await _schedule_note_compile(job, kb.id, source.id, reused)
        jobs += 1

    kb.wiki_compile_last_at = now
    kb.wiki_compile_last_status = {
        "at": now.isoformat(),
        "trigger": "schedule",
        "status": "scheduled",
        "scheduled": jobs,
        "candidates": len(candidates),
        "busy": busy,
        "empty": empty,
        "failed": failed,
        "truncated": max(0, len(candidates) - MAX_COMPILE_PER_RUN),
    }
    await session.commit()
    return kb.wiki_compile_last_status


async def _tick() -> None:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        kbs = (
            (
                await session.execute(
                    select(KnowledgeBase).where(
                        KnowledgeBase.deleted_at.is_(None),
                        (KnowledgeBase.wiki_compile_interval_hours > 0)
                        | (KnowledgeBase.todo_sync_interval_hours > 0),
                    )
                )
            )
            .scalars()
            .all()
        )
        for kb in kbs:
            if _due(kb.wiki_compile_last_at, kb.wiki_compile_interval_hours, now):
                try:
                    status = await _run_wiki_compile(session, kb, now)
                    logger.info("知识库 %s 定时编译：%s", kb.id, status)
                except Exception:  # noqa: BLE001
                    logger.exception("知识库 %s 定时编译失败", kb.id)
                    await session.rollback()
                    kb = await session.get(KnowledgeBase, kb.id)
                    if kb is not None:
                        kb.wiki_compile_last_at = now
                        kb.wiki_compile_last_status = {
                            "at": now.isoformat(),
                            "trigger": "schedule",
                            "status": "failed",
                            "error": "调度失败，详见后端日志",
                        }
                        await session.commit()

            if _due(kb.todo_sync_last_at, kb.todo_sync_interval_hours, now):
                try:
                    stats = await todo_sync.sync_kb_todos(session, kb.id)
                    logger.info("知识库 %s 定时待办同步：%s", kb.id, stats)
                except Exception:  # noqa: BLE001
                    logger.exception("知识库 %s 定时待办同步失败", kb.id)
                    await session.rollback()


async def _loop() -> None:
    # 启动后稍等，避免和内置演示库初始化争抢数据库 / 向量资源。
    await asyncio.sleep(15)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("知识库定时任务异常")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_scheduler_task() -> asyncio.Task[None]:
    return asyncio.create_task(_loop(), name="kiwi-kb-scheduler")
