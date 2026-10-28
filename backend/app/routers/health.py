"""健康检查与运行状态。"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.build_info import info as build_info
from app.db.models import Job, LLMConfig
from app.db.session import async_session_factory
from app.services import backup_service, qdrant_store
from app.services.embedder import is_disabled, runtime_config

logger = logging.getLogger("kiwi.health")
router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health():
    """基础存活探针。"""
    return {"status": "ok"}


@router.get("/version")
async def version():
    return build_info()


@router.get("/detail")
async def health_detail():
    """深度探活：PG、Qdrant、LLM 配置、任务队列与最近失败。"""
    result: dict = {
        "status": "ok",
        "postgres": "down",
        "qdrant": "down",
        "llm": {"configured": False, "model": ""},
        "jobs": {},
        "recent_failures": [],
        "backup": {"latest": None, "enabled": backup_service.settings.backup_enabled},
        "version": build_info(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
            result["postgres"] = "up"
            total = (
                await db.execute(select(func.count(LLMConfig.id)))
            ).scalar_one()
            default = (
                await db.execute(
                    select(LLMConfig).where(LLMConfig.is_default.is_(True)).limit(1)
                )
            ).scalar_one_or_none()
            if default is None and total:
                default = (
                    await db.execute(select(LLMConfig).limit(1))
                ).scalar_one_or_none()
            result["llm"] = {
                "configured": bool(total),
                "model": (default.model_name if default else ""),
            }
            rows = (
                await db.execute(
                    select(Job.status, func.count(Job.id)).group_by(Job.status)
                )
            ).all()
            result["jobs"] = {status: int(count) for status, count in rows}
            failed = (
                await db.execute(
                    select(Job)
                    .where(Job.status == "failed")
                    .order_by(Job.finished_at.desc().nullslast())
                    .limit(5)
                )
            ).scalars().all()
            result["recent_failures"] = [
                {
                    "id": str(job.id),
                    "kind": job.kind,
                    "error": (job.error or "")[:300],
                    "finished_at": (
                        job.finished_at.isoformat() if job.finished_at else None
                    ),
                }
                for job in failed
            ]
    except Exception as e:  # noqa: BLE001
        logger.warning("健康检查数据库探测失败：%s", e)

    vectors_disabled = is_disabled()
    result["embedding"] = {
        "enabled": not vectors_disabled,
        "provider": runtime_config().provider.strip().lower() or "local",
    }
    if vectors_disabled:
        # 桌面版可以完全不启动 Qdrant：这是主动禁用，不算降级。
        result["qdrant"] = "disabled"
    else:
        try:
            await asyncio.to_thread(qdrant_store.count_raw_points)
            result["qdrant"] = "up"
        except Exception as e:  # noqa: BLE001
            logger.warning("健康检查 Qdrant 探测失败：%s", e)

    try:
        latest = await asyncio.to_thread(backup_service.latest_backup)
        if latest is not None:
            result["backup"]["latest"] = {
                "name": latest.get("name"),
                "created_at": latest.get("created_at"),
                "app_version": latest.get("app_version"),
            }
    except Exception:  # noqa: BLE001
        logger.warning("健康检查读取备份清单失败", exc_info=True)

    degraded = (
        result["postgres"] != "up"
        or (not vectors_disabled and result["qdrant"] != "up")
        or result["jobs"].get("failed", 0) > 0
    )
    result["status"] = "degraded" if degraded else "ok"
    return result
