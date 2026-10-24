"""Web Push：订阅管理、每日 / 每周提醒与失效订阅清理。"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.models import PushSubscription, StudyReview, SystemSettings
from app.db.models.system_settings import SYSTEM_SETTINGS_ID
from app.db.session import async_session_factory
from app.services import push_service


async def test_push_subscribe_and_reminders(client, kb, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        push_service,
        "_send_one",
        lambda endpoint, p256dh, auth, data, vapid: sent.append(json.loads(data)),
    )

    async with async_session_factory() as session:
        row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
        snapshot = (
            None
            if row is None
            else {
                "push_enabled": row.push_enabled,
                "push_reminder_hour": row.push_reminder_hour,
                "push_weekly_report": row.push_weekly_report,
                "push_last_daily_date": row.push_last_daily_date,
                "push_last_weekly_date": row.push_last_weekly_date,
            }
        )

    endpoint = f"https://push.example.com/{uuid.uuid4().hex}"
    try:
        status = await client.get("/api/push/status")
        assert status.status_code == 200, status.text
        assert status.json()["public_key"]
        assert status.json()["subscriptions"] == []

        bad = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": "ftp://example.com/x",
                "keys": {"p256dh": "B" * 65, "auth": "a" * 22},
            },
        )
        assert bad.status_code == 400

        resp = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": endpoint,
                "keys": {"p256dh": "B" * 65, "auth": "a" * 22},
                "user_agent": "pytest",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["failure_count"] == 0

        settings = await client.patch(
            "/api/push/settings",
            json={"enabled": True, "reminder_hour": 20, "weekly_report": True},
        )
        assert settings.status_code == 200, settings.text
        assert settings.json()["enabled"] is True
        assert settings.json()["reminder_hour"] == 20

        test_push = await client.post("/api/push/test")
        assert test_push.status_code == 200, test_push.text
        assert test_push.json()["sent"] == 1
        assert sent[0]["title"] == "Kiwi 测试通知"
        sent.clear()

        async with async_session_factory() as session:
            session.add(
                StudyReview(
                    kb_id=uuid.UUID(kb["id"]),
                    slug=f"push-{uuid.uuid4().hex[:6]}",
                    due_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

            # 2026-10-19 是周一：每日提醒与周报会同时触发。
            local = datetime.combine(date(2026, 10, 19), datetime.min.time()).replace(
                hour=20
            )
            first = await push_service.run_push_tick(session, local_now=local)
            second = await push_service.run_push_tick(session, local_now=local)

        assert first["daily"]["sent"] == 1
        assert first["weekly"]["sent"] == 1
        # 同一天重复调度不会再次推送。
        assert second["daily"] is None
        assert second["weekly"] is None
        titles = {item["title"] for item in sent}
        assert titles == {"今日学习提醒", "本周学习周报"}
        daily = next(item for item in sent if item["title"] == "今日学习提醒")
        assert "待复习" in daily["body"]

        listed = await client.get("/api/push/status")
        assert listed.json()["last_daily_date"] == "2026-10-19"
        assert listed.json()["last_weekly_date"] == "2026-10-19"

        removed = await client.post(
            "/api/push/unsubscribe", json={"endpoint": endpoint}
        )
        assert removed.json()["removed"] is True
        empty = await client.post("/api/push/test")
        assert empty.status_code == 400
    finally:
        async with async_session_factory() as session:
            for sub in (await session.execute(select(PushSubscription))).scalars():
                if sub.endpoint == endpoint:
                    await session.delete(sub)
            row = await session.get(SystemSettings, SYSTEM_SETTINGS_ID)
            if row is not None:
                if snapshot is None:
                    await session.delete(row)
                else:
                    for key, value in snapshot.items():
                        setattr(row, key, value)
            await session.commit()
