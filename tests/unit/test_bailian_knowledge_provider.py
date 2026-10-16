from __future__ import annotations

import pytest

from openkitsune.integrations.knowledge import BailianKnowledgeProvider, save_bailian_config
from openkitsune.integrations.knowledge import provider as provider_module


@pytest.mark.asyncio
async def test_bailian_provider_returns_semantic_chunks(tmp_path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "knowledge_connectors.json"
    save_bailian_config(
        {
            "enabled": True,
            "auto_retrieve": True,
            "workspace_id": "llm-workspace",
            "agent_id": "aid-service",
            "service_name": "产品资料",
            "region": "cn-beijing",
            "top_k": 3,
        },
        config_path,
    )
    monkeypatch.setenv("BAILIAN_KNOWLEDGE_API_KEY", "key")

    class FakeBailianClient:
        def __init__(self, workspace_id, api_key, agent_id, *, region, timeout):
            assert (workspace_id, api_key, agent_id, region, timeout) == (
                "llm-workspace",
                "key",
                "aid-service",
                "cn-beijing",
                4.0,
            )

        async def search(self, query: str, *, limit: int):
            assert (query, limit) == ("发布", 3)
            return [
                {
                    "media_id": "file-1",
                    "title": "发布流程",
                    "content": "发布前需要完成回归测试。",
                    "score": 0.92,
                }
            ]

    monkeypatch.setattr(provider_module, "BailianClient", FakeBailianClient)
    results = await BailianKnowledgeProvider(config_path).retrieve("发布", limit=5)

    assert results[0]["source"] == "阿里云百炼 · 产品资料"
    assert "回归测试" in results[0]["content"]
    assert results[0]["relevance"] == 0.92
