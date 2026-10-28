"""学习模式联网核查：可插拔搜索提供方（DuckDuckGo / SearXNG / Tavily）。

联网结果只作为题目的「参考来源」，不写入知识库、不触发编译。
未配置或查询失败时把题目标记为 unverified，并记录日志。
"""

from __future__ import annotations

import html
import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import settings
from app.db.models import StudyQuestion, WebResearchLog

logger = logging.getLogger(__name__)


def _strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


async def _duckduckgo(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            settings.study_search_base_url or "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) KiwiStudy/1.0"
                )
            },
        )
        resp.raise_for_status()
    text = resp.text
    title_re = re.compile(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S
    )
    snippet_re = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S
    )
    titles = title_re.findall(text)
    snippets = snippet_re.findall(text)
    results = []
    for i, (href, title_html) in enumerate(titles[:6]):
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        results.append(
            {
                "title": _strip_tags(title_html)[:200],
                "url": _ddg_url(href),
                "snippet": snippet[:400],
                "provider": "duckduckgo",
            }
        )
    return results


async def _searxng(query: str) -> list[dict]:
    base = (settings.study_search_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("未配置 SearXNG 地址（KIWI_STUDY_SEARCH_BASE_URL）。")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            f"{base}/search", params={"q": query, "format": "json"}
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {
            "title": str(r.get("title") or "")[:200],
            "url": str(r.get("url") or ""),
            "snippet": str(r.get("content") or "")[:400],
            "provider": "searxng",
        }
        for r in (data.get("results") or [])[:6]
        if r.get("url")
    ]


async def _tavily(query: str) -> list[dict]:
    if not settings.study_search_api_key:
        raise RuntimeError("未配置 Tavily API Key（KIWI_STUDY_SEARCH_API_KEY）。")
    url = settings.study_search_base_url or "https://api.tavily.com/search"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.post(
            url,
            json={
                "api_key": settings.study_search_api_key,
                "query": query,
                "max_results": 6,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {
            "title": str(r.get("title") or "")[:200],
            "url": str(r.get("url") or ""),
            "snippet": str(r.get("content") or "")[:400],
            "provider": "tavily",
        }
        for r in (data.get("results") or [])[:6]
        if r.get("url")
    ]


PROVIDERS = {
    "duckduckgo": _duckduckgo,
    "searxng": _searxng,
    "tavily": _tavily,
}

# 事实性内容特征：法规条款、标准编号、年份/日期、具体数值、版本号等。
_FACTUAL_RE = re.compile(
    r"(第[一二三四五六七八九十百千零\d]+条"
    r"|(?:GB|GBT|GB/T|ISO|IEC|IEEE|RFC|CMMI)\s*[/\s]?\s*\d"
    r"|\b\d{4}\s*年"
    r"|\d+(?:\.\d+)?\s*(?:%|％|年版|版本|号|万元|亿元|万|亿|天|个月|小时|分钟|人|次|项|分|秒)"
    r"|(?:法规|条例|办法|标准|规范|政策|准则|条款|国标))"
)


def provider_enabled() -> bool:
    # 桌面版默认离线：联网核查强制关闭，即使环境变量里配置了搜索服务。
    if settings.desktop_mode:
        return False
    return (settings.study_search_provider or "disabled").lower() in PROVIDERS


def needs_research(question_json: dict | None) -> bool:
    """题目是否涉及可核验的事实性内容（README 14.4.4）。"""
    qj = question_json or {}
    text = " ".join(
        str(qj.get(key) or "")
        for key in ("question", "material", "requirements", "reference_answer")
    )
    return bool(_FACTUAL_RE.search(text))


async def maybe_research_question(db, kb_id: uuid.UUID, q: StudyQuestion) -> None:
    """出题后按需自动联网核查；未配置搜索服务时静默跳过。

    只对事实性题目触发，避免每道概念题都产生外网请求。
    """
    if not provider_enabled():
        return
    if q.confidence_level == "verified" or q.web_sources_json:
        return
    if not needs_research(q.question_json):
        return
    await research_question(db, kb_id, q)


async def research_question(
    db, kb_id: uuid.UUID, q: StudyQuestion
) -> tuple[list[dict], str]:
    """对题目做一次联网核查，写日志并返回 (sources, outcome)。"""
    if settings.desktop_mode:
        return [], "disabled"
    provider = (settings.study_search_provider or "disabled").lower()
    query = (q.question_json or {}).get("question", "")[:240]
    if provider not in PROVIDERS:
        if provider != "disabled":
            logger.warning("未知联网核查提供方：%s", provider)
        db.add(
            WebResearchLog(
                question_id=q.id,
                kb_id=kb_id,
                query=query,
                provider=provider,
                sources_json=[],
                outcome="disabled",
                verified_at=datetime.now(timezone.utc),
            )
        )
        return [], "unavailable"

    sources: list[dict] = []
    outcome = "unavailable"
    try:
        sources = await PROVIDERS[provider](query)
        outcome = "ok" if sources else "empty"
    except Exception as e:  # 网络失败不阻断学习流程
        logger.warning("联网核查失败（%s）：%s", provider, e)
        outcome = "unavailable"

    db.add(
        WebResearchLog(
            question_id=q.id,
            kb_id=kb_id,
            query=query,
            provider=provider,
            sources_json=sources,
            outcome=outcome,
            verified_at=datetime.now(timezone.utc),
        )
    )
    if sources:
        q.web_sources_json = sources
        q.confidence_level = "verified"
    else:
        q.web_sources_json = []
        q.confidence_level = "unverified"
    await db.flush()
    return sources, outcome
