from __future__ import annotations

import json

import httpx
import pytest

from openkitsune.integrations.knowledge.bailian import BailianAPIError, BailianClient


@pytest.mark.asyncio
async def test_search_uses_official_endpoint_and_groups_chunks_by_document():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://llm-workspace.cn-beijing.maas.aliyuncs.com/api/v1/indices/knowledge/search"
        )
        assert request.headers["authorization"] == "Bearer sk-secret"
        assert json.loads(request.content) == {
            "agent_id": "aid-service",
            "query": "BL0939 功能",
            "images": [],
        }
        return httpx.Response(
            200,
            json={
                "success": True,
                "status": "SUCCESS",
                "data": {
                    "nodes": [
                        {
                            "score": 0.91,
                            "text": "BL0939 支持两路电流和一路电压计量。",
                            "metadata": {
                                "doc_id": "file-1",
                                "doc_name": "BL0939.pdf",
                                "pipeline_id": "index-1",
                                "_id": "chunk-1",
                            },
                        },
                        {
                            "score": 0.86,
                            "text": "它支持 UART 和 SPI 通信。",
                            "metadata": {
                                "doc_id": "file-1",
                                "doc_name": "BL0939.pdf",
                                "pipeline_id": "index-1",
                                "_id": "chunk-2",
                            },
                        },
                    ]
                },
            },
        )

    client = BailianClient(
        "llm-workspace",
        "sk-secret",
        "aid-service",
        transport=httpx.MockTransport(handler),
    )
    results = await client.search("BL0939 功能")

    assert len(results) == 1
    assert results[0]["media_id"] == "file-1"
    assert results[0]["title"] == "BL0939.pdf"
    assert results[0]["score"] == 0.91
    assert results[0]["chunk_ids"] == ["chunk-1", "chunk-2"]
    assert "UART" in results[0]["content"]
    assert results[0]["content_scope"] == "matched_chunks"


@pytest.mark.asyncio
async def test_search_classifies_authentication_failure_without_exposing_key():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid sk-secret"})

    client = BailianClient(
        "llm-workspace",
        "sk-secret",
        "aid-service",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(BailianAPIError) as exc_info:
        await client.search("测试")

    assert exc_info.value.code == "authentication_failed"
    assert "sk-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_search_rejects_missing_connection_before_network_call():
    client = BailianClient("", "", "")

    with pytest.raises(BailianAPIError) as exc_info:
        await client.search("测试")

    assert exc_info.value.code == "missing_credentials"
