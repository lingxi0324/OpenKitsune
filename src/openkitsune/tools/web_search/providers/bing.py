"""Bing provider — 国内可达的无 Key 兜底源.

实测（2026-10-10）：jina / duckduckgo 在当前网络环境超时不可达，
而 bing.com 0.8s 可达（百度 0.2s 可达但无公开搜索 HTML 端点协议保证）。
本 provider 抓取 Bing 网页搜索结果（无凭据），解析 b_algo 结果块，
作为 auto-detect 链上的国内可用兜底。
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ..base import NetworkUnreachableError, SearchResult
from ..registry import register

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _fetch_html(query: str, max_results: int, timeout_seconds: float) -> str:
    """抓取 Bing 搜索页 HTML。"""
    params = urllib.parse.urlencode({"q": query, "count": max_results, "setlang": "zh-hans"})
    url = f"https://www.bing.com/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else 15
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _AlgoParser(HTMLParser):
    """解析 <li class="b_algo"> 结果块：标题链接 + 摘要。"""

    def __init__(self) -> None:
        super().__init__()
        self._in_algo = 0
        self._in_h2 = False
        self._in_anchor = False
        self._in_p = False
        self._cur_url = ""
        self._cur_title_parts: list[str] = []
        self._cur_snippet_parts: list[str] = []
        self.results: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs = dict(attrs)
        if tag == "li" and "b_algo" in attrs.get("class", ""):
            self._in_algo += 1
            self._flush_current()
        elif self._in_algo:
            if tag == "h2":
                self._in_h2 = True
            elif tag == "a" and self._in_h2:
                self._in_anchor = True
                self._cur_url = attrs.get("href", "")
            elif tag == "p":
                self._in_p = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._in_algo:
            self._in_algo -= 1
            self._flush_current()
        elif self._in_algo:
            if tag == "h2":
                self._in_h2 = False
                self._in_anchor = False
            elif tag == "p":
                self._in_p = False

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._cur_title_parts.append(data)
        elif self._in_p:
            self._cur_snippet_parts.append(data)

    def _flush_current(self) -> None:
        title = html_mod.unescape("".join(self._cur_title_parts)).strip()
        snippet = html_mod.unescape("".join(self._cur_snippet_parts)).strip()
        url = self._cur_url.strip()
        if title or url:
            self.results.append({"title": title, "url": url, "snippet": snippet})
        self._cur_url = ""
        self._cur_title_parts = []
        self._cur_snippet_parts = []


def _parse_results(page: str) -> list[dict]:
    parser = _AlgoParser()
    parser.feed(page)
    out = []
    for r in parser.results:
        # 去掉 bing 跳转前缀，保留真实目标 URL
        url = r["url"]
        m = re.search(r"https?://[^&\"]+", url)
        if m:
            url = m.group(0)
        out.append({"title": r["title"], "url": url, "snippet": r["snippet"]})
    return out


def _sync_search(query: str, max_results: int, timeout_seconds: float) -> list[dict]:
    page = _fetch_html(query, max_results, timeout_seconds)
    return _parse_results(page)


class BingProvider:
    id = "bing"
    label = "Bing（国内可达，无需 Key）"
    requires_credential = False
    auto_detect_order = 40  # 高于 jina/ddg，低于需 key 的 bocha/tavily 语义优先级
    signup_url = ""
    docs_url = "https://www.bing.com/"

    def is_available(self) -> bool:
        # 无凭据即可用；真实可达性由 search 运行时决定（失败抛 NetworkUnreachableError）
        return True

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timeout_seconds: float = 0.0,
    ) -> list[SearchResult]:
        try:
            raw = await asyncio.to_thread(
                _sync_search, query, max_results, timeout_seconds
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise NetworkUnreachableError(
                f"Bing request failed: {type(exc).__name__}: {exc}",
                provider_id=self.id,
            ) from exc
        return [
            SearchResult(
                title=r["title"] or "无标题",
                url=r["url"],
                snippet=r["snippet"],
                source="bing",
                date="",
            )
            for r in raw
        ]

    async def news_search(
        self,
        query: str,
        *,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: str | None = None,
        timeout_seconds: float = 0.0,
    ) -> list[SearchResult] | None:
        # Bing 网页端点不单独提供结构化 news；返回 None 表示无此能力，
        # runtime 会明确提示改用 web_search。
        return None


register(BingProvider())
