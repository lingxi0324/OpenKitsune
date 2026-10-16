"""Handlers for read-only cloud knowledge-base tools."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass
from ...integrations.knowledge import (
    BailianAPIError,
    BailianClient,
    IMAAPIError,
    IMAClient,
    knowledge_config_path,
    load_bailian_config,
    load_ima_config,
)

if TYPE_CHECKING:
    from ...agent.core import Agent


PROVIDER_IMA = "tencent-ima"
PROVIDER_BAILIAN = "aliyun-bailian"


class KnowledgeHandler:
    TOOLS = ["knowledge_list", "knowledge_search", "knowledge_read"]
    TOOL_CLASSES = {
        "knowledge_list": ApprovalClass.READONLY_SEARCH,
        "knowledge_search": ApprovalClass.READONLY_SEARCH,
        "knowledge_read": ApprovalClass.READONLY_SEARCH,
    }

    def __init__(self, agent: Agent, config_path: Path | None = None) -> None:
        self.agent = agent
        self.config_path = config_path
        self._bailian_documents: dict[tuple[str, str], dict[str, Any]] = {}

    def _resolve_config_path(self) -> Path:
        if self.config_path is not None:
            return self.config_path
        from ...config import settings

        return knowledge_config_path(Path(settings.project_root))

    def _ima_connection(self) -> tuple[dict[str, Any] | None, IMAClient | None, dict | None]:
        config = load_ima_config(self._resolve_config_path())
        if not config["enabled"]:
            return None, None, self._connector_error(PROVIDER_IMA, "connector_disabled")
        if not config["knowledge_bases"]:
            return None, None, self._connector_error(PROVIDER_IMA, "no_knowledge_bases")
        client_id = os.environ.get("IMA_OPENAPI_CLIENTID", "").strip()
        api_key = os.environ.get("IMA_OPENAPI_APIKEY", "").strip()
        if not client_id or not api_key:
            return None, None, self._connector_error(PROVIDER_IMA, "missing_credentials")
        return config, IMAClient(client_id, api_key), None

    def _bailian_connection(
        self,
    ) -> tuple[dict[str, Any] | None, BailianClient | None, dict | None]:
        config = load_bailian_config(self._resolve_config_path())
        if not config["enabled"]:
            return None, None, self._connector_error(PROVIDER_BAILIAN, "connector_disabled")
        if not config["workspace_id"] or not config["agent_id"]:
            return None, None, self._connector_error(PROVIDER_BAILIAN, "no_knowledge_bases")
        api_key = (
            os.environ.get("BAILIAN_KNOWLEDGE_API_KEY", "").strip()
            or os.environ.get("DASHSCOPE_API_KEY", "").strip()
        )
        if not api_key:
            return None, None, self._connector_error(PROVIDER_BAILIAN, "missing_credentials")
        return (
            config,
            BailianClient(
                config["workspace_id"],
                api_key,
                config["agent_id"],
                region=config["region"],
            ),
            None,
        )

    @staticmethod
    def _connector_error(provider: str, code: str) -> dict[str, Any]:
        names = {PROVIDER_IMA: "腾讯 ima", PROVIDER_BAILIAN: "阿里云百炼"}
        messages = {
            "connector_disabled": f"尚未启用{names[provider]}知识库连接。",
            "no_knowledge_bases": f"尚未配置{names[provider]}可用的知识检索范围。",
            "missing_credentials": f"{names[provider]}连接缺少凭据，请在知识库设置中重新连接。",
        }
        return {
            "success": False,
            "provider": provider,
            "error_code": code,
            "message": messages[code],
        }

    @staticmethod
    def _provider_scope(params: dict[str, Any]) -> str:
        provider = str(params.get("provider") or "").strip().lower()
        return provider if provider in {PROVIDER_IMA, PROVIDER_BAILIAN} else ""

    @staticmethod
    def _select_ima_bases(config: dict[str, Any], knowledge_base_id: str) -> list[dict[str, str]]:
        selected = list(config["knowledge_bases"])
        requested_id = knowledge_base_id.strip()
        if not requested_id:
            return selected
        return [item for item in selected if item["id"] == requested_id]

    async def handle(self, tool_name: str, params: dict[str, Any]) -> dict:
        if tool_name == "knowledge_list":
            result = await self._list(params)
        elif tool_name == "knowledge_search":
            result = await self._search(params)
        elif tool_name == "knowledge_read":
            result = await self._read(params)
        else:
            result = {
                "success": False,
                "error_code": "unknown_tool",
                "message": f"Unknown knowledge tool: {tool_name}",
            }
        self._record_priority_status(tool_name, result)
        return result

    def _record_priority_status(self, tool_name: str, result: dict) -> None:
        if not getattr(self.agent, "_knowledge_priority_active", False):
            return
        if tool_name == "knowledge_search":
            if result.get("success") and int(result.get("result_count") or 0) > 0:
                status = "search_hit"
            else:
                status = "search_empty" if result.get("success") else "search_failed"
        elif tool_name == "knowledge_read":
            status = "read_success" if result.get("success") else "read_failed"
        elif tool_name == "knowledge_list":
            status = "list_success" if result.get("success") else "list_failed"
        else:
            return
        self.agent._knowledge_priority_status = status

    async def _list(self, params: dict[str, Any]) -> dict:
        provider_scope = self._provider_scope(params)
        knowledge_base_id = str(params.get("knowledge_base_id") or "").strip()
        pages: list[dict[str, Any]] = []
        connector_results: list[dict[str, Any]] = []
        unmatched_available: list[dict[str, str]] = []

        if provider_scope in {"", PROVIDER_IMA}:
            ima_config, ima_client, ima_error = self._ima_connection()
            if not ima_error and ima_config is not None and ima_client is not None:
                selected = self._select_ima_bases(ima_config, knowledge_base_id)
                if knowledge_base_id and not selected:
                    if provider_scope == PROVIDER_IMA:
                        return self._scope_error(ima_config["knowledge_bases"])
                    unmatched_available.extend(ima_config["knowledge_bases"])
                else:
                    ima_pages = await self._list_ima(params, ima_config, ima_client, selected)
                    pages.extend(ima_pages)
                    connector_results.append(
                        {
                            "provider": PROVIDER_IMA,
                            "success": not all("error_code" in page for page in ima_pages),
                        }
                    )
            elif provider_scope == PROVIDER_IMA:
                return ima_error or self._connector_error(PROVIDER_IMA, "connector_disabled")

        if provider_scope in {"", PROVIDER_BAILIAN}:
            bailian_config, _, bailian_error = self._bailian_connection()
            if not bailian_error and bailian_config is not None:
                service_id = bailian_config["agent_id"]
                if not knowledge_base_id or knowledge_base_id == service_id:
                    pages.append(
                        {
                            "provider": PROVIDER_BAILIAN,
                            "id": service_id,
                            "name": bailian_config["service_name"],
                            "items": [],
                            "is_end": True,
                            "next_cursor": "",
                            "listing_supported": False,
                            "message": "百炼知识检索服务不提供文件目录浏览，请使用 knowledge_search 检索正文。",
                        }
                    )
                    connector_results.append({"provider": PROVIDER_BAILIAN, "success": True})
                elif provider_scope == PROVIDER_BAILIAN:
                    return self._scope_error(bailian_config["knowledge_bases"])
                else:
                    unmatched_available.extend(bailian_config["knowledge_bases"])
            elif provider_scope == PROVIDER_BAILIAN:
                return bailian_error or self._connector_error(
                    PROVIDER_BAILIAN, "connector_disabled"
                )

        if not connector_results:
            if knowledge_base_id and unmatched_available:
                return self._scope_error(unmatched_available)
            return {
                "success": False,
                "error_code": "connector_disabled",
                "message": "尚未启用可用的云知识库连接。",
            }
        providers = [item["provider"] for item in connector_results]
        return {
            "success": any(item["success"] for item in connector_results),
            "provider": providers[0] if len(providers) == 1 else "multiple",
            "knowledge_bases": pages,
            "item_count": sum(len(page.get("items") or []) for page in pages),
            "connector_results": connector_results,
        }

    async def _list_ima(
        self,
        params: dict[str, Any],
        config: dict[str, Any],
        client: IMAClient,
        bases: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        folder_id = str(params.get("folder_id") or "").strip()
        cursor = str(params.get("cursor") or "").strip()
        try:
            limit = max(1, min(int(params.get("limit") or 20), 50))
        except (TypeError, ValueError):
            limit = 20
        validation_error = self._validate_ima_scope(
            config=config,
            bases=bases,
            knowledge_base_id=str(params.get("knowledge_base_id") or ""),
            scoped_value=folder_id or cursor,
        )
        if validation_error:
            return [{"provider": PROVIDER_IMA, **validation_error, "items": []}]

        async def browse_one(base: dict[str, str]) -> dict[str, Any]:
            try:
                page = await client.get_knowledge_list(
                    knowledge_base_id=base["id"],
                    folder_id=folder_id,
                    cursor=cursor,
                    limit=limit,
                )
                return {
                    "provider": PROVIDER_IMA,
                    "id": base["id"],
                    "name": base["name"],
                    **page,
                }
            except IMAAPIError as exc:
                return {
                    "provider": PROVIDER_IMA,
                    "id": base["id"],
                    "name": base["name"],
                    "items": [],
                    "error_code": exc.code,
                    "message": str(exc),
                }

        return list(await asyncio.gather(*(browse_one(base) for base in bases)))

    async def _search(self, params: dict[str, Any]) -> dict:
        query = str(params.get("query") or "").strip()
        if not query:
            return {
                "success": False,
                "error_code": "invalid_request",
                "message": "知识库搜索关键词不能为空。",
            }
        provider_scope = self._provider_scope(params)
        knowledge_base_id = str(params.get("knowledge_base_id") or "").strip()
        results: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        configured_limits: list[int] = []
        unmatched_available: list[dict[str, str]] = []

        ima_config, ima_client, ima_error = self._ima_connection()
        if provider_scope in {"", PROVIDER_IMA} and not ima_error:
            assert ima_config is not None and ima_client is not None
            bases = self._select_ima_bases(ima_config, knowledge_base_id)
            if not knowledge_base_id or bases:
                ima_results, ima_summaries, ima_success = await self._search_ima(
                    query, params, ima_config, ima_client, bases
                )
                results.extend(ima_results)
                summaries.extend(ima_summaries)
                configured_limits.append(int(ima_config["top_k"]))
                summaries.append({"provider": PROVIDER_IMA, "success": ima_success})
            elif provider_scope == PROVIDER_IMA:
                return self._scope_error(ima_config["knowledge_bases"])
            else:
                unmatched_available.extend(ima_config["knowledge_bases"])
        elif provider_scope == PROVIDER_IMA:
            return ima_error or self._connector_error(PROVIDER_IMA, "connector_disabled")

        bailian_config, bailian_client, bailian_error = self._bailian_connection()
        if provider_scope in {"", PROVIDER_BAILIAN} and not bailian_error:
            assert bailian_config is not None and bailian_client is not None
            service_id = bailian_config["agent_id"]
            if not knowledge_base_id or knowledge_base_id == service_id:
                try:
                    bailian_items = await bailian_client.search(
                        query, limit=int(bailian_config["top_k"])
                    )
                    for item in bailian_items:
                        normalized = {
                            **item,
                            "provider": PROVIDER_BAILIAN,
                            "knowledge_base_id": service_id,
                            "knowledge_base_name": bailian_config["service_name"],
                        }
                        results.append(normalized)
                        self._bailian_documents[(service_id, item["media_id"])] = normalized
                    summaries.append(
                        {
                            "provider": PROVIDER_BAILIAN,
                            "success": True,
                            "id": service_id,
                            "name": bailian_config["service_name"],
                        }
                    )
                    configured_limits.append(int(bailian_config["top_k"]))
                except BailianAPIError as exc:
                    summaries.append(
                        {
                            "provider": PROVIDER_BAILIAN,
                            "success": False,
                            "error_code": exc.code,
                            "message": str(exc),
                        }
                    )
            elif provider_scope == PROVIDER_BAILIAN:
                return self._scope_error(bailian_config["knowledge_bases"])
            else:
                unmatched_available.extend(bailian_config["knowledge_bases"])
        elif provider_scope == PROVIDER_BAILIAN:
            return bailian_error or self._connector_error(PROVIDER_BAILIAN, "connector_disabled")

        provider_statuses = [item for item in summaries if "success" in item]
        if not provider_statuses:
            if knowledge_base_id and unmatched_available:
                return self._scope_error(unmatched_available)
            return {
                "success": False,
                "error_code": "connector_disabled",
                "message": "尚未启用可用的云知识库连接。",
            }
        default_limit = max(configured_limits or [5])
        try:
            limit = max(1, min(int(params.get("limit") or default_limit), 20))
        except (TypeError, ValueError):
            limit = default_limit
        results.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        providers = sorted({str(item["provider"]) for item in provider_statuses})
        return {
            "success": any(bool(item["success"]) for item in provider_statuses),
            "provider": (
                providers[0]
                if len(providers) == 1
                else ("multiple" if providers else provider_scope or "multiple")
            ),
            "query": query,
            "results": results[:limit],
            "result_count": min(len(results), limit),
            "knowledge_bases": [item for item in summaries if "id" in item],
            "connector_results": provider_statuses,
        }

    async def _search_ima(
        self,
        query: str,
        params: dict[str, Any],
        config: dict[str, Any],
        client: IMAClient,
        bases: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        cursor = str(params.get("cursor") or "").strip()
        validation_error = self._validate_ima_scope(
            config=config,
            bases=bases,
            knowledge_base_id=str(params.get("knowledge_base_id") or ""),
            scoped_value=cursor,
        )
        if validation_error:
            return [], [], False

        async def search_one(base: dict[str, str]) -> dict[str, Any]:
            try:
                page = await client.search_knowledge_page(
                    knowledge_base_id=base["id"], query=query, cursor=cursor
                )
                return {
                    "provider": PROVIDER_IMA,
                    "id": base["id"],
                    "name": base["name"],
                    **page,
                }
            except IMAAPIError as exc:
                return {
                    "provider": PROVIDER_IMA,
                    "id": base["id"],
                    "name": base["name"],
                    "items": [],
                    "error_code": exc.code,
                    "message": str(exc),
                }

        pages = list(await asyncio.gather(*(search_one(base) for base in bases)))
        results = [
            {
                **item,
                "provider": PROVIDER_IMA,
                "knowledge_base_id": page["id"],
                "knowledge_base_name": page["name"],
            }
            for page in pages
            for item in page.get("items") or []
        ]
        summaries = [
            {
                "provider": PROVIDER_IMA,
                "id": page["id"],
                "name": page["name"],
                "is_end": page.get("is_end", True),
                "next_cursor": page.get("next_cursor", ""),
                **(
                    {
                        "error_code": page["error_code"],
                        "message": page.get("message", ""),
                    }
                    if "error_code" in page
                    else {}
                ),
            }
            for page in pages
        ]
        return results, summaries, not all("error_code" in page for page in pages)

    async def _read(self, params: dict[str, Any]) -> dict:
        media_id = str(params.get("media_id") or "").strip()
        knowledge_base_id = str(params.get("knowledge_base_id") or "").strip()
        provider_scope = self._provider_scope(params)
        if not media_id or not knowledge_base_id:
            return {
                "success": False,
                "error_code": "invalid_request",
                "message": "读取知识正文需要 media_id 和 knowledge_base_id。",
                "external_search_allowed": False,
            }

        bailian_config = load_bailian_config(self._resolve_config_path())
        wants_bailian = provider_scope == PROVIDER_BAILIAN or (
            provider_scope == "" and knowledge_base_id == bailian_config.get("agent_id")
        )
        if wants_bailian:
            cached = self._bailian_documents.get((knowledge_base_id, media_id))
            if cached is None:
                return {
                    "success": False,
                    "provider": PROVIDER_BAILIAN,
                    "error_code": "search_required",
                    "message": "请先调用 knowledge_search 获取这份百炼资料的正文切片。",
                    "external_search_allowed": False,
                }
            content = str(cached.get("content") or "")
            return {
                "success": True,
                "provider": PROVIDER_BAILIAN,
                "knowledge_base_id": knowledge_base_id,
                "knowledge_base_name": bailian_config["service_name"],
                "media_id": media_id,
                "title": cached.get("title") or "未命名资料",
                "content_available": bool(content),
                "content_scope": "matched_chunks",
                "content_type": "text/plain",
                "content": content,
                "char_count": len(content),
                "chunk_count": len(cached.get("chunk_ids") or []),
                "truncated": bool(cached.get("truncated", False)),
            }
        return await self._read_ima(params, media_id, knowledge_base_id)

    async def _read_ima(
        self, params: dict[str, Any], media_id: str, knowledge_base_id: str
    ) -> dict:
        config, client, error = self._ima_connection()
        if error:
            return {**error, "external_search_allowed": False}
        assert config is not None and client is not None
        bases = self._select_ima_bases(config, knowledge_base_id)
        if not bases:
            return {
                "success": False,
                "error_code": "knowledge_base_not_selected",
                "message": "只能读取已在设置中选中的知识库。",
                "available_knowledge_bases": config["knowledge_bases"],
                "external_search_allowed": False,
            }
        parent_folder_id = str(params.get("parent_folder_id") or "").strip()
        try:
            start_page = max(1, int(params.get("start_page") or 1))
            max_pages = max(1, min(int(params.get("max_pages") or 20), 50))
            max_chars = max(1_000, min(int(params.get("max_chars") or 40_000), 80_000))
        except (TypeError, ValueError):
            return {
                "success": False,
                "error_code": "invalid_request",
                "message": "读取范围参数必须是整数。",
                "external_search_allowed": False,
            }
        try:
            item = await self._find_media_in_folder(
                client=client,
                knowledge_base_id=knowledge_base_id,
                folder_id=parent_folder_id,
                media_id=media_id,
            )
            if item is None:
                return {
                    "success": False,
                    "error_code": "media_not_in_selected_scope",
                    "message": "未能在指定的已选知识库目录中确认这份资料。",
                    "external_search_allowed": False,
                }
            content = await client.read_media_text(
                media_id=media_id,
                start_page=start_page,
                max_pages=max_pages,
                max_chars=max_chars,
            )
        except IMAAPIError as exc:
            return {
                "success": False,
                "error_code": exc.code,
                "message": str(exc),
                "external_search_allowed": False,
            }
        return {
            "success": True,
            "provider": PROVIDER_IMA,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": bases[0]["name"],
            "media_id": media_id,
            "title": item["title"],
            "content_available": True,
            **content,
        }

    @staticmethod
    async def _find_media_in_folder(
        *, client: IMAClient, knowledge_base_id: str, folder_id: str, media_id: str
    ) -> dict[str, Any] | None:
        cursor = ""
        seen_cursors: set[str] = set()
        for _ in range(20):
            page = await client.get_knowledge_list(
                knowledge_base_id=knowledge_base_id,
                folder_id=folder_id,
                cursor=cursor,
                limit=50,
            )
            for item in page.get("items") or []:
                if item.get("type") == "file" and item.get("media_id") == media_id:
                    return item
            if page.get("is_end", True):
                break
            next_cursor = str(page.get("next_cursor") or "")
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return None

    @staticmethod
    def _scope_error(available: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": "knowledge_base_not_selected",
            "message": "只能读取已在设置中选中的知识库。",
            "available_knowledge_bases": available,
        }

    @classmethod
    def _validate_ima_scope(
        cls,
        *,
        config: dict[str, Any],
        bases: list[dict[str, str]],
        knowledge_base_id: str,
        scoped_value: str,
    ) -> dict | None:
        if knowledge_base_id and not bases:
            return cls._scope_error(config["knowledge_bases"])
        if scoped_value and len(bases) != 1:
            return {
                "success": False,
                "error_code": "knowledge_base_required",
                "message": "浏览文件夹或继续分页时需要指定 knowledge_base_id。",
                "available_knowledge_bases": config["knowledge_bases"],
            }
        return None


def create_handler(agent: Agent):
    handler = KnowledgeHandler(agent)
    return handler.handle
