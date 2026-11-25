"""ClawBot 渠道管理：扫码登录、知识库绑定、计划预览与定时推送。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase
from app.db.session import get_session
from app.schemas.wechat import (
    WeChatScheduleCreate,
    WeChatSchedulePreview,
    WeChatScheduleUpdate,
    WeChatSettingsUpdate,
    WeChatTestPush,
)
from app.services import cron_schedule, schedule_parser, wechat_clawbot
from app.services.agent_planner import app_timezone

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


async def _validate_kbs(session: AsyncSession, kb_ids: list[str]) -> list[str]:
    values = [item.strip() for item in kb_ids if item and item.strip()]
    if not values:
        return []
    out: list[str] = []
    for item in dict.fromkeys(values):
        out.append(await _validate_kb(session, item))
    return out


@router.get("/status")
async def wechat_status():
    """当前登录状态、知识库绑定与定时任务。"""
    return await _channel().full_status()


@router.put("/settings")
async def update_wechat_settings(payload: WeChatSettingsUpdate):
    return await _channel().update_settings(enabled=payload.enabled)


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
    status = await _channel().full_status()
    return {"items": status.get("schedules") or []}


@router.post("/schedules/preview")
async def preview_wechat_schedule(
    payload: WeChatSchedulePreview,
    session: AsyncSession = Depends(get_session),
):
    """自然语言或 cron → 标准 cron、中文描述与最近运行时间。"""
    try:
        cron, description = await schedule_parser.parse_schedule(
            payload.text, session=session
        )
    except schedule_parser.ScheduleParseError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "cron": cron,
        "description": description,
        "next_runs": cron_schedule.next_runs(
            cron, count=3, now=datetime.now(app_timezone()).replace(tzinfo=None)
        ),
    }


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
    kb_ids = payload.kb_ids or ([payload.kb_id] if payload.kb_id else [])
    kb_ids = await _validate_kbs(session, list(kb_ids))

    try:
        if payload.cron:
            cron = cron_schedule.validate_cron(payload.cron)
        elif payload.schedule_text:
            cron, _description = await schedule_parser.parse_schedule(
                payload.schedule_text, session=session
            )
        elif payload.time:
            cron = cron_schedule.from_legacy_time(payload.time, payload.days)
        else:
            raise HTTPException(400, "请设置执行计划（自然语言或 cron）")
    except cron_schedule.CronError as exc:
        raise HTTPException(400, str(exc)) from exc
    except schedule_parser.ScheduleParseError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        item = await _channel().schedule_push(
            sender,
            kb_ids,
            payload.prompt,
            cron,
        )
    except (ValueError, cron_schedule.CronError) as exc:
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
