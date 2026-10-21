"""复习调度（ease-factor）纯逻辑测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.study_engine import (
    REVIEW_MAX_EASE,
    REVIEW_MIN_EASE,
    _apply_review_schedule,
)


def review(**kwargs):
    base = {
        "ease_factor": 2.5,
        "repetitions": 0,
        "interval_days": 0.0,
        "last_reviewed_at": None,
        "last_correct": None,
        "due_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_first_and_second_correct_answers_use_fixed_intervals():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    item = review()
    _apply_review_schedule(item, True, "medium", now)
    assert item.repetitions == 1
    assert item.interval_days == 1.0
    assert item.ease_factor == 2.6
    assert item.due_at == now + timedelta(days=1)

    _apply_review_schedule(item, True, "medium", now)
    assert item.repetitions == 2
    assert item.interval_days == 3.0


def test_difficulty_factor_and_ease_cap():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    # 第二次答对：固定 3 天 × 难度系数。
    item = review(ease_factor=REVIEW_MAX_EASE, repetitions=1, interval_days=1.0)
    _apply_review_schedule(item, True, "basic", now)
    assert item.interval_days == 3.9
    assert item.ease_factor == REVIEW_MAX_EASE

    # 第三次及以后：上一间隔 × ease × 难度系数。
    item = review(ease_factor=2.5, repetitions=2, interval_days=4.0)
    _apply_review_schedule(item, True, "hard", now)
    assert item.interval_days == 8.0


def test_wrong_answer_resets_and_lowers_ease():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    item = review(ease_factor=REVIEW_MIN_EASE, repetitions=5, interval_days=30.0)
    _apply_review_schedule(item, False, "medium", now)
    assert item.repetitions == 0
    assert item.interval_days == 1.0
    assert item.ease_factor == REVIEW_MIN_EASE
    assert item.last_correct is False
    assert item.due_at == now + timedelta(days=1)
