"""微信 ClawBot 渠道管理：扫码登录、允许联系人、知识库绑定与定时推送。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase
from app.db.session import get_session
from app.schemas.wechat import (
    WeChatScheduleCreate,
    WeChatScheduleUpdate,
    WeChatSettingsUpdate,
    WeChatTestPush,
)
from app.services import wechat_clawbot

router = APIRouter(prefix="/api/wechat", tags=["wechat"])


def _channel() -> wechat_clawbot.WeChatChannel:
    return wechat_clawbot.get_channel()


async def _validate_kb(session: AsyncSession, kb_id: str) -> str:
    try:
        value = uuid.UUID(kb_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "知识库 ID 格式不正确") from None
    kb = await session.get(KnowledgeBase, value)
    if kb is None or kb.deleted_at is not None:
        raise HTTPException(404, "知识库不存在")
    return str(kb.id)


@router.get("/status")
async def wechat_status():
    """当前登录状态、允许联系人、知识库绑定与定时任务。"""
    return await _channel().full_status()


@router.put("/settings")
async def update_wechat_settings(
    payload: WeChatSettingsUpdate,
    session: AsyncSession = Depends(get_session),
):
    default_kb_id = payload.default_kb_id
    if default_kb_id is not None and default_kb_id.strip():
        default_kb_id = await _validate_kb(session, default_kb_id.strip())
    elif default_kb_id is not None:
        default_kb_id = ""
    return await _channel().update_settings(
        enabled=payload.enabled,
        default_kb_id=default_kb_id,
        allow_write=payload.allow_write,
        allowed_users=payload.allowed_users,
    )


@router.post("/login")
async def start_wechat_login():
    if not settings.wechat_enabled:
        raise HTTPException(
            400,
            "服务端未启用 ClawBot 渠道：请在 .env 设置 KIWI_WECHAT_ENABLED=true 并重启后端。",
        )
    return await _channel().start_login()


@router.post("/logout")
async def logout_wechat():
    await _channel().logout()
    return await _channel().full_status()


@router.get("/schedules")
async def list_wechat_schedules():
    return {"items": await _channel().list_schedules()}


@router.post("/schedules", status_code=201)
async def create_wechat_schedule(
    payload: WeChatScheduleCreate,
    session: AsyncSession = Depends(get_session),
):
    status = await _channel().full_status()
    sender = (payload.sender or "").strip()
    if not sender:
        last = status.get("last_contact") or {}
        sender = str(last.get("sender") or "")
    if not sender:
        allowed = status.get("allowed_users") or []
        sender = str(allowed[0]) if allowed else ""
    if not sender:
        raise HTTPException(400, "还没有联系人；请先让用户给 Bot 发一条消息")
    kb_id = (payload.kb_id or "").strip() or str(status.get("default_kb_id") or "")
    if not kb_id:
        raise HTTPException(400, "请先选择默认知识库")
    kb_id = await _validate_kb(session, kb_id)
    try:
        item = await _channel().schedule_push(
            sender,
            kb_id,
            payload.prompt,
            payload.time,
            payload.days,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return item


@router.patch("/schedules/{schedule_id}")
async def update_wechat_schedule(
    schedule_id: str,
    payload: WeChatScheduleUpdate,
):
    if not await _channel().toggle_schedule(schedule_id, payload.enabled):
        raise HTTPException(404, "定时任务不存在")
    return {"ok": True}


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_wechat_schedule(schedule_id: str):
    if not await _channel().delete_schedule(schedule_id):
        raise HTTPException(404, "定时任务不存在")


@router.post("/test")
async def send_wechat_test(payload: WeChatTestPush):
    status = await _channel().full_status()
    last = status.get("last_contact") or {}
    sender = str(last.get("sender") or "")
    if not sender:
        raise HTTPException(400, "还没有联系人；请先让用户给 Bot 发一条消息")
    sent = await _channel().send_proactive(sender, payload.text)
    return {"ok": sent, "queued": not sent}
