"""在线链接抓取：httpx + trafilatura → Markdown，带 SSRF 防护与降级。

单用户本地场景：拒绝私网/回环/链路本地地址，每次重定向都重新校验；
抓取失败返回 fetch_status='failed'，由路由降级为书签卡片。
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 KiwiBookmark/1.0"
)
HTML_TYPES = ("text/html", "application/xhtml+xml")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# 198.18.0.0/15 为基准测试保留段，常被本地透明代理用作 fake-IP，不可路由到内网
_BENCHMARK_NET = ipaddress.ip_network("198.18.0.0/15")


class LinkFetchError(Exception):
    pass


class SSRFError(LinkFetchError):
    """目标地址属于本机/私网：不降级为书签，直接拒绝。"""


@dataclass
class LinkFetchResult:
    url: str
    final_url: str
    title: str
    markdown: str
    site: str
    excerpt: str
    favicon: str
    fetch_status: str  # ok / failed
    error: str | None = None


@dataclass
class LinkMetaResult:
    url: str
    final_url: str
    title: str
    site: str
    excerpt: str
    favicon: str
    fetch_status: str
    error: str | None = None


def normalize_url(raw: str) -> str:
    """补全 scheme 并做基础清洗；非法输入抛 LinkFetchError。"""
    url = (raw or "").strip()
    if not url:
        raise LinkFetchError("链接不能为空")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise LinkFetchError("仅支持 http/https 链接")
    if parsed.username or parsed.password:
        raise LinkFetchError("链接不能包含用户名或密码")
    if not parsed.hostname:
        raise LinkFetchError("链接缺少主机名")
    # 去掉 fragment，避免同一页面产生不同 URL
    return urlunparse(parsed._replace(fragment=""))


def _site_of(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


async def ensure_public_url(url: str) -> None:
    """拒绝私网 / 回环 / 链路本地等地址（含 DNS 解析结果）。"""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise LinkFetchError("链接缺少主机名")
    if host.lower() == "localhost":
        raise SSRFError("不允许访问本地地址")
    try:
        ip = ipaddress.ip_address(host)
        ips = [ip]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except socket.gaierror as e:
            raise LinkFetchError(f"无法解析域名：{host}") from e
        ips = []
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        if not ips:
            raise LinkFetchError(f"无法解析域名：{host}")
    for ip in ips:
        if ip.version == 4 and ip in _BENCHMARK_NET:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFError("不允许访问私网或本机地址")


async def _fetch_html(url: str) -> tuple[str, str]:
    """抓取 HTML，返回 (final_url, html)。每次重定向都做 SSRF 校验。"""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await ensure_public_url(current)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise LinkFetchError("重定向缺少目标地址")
                        current = urljoin(current, location)
                        parsed = urlparse(current)
                        if parsed.scheme not in ("http", "https"):
                            raise LinkFetchError("重定向到不支持的协议")
                        continue
                    if resp.status_code >= 400:
                        raise LinkFetchError(f"页面返回 {resp.status_code}")
                    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if ctype and ctype not in HTML_TYPES:
                        raise LinkFetchError(f"不是网页内容（{ctype}）")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise LinkFetchError("页面超过 5MB 限制")
                        chunks.append(chunk)
                    encoding = resp.encoding or "utf-8"
                    return current, b"".join(chunks).decode(encoding, errors="replace")
            except httpx.HTTPError as e:
                raise LinkFetchError(f"抓取失败：{e}") from e
    raise LinkFetchError("重定向次数过多")


def _extract(html: str, url: str) -> tuple[str, str, str, str]:
    """返回 (title, markdown, site, excerpt)。"""
    title = ""
    site = ""
    excerpt = ""
    markdown = ""
    try:
        import trafilatura
    except ImportError:  # pragma: no cover - 依赖缺失时仅保留书签
        trafilatura = None  # type: ignore[assignment]

    if trafilatura is not None:
        try:
            metadata = trafilatura.extract_metadata(html, default_url=url)
            if metadata is not None:
                title = (getattr(metadata, "title", None) or "").strip()
                site = (getattr(metadata, "sitename", None) or "").strip()
                excerpt = (getattr(metadata, "description", None) or "").strip()
            markdown = (
                trafilatura.extract(
                    html,
                    url=url,
                    output_format="markdown",
                    include_links=True,
                    include_formatting=True,
                    include_images=True,
                    include_tables=True,
                    favor_recall=True,
                )
                or ""
            ).strip()
        except Exception:  # noqa: BLE001 - 解析失败按降级处理
            markdown = ""

    if not title:
        match = TITLE_RE.search(html)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
    if not title:
        title = _site_of(url) or url
    if not site:
        site = _site_of(url)
    if not excerpt and markdown:
        plain = re.sub(r"[#*`>\-\[\]\(\)!]", " ", markdown)
        excerpt = re.sub(r"\s+", " ", plain).strip()[:200]
    return title[:300], markdown, site[:200], excerpt[:400]


async def fetch_meta(raw_url: str) -> LinkMetaResult:
    """只抓取标题 / 站点 / 摘要，用于编辑器里的链接卡片，不生成正文。"""
    url = normalize_url(raw_url)
    site = _site_of(url)
    host = urlparse(url).hostname or ""
    favicon = f"https://{host}/favicon.ico" if host else ""
    try:
        final_url, html = await _fetch_html(url)
        title = ""
        excerpt = ""
        try:
            import trafilatura

            metadata = trafilatura.extract_metadata(html, default_url=final_url)
            if metadata is not None:
                title = (getattr(metadata, "title", None) or "").strip()
                site = (getattr(metadata, "sitename", None) or "").strip() or site
                excerpt = (getattr(metadata, "description", None) or "").strip()
        except Exception:  # noqa: BLE001 - 元数据解析失败时回退到 title 标签
            pass
        if not title:
            match = TITLE_RE.search(html)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()
        return LinkMetaResult(
            url=url,
            final_url=final_url,
            title=(title or site or url)[:300],
            site=site[:200],
            excerpt=excerpt[:400],
            favicon=favicon,
            fetch_status="ok",
        )
    except SSRFError:
        raise
    except LinkFetchError as e:
        return LinkMetaResult(
            url=url,
            final_url=url,
            title=site or url,
            site=site,
            excerpt="",
            favicon=favicon,
            fetch_status="failed",
            error=str(e),
        )


async def fetch_and_extract(raw_url: str) -> LinkFetchResult:
    """抓取并解析链接；任何失败都返回降级结果而非抛错（URL 非法除外）。"""
    url = normalize_url(raw_url)
    site = _site_of(url)
    favicon = f"https://{urlparse(url).hostname}/favicon.ico" if urlparse(url).hostname else ""
    try:
        final_url, html = await _fetch_html(url)
        title, markdown, site, excerpt = _extract(html, final_url)
        if markdown:
            return LinkFetchResult(
                url=url,
                final_url=final_url,
                title=title or site or final_url,
                markdown=markdown,
                site=site,
                excerpt=excerpt,
                favicon=favicon,
                fetch_status="ok",
            )
        return LinkFetchResult(
            url=url,
            final_url=final_url,
            title=title or site or final_url,
            markdown="",
            site=site,
            excerpt=excerpt,
            favicon=favicon,
            fetch_status="failed",
            error="未能从页面提取正文",
        )
    except SSRFError:
        raise
    except LinkFetchError as e:
        return LinkFetchResult(
            url=url,
            final_url=url,
            title=site or url,
            markdown="",
            site=site,
            excerpt="",
            favicon=favicon,
            fetch_status="failed",
            error=str(e),
        )
