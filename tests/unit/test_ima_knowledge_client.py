from __future__ import annotations

import json

import httpx
import pytest

from openkitsune.integrations.knowledge.ima import IMAAPIError, IMAClient


@pytest.mark.asyncio
async def test_list_addable_knowledge_bases_uses_official_headers_and_normalizes_items():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://ima.qq.com/openapi/wiki/v1/get_addable_knowledge_base_list"
        )
        assert request.headers["ima-openapi-clientid"] == "client-id"
        assert request.headers["ima-openapi-apikey"] == "api-key"
        return httpx.Response(
            200,
            json={
                "retcode": 0,
                "errmsg": "success",
                "data": {
                    "addable_knowledge_base_list": [
                        {"id": "kb-1", "name": "产品资料"},
                        {"id": "", "name": "ignored"},
                    ]
                },
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    assert await client.list_addable_knowledge_bases() == [{"id": "kb-1", "name": "产品资料"}]


@pytest.mark.asyncio
async def test_search_knowledge_normalizes_public_highlight_fields():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "retcode": 0,
                "data": {
                    "info_list": [
                        {
                            "media_id": "media-1",
                            "title": "发布流程",
                            "parent_folder_id": "folder-1",
                            "highlight_content": "发布前需要完成回归测试",
                        }
                    ]
                },
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    assert await client.search_knowledge(knowledge_base_id="kb-1", query="回归测试") == [
        {
            "media_id": "media-1",
            "title": "发布流程",
            "parent_folder_id": "folder-1",
            "highlight_content": "发布前需要完成回归测试",
            "excerpt_available": True,
            "match_type": "content",
        }
    ]


@pytest.mark.asyncio
async def test_search_knowledge_marks_title_only_results_for_followup_read():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "retcode": 0,
                "data": {
                    "info_list": [
                        {
                            "media_id": "media-1",
                            "title": "BL0939.pdf",
                            "parent_folder_id": "folder-1",
                            "highlight_content": "",
                        }
                    ]
                },
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    result = await client.search_knowledge(knowledge_base_id="kb-1", query="BL0939")

    assert result[0]["excerpt_available"] is False
    assert result[0]["match_type"] == "title_only"


@pytest.mark.asyncio
async def test_get_knowledge_list_browses_folder_and_normalizes_files_and_folders():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://ima.qq.com/openapi/wiki/v1/get_knowledge_list"
        )
        assert json.loads(request.content) == {
            "cursor": "page-1",
            "limit": 20,
            "knowledge_base_id": "kb-1",
            "folder_id": "folder-parent",
        }
        return httpx.Response(
            200,
            json={
                "retcode": 0,
                "data": {
                    "knowledge_list": [
                        {
                            "media_id": "media-1",
                            "title": "产品手册.pdf",
                            "media_type": 1,
                            "parent_folder_id": "folder-parent",
                        },
                        {
                            "folder_id": "folder-child",
                            "name": "发布资料",
                            "file_number": 3,
                            "folder_number": 1,
                            "parent_folder_id": "folder-parent",
                        },
                    ],
                    "is_end": False,
                    "next_cursor": "page-2",
                    "current_path": [
                        {"folder_id": "folder-parent", "name": "产品资料"}
                    ],
                },
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    assert await client.get_knowledge_list(
        knowledge_base_id="kb-1",
        folder_id="folder-parent",
        cursor="page-1",
    ) == {
        "items": [
            {
                "type": "file",
                "title": "产品手册.pdf",
                "parent_folder_id": "folder-parent",
                "media_id": "media-1",
                "media_type": 1,
            },
            {
                "type": "folder",
                "title": "发布资料",
                "parent_folder_id": "folder-parent",
                "folder_id": "folder-child",
                "file_count": 3,
                "folder_count": 1,
            },
        ],
        "is_end": False,
        "next_cursor": "page-2",
        "current_path": [{"folder_id": "folder-parent", "name": "产品资料"}],
    }


@pytest.mark.asyncio
async def test_search_knowledge_page_preserves_cursor_metadata():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["cursor"] == "next-page"
        return httpx.Response(
            200,
            json={
                "retcode": 0,
                "data": {"info_list": [], "is_end": False, "next_cursor": "last-page"},
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    assert await client.search_knowledge_page(
        knowledge_base_id="kb-1", query="发布", cursor="next-page"
    ) == {"items": [], "is_end": False, "next_cursor": "last-page"}


@pytest.mark.asyncio
async def test_ima_business_error_is_sanitized_and_classified():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"retcode": 40101, "errmsg": "凭证无效"})

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    with pytest.raises(IMAAPIError) as exc_info:
        await client.list_addable_knowledge_bases()

    assert exc_info.value.code == "ima_40101"
    assert str(exc_info.value) == "凭证无效"
    assert "api-key" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_media_info_supports_code_msg_response_and_normalizes_access_data():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://ima.qq.com/openapi/wiki/v1/get_media_info")
        assert json.loads(request.content) == {"media_id": "media-1"}
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "media_type": 1,
                    "url_info": {
                        "url": "https://res-pkb.ima.qq.com/document.pdf",
                        "headers": {"X-IMA-Token": "temporary-token"},
                    },
                },
            },
        )

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    assert await client.get_media_info(media_id="media-1") == {
        "media_type": 1,
        "url": "https://res-pkb.ima.qq.com/document.pdf",
        "headers": {"X-IMA-Token": "temporary-token"},
        "notebook_id": "",
    }


@pytest.mark.asyncio
async def test_get_media_info_classifies_code_msg_business_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 110001, "msg": "参数非法"})

    client = IMAClient("client-id", "api-key", transport=httpx.MockTransport(handler))

    with pytest.raises(IMAAPIError) as exc_info:
        await client.get_media_info(media_id="media-1")

    assert exc_info.value.code == "ima_110001"
    assert str(exc_info.value) == "参数非法"


@pytest.mark.asyncio
async def test_read_media_text_returns_bounded_plain_text(monkeypatch: pytest.MonkeyPatch):
    client = IMAClient("client-id", "api-key")

    async def fake_media_info(**_params):
        return {
            "media_type": 13,
            "url": "https://res-pkb.ima.qq.com/document.txt",
            "headers": {},
            "notebook_id": "",
        }

    async def fake_download(**_params):
        return "知识正文".encode(), "text/plain"

    monkeypatch.setattr(client, "get_media_info", fake_media_info)
    monkeypatch.setattr(client, "_download_media", fake_download)

    assert await client.read_media_text(media_id="media-1") == {
        "media_type": 13,
        "content_type": "text/plain",
        "content": "知识正文",
        "char_count": 4,
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_ima_client_rejects_missing_credentials_without_network_call():
    client = IMAClient("", "")

    with pytest.raises(IMAAPIError) as exc_info:
        await client.list_addable_knowledge_bases()

    assert exc_info.value.code == "missing_credentials"
