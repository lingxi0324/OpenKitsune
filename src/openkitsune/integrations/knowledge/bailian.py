"""Async client for Alibaba Cloud Model Studio knowledge retrieval services."""

from __future__ import annotations

import re
from typing import Any

import httpx

BAILIAN_REGIONS = {"cn-beijing", "ap-southeast-1"}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class BailianAPIError(RuntimeError):
    """A sanitized failure returned by Bailian or its transport."""

    def __init__(self, message: str, *, code: str = "bailian_error") -> None:
        super().__init__(message)
        self.code = code


class BailianClient:
    """Read-only client for a published Bailian knowledge retrieval service."""

    def __init__(
        self,
        workspace_id: str,
        api_key: str,
        agent_id: str,
        *,
        region: str = "cn-beijing",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.workspace_id = workspace_id.strip()
        self._api_key = api_key.strip()
        self.agent_id = agent_id.strip()
        self.region = region.strip() or "cn-beijing"
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(
            self.workspace_id
            and self._api_key
            and self.agent_id
            and self.region in BAILIAN_REGIONS
            and _IDENTIFIER_PATTERN.fullmatch(self.workspace_id)
            and _IDENTIFIER_PATTERN.fullmatch(self.agent_id)
        )

    @property
    def base_url(self) -> str:
        return f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com"

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Run semantic retrieval and group returned chunks by source document."""
        clean_query = query.strip()
        if not self.configured:
            raise BailianAPIError(
                "请填写百炼业务空间、检索服务和 API Key", code="missing_credentials"
            )
        if not clean_query:
            raise BailianAPIError("知识库搜索关键词不能为空", code="invalid_request")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": self._timeout,
            "follow_redirects": False,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.post(
                    "/api/v1/indices/knowledge/search",
                    headers=headers,
                    json={"agent_id": self.agent_id, "query": clean_query, "images": []},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise BailianAPIError("连接阿里云百炼超时，请稍后重试", code="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = "百炼凭证无效或无权访问该检索服务"
                code = "authentication_failed"
            elif status == 429:
                message = "百炼检索请求过于频繁，请稍后重试"
                code = "rate_limited"
            else:
                message = f"阿里云百炼返回 HTTP {status}"
                code = "http_error"
            raise BailianAPIError(message, code=code) from exc
        except httpx.RequestError as exc:
            raise BailianAPIError("无法连接阿里云百炼，请检查网络", code="network_error") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise BailianAPIError("百炼返回了无法解析的响应", code="invalid_response") from exc
        if not isinstance(body, dict):
            raise BailianAPIError("百炼返回了无效的数据格式", code="invalid_response")

        if body.get("success") is False or str(body.get("status") or "").upper() == "FAILED":
            raw_code = str(body.get("code") or "request_failed")
            message = str(body.get("message") or "百炼拒绝了本次请求")
            raise BailianAPIError(message, code=f"bailian_{raw_code}")

        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise BailianAPIError("百炼返回了无效的业务数据", code="invalid_response")
        nodes = data.get("nodes") or []
        if not isinstance(nodes, list):
            nodes = []

        groups: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for rank, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            metadata = node.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            text = str(node.get("text") or metadata.get("content") or "").strip()
            doc_id = str(metadata.get("doc_id") or metadata.get("_id") or "").strip()
            if not doc_id:
                doc_id = f"result-{rank + 1}"
            title = str(metadata.get("doc_name") or metadata.get("title") or "未命名资料").strip()
            try:
                score = float(node.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0

            if doc_id not in groups:
                order.append(doc_id)
                groups[doc_id] = {
                    "media_id": doc_id,
                    "document_id": doc_id,
                    "title": title or "未命名资料",
                    "parent_folder_id": "",
                    "highlight_content": "",
                    "content": "",
                    "excerpt_available": bool(text),
                    "content_available": bool(text),
                    "content_scope": "matched_chunks",
                    "match_type": "semantic_content",
                    "score": score,
                    "remote_knowledge_base_id": str(metadata.get("pipeline_id") or ""),
                    "chunk_ids": [],
                }
            group = groups[doc_id]
            group["score"] = max(float(group["score"]), score)
            chunk_id = str(metadata.get("_id") or "").strip()
            if chunk_id:
                group["chunk_ids"].append(chunk_id)
            if text:
                existing = str(group["content"])
                if text not in existing:
                    combined = f"{existing}\n\n{text}".strip()
                    group["content"] = combined[:40_000]
                    group["highlight_content"] = group["content"]
                    group["excerpt_available"] = True
                    group["content_available"] = True
                    group["truncated"] = len(combined) > 40_000

        result_limit = max(1, min(int(limit), 20))
        return [groups[key] for key in order][:result_limit]
