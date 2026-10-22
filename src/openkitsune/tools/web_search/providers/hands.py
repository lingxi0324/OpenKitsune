"""openkitsune-hands provider —— 本机九尾网络爪牙.

API: ``POST {base_url}/api/search/web``
- 请求/响应均为 camelCase；
- 服务默认监听 ``http://127.0.0.1:8320``（可用 ``OPENKITSUNE_HANDS_URL`` 覆盖）；
- 内部自带 SearXNG / Bing / Baidu / DuckDuckGo 故障转移链。

Auto-detect priority: 5。本机服务无凭据、延迟低，可用时优先；
不可用时由运行时自动回退到其它搜索源。
"""

from __future__ import annotations

from typing import Any

from ..base import (
    AuthFailedError,
    MissingCredentialError,
    NetworkUnreachableError,
    RateLimitedError,
    SearchResult,
)
from ..hands_stack import resolve_hands_url, service_reachable
from ..registry import register
from ._http import describe_httpx_failure, search_httpx_client_kwargs

_SAFESEARCH_TO_INT = {"off": 0, "moderate": 1, "strict": 2}


class HandsProvider:
    id = "hands"
    label = "openkitsune-hands (本机九尾)"
    requires_credential = False
    auto_detect_order = 5
    signup_url = ""
    docs_url = ""

    def is_available(self) -> bool:
        return service_reachable(resolve_hands_url())

    def _endpoint(self) -> str:
        return f"{resolve_hands_url()}/api/search/web"

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timeout_seconds: float = 0.0,
    ) -> list[SearchResult]:
        if not self.is_available():
            raise MissingCredentialError(
                f"openkitsune-hands service is not reachable at {resolve_hands_url()}",
                provider_id=self.id,
            )

        payload: dict[str, Any] = {
            "query": query,
            "maxResults": max_results,
            "safeSearch": _SAFESEARCH_TO_INT.get(safesearch, 1),
        }
        language = _region_to_language(region)
        if language:
            payload["language"] = language

        timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else 30.0
        endpoint = self._endpoint()

        import httpx

        try:
            async with httpx.AsyncClient(
                **search_httpx_client_kwargs(timeout=timeout, target_url=endpoint)
            ) as client:
                # 服务端强制要求隔离上下文（header / project_id / API Key 三选一）。
                resp = await client.post(
                    endpoint,
                    json=payload,
                    headers={"X-Project-ID": "openkitsune"},
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise NetworkUnreachableError(
                f"openkitsune-hands transport failure: {describe_httpx_failure(exc)}",
                provider_id=self.id,
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkUnreachableError(
                f"openkitsune-hands HTTP error: {describe_httpx_failure(exc)}",
                provider_id=self.id,
            ) from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise AuthFailedError(
                f"openkitsune-hands HTTP {resp.status_code}: {resp.text[:200]}",
                provider_id=self.id,
            )
        if resp.status_code == 429:
            raise RateLimitedError(
                f"openkitsune-hands HTTP 429: {resp.text[:200]}",
                provider_id=self.id,
            )
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            if resp.status_code == 503 and "disabled" in detail:
                raise MissingCredentialError(
                    "openkitsune-hands web_search is disabled in its config.yaml",
                    provider_id=self.id,
                )
            raise NetworkUnreachableError(
                f"openkitsune-hands HTTP {resp.status_code}: {detail}",
                provider_id=self.id,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise NetworkUnreachableError(
                "openkitsune-hands returned non-JSON response",
                provider_id=self.id,
            ) from exc

        return _parse_results(data, max_results=max_results)

    async def news_search(self, *args: Any, **kwargs: Any) -> list[SearchResult] | None:
        # 该服务只提供通用网页搜索；新闻交给其它 provider。
        return None


def _error_detail(resp: Any) -> str:
    try:
        data = resp.json()
    except ValueError:
        return str(getattr(resp, "text", ""))[:200]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("code") or data)[:200]
    return str(data)[:200]


def _parse_results(data: Any, *, max_results: int) -> list[SearchResult]:
    if not isinstance(data, dict):
        return []

    provider_name = str(data.get("provider") or "")
    out: list[SearchResult] = []
    for item in (data.get("hits") or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        title = str(item.get("title") or url or "无标题")
        out.append(
            SearchResult(
                title=title,
                url=url,
                snippet=str(item.get("snippet") or ""),
                source=str(item.get("source") or provider_name),
                date=str(item.get("publishedDate") or ""),
                extra={"provider": provider_name} if provider_name else {},
            )
        )

    infobox = data.get("infobox")
    if not out and isinstance(infobox, dict):
        content = str(infobox.get("content") or "")
        if content:
            out.append(
                SearchResult(
                    title=str(infobox.get("title") or ""),
                    url=str(infobox.get("url") or ""),
                    snippet=content,
                    source=f"openkitsune-hands:{infobox.get('infoboxType') or 'infobox'}",
                )
            )
    return out


def _region_to_language(region: str) -> str:
    if not region or region in ("wt-wt", ""):
        return ""
    if region.startswith("cn") or region.endswith("zh"):
        return "zh-CN"
    if region.startswith("us") or region.endswith("en"):
        return "en-US"
    return ""


register(HandsProvider())
