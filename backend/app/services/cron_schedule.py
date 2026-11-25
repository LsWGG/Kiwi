"""轻量 cron 与自然语言计划解析。

只支持标准 5 段 cron（分 时 日 月 周），周字段 0/7 都表示周日；
不引入额外依赖。供微信定时推送的任务解析、预览与调度使用。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache

WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"]
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


class CronError(ValueError):
    """cron 语法或自然语言无法解析。"""


def _int(value: str, *, dow: bool = False) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise CronError(f"无效数字：{value}") from exc
    if dow and number == 7:
        number = 0
    return number


@lru_cache(maxsize=512)
def _field_values(field: str, lo: int, hi: int, dow: bool = False) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError("cron 字段不能为空")
        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = _int(step_text)
            if step <= 0:
                raise CronError("cron 步长必须大于 0")
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = _int(left, dow=dow), _int(right, dow=dow)
        else:
            start = end = _int(base, dow=dow)
        if start < lo or end > hi or start > end:
            raise CronError(f"cron 字段超出范围：{part}")
        values.update(range(start, end + 1, step))
    if not values:
        raise CronError(f"cron 字段没有有效值：{field}")
    return frozenset(values)


def validate_cron(expression: str) -> str:
    """校验并规范化 5 段 cron；返回去掉多余空白的表达式。"""
    fields = str(expression or "").strip().split()
    if len(fields) != 5:
        raise CronError("cron 需要 5 段：分 时 日 月 周")
    for index, (field, (lo, hi)) in enumerate(zip(fields, _FIELD_RANGES, strict=True)):
        _field_values(field, lo, hi, dow=index == 4)
    return " ".join(fields)


def _matches_field(field: str, value: int, lo: int, hi: int, dow: bool = False) -> bool:
    return value in _field_values(field, lo, hi, dow=dow)


def matches(expression: str, when: datetime) -> bool:
    """判断某个本地时间是否命中 cron（到分钟）。"""
    fields = validate_cron(expression).split()
    minute, hour, dom, month, dow = fields
    if not _matches_field(minute, when.minute, 0, 59):
        return False
    if not _matches_field(hour, when.hour, 0, 23):
        return False
    if not _matches_field(month, when.month, 1, 12):
        return False
    cron_dow = (when.weekday() + 1) % 7
    dom_any = dom == "*"
    dow_any = dow == "*"
    dom_ok = _matches_field(dom, when.day, 1, 31)
    dow_ok = _matches_field(dow, cron_dow, 0, 6, dow=True)
    if dom_any and dow_any:
        return True
    if dom_any:
        return dow_ok
    if dow_any:
        return dom_ok
    # 标准 cron：日与周同时限定时取并集。
    return dom_ok or dow_ok


def _minute_hour(fields: list[str]) -> tuple[int, int] | None:
    """返回 (hour, minute)，用于展示；cron 字段顺序是 minute hour。"""
    try:
        return int(fields[1]), int(fields[0])
    except (ValueError, IndexError):
        return None


def describe(expression: str) -> str:
    """把常见 cron 转成一句中文；无法识别时原样展示。"""
    try:
        fields = validate_cron(expression).split()
    except CronError:
        return str(expression or "")
    minute, hour, dom, month, dow = fields
    if month != "*":
        return f"Cron {expression}"
    if minute == "*" and hour == "*" and dom == "*" and dow == "*":
        return "每分钟"
    if minute.startswith("*/") and hour == "*" and dom == "*" and dow == "*":
        return f"每 {minute[2:]} 分钟"
    if hour.startswith("*/") and minute == "0" and dom == "*" and dow == "*":
        return f"每 {hour[2:]} 小时"
    moment = _minute_hour(fields)
    if moment is None:
        return f"Cron {expression}"
    hhmm = f"{moment[0]:02d}:{moment[1]:02d}"
    if dom == "*" and dow == "*":
        return f"每天 {hhmm}"
    if dom == "*" and dow == "1-5":
        return f"工作日 {hhmm}"
    if dom == "*" and re.fullmatch(r"[0-6]", dow):
        return f"每周{WEEKDAY_LABELS[int(dow)]} {hhmm}"
    if dow == "*" and dom.isdigit():
        return f"每月 {int(dom)} 号 {hhmm}"
    return f"Cron {expression}"


def next_runs(
    expression: str, *, count: int = 3, now: datetime | None = None
) -> list[str]:
    """从下一分钟开始找 count 次触发时间（ISO 字符串）。"""
    validate_cron(expression)
    start = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    found: list[str] = []
    cursor = start
    # 最多找一年，避免非法组合（如 2 月 31 日）无限循环。
    for _ in range(366 * 24 * 60):
        if matches(expression, cursor):
            found.append(cursor.isoformat(timespec="minutes"))
            if len(found) >= count:
                break
        cursor += timedelta(minutes=1)
    return found


_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _cn_int(text: str) -> int | None:
    text = (text or "").strip()
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        units = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + units
    if len(text) == 1:
        return _CN_DIGITS.get(text)
    return None


_TIME_COLON_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]?\d)(?!\d)")
_TIME_CN_RE = re.compile(
    r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|晚)?\s*"
    r"([零〇一二两三四五六七八九十\d]{1,3})\s*[点时]"
    r"(半|一刻|三刻|(\d{1,2})\s*分?)?"
)


def _extract_time(text: str) -> tuple[int, int] | None:
    colon = _TIME_COLON_RE.search(text)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
        prefix = text[max(0, colon.start() - 3) : colon.start()]
        if any(word in prefix for word in ("下午", "傍晚", "晚上", "夜里")) and hour < 12:
            hour += 12
        return hour % 24, minute
    cn = _TIME_CN_RE.search(text)
    if not cn:
        return None
    prefix, number, suffix, minute_text = cn.groups()
    hour = _cn_int(number)
    if hour is None:
        return None
    if prefix in ("下午", "傍晚", "晚上", "夜里", "晚") and hour < 12:
        hour += 12
    if prefix == "中午" and hour < 11:
        hour += 12
    if prefix == "凌晨" and hour == 12:
        hour = 0
    minute = 0
    if suffix == "半":
        minute = 30
    elif suffix == "一刻":
        minute = 15
    elif suffix == "三刻":
        minute = 45
    elif minute_text:
        minute = int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise CronError("时间超出范围")
    return hour, minute


_WEEKDAY_CN = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 0,
    "天": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 0,
}


def natural_to_cron(text: str) -> tuple[str, str]:
    """把常见自然语言计划转成 cron，返回 (cron, 中文描述)。"""
    raw = (text or "").strip()
    if not raw:
        raise CronError("请填写计划，例如「每天早上九点」")
    # 已经是 5 段 cron。
    if len(raw.split()) == 5:
        expr = validate_cron(raw)
        return expr, describe(expr)

    normalized = raw.replace("每个", "每").replace("每日", "每天")
    lowered = normalized.lower()

    # 间隔型：每 N 分钟 / 每 N 小时。
    every_minutes = re.search(
        r"每\s*([0-9一二两三四五六七八九十]+)\s*分钟", normalized
    ) or re.search(r"every\s+(\d+)\s*minutes?", lowered)
    if every_minutes:
        count = _cn_int(every_minutes.group(1))
        if not count or not 1 <= count <= 59:
            raise CronError("分钟间隔应在 1–59 之间")
        expr = f"*/{count} * * * *"
        return expr, describe(expr)
    if "半小时" in normalized or "每30分钟" in normalized:
        expr = "*/30 * * * *"
        return expr, describe(expr)
    every_hours = re.search(
        r"每\s*([0-9一二两三四五六七八九十]+)\s*小时", normalized
    ) or re.search(r"every\s+(\d+)\s+hours?", lowered)
    if every_hours:
        count = _cn_int(every_hours.group(1))
        if not count or not 1 <= count <= 23:
            raise CronError("小时间隔应在 1–23 之间")
        expr = f"0 */{count} * * *"
        return expr, describe(expr)
    if re.search(r"每小时|每个小时|hourly", lowered):
        expr = "0 * * * *"
        return expr, describe(expr)

    # 先去掉频率词，避免「每周一10点」被正则读成「一10」。
    time_text = normalized
    time_text = re.sub(r"工作日|周一至周五|周一到周五|weekdays?", " ", time_text)
    time_text = re.sub(r"每周\s*[一二三四五六日天1-7]", " ", time_text)
    time_text = re.sub(
        r"每月\s*[0-9一二两三四五六七八九十]+\s*[号日]", " ", time_text
    )
    time_text = re.sub(r"每天|每日|daily|every day", " ", time_text)
    moment = _extract_time(time_text)
    if moment is None:
        raise CronError("没有识别到时间，例如「每天 09:00」「工作日早上八点半」")
    hour, minute = moment

    dow = "*"
    dom = "*"
    if re.search(r"工作日|周一至周五|周一到周五|weekdays?", lowered):
        dow = "1-5"
    else:
        weekly = re.search(r"每周\s*([一二三四五六日天1-7])", normalized)
        if weekly:
            dow = str(_WEEKDAY_CN[weekly.group(1)])
        else:
            monthly = re.search(
                r"每月\s*([0-9一二两三四五六七八九十]+)\s*[号日]", normalized
            )
            if monthly:
                day = _cn_int(monthly.group(1))
                if not day or not 1 <= day <= 31:
                    raise CronError("每月日期应在 1–31 之间")
                dom = str(day)
            elif not re.search(r"每天|daily|every day", lowered):
                raise CronError("请说明频率，例如「每天」「工作日」「每周一」「每月 1 号」")

    expr = validate_cron(f"{minute} {hour} {dom} * {dow}")
    return expr, describe(expr)


def from_legacy_time(at_time: str, days: str = "daily") -> str:
    """兼容旧版 HH:MM + days 字段，生成 cron。"""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (at_time or "").strip())
    if not match:
        raise CronError("时间格式应为 HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    dow = "*"
    if days in ("weekdays", "工作日"):
        dow = "1-5"
    return validate_cron(f"{minute} {hour} * * {dow}")


def schedule_cron(item: dict) -> str:
    """读取任务 cron；兼容旧的 time / days 字段。"""
    cron = str(item.get("cron") or "").strip()
    if cron:
        return validate_cron(cron)
    return from_legacy_time(str(item.get("time") or "09:00"), str(item.get("days") or "daily"))



__all__ = [
    "CronError",
    "describe",
    "from_legacy_time",
    "matches",
    "natural_to_cron",
    "next_runs",
    "schedule_cron",
    "validate_cron",
]
