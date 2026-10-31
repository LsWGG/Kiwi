"""问答 Agent 规划：把自然语言问题解析成「时间窗口 + 检索查询 + 是否联网」。

设计目标（对应 261029 迭代遗留待办）：

- 「这周我干嘛了」这类问题应先解析出本周日期范围，再按笔记更新时间过滤，
  而不是把原句直接丢给向量检索或联网搜索；
- 联网只在问题确实需要外部 / 最新信息时触发，并且使用更具体的搜索词，
  不再无脑搜索用户原句；
- Agent 模式下由模型做一次轻量规划（选工具 + 生成查询），规则解析作为
  始终可用的兜底，模型超时 / 返回非法 JSON 时不会阻断问答。

规划结果只影响检索与联网，不改变最终回答的引用格式。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.retrieval import RetrievalFilters

logger = logging.getLogger("kiwi.agent")

# 与聊天路由共享的并列子问题拆分规则。保留在服务层，便于单测覆盖。
_AGENT_SPLIT_RE = re.compile(r"(?:以及|还有|和|与|、|,|，|;|；|\band\b)", re.IGNORECASE)


def split_queries(query: str, *, limit: int = 3) -> list[str]:
    """拆出 2–3 个并列子问题；拆不出来时只检索原问题。"""
    text = (query or "").strip()
    if not text or len(text) > 160:
        return [text]
    parts = [part.strip(" ？?。.!！") for part in _AGENT_SPLIT_RE.split(text)]
    if len(parts) <= 1:
        return [text]
    queries = [text]
    for part in parts:
        if len(part) >= 2 and part != text and part not in queries:
            queries.append(part)
        if len(queries) >= limit:
            break
    return queries


@lru_cache(maxsize=1)
def app_timezone() -> tzinfo:
    """应用时区：显式配置优先，配置不可用时回退到系统本地时区。"""
    name = (settings.timezone or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 —— 缺少 tzdata 时退回本地时区
            logger.warning("无法加载时区 %s，回退到系统本地时区", name)
    return datetime.now().astimezone().tzinfo or timezone.utc


def _local_now(now: datetime | None) -> datetime:
    value = now or datetime.now(app_timezone())
    if value.tzinfo is None:
        return value.replace(tzinfo=app_timezone())
    return value.astimezone(app_timezone())


@dataclass(slots=True)
class TimeWindow:
    """闭区间日期范围；转换为数据库比较用的带时区 datetime。"""

    start: date
    end: date
    label: str

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=app_timezone())

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time.max, tzinfo=app_timezone())

    def describe(self) -> str:
        return f"{self.start.isoformat()} ~ {self.end.isoformat()}"


_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_number(text: str) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        units = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + units
    if len(text) == 1 and text in _CN_DIGITS:
        return _CN_DIGITS[text]
    return None


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    if month == 12:
        return date(year, month, 1), date(year, 12, 31)
    return date(year, month, 1), date(year, month + 1, 1) - timedelta(days=1)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def resolve_time_window(query: str, *, now: datetime | None = None) -> TimeWindow | None:
    """解析中文相对时间，返回按笔记更新时间过滤的日期窗口。

    规则解析优先于模型：日期算术是确定性的，交给模型容易在「周从哪天开始」
    这类边界上出错。没有命中任何时间词时返回 ``None``。
    """
    text = (query or "").strip()
    if not text:
        return None
    today = _local_now(now).date()

    # 最近 N 天 / 周 / 个月 / 年：先于「这周」等词匹配，避免被短词抢占。
    recent = re.search(
        r"(?:最近|近|过去)\s*([0-9一二两三四五六七八九十]+)\s*(天|日|周|星期|礼拜|个月|月|年)",
        text,
    )
    if recent:
        count = _parse_number(recent.group(1))
        unit = recent.group(2)
        if count and count > 0:
            if unit in ("天", "日"):
                start = today - timedelta(days=count - 1)
                label = f"最近 {count} 天"
            elif unit in ("周", "星期", "礼拜"):
                start = today - timedelta(days=count * 7 - 1)
                label = f"最近 {count} 周"
            elif unit in ("个月", "月"):
                start = today - timedelta(days=count * 30 - 1)
                label = f"最近 {count} 个月"
            else:
                start = today - timedelta(days=count * 365 - 1)
                label = f"最近 {count} 年"
            return TimeWindow(start=start, end=today, label=label)

    # 上上周要写在「上周」之前，否则会被短词提前匹配。
    if re.search(r"上上(?:周|星期|礼拜)", text):
        monday = today - timedelta(days=today.weekday() + 14)
        return TimeWindow(
            start=monday,
            end=monday + timedelta(days=6),
            label="上上周",
        )
    if re.search(r"上个?(?:周|星期|礼拜)", text):
        monday = today - timedelta(days=today.weekday() + 7)
        return TimeWindow(
            start=monday,
            end=monday + timedelta(days=6),
            label="上周",
        )
    if re.search(r"(?:这|本|当前|这个|本个)(?:周|星期|礼拜)", text):
        monday = today - timedelta(days=today.weekday())
        return TimeWindow(start=monday, end=today, label="本周")
    if re.search(r"下个?(?:周|星期|礼拜)", text):
        monday = today + timedelta(days=7 - today.weekday())
        return TimeWindow(
            start=monday,
            end=monday + timedelta(days=6),
            label="下周",
        )

    if re.search(r"(?:今天|今日|本日|当天)", text):
        return TimeWindow(start=today, end=today, label="今天")
    if re.search(r"(?:昨天|昨日)", text):
        day = today - timedelta(days=1)
        return TimeWindow(start=day, end=day, label="昨天")
    if re.search(r"前天", text):
        day = today - timedelta(days=2)
        return TimeWindow(start=day, end=day, label="前天")
    if re.search(r"(?:明天|明日)", text):
        day = today + timedelta(days=1)
        return TimeWindow(start=day, end=day, label="明天")

    if re.search(r"(?:这个?月|本月|当月)", text):
        start, _ = _month_bounds(today.year, today.month)
        return TimeWindow(start=start, end=today, label="本月")
    if re.search(r"上个?月", text):
        year, month = _shift_month(today.year, today.month, -1)
        start, end = _month_bounds(year, month)
        return TimeWindow(start=start, end=end, label="上个月")
    if re.search(r"下个?月", text):
        year, month = _shift_month(today.year, today.month, 1)
        start, end = _month_bounds(year, month)
        return TimeWindow(start=start, end=end, label="下个月")

    if re.search(r"(?:今年|本年|当年)", text):
        return TimeWindow(
            start=date(today.year, 1, 1),
            end=today,
            label="今年",
        )
    if re.search(r"(?:去年|上一年|上年)", text):
        return TimeWindow(
            start=date(today.year - 1, 1, 1),
            end=date(today.year - 1, 12, 31),
            label="去年",
        )
    if re.search(r"明年", text):
        return TimeWindow(
            start=date(today.year + 1, 1, 1),
            end=date(today.year + 1, 12, 31),
            label="明年",
        )

    # 具体日期：2026-10-29 / 2026年10月29日 / 2026/10/29
    full_date = re.search(
        r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?", text
    )
    if full_date:
        try:
            day = date(
                int(full_date.group(1)),
                int(full_date.group(2)),
                int(full_date.group(3)),
            )
        except ValueError:
            day = None
        if day:
            return TimeWindow(start=day, end=day, label=day.isoformat())

    # 2025年3月：只到月份的年份 + 月份。
    year_month = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d)", text)
    if year_month:
        year = int(year_month.group(1))
        month = int(year_month.group(2))
        if 1 <= month <= 12:
            start, end = _month_bounds(year, month)
            return TimeWindow(start=start, end=end, label=f"{year} 年 {month} 月")

    # 10月29日 / 10-29：默认按今年解释。
    month_day = re.search(r"(?<!\d)(\d{1,2})\s*[月\-]\s*(\d{1,2})\s*日?", text)
    if month_day:
        try:
            day = date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError:
            day = None
        if day:
            return TimeWindow(start=day, end=day, label=day.isoformat())

    year_only = re.search(r"(\d{4})\s*年", text)
    if year_only:
        year = int(year_only.group(1))
        return TimeWindow(
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            label=f"{year} 年",
        )
    month_only = re.search(r"(?<!\d)(\d{1,2})\s*月", text)
    if month_only:
        month = int(month_only.group(1))
        if 1 <= month <= 12:
            start, end = _month_bounds(today.year, month)
            return TimeWindow(start=start, end=end, label=f"{month} 月")

    return None


# 强外部信息需求：命中时即使问题里带「我」也允许联网。
_STRONG_EXTERNAL_RE = re.compile(
    r"(最新|实时|新闻|天气|股价|汇率|比分|官网|维基|百科|"
    r"https?://|www\.|发布会|上市|政策|法规|标准|版本号)"
)
_EXTERNAL_RE = re.compile(
    r"(最新|实时|今天.{0,6}(?:新闻|天气|价格|汇率|股价|赛事|比分)|"
    r"新闻|天气|股价|汇率|比分|官网|维基|百科|"
    r"发布(?:会)?|上市|政策|法规|标准|版本|价格|多少钱|"
    r"https?://|www\.|查一下|查查|搜一下|搜索一下|帮我查|网上)"
)
# 个人记录类问题：默认不联网，只检索知识库。
_PERSONAL_RE = re.compile(
    r"(我的?(?:笔记|记录|文档|知识库|日记|周报|月报)|"
    r"我(?:这|那|上|本|最|今天|昨天|前天|本周|上周).{0,6}(?:干嘛|做了什么|干了|忙|记录|笔记)|"
    r"我.{0,4}(?:干嘛|做了什么|干了什么|干了些什么|忙了些什么|在忙什么)|"
    r"日记|周报|工作记录|待办|完成了什么)"
)


def looks_personal(query: str) -> bool:
    return bool(_PERSONAL_RE.search(query or ""))


# 追问 / 省略式回复：只靠当前几个字无法独立检索，需要补上上一轮主题。
_FOLLOWUP_PREFIX_RE = re.compile(
    r"^\s*(?:那|那么|还有|还有呢|再|另外|然后|接着|继续|换成|改成|改为|"
    r"它|他|她|这个|那个|这些|那些)"
)
_GREETING_RE = re.compile(
    r"^\s*(?:你好|您好|谢谢|多谢|好的|好|嗯|ok|okay|收到|再见|晚安|"
    r"早上好|晚上好)\s*[！!。.,，]?\s*$",
    re.IGNORECASE,
)


def _clean_followup_text(text: str) -> str:
    """去掉「那 / 还有 / 呢」等追问外壳，保留真正的补充信息。"""
    raw = (text or "").strip()
    cleaned = _FOLLOWUP_PREFIX_RE.sub("", raw)
    cleaned = re.sub(r"(?:呢|吗|啊|呀|吧)\s*[？?]?\s*$", "", cleaned).strip()
    return cleaned or raw


def is_follow_up(text: str) -> bool:
    """判断一条用户消息是否依赖上一轮上下文。

    只有非常短、带追问连接词或以「呢 / 吗」收尾的消息才视为追问；
    「北京有什么景点」这类完整问题仍然独立检索，避免被上一轮主题污染。
    """
    raw = (text or "").strip()
    if not raw or _GREETING_RE.match(raw):
        return False
    if _FOLLOWUP_PREFIX_RE.match(raw):
        return True
    compact = re.sub(r"\s+", "", raw)
    if len(compact) <= 3:
        return True
    if compact.endswith(("呢", "吗")) and len(compact) <= 20:
        return True
    return False


def contextualize_query(messages: list[dict]) -> str:
    """把多轮对话里的追问补全成可独立检索的问题。

    「今天天气怎么样」→「北京」应变成「今天天气怎么样 北京」，而不是只拿
    「北京」去检索知识库。连续追问会继续向前回溯，最多合并三条用户消息；
    完整问题或寒暄则保持原样。
    """
    user_texts: list[str] = []
    for message in messages or []:
        if message.get("role") != "user":
            continue
        text = str(message.get("content") or "").strip()
        if text:
            user_texts.append(text)
    if not user_texts:
        return ""
    current = user_texts[-1]
    if not is_follow_up(current):
        return current

    parts = [_clean_followup_text(current)]
    for previous in reversed(user_texts[:-1]):
        if _GREETING_RE.match(previous):
            continue
        if previous not in parts:
            parts.append(previous)
        if not is_follow_up(previous) or len(parts) >= 3:
            break
    return " ".join(reversed(parts)).strip()


_DATE_TITLE_RE = re.compile(
    r"^\s*(20\d{2})\s*(?:[-_.年]\s*(\d{1,2})\s*[-_.月]\s*(\d{1,2})\s*日?|"
    r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?)\s*$"
)


def note_title_date(title: str) -> date | None:
    """从「20261020 / 2026-10-20 / 2026年10月20日」这类日记标题提取日期。"""
    text = (title or "").strip()
    compact = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})", text)
    if compact:
        try:
            return date(
                int(compact.group(1)),
                int(compact.group(2)),
                int(compact.group(3)),
            )
        except ValueError:
            return None
    match = _DATE_TITLE_RE.match(text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or match.group(4))
    day = int(match.group(3) or match.group(5))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def in_time_window(title: str, window: TimeWindow | None) -> bool:
    """带日期的日记按标题日期判断，避免待办同步刷新 updated_at 后混入其它周。"""
    if window is None:
        return True
    day = note_title_date(title)
    return day is None or window.start <= day <= window.end


def needs_web(query: str) -> bool:
    """规则判断问题是否需要外部 / 最新信息。

    个人记录类问题除非同时出现「最新 / 天气 / 新闻」等强外部信号，否则不联网。
    """
    text = (query or "").strip()
    if not text:
        return False
    strong = bool(_STRONG_EXTERNAL_RE.search(text))
    if looks_personal(text):
        return strong
    return strong or bool(_EXTERNAL_RE.search(text))


def refine_web_query(query: str, *, now: datetime | None = None) -> str:
    """把用户原句收敛成更具体的搜索词，去掉口语化外壳。"""
    text = (query or "").strip()
    if not text:
        return ""
    cleaned = re.sub(
        r"(请|麻烦)?(帮我|帮忙|给我)?(查一下|查查|搜一下|搜索一下|搜搜|看一下|告诉我|我想知道|想知道)",
        " ",
        text,
    )
    cleaned = re.sub(r"[？?！!。；;，,]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 2:
        cleaned = text
    cleaned = cleaned[:180]
    if re.search(r"(最新|今年|当前|现在)", cleaned) and not re.search(r"20\d{2}", cleaned):
        cleaned = f"{cleaned} {_local_now(now).year}"
    return cleaned


@dataclass(slots=True)
class AgentPlan:
    """一次问答的检索计划。"""

    queries: list[str] = field(default_factory=list)
    time_window: TimeWindow | None = None
    # wants_web 是「是否需要联网」的判断；use_web 还要求用户开关已开启。
    wants_web: bool = False
    use_web: bool = False
    web_queries: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "rules"
    personal: bool = False

    def describe(self) -> str:
        parts: list[str] = []
        if self.time_window:
            parts.append(f"时间 {self.time_window.describe()}")
        parts.append(f"知识库查询 {len(self.queries)} 条")
        if self.use_web:
            parts.append(f"联网 {len(self.web_queries)} 条")
        elif self.wants_web:
            parts.append("需要联网但开关未开启")
        else:
            parts.append("不联网")
        return " · ".join(parts)

    def prompt_context(self, *, now: datetime | None = None) -> str:
        """给生成模型的事实上下文：当前日期与已应用的检索范围。

        缺少这段信息时，模型会拿资料里的最新日期反推「今天 / 这周」，
        从而把用户问题误解成另一个时间段。
        """
        current = _local_now(now)
        weekday = "一二三四五六日"[current.weekday()]
        lines = [
            f"当前时间：{current.strftime('%Y-%m-%d %H:%M')}"
            f"（星期{weekday}，{settings.timezone or '本地时区'}）。"
        ]
        if self.time_window:
            lines.append(
                f"本次资料检索的时间范围：{self.time_window.start.isoformat()} 至 "
                f"{self.time_window.end.isoformat()}（{self.time_window.label}），"
                "已按笔记日期过滤。回答时请以该范围为准，不要根据资料里的日期另行推断。"
            )
        if self.use_web:
            lines.append("本次已按需联网检索，可结合网页资料回答。")
        elif self.wants_web:
            lines.append("该问题可能需要外部信息，但本次未开启联网，只能基于知识库回答。")
        return "\n".join(lines)


def rules_plan(
    query: str,
    *,
    agent: bool,
    web_allowed: bool,
    now: datetime | None = None,
    current_query: str | None = None,
) -> AgentPlan:
    """无模型时的确定性规划，也是模型规划失败后的兜底。

    ``query`` 是补全上下文后的检索问题，``current_query`` 是用户这一轮的原话。
    追问里的时间词（如「那上周呢」）优先于上一轮的时间词，避免沿用错范围。
    """
    current = (current_query or "").strip() or query
    window = resolve_time_window(current, now=now) or resolve_time_window(query, now=now)
    personal = looks_personal(query)
    queries = split_queries(query) if agent else [query.strip()]
    if window and personal:
        # 个人记录类问题往往缺少可用检索词；补两个通用查询，
        # 时间过滤已经把候选压到窗口内，不会带出无关笔记。
        for extra in (f"{window.label}记录", "完成事项 进展"):
            if extra not in queries:
                queries.append(extra)
        queries = queries[:3]
    wants_web = needs_web(query)
    use_web = bool(web_allowed and wants_web)
    web_queries = [refine_web_query(query, now=now)] if wants_web else []
    if web_queries and not web_queries[0]:
        web_queries = []
        use_web = False
    reason = "命中外部信息需求" if wants_web else "优先检索知识库"
    return AgentPlan(
        queries=queries,
        time_window=window,
        wants_web=wants_web,
        use_web=use_web,
        web_queries=web_queries if use_web else [],
        reason=reason,
        source="rules",
        personal=personal,
    )


_PLANNER_SYSTEM = """你是 Kiwi 个人知识库问答的检索规划器。你只输出 JSON，不回答用户问题。

