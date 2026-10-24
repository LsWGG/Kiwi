"""每周学习报告：答题量、正确率、薄弱知识点与留存曲线。

数据来自 ``study_attempts`` 与 ``study_profiles.mastery``，不额外建表；
留存曲线用「同一知识点两次作答的间隔」近似，间隔越长正确率越低即说明遗忘。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StudyAttempt, StudyProfile, StudyQuestion, WikiPage

RETENTION_DAYS = 180
RETENTION_BUCKETS = (
    ("当天", 0.0, 1.0),
    ("1–2 天", 1.0, 3.0),
    ("3–7 天", 3.0, 8.0),
    ("8–30 天", 8.0, 31.0),
    ("30 天以上", 31.0, float("inf")),
)


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total, 3) if total else 0.0


def _minutes(total_ms: int) -> float:
    return round(total_ms / 60_000, 1)


def _totals(rows: list[tuple]) -> dict:
    correct = sum(1 for row in rows if row.correct)
    return {
        "attempts": len(rows),
        "correct": correct,
        "accuracy": _accuracy(correct, len(rows)),
        "minutes": _minutes(sum(int(row.time_ms or 0) for row in rows)),
        "active_days": len({_local_date(row.attempted_at) for row in rows}),
    }


def _local_date(value: datetime) -> object:
    # 容器 TZ 默认 Asia/Shanghai；做题日期按本地时区归组。
    return value.astimezone().date() if value.tzinfo else value.date()


async def build_weekly_report(
    session: AsyncSession,
    kb_id: uuid.UUID,
    *,
    days: int = 7,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    retention_start = now - timedelta(days=RETENTION_DAYS)

    rows = (
        await session.execute(
            select(
                StudyAttempt.correct,
                StudyAttempt.time_ms,
                StudyAttempt.attempted_at,
                StudyQuestion.topic_slug,
                StudyQuestion.wiki_page_id,
                StudyQuestion.question_json,
            )
            .outerjoin(StudyQuestion, StudyAttempt.question_id == StudyQuestion.id)
            .where(
                StudyAttempt.kb_id == kb_id,
                StudyAttempt.attempted_at >= retention_start,
            )
            .order_by(StudyAttempt.attempted_at)
        )
    ).all()

    period_rows = [row for row in rows if row.attempted_at >= start]
    previous_rows = [
        row for row in rows if previous_start <= row.attempted_at < start
    ]
    totals = _totals(period_rows)
    previous = _totals(previous_rows)

    # 每日分布：固定输出 7 天，前端可以直接铺开，无需补零。
    daily_map: dict[object, list] = defaultdict(list)
    for row in period_rows:
        daily_map[_local_date(row.attempted_at)].append(row)
    daily = []
    for offset in range(days):
        date = _local_date(now) - timedelta(days=days - 1 - offset)
        day_rows = daily_map.get(date, [])
        day_correct = sum(1 for row in day_rows if row.correct)
        daily.append(
            {
                "date": date.isoformat(),
                "attempts": len(day_rows),
                "correct": day_correct,
                "accuracy": _accuracy(day_correct, len(day_rows)),
                "minutes": _minutes(sum(int(row.time_ms or 0) for row in day_rows)),
            }
        )

    pages = (
        (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id)))
        .scalars()
        .all()
    )
    title_by_slug = {page.slug: page.title for page in pages}
    title_by_id = {page.id: page.title for page in pages}

    profile = (
        (await session.execute(select(StudyProfile).where(StudyProfile.kb_id == kb_id)))
        .scalars()
        .first()
    )
    mastery = dict(profile.mastery or {}) if profile else {}

    topic_stats: dict[str, list] = defaultdict(list)
    for row in period_rows:
        slug = row.topic_slug or ""
        topic_stats[slug].append(row)

    weak_topics = []
    for slug, topic_rows in topic_stats.items():
        correct = sum(1 for row in topic_rows if row.correct)
        accuracy = _accuracy(correct, len(topic_rows))
        mastery_value = float(mastery.get(slug, 0.0)) if slug else 0.0
        if len(topic_rows) < 2 and accuracy >= 0.7:
            continue
        if accuracy >= 0.7 and mastery_value >= 0.5:
            continue
        title = (
            title_by_slug.get(slug)
            or next(
                (
                    title_by_id.get(row.wiki_page_id)
                    for row in topic_rows
                    if row.wiki_page_id in title_by_id
                ),
                None,
            )
            or slug
            or "未分类"
        )
        weak_topics.append(
            {
                "slug": slug,
                "title": title,
                "attempts": len(topic_rows),
                "accuracy": accuracy,
                "mastery": round(mastery_value, 3),
            }
        )
    weak_topics.sort(key=lambda item: (item["accuracy"], -item["attempts"]))
    weak_topics = weak_topics[:8]

    # 留存曲线：同一知识点相邻两次作答的间隔与正确率。
    retention_counts: dict[str, list[int]] = {
        label: [0, 0] for label, _, _ in RETENTION_BUCKETS
    }
    last_seen: dict[str, datetime] = {}
    for row in rows:
        slug = row.topic_slug or ""
        if not slug:
            continue
        previous_at = last_seen.get(slug)
        last_seen[slug] = row.attempted_at
        if previous_at is None:
            continue
        gap = max(0.0, (row.attempted_at - previous_at).total_seconds() / 86400)
        for label, low, high in RETENTION_BUCKETS:
            if low <= gap < high:
                retention_counts[label][0] += 1
                retention_counts[label][1] += 1 if row.correct else 0
                break
    retention = [
        {
            "bucket": label,
            "attempts": counts[0],
            "accuracy": _accuracy(counts[1], counts[0]),
        }
        for label, counts in (
            (label, retention_counts[label]) for label, _, _ in RETENTION_BUCKETS
        )
    ]

    mastery_values = [float(value) for value in mastery.values() if value is not None]
    return {
        "start": start.date().isoformat(),
        "end": now.date().isoformat(),
        "days": days,
        **totals,
        "previous_attempts": previous["attempts"],
        "previous_correct": previous["correct"],
        "previous_accuracy": previous["accuracy"],
        "previous_minutes": previous["minutes"],
        "mastery_average": round(
            sum(mastery_values) / len(mastery_values), 3
        )
        if mastery_values
        else 0.0,
        "mastery_topics": len(mastery_values),
        "weak_count": sum(1 for value in mastery_values if value < 0.5),
        "daily": daily,
        "weak_topics": weak_topics,
        "retention": retention,
    }
