from __future__ import annotations

from types import SimpleNamespace

import pytest

from openkitsune.integrations.knowledge import save_bailian_config, save_ima_config
from openkitsune.tools.defer_config import STABLE_MAIN_CHAT_CORE_TOOL_SET
from openkitsune.tools.definitions import get_tool_definition
from openkitsune.tools.handlers import knowledge as knowledge_module
from openkitsune.tools.handlers.knowledge import KnowledgeHandler


def _save_enabled_config(path) -> None:
    save_ima_config(
        {
            "enabled": True,
            "auto_retrieve": False,
            "knowledge_bases": [
                {"id": "kb-1", "name": "项目资料"},
                {"id": "kb-2", "name": "产品手册"},
            ],
            "top_k": 5,
        },
        path,
    )


def test_knowledge_tools_have_explicit_readonly_definitions():
    list_tool = get_tool_definition("knowledge_list")
    search_tool = get_tool_definition("knowledge_search")
    read_tool = get_tool_definition("knowledge_read")

    assert list_tool is not None
    assert "read-only" in list_tool["description"]
    assert search_tool is not None
    assert search_tool["input_schema"]["required"] == ["query"]
    assert read_tool is not None
    assert read_tool["input_schema"]["required"] == ["media_id", "knowledge_base_id"]
    assert "do not switch to web" in read_tool["description"]
    assert {"knowledge_list", "knowledge_search", "knowledge_read"} <= (
        STABLE_MAIN_CHAT_CORE_TOOL_SET
    )


