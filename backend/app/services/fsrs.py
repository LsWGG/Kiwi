"""FSRS-5 复习调度纯函数。

实现自由间隔重复调度（Free Spaced Repetition Scheduler）的确定性核心：

- 默认权重：FSRS-5 的 19 个参数 + 2 个保留参数（共 21 个），无第三方依赖；
- 可提取度：``R = (1 + t / (9 * S)) ** -1``；
- 下次间隔按目标保持率 0.9 反解，即 ``I = 9 * S * (1 / R - 1)``（R=0.9 时 I=S）；
- 状态机：new → learning → review，遗忘后进入 relearning；
- Again 使用遗忘稳定性公式并累计 lapses；
- 间隔上限 36500 天，可选确定性 fuzz（默认关闭，保证测试可复现）。

本模块只做纯计算，不依赖数据库或 ORM，便于独立测试与复用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# FSRS-5 默认权重（w0..w18 为 FSRS-5 参数；w19、w20 为 FSRS-6 同天复习参数，
# 本实现暂不使用，保留为 0，使权重向量满足 21 参数的接口约定）。
FSRS_WEIGHTS: tuple[float, ...] = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.6621,
    0.0,
    0.0,
)

# 评分：1=Again（遗忘）、2=Hard、3=Good、4=Easy。
AGAIN = 1
HARD = 2
GOOD = 3
EASY = 4
RATINGS = (AGAIN, HARD, GOOD, EASY)

# 复习状态。
STATE_NEW = "new"
STATE_LEARNING = "learning"
STATE_REVIEW = "review"
STATE_RELEARNING = "relearning"
REVIEW_STATES = (STATE_NEW, STATE_LEARNING, STATE_REVIEW, STATE_RELEARNING)

TARGET_RETENTION = 0.9
MAX_INTERVAL_DAYS = 36500.0
MIN_STABILITY = 0.1
MIN_DIFFICULTY = 1.0
MAX_DIFFICULTY = 10.0
EASE_MIN = 1.3
EASE_MAX = 2.8

# 首次学习/重学步骤（天）。Good/Easy 给出 1-3 天的首个间隔。
FIRST_INTERVAL_DAYS: dict[int, float] = {
    AGAIN: 0.0,
    HARD: 0.0,
    GOOD: 1.0,
    EASY: 3.0,
}


@dataclass(frozen=True, slots=True)
class FSRSState:
    """一张复习卡片的 FSRS 状态。"""

    stability: float = 0.0
    difficulty: float = 0.0
    reps: int = 0
    lapses: int = 0
    state: str = STATE_NEW
    last_rating: int | None = None


@dataclass(frozen=True, slots=True)
class FSRSResult:
    """一次评分后的调度结果。"""

    stability: float
    difficulty: float
    reps: int
    lapses: int
    state: str
    last_rating: int
    interval_days: float
    retrievability: float
    elapsed_days: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_rating(rating: int) -> int:
    try:
        value = int(rating)
    except (TypeError, ValueError) as exc:  # pragma: no cover - 防御式分支
        raise ValueError(f"无效评分：{rating!r}") from exc
    if value not in RATINGS:
        raise ValueError(f"评分必须是 1-4，收到 {rating!r}")
    return value


def rating_for_ratio(ratio: float, difficulty: str | None = None) -> int:
    """把 0-1 的得分映射为 FSRS 评分。

    题目难度只做很小的边界微调（basic +0.015 / hard -0.015），
    用于同一分数在不同难度题上的取舍，不参与核心算法。
    """

    try:
        value = float(ratio)
    except (TypeError, ValueError):
        value = 0.0
    nudge = {"basic": 0.015, "hard": -0.015}.get((difficulty or "").lower(), 0.0)
    value = _clamp(value + nudge, 0.0, 1.0)
    if value >= 0.9:
        return EASY
    if value >= 0.6:
        return GOOD
    if value >= 0.3:
        return HARD
    return AGAIN


def initial_stability(rating: int) -> float:
    """S0(G) = w[G-1]。"""

    rating = _normalize_rating(rating)
    return max(MIN_STABILITY, float(FSRS_WEIGHTS[rating - 1]))


def initial_difficulty(rating: int) -> float:
    """D0(G) = w4 - exp(w5 * (G - 1)) + 1，裁剪到 [1, 10]。"""

    rating = _normalize_rating(rating)
    value = FSRS_WEIGHTS[4] - math.exp(FSRS_WEIGHTS[5] * (rating - 1)) + 1.0
    return _clamp(value, MIN_DIFFICULTY, MAX_DIFFICULTY)


def next_difficulty(difficulty: float, rating: int) -> float:
    """难度更新：线性修正 + 向 D0(Easy) 均值回归。"""

    rating = _normalize_rating(rating)
    current = float(difficulty)
    if current <= 0.0:
        current = initial_difficulty(GOOD)
    updated = current - FSRS_WEIGHTS[6] * (rating - 3)
    updated = (
        FSRS_WEIGHTS[7] * initial_difficulty(EASY)
        + (1.0 - FSRS_WEIGHTS[7]) * updated
    )
    return _clamp(updated, MIN_DIFFICULTY, MAX_DIFFICULTY)


def retrievability(stability: float, elapsed_days: float) -> float:
    """可提取度 R = (1 + t / (9 * S))^-1。"""

    try:
        stability_value = float(stability)
        elapsed = float(elapsed_days)
    except (TypeError, ValueError):
        return 0.0
    if stability_value <= 0.0:
        return 0.0
    if elapsed <= 0.0:
        return 1.0
    return _clamp((1.0 + elapsed / (9.0 * stability_value)) ** -1, 0.0, 1.0)


def next_interval(stability: float, retention: float = TARGET_RETENTION) -> float:
    """按目标保持率反解间隔：I = 9 * S * (1 / retention - 1)。"""

    stability_value = float(stability)
    if stability_value <= 0.0:
        return 0.0
    if not 0.0 < retention <= 1.0:
        raise ValueError("retention 必须位于 (0, 1]")
    interval = 9.0 * stability_value * (1.0 / retention - 1.0)
    return _clamp(interval, 0.0, MAX_INTERVAL_DAYS)


def recall_stability(
    difficulty: float, stability: float, value: float, rating: int
) -> float:
    """成功回忆后的稳定性更新（Hard/Good/Easy）。"""

    rating = _normalize_rating(rating)
    hard_penalty = FSRS_WEIGHTS[15] if rating == HARD else 1.0
    easy_bonus = FSRS_WEIGHTS[16] if rating == EASY else 1.0
    growth = (
        math.exp(FSRS_WEIGHTS[8])
        * (11.0 - _clamp(float(difficulty), MIN_DIFFICULTY, MAX_DIFFICULTY))
        * max(MIN_STABILITY, float(stability)) ** (-FSRS_WEIGHTS[9])
        * (math.exp(FSRS_WEIGHTS[10] * (1.0 - _clamp(value, 0.0, 1.0))) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    updated = max(MIN_STABILITY, float(stability)) * (1.0 + growth)
    return _clamp(updated, MIN_STABILITY, MAX_INTERVAL_DAYS)


def forgetting_stability(
    difficulty: float, stability: float, value: float
) -> float:
    """遗忘（Again）后的稳定性更新。"""

    updated = (
        FSRS_WEIGHTS[11]
        * _clamp(float(difficulty), MIN_DIFFICULTY, MAX_DIFFICULTY)
        ** (-FSRS_WEIGHTS[12])
        * ((max(MIN_STABILITY, float(stability)) + 1.0) ** FSRS_WEIGHTS[13] - 1.0)
        * math.exp(FSRS_WEIGHTS[14] * (1.0 - _clamp(value, 0.0, 1.0)))
    )
    return _clamp(updated, MIN_STABILITY, MAX_INTERVAL_DAYS)


def difficulty_from_ease(ease_factor: float) -> float:
    """把旧 SM-2 ease（1.3-2.8）映射为 FSRS 难度（1-10，越大越难）。"""

    try:
        ease = float(ease_factor)
    except (TypeError, ValueError):
        ease = EASE_MAX
    ease = _clamp(ease, EASE_MIN, EASE_MAX)
    return _clamp(1.0 + (EASE_MAX - ease) * 6.0, MIN_DIFFICULTY, MAX_DIFFICULTY)


def ease_from_difficulty(difficulty: float) -> float:
    """把 FSRS 难度映射回旧 ease 字段，保持展示兼容。"""

    try:
        value = float(difficulty)
    except (TypeError, ValueError):
        value = MIN_DIFFICULTY
    value = _clamp(value, MIN_DIFFICULTY, MAX_DIFFICULTY)
    return _clamp(
        EASE_MAX - (value - MIN_DIFFICULTY) * (EASE_MAX - EASE_MIN) / 9.0,
        EASE_MIN,
        EASE_MAX,
    )


def _fuzz_interval(interval: float, stability: float, reps: int, rating: int) -> float:
    """确定性 fuzz：±5% 的伪随机扰动，便于测试复现。"""

    seed = stability * 12.9898 + reps * 78.233 + rating * 37.719
    noise = math.sin(seed) * 43758.5453
    fraction = noise - math.floor(noise)
    return interval * (1.0 + (fraction - 0.5) * 0.1)


def fsrs_schedule(
    state: FSRSState,
    rating: int,
    *,
    elapsed_days: float | None = None,
    fuzz: bool = False,
    retention: float = TARGET_RETENTION,
) -> FSRSResult:
    """根据当前状态与评分计算下一次复习安排。

    参数
    ----
    state: 当前 FSRS 状态（新卡传 ``FSRSState()``）。
    rating: 1=Again / 2=Hard / 3=Good / 4=Easy。
    elapsed_days: 距上次复习的天数；新卡忽略。
    fuzz: 是否对间隔做确定性扰动，默认关闭以保证测试可复现。
    retention: 目标保持率，默认 0.9。

    返回不可变的 :class:`FSRSResult`，不修改入参。
    """

    rating = _normalize_rating(rating)
    if not 0.0 < retention <= 1.0:
        raise ValueError("retention 必须位于 (0, 1]")

    stability = max(0.0, float(state.stability or 0.0))
    difficulty = float(state.difficulty or 0.0)
    reps = max(0, int(state.reps or 0))
    lapses = max(0, int(state.lapses or 0))
    previous_state = str(state.state or STATE_NEW)
    if previous_state not in REVIEW_STATES:
        previous_state = STATE_NEW
    elapsed = 0.0 if elapsed_days is None else max(0.0, float(elapsed_days))
    reps += 1

    if previous_state == STATE_NEW or stability <= 0.0:
        stability = initial_stability(rating)
        difficulty = initial_difficulty(rating)
        interval = FIRST_INTERVAL_DAYS[rating]
        if rating == EASY:
            next_state = STATE_REVIEW
        else:
            next_state = STATE_LEARNING
        current_retrievability = 1.0
    else:
        if difficulty <= 0.0:
            difficulty = initial_difficulty(GOOD)
        current_retrievability = retrievability(stability, elapsed)
        if rating == AGAIN:
            stability = forgetting_stability(
                difficulty, stability, current_retrievability
            )
            difficulty = next_difficulty(difficulty, rating)
            lapses += 1
            next_state = STATE_RELEARNING
            interval = 0.0
        else:
            stability = recall_stability(
                difficulty, stability, current_retrievability, rating
            )
            difficulty = next_difficulty(difficulty, rating)
            next_state = STATE_REVIEW
            interval = max(1.0, next_interval(stability, retention))

    stability = _clamp(stability, MIN_STABILITY, MAX_INTERVAL_DAYS)
    if fuzz and interval > 0.0:
        interval = _fuzz_interval(interval, stability, reps, rating)
    interval = _clamp(interval, 0.0, MAX_INTERVAL_DAYS)

    return FSRSResult(
        stability=round(stability, 6),
        difficulty=round(difficulty, 6),
        reps=reps,
        lapses=lapses,
        state=next_state,
        last_rating=rating,
        interval_days=round(interval, 2),
        retrievability=round(current_retrievability, 6),
        elapsed_days=round(elapsed, 6),
    )
