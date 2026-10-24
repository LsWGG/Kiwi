"""FSRS-5 复习调度纯逻辑测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.fsrs import (
    AGAIN,
    EASY,
    FSRS_WEIGHTS,
    GOOD,
    HARD,
    MAX_INTERVAL_DAYS,
    STATE_LEARNING,
    STATE_RELEARNING,
    STATE_REVIEW,
    FSRSState,
    fsrs_schedule,
    next_interval,
    rating_for_ratio,
    retrievability,
)
from app.services.study_engine import _apply_review_schedule

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def review(**kwargs):
    """不包含任何 FSRS 新字段的旧版行（SimpleNamespace 模拟 ORM 对象）。"""

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


def as_state(result) -> FSRSState:
    return FSRSState(
        stability=result.stability,
        difficulty=result.difficulty,
        reps=result.reps,
        lapses=result.lapses,
        state=result.state,
        last_rating=result.last_rating,
    )


def test_first_good_and_easy_have_sane_interval_and_stability():
    good = fsrs_schedule(FSRSState(), GOOD)
    easy = fsrs_schedule(FSRSState(), EASY)

    assert 1.0 <= good.interval_days <= 3.0
    assert 1.0 <= easy.interval_days <= 3.0
    assert good.stability > 0
    assert easy.stability > 0
    assert easy.stability > good.stability
    assert good.state == STATE_LEARNING
    assert easy.state == STATE_REVIEW
    assert good.reps == easy.reps == 1
    assert good.last_rating == GOOD
    assert easy.last_rating == EASY


def test_repeated_good_grows_intervals_and_stability_monotonically():
    state = FSRSState()
    elapsed: float | None = None
    intervals: list[float] = []
    stabilities: list[float] = []

    for _ in range(6):
        result = fsrs_schedule(state, GOOD, elapsed_days=elapsed)
        intervals.append(result.interval_days)
        stabilities.append(result.stability)
        state = as_state(result)
        elapsed = result.interval_days

    assert intervals[0] == 1.0
    assert all(b > a for a, b in zip(intervals, intervals[1:]))
    assert all(b > a for a, b in zip(stabilities, stabilities[1:]))


def test_again_resets_to_relearning_and_increments_lapses():
    state = FSRSState(
        stability=20.0,
        difficulty=5.0,
        reps=5,
        lapses=2,
        state=STATE_REVIEW,
        last_rating=GOOD,
    )
    result = fsrs_schedule(state, AGAIN, elapsed_days=20.0)

    assert result.state == STATE_RELEARNING
    assert result.lapses == 3
    assert 0.0 <= result.interval_days <= 1.0
    assert 0.0 < result.stability < 20.0
    assert result.reps == 6

    # 新卡首次 Again 进入 learning，不计 lapse。
    fresh = fsrs_schedule(FSRSState(), AGAIN)
    assert fresh.state == STATE_LEARNING
    assert fresh.lapses == 0
    assert fresh.interval_days <= 1.0


def test_hard_good_easy_intervals_are_ordered():
    review_state = FSRSState(
        stability=10.0,
        difficulty=5.0,
        reps=3,
        state=STATE_REVIEW,
        last_rating=GOOD,
    )
    hard = fsrs_schedule(review_state, HARD, elapsed_days=10.0)
    good = fsrs_schedule(review_state, GOOD, elapsed_days=10.0)
    easy = fsrs_schedule(review_state, EASY, elapsed_days=10.0)

    assert hard.interval_days < good.interval_days < easy.interval_days

    # 新卡同样满足 Hard < Good < Easy（0 < 1 < 3）。
    new_hard = fsrs_schedule(FSRSState(), HARD)
    new_good = fsrs_schedule(FSRSState(), GOOD)
    new_easy = fsrs_schedule(FSRSState(), EASY)
    assert new_hard.interval_days < new_good.interval_days < new_easy.interval_days


def test_default_weight_vector_and_target_retention_interval():
    assert len(FSRS_WEIGHTS) == 21
    # R = (1 + t/(9S))^-1 下，目标保持率 0.9 对应的间隔恰为 stability。
    assert next_interval(10.0) == pytest.approx(10.0)
    assert next_interval(10.0, retention=0.8) > 10.0


def test_retrievability_decreases_as_elapsed_days_grow():
    days = [0, 1, 5, 10, 20, 50, 200]
    values = [retrievability(10.0, day) for day in days]

    assert values[0] == 1.0
    assert all(b < a for a, b in zip(values, values[1:]))
    # 间隔等于 stability 时保持率恰为 0.9。
    assert retrievability(10.0, 10.0) == pytest.approx(0.9)
    assert retrievability(0.0, 10.0) == 0.0


def test_ratio_to_rating_mapping_and_difficulty_tie_break():
    assert rating_for_ratio(1.0) == EASY
    assert rating_for_ratio(0.9) == EASY
    assert rating_for_ratio(0.75) == GOOD
    assert rating_for_ratio(0.6) == GOOD
    assert rating_for_ratio(0.5) == HARD
    assert rating_for_ratio(0.3) == HARD
    assert rating_for_ratio(0.29) == AGAIN
    assert rating_for_ratio(0.0) == AGAIN

    # 难度只做很小的边界微调（basic +0.015 / hard -0.015）。
    assert rating_for_ratio(0.595, "basic") == GOOD
    assert rating_for_ratio(0.595, "hard") == HARD
    assert rating_for_ratio(0.895, "hard") == GOOD
    assert rating_for_ratio(0.895, "basic") == EASY


def test_interval_is_capped():
    state = FSRSState(
        stability=10_000_000.0,
        difficulty=1.0,
        reps=50,
        state=STATE_REVIEW,
        last_rating=EASY,
    )
    result = fsrs_schedule(state, EASY, elapsed_days=1.0)
    assert result.interval_days <= MAX_INTERVAL_DAYS


def test_optional_fuzz_is_deterministic():
    state = FSRSState(
        stability=10.0,
        difficulty=5.0,
        reps=3,
        state=STATE_REVIEW,
        last_rating=GOOD,
    )
    first = fsrs_schedule(state, GOOD, elapsed_days=10.0, fuzz=True)
    second = fsrs_schedule(state, GOOD, elapsed_days=10.0, fuzz=True)
    plain = fsrs_schedule(state, GOOD, elapsed_days=10.0)

    assert first.interval_days == second.interval_days
    assert abs(first.interval_days - plain.interval_days) <= plain.interval_days * 0.06


def test_legacy_row_without_fsrs_state_still_schedules():
    item = review(
        ease_factor=2.4,
        repetitions=4,
        interval_days=12.0,
        last_reviewed_at=NOW - timedelta(days=12),
        last_correct=True,
    )
    _apply_review_schedule(item, 0.8, "medium", NOW, correct=True)

    assert item.stability > 0
    assert item.difficulty > 0
    assert item.review_state == STATE_REVIEW
    assert item.lapses == 0
    assert item.last_rating == GOOD
    assert item.fsrs_reps == 5
    assert item.interval_days > 12.0
    assert item.due_at > NOW
    # 兼容字段同步。
    assert item.repetitions == 5
    assert 1.3 <= item.ease_factor <= 2.8
    assert item.last_correct is True


def test_legacy_row_with_null_fsrs_columns_still_schedules():
    item = review(
        stability=None,
        difficulty=None,
        lapses=None,
        review_state=None,
        last_rating=None,
        fsrs_reps=None,
    )
    _apply_review_schedule(item, 0.0, "basic", NOW, correct=False)

    assert item.stability > 0
    assert 1.0 <= item.difficulty <= 10.0
    assert item.review_state in {STATE_LEARNING, STATE_RELEARNING}
    assert item.interval_days <= 1.0
    assert item.due_at <= NOW + timedelta(days=1)
    assert item.repetitions == 0
    assert item.fsrs_reps == 1