@pytest.mark.asyncio
async def test_knowledge_list_browses_all_selected_bases_without_auto_retrieve(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            assert (client_id, api_key) == ("client", "key")

        async def get_knowledge_list(self, **params):
            return {
                "items": [
                    {
                        "type": "file",
                        "media_id": f"media-{params['knowledge_base_id']}",
                        "title": f"{params['knowledge_base_id']}.pdf",
                        "parent_folder_id": "",
                    }
                ],
                "is_end": True,
                "next_cursor": "",
                "current_path": [],
            }

    monkeypatch.setattr(knowledge_module, "IMAClient", FakeIMAClient)
    handler = KnowledgeHandler(object(), config_path=config_path)

    result = await handler.handle("knowledge_list", {})

    assert result["success"] is True
    assert result["item_count"] == 2
    assert [page["name"] for page in result["knowledge_bases"]] == [
        "项目资料",
        "产品手册",
    ]


@pytest.mark.asyncio
async def test_knowledge_list_rejects_unselected_knowledge_base(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")
    monkeypatch.setattr(knowledge_module, "IMAClient", lambda *_args: object())
    handler = KnowledgeHandler(object(), config_path=config_path)

    result = await handler.handle("knowledge_list", {"knowledge_base_id": "kb-other"})

    assert result["success"] is False
    assert result["error_code"] == "knowledge_base_not_selected"


@pytest.mark.asyncio
async def test_knowledge_search_uses_explicit_tool_even_when_auto_retrieve_is_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            assert (client_id, api_key) == ("client", "key")

        async def search_knowledge_page(self, **params):
            return {
                "items": [
                    {
                        "media_id": f"media-{params['knowledge_base_id']}",
                        "title": "发布流程",
                        "parent_folder_id": "",
                        "highlight_content": "发布前需要完成回归测试",
                    }
                ],
                "is_end": True,
                "next_cursor": "",
            }

    monkeypatch.setattr(knowledge_module, "IMAClient", FakeIMAClient)
    handler = KnowledgeHandler(object(), config_path=config_path)

    result = await handler.handle(
        "knowledge_search",
        {"query": "发布流程", "knowledge_base_id": "kb-1"},
    )

    assert result["success"] is True
    assert result["result_count"] == 1
    assert result["results"][0]["knowledge_base_name"] == "项目资料"
    assert result["results"][0]["highlight_content"] == "发布前需要完成回归测试"


@pytest.mark.asyncio
async def test_knowledge_search_records_priority_hit_for_current_turn(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, *_args) -> None:
            pass

        async def search_knowledge_page(self, **_params):
            return {
                "items": [{"media_id": "media-1", "title": "BL0939.pdf"}],
                "is_end": True,
                "next_cursor": "",
            }

    monkeypatch.setattr(knowledge_module, "IMAClient", FakeIMAClient)
    agent = SimpleNamespace(_knowledge_priority_active=True, _knowledge_priority_status="pending")
    handler = KnowledgeHandler(agent, config_path=config_path)

    result = await handler.handle("knowledge_search", {"query": "BL0939"})

    assert result["success"] is True
    assert agent._knowledge_priority_status == "search_hit"


@pytest.mark.asyncio
async def test_knowledge_read_verifies_scope_and_returns_content_without_access_secrets(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            assert (client_id, api_key) == ("client", "key")

        async def get_knowledge_list(self, **params):
            assert params["knowledge_base_id"] == "kb-1"
            assert params["folder_id"] == "folder-1"
            return {
                "items": [
                    {
                        "type": "file",
                        "media_id": "media-1",
                        "title": "BL0939.pdf",
                        "parent_folder_id": "folder-1",
                    }
                ],
                "is_end": True,
                "next_cursor": "",
            }

        async def read_media_text(self, **params):
            assert params == {
                "media_id": "media-1",
                "start_page": 1,
                "max_pages": 20,
                "max_chars": 40_000,
            }
            return {
                "media_type": 1,
                "content_type": "application/pdf",
                "content": "BL0939 是一款电能计量芯片。",
                "char_count": 18,
                "truncated": False,
                "total_pages": 16,
                "pages_read": 16,
                "next_page": None,
            }

    monkeypatch.setattr(knowledge_module, "IMAClient", FakeIMAClient)
    handler = KnowledgeHandler(object(), config_path=config_path)

    result = await handler.handle(
        "knowledge_read",
        {
            "knowledge_base_id": "kb-1",
            "parent_folder_id": "folder-1",
            "media_id": "media-1",
        },
    )

    assert result["success"] is True
    assert result["knowledge_base_name"] == "项目资料"
    assert result["title"] == "BL0939.pdf"
    assert "BL0939" in result["content"]
    assert "url" not in result
    assert "headers" not in result


@pytest.mark.asyncio
async def test_knowledge_read_rejects_media_outside_selected_folder(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    _save_enabled_config(config_path)
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    class FakeIMAClient:
        def __init__(self, *_args) -> None:
            pass

        async def get_knowledge_list(self, **_params):
            return {"items": [], "is_end": True, "next_cursor": ""}

        async def read_media_text(self, **_params):
            raise AssertionError("out-of-scope media must not be read")

    monkeypatch.setattr(knowledge_module, "IMAClient", FakeIMAClient)
    handler = KnowledgeHandler(object(), config_path=config_path)

    result = await handler.handle(
        "knowledge_read",
        {
            "knowledge_base_id": "kb-1",
            "parent_folder_id": "folder-1",
            "media_id": "outside-media",
        },
    )

    assert result["success"] is False
    assert result["error_code"] == "media_not_in_selected_scope"
    assert result["external_search_allowed"] is False


@pytest.mark.asyncio
async def test_knowledge_search_aggregates_bailian_and_reads_cached_chunks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "knowledge_connectors.json"
    save_bailian_config(
        {
            "enabled": True,
            "auto_retrieve": True,
            "workspace_id": "llm-workspace",
            "agent_id": "aid-service",
            "service_name": "产品资料",
            "region": "cn-beijing",
            "top_k": 5,
        },
        config_path,
    )
    monkeypatch.setenv("BAILIAN_KNOWLEDGE_API_KEY", "key")

    class FakeBailianClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, query: str, *, limit: int):
            assert (query, limit) == ("BL0939", 5)
            return [
                {
                    "media_id": "file-1",
                    "title": "BL0939.pdf",
                    "content": "BL0939 是一款电能计量芯片。",
                    "highlight_content": "BL0939 是一款电能计量芯片。",
                    "score": 0.95,
                    "chunk_ids": ["chunk-1"],
                }
            ]

    monkeypatch.setattr(knowledge_module, "BailianClient", FakeBailianClient)
    handler = KnowledgeHandler(object(), config_path=config_path)

    searched = await handler.handle("knowledge_search", {"query": "BL0939"})
    assert searched["success"] is True
    assert searched["results"][0]["provider"] == "aliyun-bailian"
    assert searched["results"][0]["knowledge_base_id"] == "aid-service"

    read = await handler.handle(
        "knowledge_read",
        {
            "provider": "aliyun-bailian",
            "knowledge_base_id": "aid-service",
            "media_id": "file-1",
        },
    )
    assert read["success"] is True
    assert read["content_scope"] == "matched_chunks"
    assert "电能计量" in read["content"]
