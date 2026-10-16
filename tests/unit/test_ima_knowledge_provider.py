from __future__ import annotations

import pytest

from openkitsune.integrations.knowledge import IMAKnowledgeProvider, save_ima_config
from openkitsune.integrations.knowledge import provider as provider_module


@pytest.mark.asyncio
async def test_provider_searches_selected_bases_and_labels_results(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    save_ima_config(
        {
            "enabled": True,
            "auto_retrieve": True,
            "knowledge_bases": [
                {"id": "kb-1", "name": "项目资料"},
                {"id": "kb-2", "name": "产品手册"},
            ],
            "top_k": 3,
        },
        config_path,
    )
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str, *, timeout: float) -> None:
            assert (client_id, api_key, timeout) == ("client", "key", 2.5)

        async def search_knowledge(
            self, *, knowledge_base_id: str, query: str
        ) -> list[dict[str, str]]:
            return [
                {
                    "media_id": f"media-{knowledge_base_id}",
                    "title": f"{query} 指南",
                    "highlight_content": "请先完成检查。",
                }
            ]

    monkeypatch.setattr(provider_module, "IMAClient", FakeIMAClient)

    results = await IMAKnowledgeProvider(config_path).retrieve("发布", limit=5)

    assert len(results) == 2
    assert results[0]["source"] == "腾讯 ima · 项目资料"
    assert results[0]["content"] == "[腾讯 ima · 项目资料] 发布 指南\n请先完成检查。"
    assert results[1]["knowledge_base_id"] == "kb-2"


@pytest.mark.asyncio
async def test_provider_skips_search_when_connection_is_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    save_ima_config(
        {
            "enabled": False,
            "auto_retrieve": True,
            "knowledge_bases": [{"id": "kb-1", "name": "项目资料"}],
            "top_k": 5,
        },
        config_path,
    )
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class UnexpectedIMAClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("disabled provider must not create an ima client")

    monkeypatch.setattr(provider_module, "IMAClient", UnexpectedIMAClient)

    assert await IMAKnowledgeProvider(config_path).retrieve("发布", limit=5) == []
