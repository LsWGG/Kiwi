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


def test_bing_parse_extracts_results_and_redirects():
    sample = """
    <li class="b_algo"><h2><a href="https://example.com/a">标题 <b>A</b></a></h2>
      <p>摘要 A &amp; B</p></li>
    <li class="b_algo"><h2><a href="/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9i">标题 B</a></h2>
      <div class="b_caption"><p>摘要 B</p></div></li>
    <li class="b_algo"><h2><a href="">无地址</a></h2></li>
    """
    results = web_research._parse_bing_html(sample)
    assert [item["url"] for item in results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert results[0]["title"] == "标题 A"
    assert results[0]["snippet"] == "摘要 A & B"
    assert results[1]["provider"] == "bing"


def test_deepseek_endpoint_handles_v1_suffix():
    assert (
        web_research._deepseek_endpoint("https://api.deepseek.com")
        == "https://api.deepseek.com/v1/tools/search"
    )
    assert (
        web_research._deepseek_endpoint("https://api.deepseek.com/v1")
        == "https://api.deepseek.com/v1/tools/search"
    )


async def test_search_web_uses_deepseek_llm_credentials(monkeypatch):
    calls: dict = {}

    async def fake_deepseek(query: str, *, api_key: str, base_url: str = "") -> list[dict]:
        calls.update(query=query, api_key=api_key, base_url=base_url)
        return [
            {
                "title": "DeepSeek 结果",
                "url": "https://example.com/ds",
                "snippet": "摘要",
                "content": "正文",
                "provider": "deepseek",
            }
        ]

    monkeypatch.setattr(web_research, "_deepseek", fake_deepseek)
    monkeypatch.setattr(settings, "study_search_provider", "disabled")
    results = await search_web(
        "  今天天气  ",
        llm_base_url="https://api.deepseek.com/v1",
        llm_api_key="test-key",
    )
    assert calls == {
        "query": "今天天气",
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com/v1",
    }
    assert results[0]["provider"] == "deepseek"


async def test_search_web_falls_back_to_bing_when_deepseek_fails(monkeypatch):
    async def fail_deepseek(*args, **kwargs) -> list[dict]:
        raise RuntimeError("402 余额不足")

    async def fake_bing(query: str) -> list[dict]:
        return [{"title": "Bing 结果", "url": "https://example.com/bing", "snippet": ""}]

    monkeypatch.setattr(web_research, "_deepseek", fail_deepseek)
    monkeypatch.setattr(web_research, "_bing", fake_bing)
    monkeypatch.setattr(settings, "study_search_provider", "disabled")
    results = await search_web(
        "问题", llm_base_url="https://api.deepseek.com", llm_api_key="test-key"
    )
    assert results[0]["url"] == "https://example.com/bing"


async def test_search_web_defaults_to_bing_for_non_deepseek_models(monkeypatch):
    async def fake_bing(query: str) -> list[dict]:
        return [{"title": "Bing", "url": "https://example.com/b", "snippet": ""}]

    monkeypatch.setattr(web_research, "_bing", fake_bing)
    monkeypatch.setattr(settings, "study_search_provider", "disabled")
    results = await search_web(
        "问题", llm_base_url="http://127.0.0.1:11434/v1", llm_api_key="local"
    )
    assert results[0]["url"] == "https://example.com/b"


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
