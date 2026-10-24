"""每周学习报告：统计口径、薄弱知识点与留存曲线。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import StudyAttempt, StudyProfile, StudyQuestion
from app.db.session import async_session_factory


async def test_weekly_report_aggregates_attempts(client, kb):
    slug = f"cache-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        question = StudyQuestion(
            kb_id=uuid.UUID(kb["id"]),
            topic_slug=slug,
            fingerprint=uuid.uuid4().hex,
            question_json={"question": "缓存命中率？"},
        )
        session.add(question)
        await session.flush()
        session.add_all(
            [
                StudyAttempt(
                    kb_id=uuid.UUID(kb["id"]),
                    question_id=question.id,
                    correct=False,
                    time_ms=60_000,
                    attempted_at=now - timedelta(days=10),
                ),
                StudyAttempt(
                    kb_id=uuid.UUID(kb["id"]),
                    question_id=question.id,
                    correct=False,
                    time_ms=90_000,
                    attempted_at=now - timedelta(days=3),
                ),
                StudyAttempt(
                    kb_id=uuid.UUID(kb["id"]),
                    question_id=question.id,
                    correct=True,
                    time_ms=30_000,
                    attempted_at=now - timedelta(days=1),
                ),
                StudyAttempt(
                    kb_id=uuid.UUID(kb["id"]),
                    question_id=question.id,
                    correct=True,
                    time_ms=20_000,
                    attempted_at=now - timedelta(hours=8),
                ),
            ]
        )
        session.add(
            StudyProfile(
                kb_id=uuid.UUID(kb["id"]),
                onboarded=True,
                mastery={slug: 0.3},
            )
        )
        await session.commit()

    resp = await client.get(f"/api/study/report/weekly?kb_id={kb['id']}&days=7")
    assert resp.status_code == 200, resp.text
    report = resp.json()

    assert report["days"] == 7
    assert report["attempts"] == 3
    assert report["correct"] == 2
    assert report["accuracy"] == 0.667
    assert report["minutes"] == 2.3
    assert report["previous_attempts"] == 1
    assert report["previous_accuracy"] == 0.0
    assert report["mastery_topics"] == 1
    assert report["mastery_average"] == 0.3
    assert report["weak_count"] == 1

    assert len(report["daily"]) == 7
    assert sum(day["attempts"] for day in report["daily"]) == 3

    assert report["weak_topics"][0]["slug"] == slug
    assert report["weak_topics"][0]["accuracy"] == 0.667

    buckets = {item["bucket"]: item for item in report["retention"]}
    assert len(buckets) == 5
    # 间隔 2 天的一次作答与当天 / 1 天内的两次作答分别落入不同档位。
    assert buckets["1–2 天"]["attempts"] == 1
    assert buckets["当天"]["attempts"] == 1
    assert buckets["1–2 天"]["accuracy"] == 1.0
