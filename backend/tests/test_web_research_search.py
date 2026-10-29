"""问答联网检索与 Agent 子问题拆分。"""

from __future__ import annotations

import pytest

from app.config import settings
from app.routers.chat import _agent_queries
from app.services import web_research
from app.services.web_research import search_web


async def test_search_web_dedupes_and_limits(monkeypatch):
    calls: list[str] = []

    async def fake_provider(query: str) -> list[dict]:
        calls.append(query)
        return [
            {"title": "一", "url": "https://example.com/a", "snippet": ""},
            {"title": "重复", "url": "https://example.com/a", "snippet": ""},
            {"title": "无地址", "url": "", "snippet": ""},
            {"title": "二", "url": "https://example.com/b", "snippet": ""},
            {"title": "三", "url": "https://example.com/c", "snippet": ""},
        ]

    monkeypatch.setitem(web_research.PROVIDERS, "fake", fake_provider)
    monkeypatch.setattr(settings, "study_search_provider", "fake")
    results = await search_web("  测试问题  ", limit=2)
    assert calls == ["测试问题"]
    assert [item["url"] for item in results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


async def test_search_web_empty_query_skips_provider(monkeypatch):
    async def fail_provider(query: str) -> list[dict]:
        raise AssertionError("空查询不应调用检索服务")

    monkeypatch.setitem(web_research.PROVIDERS, "fake", fail_provider)
    monkeypatch.setattr(settings, "study_search_provider", "fake")
    assert await search_web("   ") == []


async def test_search_web_rejects_desktop_mode(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    with pytest.raises(RuntimeError):
        await search_web("离线不应联网")


def test_agent_queries_keep_original_and_split_compounds():
    query = "总结 A 与 B，以及 C 的区别"
    queries = _agent_queries(query)
    assert queries[0] == query
    # 单字片段（「B」）不单独检索，避免把关键词拆碎。
    assert queries == [query, "总结 A", "C 的区别"]


def test_agent_queries_leave_single_question_untouched():
    assert _agent_queries("什么是向量检索？") == ["什么是向量检索？"]


def test_agent_queries_skip_overlong_question():
    query = "很长的句子" * 40
    assert _agent_queries(query) == [query]
