"""学习模式联网核查：可插拔搜索提供方（Bing / DuckDuckGo / SearXNG / Tavily）。

联网结果只作为题目的「参考来源」，不写入知识库、不触发编译。
未配置或查询失败时把题目标记为 unverified，并记录日志。
"""

from __future__ import annotations

import base64
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


def _bing_url(href: str) -> str:
    """还原 Bing 的 /ck/a 跳转链接；普通链接原样返回。"""
    href = html.unescape(href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://www.bing.com" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target.startswith("a1"):
            raw = target[2:] + "=" * (-len(target[2:]) % 4)
            try:
                return base64.urlsafe_b64decode(raw).decode("utf-8", "ignore")
            except (ValueError, UnicodeDecodeError):
                return href
    return href


def _parse_bing_html(text: str) -> list[dict]:
    blocks = re.findall(r'<li[^>]+class="b_algo"[^>]*>.*?</li>', text, re.S)
    results: list[dict] = []
    for block in blocks[:8]:
        link = re.search(
            r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S
        )
        if not link:
            continue
        href = _bing_url(link.group(1))
        title = _strip_tags(link.group(2))[:200]
        if not href or not title:
            continue
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        results.append(
            {
                "title": title,
                "url": href,
                "snippet": (
                    _strip_tags(snippet_match.group(1))[:400]
                    if snippet_match
                    else ""
                ),
                "provider": "bing",
            }
        )
        if len(results) >= 6:
            break
    return results


async def _bing(query: str) -> list[dict]:
    """抓取 Bing 结果页；默认使用可直连的 www.bing.com（国内会跳转 cn.bing.com）。"""
    url = settings.study_search_base_url or "https://www.bing.com/search"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(
            url,
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        resp.raise_for_status()
    return _parse_bing_html(resp.text)


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


def _is_deepseek_base(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def _deepseek_endpoint(base_url: str) -> str:
    base = (base_url or "https://api.deepseek.com").rstrip("/")
    return base + ("/tools/search" if base.endswith("/v1") else "/v1/tools/search")


async def _deepseek(
    query: str, *, api_key: str, base_url: str = ""
) -> list[dict]:
    """DeepSeek 官方 Search 接口：返回结构化网页结果，无需另外抓取 HTML。"""
    if not api_key:
        raise RuntimeError("未配置 DeepSeek API Key，无法使用网页搜索。")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            _deepseek_endpoint(base_url),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "count": 6, "need_content": False},
        )
        resp.raise_for_status()
        data = resp.json()
    results: list[dict] = []
    for item in (data.get("results") or [])[:6]:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or "")[:200],
                "url": url,
                "snippet": str(item.get("snippet") or "")[:400],
                # summary 约 600–800 字，适合作为模型上下文；citation 仍用短摘要。
                "content": str(item.get("summary") or item.get("content") or "")[:1200],
                "provider": "deepseek",
            }
        )
    return results


async def _deepseek_settings(query: str) -> list[dict]:
    return await _deepseek(
        query,
        api_key=settings.study_search_api_key,
        base_url=settings.study_search_base_url,
    )


PROVIDERS = {
    "bing": _bing,
    "duckduckgo": _duckduckgo,
    "searxng": _searxng,
    "tavily": _tavily,
    "deepseek": _deepseek_settings,
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


async def search_web(
    query: str,
    limit: int = 5,
    *,
    llm_base_url: str = "",
    llm_api_key: str = "",
) -> list[dict]:
    """问答里的显式联网检索。

    与学习核查不同，这里是用户主动打开「联网」开关触发的，因此即使没有
    配置搜索服务也要尽量给出结果：

    1. 显式配置 ``KIWI_STUDY_SEARCH_PROVIDER`` 时使用该提供方；
    2. 当前对话模型是 DeepSeek 时复用模型 Key 调用官方 Search 接口；
    3. 否则抓取 Bing 结果页（国内可直连），失败再回退 DuckDuckGo。

    桌面版仍然拒绝。返回按 URL 去重后的 ``{title,url,snippet,provider}``，
    调用方负责包成引用与上下文。
    """
    if settings.desktop_mode:
        raise RuntimeError("桌面版已禁用联网检索")
    text = (query or "").strip()[:240]
    if not text:
        return []
    provider = (settings.study_search_provider or "disabled").lower()
    if provider in PROVIDERS:
        results = await PROVIDERS[provider](text)
    elif _is_deepseek_base(llm_base_url) and llm_api_key:
        try:
            results = await _deepseek(
                text, api_key=llm_api_key, base_url=llm_base_url
            )
        except Exception as exc:  # 接口不可用/余额不足时仍尝试免密搜索
            logger.warning("DeepSeek 搜索失败，回退 Bing：%s", exc)
            results = await _bing(text)
    else:
        try:
            results = await _bing(text)
        except Exception as exc:  # Bing 不可达时回退 DuckDuckGo
            logger.warning("Bing 搜索失败，回退 DuckDuckGo：%s", exc)
            results = await _duckduckgo(text)
    out: list[dict] = []
    seen: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({**item, "url": url})
        if len(out) >= limit:
            break
    return out


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