可用工具：
1. kb_search：在用户的知识库（Wiki + 笔记）中检索。支持按笔记更新时间过滤日期范围。
2. web_search：联网搜索。仅当问题需要知识库之外的「最新 / 外部 / 公共」信息时使用。
   不要用它搜索用户的个人记录、日记、待办或工作进展。

输出 JSON：
{
  "time_range": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} 或 null,
  "queries": ["用于知识库检索的 1-3 个查询"],
  "use_web": true/false,
  "web_queries": ["最多 2 个具体、可搜索的联网查询"],
  "reason": "一句话说明检索策略"
}

规则：
- 问题里出现「今天 / 这周 / 上周 / 最近 N 天 / 上个月 / 去年」等相对时间时，
  time_range 必须给出对应的日期闭区间；问「我做了什么」时应结合时间范围理解。
- 「我 / 我的笔记 / 日记 / 记录 / 待办 / 这周我干嘛了」属于个人记录，use_web 必须为 false。
- 只有问题需要最新事实、公共资料或用户明确要求查资料时才 use_web=true；
  web_queries 要具体（包含主体、时间、限定词），不要照抄用户原句。
- queries 用于向量检索，应补齐问题隐含的主题词（如「这周我干嘛了」→「本周工作记录」「完成事项 进展」）。
- 当前消息可能是对上一轮的追问（如只回复「北京」「那上周呢」）。必须结合
  「最近的对话」补全主题；queries 与 web_queries 都要带上补全后的完整问题，
  不能只检索当前几个字。
