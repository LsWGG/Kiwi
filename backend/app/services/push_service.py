"""Web Push 提醒：VAPID 密钥、浏览器订阅与每日 / 每周推送。

- VAPID 密钥在首次使用时生成，私钥经 ``KIWI_FERNET_KEY`` 加密后存入
  ``system_settings``；公钥返回给浏览器作为 ``applicationServerKey``。
- 订阅保存在 ``push_subscriptions``，推送失败按状态码清理失效订阅。
- 每日提醒汇总到期复习与未完成待办；每周一推送上周学习数据。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import date, datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    KnowledgeBase,
    PushSubscription,
    StudyAttempt,
    StudyReview,
    SystemSettings,
    TodoMirror,
)
from app.db.models.system_settings import SYSTEM_SETTINGS_ID
from app.services.llm_factory import CryptoError, LLMCrypto

logger = logging.getLogger("kiwi.push")

# 推送服务返回这两个状态码时订阅已永久失效，直接删除。
GONE_STATUS_CODES = {404, 410}
PUSH_TIMEOUT_SECONDS = 10
PUSH_TTL_SECONDS = 86_400


class PushUnavailable(RuntimeError):
    """推送不可用（密钥损坏等），调用方应提示用户而非静默失败。"""


# ---------------------------------------------------------------- VAPID


def _public_key_b64(vapid: Vapid) -> str:
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def ensure_vapid(session: AsyncSession) -> SystemSettings:
    """返回系统设置行，缺失 VAPID 密钥时生成并保存。"""
    row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
    if row is None:
        row = SystemSettings()
        session.add(row)
    if row.push_vapid_private_key and row.push_vapid_public_key:
        return row

    vapid = Vapid()
    vapid.generate_keys()
    row.push_vapid_private_key = LLMCrypto.encrypt(vapid.private_pem().decode())
    row.push_vapid_public_key = _public_key_b64(vapid)
    await session.commit()
    return row


def _load_vapid(row: SystemSettings) -> Vapid:
    if not row.push_vapid_private_key:
        raise PushUnavailable("推送密钥尚未初始化")
    try:
        pem = LLMCrypto.decrypt(row.push_vapid_private_key)
        return Vapid.from_pem(pem.encode())
    except CryptoError as e:
        raise PushUnavailable("推送私钥无法解密，请检查 KIWI_FERNET_KEY") from e
    except Exception as e:  # noqa: BLE001
        raise PushUnavailable("推送私钥格式无效，请重新生成订阅") from e


# ---------------------------------------------------------------- 订阅


async def list_subscriptions(session: AsyncSession) -> list[PushSubscription]:
    return list(
        (
            await session.execute(
                select(PushSubscription).order_by(PushSubscription.created_at)
            )
        ).scalars()
    )


async def active_subscription_count(session: AsyncSession) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.enabled.is_(True))
    )
    return int(value or 0)


async def upsert_subscription(
    session: AsyncSession,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
) -> PushSubscription:
    sub = (
        await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
    ).scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
        session.add(sub)
    sub.p256dh = p256dh
    sub.auth = auth
    sub.user_agent = (user_agent or "")[:300]
    sub.enabled = True
    sub.failure_count = 0
    sub.last_error = ""
    await session.commit()
    return sub


async def remove_subscription(session: AsyncSession, endpoint: str) -> bool:
    sub = (
        await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
    ).scalar_one_or_none()
    if sub is None:
        return False
    await session.delete(sub)
    await session.commit()
    return True


# ---------------------------------------------------------------- 发送


def _send_one(
    endpoint: str, p256dh: str, auth: str, data: str, vapid: Vapid
) -> None:
    webpush(
        subscription_info={
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        },
        data=data,
        vapid_private_key=vapid,
        vapid_claims={"sub": settings.push_contact},
        timeout=PUSH_TIMEOUT_SECONDS,
        ttl=PUSH_TTL_SECONDS,
    )


async def send_push(
    session: AsyncSession, payload: dict, *, endpoint: str | None = None
) -> dict:
    """向全部（或指定）订阅发送一条通知，返回成功 / 失败计数。"""
    row = await ensure_vapid(session)
    vapid = _load_vapid(row)
    data = json.dumps(payload, ensure_ascii=False)

    stmt = select(PushSubscription).where(PushSubscription.enabled.is_(True))
    if endpoint:
        stmt = stmt.where(PushSubscription.endpoint == endpoint)
    subs = list((await session.execute(stmt)).scalars())

    sent = 0
    failed = 0
    removed = 0
    now = datetime.now(timezone.utc)
    for sub in subs:
        try:
            await asyncio.to_thread(
                _send_one, sub.endpoint, sub.p256dh, sub.auth, data, vapid
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in GONE_STATUS_CODES:
                await session.delete(sub)
                removed += 1
                continue
            failed += 1
            sub.failure_count += 1
            sub.last_error = str(exc)[:500]
            logger.warning("推送失败（%s）：%s", status, sub.endpoint[:60])
        except Exception as exc:  # noqa: BLE001
            failed += 1
            sub.failure_count += 1
            sub.last_error = str(exc)[:500]
            logger.warning("推送异常：%s", exc)
        else:
            sent += 1
            sub.last_success_at = now
            sub.failure_count = 0
            sub.last_error = ""

    await session.commit()
    return {"sent": sent, "failed": failed, "removed": removed}


# ---------------------------------------------------------------- 统计


async def due_summary(session: AsyncSession, *, now: datetime | None = None) -> dict:
    """汇总所有未删除知识库的到期复习与未完成待办。"""
    now = now or datetime.now(timezone.utc)
    due_reviews = await session.scalar(
        select(func.count())
        .select_from(StudyReview)
        .join(KnowledgeBase, KnowledgeBase.id == StudyReview.kb_id)
        .where(
            KnowledgeBase.deleted_at.is_(None),
            StudyReview.due_at <= now,
        )
    )
    open_todos = await session.scalar(
        select(func.count())
        .select_from(TodoMirror)
        .join(KnowledgeBase, KnowledgeBase.id == TodoMirror.kb_id)
        .where(
            KnowledgeBase.deleted_at.is_(None),
            TodoMirror.status == "open",
        )
    )
    return {
        "due_reviews": int(due_reviews or 0),
        "open_todos": int(open_todos or 0),
    }


async def weekly_stats(session: AsyncSession, *, now: datetime | None = None) -> dict:
    """最近 7 天的答题量、正确率与学习时长（跨知识库汇总）。"""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    rows, correct, time_ms = (
        await session.execute(
            select(
                func.count(StudyAttempt.id),
                func.coalesce(
                    func.sum(case((StudyAttempt.correct.is_(True), 1), else_=0)),
                    0,
                ),
                func.coalesce(func.sum(StudyAttempt.time_ms), 0),
            )
            .join(KnowledgeBase, KnowledgeBase.id == StudyAttempt.kb_id)
            .where(
                KnowledgeBase.deleted_at.is_(None),
                StudyAttempt.attempted_at >= since,
            )
        )
    ).one()
    attempts = int(rows or 0)
    correct_count = int(correct or 0)
    return {
        "attempts": attempts,
        "accuracy": round(correct_count / attempts, 4) if attempts else 0.0,
        "minutes": round(int(time_ms or 0) / 60_000, 1),
    }


def _duration(minutes: float) -> str:
    if minutes >= 60:
        return f"{minutes / 60:.1f} 小时"
    return f"{round(minutes)} 分钟"


def daily_payload(summary: dict) -> dict:
    bits: list[str] = []
    if summary["due_reviews"]:
        bits.append(f"{summary['due_reviews']} 个知识点待复习")
    if summary["open_todos"]:
        bits.append(f"{summary['open_todos']} 项待办未完成")
    body = " · ".join(bits) + "。点击开始今天的复习。"
    return {
        "title": "今日学习提醒",
        "body": body,
        "url": "/learn?pane=review",
        "tag": "kiwi-daily",
    }


def weekly_payload(stats: dict) -> dict:
    if stats["attempts"]:
        body = (
            f"过去 7 天答题 {stats['attempts']} 道，"
            f"正确率 {round(stats['accuracy'] * 100)}%，"
            f"学习 {_duration(stats['minutes'])}。"
        )
    else:
        body = "过去 7 天还没有答题记录，新的一周从一道题开始。"
    return {
        "title": "本周学习周报",
        "body": body,
        "url": "/learn?pane=report",
        "tag": "kiwi-weekly",
    }


def test_payload() -> dict:
    return {
        "title": "Kiwi 测试通知",
        "body": "推送配置成功，复习与周报提醒会按计划送达。",
        "url": "/learn?pane=reminders",
        "tag": "kiwi-test",
    }


# ---------------------------------------------------------------- 调度


async def run_push_tick(
    session: AsyncSession, *, local_now: datetime | None = None
) -> dict | None:
    """每分钟调度入口：到点后每天最多发送一次日报 / 一次周报。

    ``local_now`` 用于测试注入；生产环境取系统本地时间，按
    ``push_reminder_hour`` 判断是否到点。返回 None 表示未开启或没有订阅。
    """
    row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
    if row is None or not row.push_enabled:
        return None
    if not await active_subscription_count(session):
        return None

    local_now = local_now or datetime.now().astimezone()
    today: date = local_now.date()
    result: dict = {"daily": None, "weekly": None}

    if local_now.hour >= row.push_reminder_hour and row.push_last_daily_date != today:
        summary = await due_summary(session)
        if summary["due_reviews"] or summary["open_todos"]:
            result["daily"] = await send_push(session, daily_payload(summary))
        row.push_last_daily_date = today
        await session.commit()

    if (
        row.push_weekly_report
        and local_now.weekday() == 0
        and local_now.hour >= row.push_reminder_hour
        and row.push_last_weekly_date != today
    ):
        stats = await weekly_stats(session)
        result["weekly"] = await send_push(session, weekly_payload(stats))
        row.push_last_weekly_date = today
        await session.commit()

    return result
