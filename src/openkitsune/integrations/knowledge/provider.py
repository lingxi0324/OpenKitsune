"""Retrieval adapter for cloud knowledge connectors."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from .bailian import BailianClient
from .config import load_bailian_config, load_ima_config
from .ima import IMAClient

logger = logging.getLogger(__name__)


class IMAKnowledgeProvider:
    """Expose selected Tencent ima knowledge bases to the memory retrieval path."""

    source_name = "knowledge:tencent-ima"

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path

    async def retrieve(self, query: str, limit: int = 5) -> list[dict]:
        config = load_ima_config(self.config_path)
        knowledge_bases = config["knowledge_bases"]
        if not config["enabled"] or not config["auto_retrieve"] or not knowledge_bases:
            return []

        client_id = os.environ.get("IMA_OPENAPI_CLIENTID", "").strip()
        api_key = os.environ.get("IMA_OPENAPI_APIKEY", "").strip()
        if not client_id or not api_key:
            return []

        result_limit = max(1, min(int(limit or config["top_k"]), config["top_k"], 10))
        client = IMAClient(client_id, api_key, timeout=2.5)

        async def search_one(knowledge_base: dict[str, str]):
            try:
                items = await client.search_knowledge(
                    knowledge_base_id=knowledge_base["id"],
                    query=query,
                )
                return knowledge_base, items
            except Exception as exc:
                logger.warning(
                    "[Knowledge] Tencent ima search failed for knowledge base %s: %s",
                    knowledge_base["id"],
                    exc,
                )
                return knowledge_base, []

        batches = await asyncio.gather(*(search_one(item) for item in knowledge_bases))
        results: list[dict] = []
        for knowledge_base, items in batches:
            for rank, item in enumerate(items):
                title = str(item.get("title") or "未命名资料").strip()
                highlight = str(item.get("highlight_content") or "").strip()
                label = f"腾讯 ima · {knowledge_base['name']}"
                content = f"[{label}] {title}"
                if highlight:
                    content += f"\n{highlight}"
                media_id = str(item.get("media_id") or title).strip()
                results.append(
                    {
                        "id": f"ima:{knowledge_base['id']}:{media_id}",
                        "content": content,
                        "title": title,
                        "source": label,
                        "knowledge_base_id": knowledge_base["id"],
                        "knowledge_base_name": knowledge_base["name"],
                        "media_id": media_id,
                        "relevance": max(0.55, 0.85 - rank * 0.04),
                    }
                )

        results.sort(key=lambda item: item["relevance"], reverse=True)
        return results[:result_limit]


class BailianKnowledgeProvider:
    """Expose a published Bailian retrieval service to automatic retrieval."""

    source_name = "knowledge:aliyun-bailian"

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path

    async def retrieve(self, query: str, limit: int = 5) -> list[dict]:
        config = load_bailian_config(self.config_path)
        if not config["enabled"] or not config["auto_retrieve"] or not config["agent_id"]:
            return []
        api_key = (
            os.environ.get("BAILIAN_KNOWLEDGE_API_KEY", "").strip()
            or os.environ.get("DASHSCOPE_API_KEY", "").strip()
        )
        if not api_key or not config["workspace_id"]:
            return []
        result_limit = max(1, min(int(limit or config["top_k"]), config["top_k"], 20))
        client = BailianClient(
            config["workspace_id"],
            api_key,
            config["agent_id"],
            region=config["region"],
            timeout=4.0,
        )
        try:
            items = await client.search(query, limit=result_limit)
        except Exception as exc:
            logger.warning("[Knowledge] Bailian retrieval failed: %s", exc)
            return []
        label = f"阿里云百炼 · {config['service_name']}"
        return [
            {
                "id": f"bailian:{config['agent_id']}:{item['media_id']}",
                "content": f"[{label}] {item['title']}\n{item['content']}",
                "title": item["title"],
                "source": label,
                "knowledge_base_id": config["agent_id"],
                "knowledge_base_name": config["service_name"],
                "media_id": item["media_id"],
                "relevance": max(0.0, min(float(item.get("score") or 0.0), 1.0)),
            }
            for item in items
        ]
