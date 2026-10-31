"""问答 Agent 规划：时间窗口解析、联网判断与模型规划兜底。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.agent_planner import (
    AgentPlan,
    TimeWindow,
    apply_time_window,
    contextualize_query,
    in_time_window,
    is_follow_up,
    needs_web,
    note_title_date,
    plan_with_llm,
    refine_web_query,
    resolve_time_window,
    rules_plan,
    split_queries,
)
from app.services.retrieval import RetrievalFilters

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 1, 10, 30, tzinfo=TZ)  # 周日


def test_split_queries_keeps_original_and_parts():
    assert split_queries("对比 A 和 B 的差异") == [
        "对比 A 和 B 的差异",
        "对比 A",
        "B 的差异",
    ]
    assert split_queries("这周我干嘛了") == ["这周我干嘛了"]
    long_query = "问" * 200
    assert split_queries(long_query) == [long_query]


@pytest.mark.parametrize(
    ("query", "start", "end", "label"),
    [
        ("这周我干嘛了", date(2026, 10, 26), date(2026, 11, 1), "本周"),
        ("本周完成情况", date(2026, 10, 26), date(2026, 11, 1), "本周"),
        ("上周的项目进展", date(2026, 10, 19), date(2026, 10, 25), "上周"),
        ("上上周做了什么", date(2026, 10, 12), date(2026, 10, 18), "上上周"),
        ("今天写了什么", date(2026, 11, 1), date(2026, 11, 1), "今天"),
        ("昨天开了什么会", date(2026, 10, 31), date(2026, 10, 31), "昨天"),
        ("前天", date(2026, 10, 30), date(2026, 10, 30), "前天"),
        ("明天要做什么", date(2026, 11, 2), date(2026, 11, 2), "明天"),
        ("本月总结", date(2026, 11, 1), date(2026, 11, 1), "本月"),
        ("上个月的记录", date(2026, 10, 1), date(2026, 10, 31), "上个月"),
        ("下个月计划", date(2026, 12, 1), date(2026, 12, 31), "下个月"),
        ("今年读过的书", date(2026, 1, 1), date(2026, 11, 1), "今年"),
        ("去年做了什么", date(2025, 1, 1), date(2025, 12, 31), "去年"),
        ("2025年3月的记录", date(2025, 3, 1), date(2025, 3, 31), "2025 年 3 月"),
        ("2026-10-29 的会议", date(2026, 10, 29), date(2026, 10, 29), "2026-10-29"),
        ("10月29日的笔记", date(2026, 10, 29), date(2026, 10, 29), "2026-10-29"),
    ],
)
def test_resolve_time_window(query, start, end, label):
    window = resolve_time_window(query, now=NOW)
    assert window is not None
    assert (window.start, window.end, window.label) == (start, end, label)


@pytest.mark.parametrize(
    ("query", "days", "label"),
    [
        ("最近7天做了什么", 7, "最近 7 天"),
        ("近两周的进展", 14, "最近 2 周"),
        ("过去三天", 3, "最近 3 天"),
        ("最近三个月", 90, "最近 3 个月"),
    ],
)
def test_resolve_recent_windows(query, days, label):
    window = resolve_time_window(query, now=NOW)
    assert window is not None
    assert window.label == label
    assert window.end == date(2026, 11, 1)
    assert window.start == date(2026, 11, 1) - timedelta(days=days - 1)


def test_unknown_time_words_return_none():
    assert resolve_time_window("Kiwi 的检索架构是什么", now=NOW) is None


def test_time_window_is_aware_and_covers_whole_end_day():
    window = TimeWindow(date(2026, 10, 26), date(2026, 11, 1), "本周")
    assert window.start_dt.utcoffset() == timedelta(hours=8)
    assert window.start_dt.hour == 0 and window.start_dt.minute == 0
    assert window.end_dt.hour == 23 and window.end_dt.minute == 59


def test_apply_time_window_intersects_with_scope_filters():
    filters = RetrievalFilters(
        updated_from=datetime(2026, 10, 28, tzinfo=TZ),
        updated_to=datetime(2026, 11, 3, tzinfo=TZ),
    )
    window = resolve_time_window("这周我干嘛了", now=NOW)
    assert apply_time_window(filters, window) is True
    assert filters.updated_from == datetime(2026, 10, 28, tzinfo=TZ)
    assert filters.updated_to == window.end_dt


def test_apply_time_window_detects_empty_intersection():
    filters = RetrievalFilters(updated_from=datetime(2026, 11, 2, tzinfo=TZ))
    window = resolve_time_window("这周我干嘛了", now=NOW)
    assert apply_time_window(filters, window) is False


def test_apply_time_window_treats_naive_as_app_timezone():
    filters = RetrievalFilters(updated_from=datetime(2026, 10, 1, 8, 0))
    window = resolve_time_window("这周我干嘛了", now=NOW)
    assert apply_time_window(filters, window) is True
    assert filters.updated_from == datetime(2026, 10, 26, tzinfo=TZ)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("20261020", date(2026, 10, 20)),
        ("2026-10-20", date(2026, 10, 20)),
        ("2026.10.20", date(2026, 10, 20)),
        ("2026年10月20日", date(2026, 10, 20)),
        ("2026-02-30", None),
        ("20261020-20261030", None),
        ("铁路", None),
    ],
)
def test_note_title_date(title, expected):
    assert note_title_date(title) == expected


def test_in_time_window_prefers_title_date_for_daily_notes():
    window = resolve_time_window("这周我干嘛了", now=NOW)
    # 10/20 的日记即使被待办同步刷新了 updated_at，也不应算进本周。
    assert in_time_window("20261020", window) is False
    assert in_time_window("20261030", window) is True
    # 没有日期标题的笔记继续依赖 updated_at 过滤。
    assert in_time_window("铁路", window) is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("这周我干嘛了", False),
        ("我上周做了什么", False),
        ("帮我查一下我的笔记里关于项目进度的记录", False),
        ("总结一下我的工作记录", False),
        ("今天北京天气怎么样", True),
        ("最新的 PostgreSQL 版本是多少", True),
        ("查一下 Kiwi 的官网", True),
        ("https://example.com 讲了什么", True),
        ("介绍一下 RAG 和向量检索", False),
        # 个人记录 + 强外部信号：允许联网。
        ("这周我干嘛了，顺便看看最新 AI 新闻", True),
    ],
)
def test_needs_web(query, expected):
    assert needs_web(query) is expected


def _messages(*turns: tuple[str, str]) -> list[dict]:
    return [{"role": role, "content": text} for role, text in turns]


def test_contextualize_query_resolves_short_follow_up():
    messages = _messages(
        ("user", "今天天气怎么样"),
        ("assistant", "北京今天晴，20 度。"),
        ("user", "北京"),
    )
    assert contextualize_query(messages) == "今天天气怎么样 北京"


def test_contextualize_query_walks_back_through_consecutive_follow_ups():
    messages = _messages(
        ("user", "今天天气怎么样"),
        ("assistant", "北京今天晴。"),
        ("user", "北京"),
        ("assistant", "多云。"),
        ("user", "那明天呢"),
    )
    assert contextualize_query(messages) == "今天天气怎么样 北京 明天"


def test_contextualize_query_keeps_complete_follow_up_question():
    messages = _messages(
        ("user", "今天天气怎么样"),
        ("assistant", "晴。"),
        ("user", "北京有什么景点"),
    )
    assert is_follow_up("北京有什么景点") is False
    assert contextualize_query(messages) == "北京有什么景点"


def test_contextualize_query_ignores_greeting_and_empty_history():
    assert contextualize_query([]) == ""
    assert is_follow_up("谢谢") is False
    assert contextualize_query(
        _messages(("user", "今天天气怎么样"), ("assistant", "晴。"), ("user", "谢谢"))
    ) == "谢谢"


def test_rules_plan_contextual_follow_up_uses_web_and_latest_message_window():
    messages = _messages(
        ("user", "今天天气怎么样"),
        ("assistant", "晴。"),
        ("user", "北京"),
    )
    query = contextualize_query(messages)
    plan = rules_plan(query, agent=True, web_allowed=True, now=NOW, current_query="北京")
    assert plan.wants_web is True
    assert plan.use_web is True
    assert "北京" in plan.web_queries[0] and "天气" in plan.web_queries[0]

    # 「那上周呢」应替换上一轮的时间范围，而不是继续沿用「本周」。
    weekly = _messages(
        ("user", "这周我干嘛了"),
        ("assistant", "本周完成了插件改造。"),
        ("user", "那上周呢"),
    )
    follow_up = contextualize_query(weekly)
    plan = rules_plan(
        follow_up, agent=True, web_allowed=True, now=NOW, current_query="那上周呢"
    )
    assert plan.time_window is not None
    assert plan.time_window.label == "上周"
    assert plan.personal is True


def test_refine_web_query_removes_chatty_prefix_and_adds_year():
    refined = refine_web_query("帮我查一下今天北京的天气怎么样？", now=NOW)
    assert "帮我查一下" not in refined
    assert "北京" in refined and "天气" in refined

    latest = refine_web_query("最新的 iPhone 价格", now=NOW)
    assert latest.endswith("2026")
    assert len(latest) <= 180


def test_rules_plan_for_personal_week_query():
    plan = rules_plan("这周我干嘛了", agent=False, web_allowed=True, now=NOW)
    assert plan.time_window is not None
    assert plan.personal is True
    assert plan.use_web is False
    assert plan.wants_web is False
    # 时间过滤之外补上通用的记录类查询，避免模糊问题检索不到内容。
    assert "本周记录" in plan.queries
    assert "完成事项 进展" in plan.queries


def test_rules_plan_external_query_without_web_permission():
    plan = rules_plan("最新的 iPhone 价格", agent=False, web_allowed=False, now=NOW)
    assert plan.wants_web is True
    assert plan.use_web is False
    assert plan.web_queries == []


def test_prompt_context_states_current_date_and_applied_window():
    plan = rules_plan("这周我干嘛了", agent=True, web_allowed=True, now=NOW)
    context = plan.prompt_context(now=NOW)
    assert "当前时间：2026-11-01 10:30" in context
    assert "星期" in context
    assert "2026-10-26 至 2026-11-01" in context
    assert "已按笔记日期过滤" in context
    assert "不要根据资料里的日期另行推断" in context


class _FakeCompletions:
    def __init__(self, content: str, *, delay: float = 0.0):
        self.content = content
        self.delay = delay
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def _fake_client(content: str, *, delay: float = 0.0):
    completions = _FakeCompletions(content, delay=delay)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


async def test_plan_with_llm_parses_json_and_reuses_rule_window():
    content = """```json
    {
      "time_range": {"from": "2026-10-01", "to": "2026-10-31"},
      "queries": ["本周工作记录", "完成事项"],
      "use_web": false,
      "web_queries": [],
      "reason": "个人记录，仅查知识库"
    }
    ```"""
    client, completions = _fake_client(content)
    plan = await plan_with_llm(
        "这周我干嘛了", client=client, model="test-model", web_allowed=True, now=NOW
    )
    assert plan.source == "llm"
    assert plan.queries == ["本周工作记录", "完成事项"]
    assert plan.use_web is False
    # 规则解析出的「本周」优先于模型给出的时间范围，避免模型算错周边界。
    assert (plan.time_window.start, plan.time_window.end) == (
        date(2026, 10, 26),
        date(2026, 11, 1),
    )
    assert completions.calls[0]["model"] == "test-model"
    assert completions.calls[0]["temperature"] == 0


async def test_plan_with_llm_respects_web_permission():
    content = (
        '{"queries": ["最新 AI 新闻"], "use_web": true, '
        '"web_queries": ["AI 最新进展 2026"], "reason": "需要最新信息"}'
    )
    client, _ = _fake_client(content)
    allowed = await plan_with_llm(
        "最新的 AI 进展", client=client, model="m", web_allowed=True, now=NOW
    )
    assert allowed.wants_web is True and allowed.use_web is True
    assert allowed.web_queries == ["AI 最新进展 2026"]

    client, _ = _fake_client(content)
    denied = await plan_with_llm(
        "最新的 AI 进展", client=client, model="m", web_allowed=False, now=NOW
    )
    assert denied.wants_web is True
    assert denied.use_web is False
    assert denied.web_queries == []


async def test_plan_with_llm_sees_history_and_forces_web_for_follow_up():
    content = (
        '{"queries": ["北京"], "use_web": false, "web_queries": [], '
        '"reason": "只查知识库"}'
    )
    client, completions = _fake_client(content)
    plan = await plan_with_llm(
        "今天天气怎么样 北京",
        client=client,
        model="m",
        web_allowed=True,
        now=NOW,
        current_query="北京",
        history=_messages(
            ("user", "今天天气怎么样"),
            ("assistant", "北京今天晴。"),
        ),
    )
    prompt = completions.calls[0]["messages"][1]["content"]
    assert "最近的对话" in prompt and "今天天气怎么样" in prompt
    assert "当前消息：北京" in prompt
    # 模型只返回片段时，用补全后的检索问题兜底。
    assert plan.queries[0] == "今天天气怎么样 北京"
    # 追问补全后已出现「天气」，即使模型漏判也必须联网。
    assert plan.wants_web is True and plan.use_web is True
    assert "北京" in plan.web_queries[0] and "天气" in plan.web_queries[0]


async def test_plan_with_llm_keeps_specific_model_query_for_follow_up():
    content = (
        '{"queries": ["北京今天天气"], "use_web": true, '
        '"web_queries": ["北京今天天气 2026"], "reason": "需要天气"}'
    )
    client, _ = _fake_client(content)
    plan = await plan_with_llm(
        "今天天气怎么样 北京",
        client=client,
        model="m",
        web_allowed=True,
        now=NOW,
        current_query="北京",
        history=_messages(("user", "今天天气怎么样"), ("assistant", "晴。")),
    )
    assert plan.queries == ["北京今天天气"]
    assert plan.web_queries[0] == "北京今天天气 2026"


async def test_plan_with_llm_falls_back_on_bad_json():
    client, _ = _fake_client("这不是 JSON")
    plan = await plan_with_llm(
        "这周我干嘛了", client=client, model="m", web_allowed=True, now=NOW
    )
    assert plan.source == "rules"
    assert isinstance(plan, AgentPlan)
    assert plan.time_window is not None


async def test_plan_with_llm_falls_back_on_timeout():
    client, _ = _fake_client("{}", delay=0.2)
    plan = await plan_with_llm(
        "这周我干嘛了",
        client=client,
        model="m",
        web_allowed=True,
        now=NOW,
        timeout=0.01,
    )
    assert plan.source == "rules"
    assert plan.time_window is not None
