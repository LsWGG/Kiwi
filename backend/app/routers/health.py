"""健康检查。"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health():
    """基础存活探针。"""
    return {"status": "ok"}


@router.get("/detail")
async def health_detail():
    """深度探活：检查 PG 与 Qdrant。"""
    import asyncio

    from sqlalchemy import text

    from app.db.session import async_session_factory
    from app.services import qdrant_store

    result = {"postgres": "down", "qdrant": "down"}

    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
        result["postgres"] = "up"
    except Exception:  # noqa: BLE001
        pass

    try:
        await asyncio.to_thread(qdrant_store.count_raw_points)
        result["qdrant"] = "up"
    except Exception:  # noqa: BLE001
        pass

    all_up = all(v == "up" for v in result.values())
    return {"status": "ok" if all_up else "degraded", **result}
