"""Web Push 提醒：订阅管理、提醒设置与测试推送。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.schemas.push import (
    PushDeviceOut,
    PushResultOut,
    PushSettingsIn,
    PushStatusOut,
    PushSubscriptionIn,
    PushUnsubscribeIn,
)
from app.services import push_service
from app.services.desktop_guard import require_online_feature
from app.services.push_service import PushUnavailable

router = APIRouter(prefix="/api/push", tags=["push"])


async def _status(session: AsyncSession) -> PushStatusOut:
    try:
        row = await push_service.ensure_vapid(session)
    except PushUnavailable as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    subs = await push_service.list_subscriptions(session)
    return PushStatusOut(
        enabled=row.push_enabled,
        reminder_hour=row.push_reminder_hour,
        weekly_report=row.push_weekly_report,
        public_key=row.push_vapid_public_key,
        contact=settings.push_contact,
        subscriptions=[PushDeviceOut.model_validate(sub) for sub in subs],
        last_daily_date=row.push_last_daily_date,
        last_weekly_date=row.push_last_weekly_date,
    )


@router.get("/status", response_model=PushStatusOut)
async def push_status(session: AsyncSession = Depends(get_session)):
    """返回提醒配置、VAPID 公钥与已订阅设备。"""
    return await _status(session)


@router.post("/subscribe", response_model=PushDeviceOut)
async def subscribe(
    payload: PushSubscriptionIn,
    session: AsyncSession = Depends(get_session),
):
    """保存（或刷新）当前浏览器的推送订阅。"""
    require_online_feature("web_push")
    if not payload.endpoint.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="推送订阅地址无效")
    try:
        await push_service.ensure_vapid(session)
    except PushUnavailable as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    sub = await push_service.upsert_subscription(
        session,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=payload.user_agent,
    )
    return PushDeviceOut.model_validate(sub)


@router.post("/unsubscribe")
async def unsubscribe(
    payload: PushUnsubscribeIn,
    session: AsyncSession = Depends(get_session),
):
    """删除某个浏览器的订阅；重复删除视为成功。"""
    removed = await push_service.remove_subscription(session, payload.endpoint)
    return {"removed": removed}


@router.patch("/settings", response_model=PushStatusOut)
async def update_settings(
    payload: PushSettingsIn,
    session: AsyncSession = Depends(get_session),
):
    """开关每日提醒、调整提醒时间与周报推送。"""
    require_online_feature("web_push")
    try:
        row = await push_service.ensure_vapid(session)
    except PushUnavailable as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if payload.enabled is not None:
        row.push_enabled = payload.enabled
    if payload.reminder_hour is not None:
        row.push_reminder_hour = payload.reminder_hour
    if payload.weekly_report is not None:
        row.push_weekly_report = payload.weekly_report
    await session.commit()
    return await _status(session)


@router.post("/test", response_model=PushResultOut)
async def send_test(session: AsyncSession = Depends(get_session)):
    """向所有已订阅设备发送一条测试通知。"""
    require_online_feature("web_push")
    if not await push_service.active_subscription_count(session):
        raise HTTPException(
            status_code=400,
            detail="还没有已订阅的设备，请先在本设备开启通知",
        )
    try:
        result = await push_service.send_push(session, push_service.test_payload())
    except PushUnavailable as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return PushResultOut(**result)