"""


def _history_excerpt(history: list[dict] | None, *, limit: int = 6, max_chars: int = 500) -> str:
    """压缩最近几轮对话，供规划器理解指代和省略。"""
    lines: list[str] = []
    for message in (history or [])[-limit:]:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if not content:
            continue
        if len(content) > max_chars:
            content = content[:max_chars] + "…"
        lines.append(f"{'用户' if role == 'user' else 'Kiwi'}：{content}")
    if not lines:
        return ""
    return "最近的对话（用于理解指代与省略）：\n" + "\n".join(lines)


def _planner_user_prompt(
    query: str,
    now: datetime,
    *,
    current_query: str | None = None,
    history: list[dict] | None = None,
) -> str:
    weekday = "一二三四五六日"[now.weekday()]
    lines = [
        f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（星期{weekday}），"
        f"时区 {settings.timezone or '本地'}。"
    ]
    excerpt = _history_excerpt(history)
    if excerpt:
        lines.append(excerpt)
    current = (current_query or "").strip()
    if current and current != (query or "").strip():
        lines.append(f"当前消息：{current}")
        lines.append(f"结合上下文补全后的问题：{query}")
    else:
        lines.append(f"用户问题：{query}")
    lines.append("请只输出 JSON。")
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _plan_from_payload(
    payload: dict[str, Any] | None,
    query: str,
    *,
    rule_window: TimeWindow | None,
    web_allowed: bool,
    now: datetime,
    current_query: str | None = None,
) -> AgentPlan | None:
    """校验模型返回的 JSON；非法时返回 None 交给规则兜底。"""
    if not payload:
        return None
    resolved = (query or "").strip()
    current = (current_query or "").strip()
    # 当前消息是追问、检索问题是补全后的完整问题时，模型可能仍只返回
    # 「北京」这种片段；用规则结果兜底，确保检索带上上一轮主题。
    follow_up = bool(current and resolved and current != resolved)

    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list):
        raw_queries = []
    queries = [
        str(item).strip()[:160]
        for item in raw_queries
        if isinstance(item, str) and str(item).strip()
    ]
    queries = list(dict.fromkeys(queries))[:3] or [resolved]
    if follow_up:
        longest = max((len(item) for item in queries), default=0)
        if resolved not in queries and longest <= len(current) + 1:
            queries = list(dict.fromkeys([resolved, *queries]))[:3]

    window = rule_window
    if window is None:
        raw_range = payload.get("time_range")
        if isinstance(raw_range, dict):
            try:
                start = date.fromisoformat(str(raw_range.get("from") or "")[:10])
                end = date.fromisoformat(str(raw_range.get("to") or "")[:10])
            except ValueError:
                start = end = None
            if start and end:
                if start > end:
                    start, end = end, start
                window = TimeWindow(start=start, end=end, label="模型解析的时间范围")

    raw_web_queries = payload.get("web_queries")
    if not isinstance(raw_web_queries, list):
        raw_web_queries = []
    web_queries = [
        str(item).strip()[:200]
        for item in raw_web_queries
        if isinstance(item, str) and str(item).strip()
    ]
    web_queries = list(dict.fromkeys(web_queries))[:2]

    wants_web = bool(payload.get("use_web"))
    forced_web = False
    if follow_up and needs_web(resolved):
        # 追问补全后已出现「天气 / 最新」等外部信息需求，模型仍按当前
        # 几个字判断为不需要联网时，以规则结果为准。
        forced_web = not wants_web
        wants_web = True
        context_web = refine_web_query(resolved, now=now)
        longest_web = max((len(item) for item in web_queries), default=0)
        if context_web and context_web not in web_queries and longest_web <= len(current) + 1:
            web_queries = [item for item in web_queries if item != current]
            web_queries = list(dict.fromkeys([context_web, *web_queries]))[:2]

    use_web = wants_web and web_allowed
    if use_web and not web_queries:
        web_queries = [refine_web_query(resolved, now=now)]
    if not web_queries:
        use_web = False
    reason = str(payload.get("reason") or "").strip()[:200]
    if forced_web:
        reason = "追问补全主题后需要联网补充信息"
    return AgentPlan(
        queries=queries,
        time_window=window,
        wants_web=wants_web,
        use_web=use_web,
        web_queries=web_queries if use_web else [],
        reason=reason or ("需要联网补充信息" if wants_web else "问题可仅用知识库回答"),
        source="llm",
        personal=looks_personal(resolved),
    )


async def plan_with_llm(
    query: str,
    *,
    client: Any,
    model: str,
    web_allowed: bool,
    now: datetime | None = None,
    timeout: float | None = None,
    current_query: str | None = None,
    history: list[dict] | None = None,
) -> AgentPlan:
    """调用一次模型做检索规划；任何失败都回退到规则规划。

    ``history`` 是当前消息之前的对话，用来让规划器理解「北京」「那上周呢」
    这类省略式追问；``current_query`` 是用户这一轮的原话。
    """
    fallback = rules_plan(
        query,
        agent=True,
        web_allowed=web_allowed,
        now=now,
        current_query=current_query,
    )
    local_now = _local_now(now)
    rule_window = fallback.time_window
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _PLANNER_SYSTEM},
                    {
                        "role": "user",
                        "content": _planner_user_prompt(
                            query,
                            local_now,
                            current_query=current_query,
                            history=history,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=500,
            ),
            timeout=timeout or settings.agent_planner_timeout,
        )
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""
        plan = _plan_from_payload(
            _extract_json(content),
            query,
            rule_window=rule_window,
            web_allowed=web_allowed,
            now=local_now,
            current_query=current_query,
        )
        if plan is None:
            logger.warning("Agent 规划返回无法解析，回退规则规划")
            return fallback
        return plan
    except asyncio.TimeoutError:
        logger.warning("Agent 规划超时（%.1fs），回退规则规划", timeout or settings.agent_planner_timeout)
        return fallback
    except Exception:  # noqa: BLE001 —— 规划失败不能阻断问答
        logger.warning("Agent 规划调用失败，回退规则规划", exc_info=True)
        return fallback


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=app_timezone())
    return value.astimezone(app_timezone())


def apply_time_window(filters: RetrievalFilters, window: TimeWindow | None) -> bool:
    """把问题里的时间窗口叠加到检索筛选（与页面筛选取交集）。

    返回 False 表示两者没有交集；此时调用方应提示用户，检索会自然返回空。
    """
    if window is None:
        return True
    start = _aware(filters.updated_from)
    end = _aware(filters.updated_to)
    start = max(start, window.start_dt) if start else window.start_dt
    end = min(end, window.end_dt) if end else window.end_dt
    filters.updated_from = start
    filters.updated_to = end
    return start <= end
