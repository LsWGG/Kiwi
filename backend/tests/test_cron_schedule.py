"""cron 与自然语言计划解析。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services import cron_schedule
from app.services.schedule_parser import ScheduleParseError, parse_schedule


@pytest.mark.parametrize(
    ("text", "cron", "description"),
    [
        ("每天早上九点", "0 9 * * *", "每天 09:00"),
        ("每天 09:00", "0 9 * * *", "每天 09:00"),
        ("工作日早上八点半", "30 8 * * 1-5", "工作日 08:30"),
        ("每周一10点", "0 10 * * 1", "每周一 10:00"),
        ("每月1号9点", "0 9 1 * *", "每月 1 号 09:00"),
        ("每2小时", "0 */2 * * *", "每 2 小时"),
        ("每30分钟", "*/30 * * * *", "每 30 分钟"),
        ("0 9 * * *", "0 9 * * *", "每天 09:00"),
    ],
)
def test_natural_language_to_cron(text, cron, description):
    assert cron_schedule.natural_to_cron(text) == (cron, description)


def test_cron_rejects_invalid_expression():
    with pytest.raises(cron_schedule.CronError):
        cron_schedule.validate_cron("0 25 * * *")
    with pytest.raises(cron_schedule.CronError):
        cron_schedule.validate_cron("0 9 * *")


def test_cron_matches_weekday_and_month_day():
    assert cron_schedule.matches("30 8 * * 1-5", datetime(2026, 11, 27, 8, 30))
    assert not cron_schedule.matches("30 8 * * 1-5", datetime(2026, 11, 29, 8, 30))
    assert cron_schedule.matches("0 9 1 * *", datetime(2026, 12, 1, 9, 0))
    # 日与周同时限定时按标准 cron 取并集。
    assert cron_schedule.matches("0 9 1 * 1", datetime(2026, 12, 7, 9, 0))
    assert cron_schedule.matches("0 9 1 * 1", datetime(2026, 12, 1, 9, 0))


def test_next_runs_is_ordered():
    runs = cron_schedule.next_runs("0 9 * * *", count=2, now=datetime(2026, 11, 25, 10, 0))
    assert runs == ["2026-11-26T09:00", "2026-11-27T09:00"]


async def test_parse_schedule_falls_back_without_llm(monkeypatch):
    async def no_llm(text, session=None):
        return None

    monkeypatch.setattr("app.services.schedule_parser._llm_parse", no_llm)
    assert await parse_schedule("每天早上九点") == ("0 9 * * *", "每天 09:00")
    with pytest.raises(ScheduleParseError):
        await parse_schedule("完全不是计划")
