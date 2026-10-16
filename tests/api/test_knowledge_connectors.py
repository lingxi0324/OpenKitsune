from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from openkitsune.api.routes import knowledge
from openkitsune.integrations.knowledge import BailianAPIError, IMAAPIError


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FastAPI:
    monkeypatch.setattr(knowledge, "_project_root", lambda: tmp_path)
    test_app = FastAPI()
    test_app.include_router(knowledge.router)
    return test_app


@pytest.mark.asyncio
async def test_connector_catalog_reports_preconfigured_ima_without_exposing_secrets(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client-secret-value")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key-secret-value")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/knowledge/connectors")

    assert response.status_code == 200
    data = response.json()
    assert data["connectors"][0]["configured"] is True
    assert "client-secret-value" not in response.text
    assert "key-secret-value" not in response.text


@pytest.mark.asyncio
async def test_validate_ima_returns_normalized_knowledge_bases(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, str] = {}

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            captured.update(client_id=client_id, api_key=api_key)

        async def list_addable_knowledge_bases(self) -> list[dict[str, str]]:
            return [{"id": "kb-1", "name": "项目资料"}]

    monkeypatch.setattr(knowledge, "IMAClient", FakeIMAClient)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/knowledge/ima/validate",
            json={"client_id": "client-id", "api_key": "api-key"},
        )

    assert response.status_code == 200
    assert response.json()["knowledge_bases"] == [{"id": "kb-1", "name": "项目资料"}]
    assert captured == {"client_id": "client-id", "api_key": "api-key"}
    assert "api-key" not in response.text


@pytest.mark.asyncio
async def test_validate_ima_returns_safe_api_error(app: FastAPI, monkeypatch: pytest.MonkeyPatch):
    class FailingIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            pass

        async def list_addable_knowledge_bases(self) -> list[dict[str, str]]:
            raise IMAAPIError("凭证无效", code="ima_40101")

    monkeypatch.setattr(knowledge, "IMAClient", FailingIMAClient)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/knowledge/ima/validate",
            json={"client_id": "client-id", "api_key": "secret-api-key"},
        )

    assert response.json()["ok"] is False
    assert response.json()["error_code"] == "ima_40101"
    assert "secret-api-key" not in response.text


@pytest.mark.asyncio
async def test_configure_ima_persists_credentials_and_read_only_scope(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "old-client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "old-key")

    class FakeIMAClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            assert client_id == "new-client"
            assert api_key == "new-key"

        async def list_addable_knowledge_bases(self) -> list[dict[str, str]]:
            return [
                {"id": "kb-1", "name": "项目资料"},
                {"id": "kb-2", "name": "产品手册"},
            ]

    monkeypatch.setattr(knowledge, "IMAClient", FakeIMAClient)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/knowledge/ima/config",
            json={
                "client_id": "new-client",
                "api_key": "new-key",
                "enabled": True,
                "auto_retrieve": True,
                "prefer_knowledge": True,
                "knowledge_bases": [{"id": "kb-1", "name": "ignored-name"}],
                "top_k": 4,
            },
        )
        catalog_response = await client.get("/api/knowledge/connectors")

    assert response.status_code == 200
    assert response.json()["knowledge_bases"] == [{"id": "kb-1", "name": "项目资料"}]
    connector = catalog_response.json()["connectors"][0]
    assert connector["enabled"] is True
    assert connector["auto_retrieve"] is True
    assert connector["prefer_knowledge"] is True
    assert connector["knowledge_bases"] == [{"id": "kb-1", "name": "项目资料"}]
    assert connector["top_k"] == 4

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "IMA_OPENAPI_CLIENTID=new-client" in env_text
    assert "IMA_OPENAPI_APIKEY=new-key" in env_text
    assert "new-key" not in catalog_response.text


@pytest.mark.asyncio
async def test_configure_ima_rejects_enabled_connection_without_selection(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "key")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/knowledge/ima/config",
            json={
                "enabled": True,
                "auto_retrieve": True,
                "prefer_knowledge": True,
                "knowledge_bases": [],
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "请至少选择一个知识库"


@pytest.mark.asyncio
async def test_validate_bailian_uses_workspace_service_and_api_key(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    captured = {}

    class FakeBailianClient:
        def __init__(self, workspace_id, api_key, agent_id, *, region):
            captured.update(
                workspace_id=workspace_id,
                api_key=api_key,
                agent_id=agent_id,
                region=region,
            )

        async def search(self, query: str, *, limit: int):
            assert (query, limit) == ("OpenKitsune 连接测试", 1)
            return []

    monkeypatch.setattr(knowledge, "BailianClient", FakeBailianClient)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/knowledge/bailian/validate",
            json={
                "workspace_id": "llm-workspace",
                "agent_id": "aid-service",
                "api_key": "sk-secret",
                "service_name": "产品资料",
            },
        )

    assert response.json()["ok"] is True
    assert response.json()["knowledge_bases"] == [{"id": "aid-service", "name": "产品资料"}]
    assert captured["api_key"] == "sk-secret"
    assert "sk-secret" not in response.text


@pytest.mark.asyncio
async def test_configure_bailian_persists_safe_connector_summary(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    class FakeBailianClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, _query: str, *, limit: int):
            assert limit == 1
            return []

    monkeypatch.setattr(knowledge, "BailianClient", FakeBailianClient)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/knowledge/bailian/config",
            json={
                "workspace_id": "llm-workspace",
                "agent_id": "aid-service",
                "api_key": "sk-secret",
                "service_name": "产品资料",
                "enabled": True,
                "auto_retrieve": True,
                "prefer_knowledge": True,
                "top_k": 8,
            },
        )
        catalog = await client.get("/api/knowledge/connectors")

    assert response.status_code == 200
    connector = catalog.json()["connectors"][1]
    assert connector["configured"] is True
    assert connector["enabled"] is True
    assert connector["prefer_knowledge"] is True
    assert connector["knowledge_bases"] == [{"id": "aid-service", "name": "产品资料"}]
    assert connector["top_k"] == 8
    assert "sk-secret" not in catalog.text
    assert "BAILIAN_KNOWLEDGE_API_KEY=sk-secret" in (tmp_path / ".env").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_validate_bailian_returns_safe_error(app: FastAPI, monkeypatch: pytest.MonkeyPatch):
    class FailingBailianClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, _query: str, *, limit: int):
            raise BailianAPIError("凭证无效", code="authentication_failed")

    monkeypatch.setattr(knowledge, "BailianClient", FailingBailianClient)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/knowledge/bailian/validate",
            json={
                "workspace_id": "llm-workspace",
                "agent_id": "aid-service",
                "api_key": "sk-secret",
            },
        )

    assert response.json()["ok"] is False
    assert response.json()["error_code"] == "authentication_failed"
    assert "sk-secret" not in response.text


@pytest.mark.asyncio
async def test_disabling_ima_is_local_only_and_preserves_selection(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "saved-client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "saved-key")
    knowledge.save_ima_config(
        {
            "configured": True,
            "enabled": True,
            "auto_retrieve": True,
            "prefer_knowledge": True,
            "knowledge_bases": [{"id": "kb-1", "name": "项目资料"}],
            "top_k": 5,
        },
        knowledge._ima_config_path(),
    )

    class UnexpectedIMAClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("disabling must not call ima")

    monkeypatch.setattr(knowledge, "IMAClient", UnexpectedIMAClient)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/knowledge/ima/config",
            json={
                "enabled": False,
                "auto_retrieve": True,
                "prefer_knowledge": True,
                "knowledge_bases": [],
            },
        )
        catalog = await client.get("/api/knowledge/connectors")

    assert response.status_code == 200
    connector = catalog.json()["connectors"][0]
    assert connector["configured"] is True
    assert connector["enabled"] is False
    assert connector["knowledge_bases"] == [{"id": "kb-1", "name": "项目资料"}]


@pytest.mark.asyncio
async def test_removing_ima_persists_disconnect_even_if_external_credentials_return(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "external-client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "external-key")
    knowledge.save_ima_config(
        {
            "configured": True,
            "enabled": True,
            "knowledge_bases": [{"id": "kb-1", "name": "项目资料"}],
        },
        knowledge._ima_config_path(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/api/knowledge/ima/config")
        monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "external-client")
        monkeypatch.setenv("IMA_OPENAPI_APIKEY", "external-key")
        catalog = await client.get("/api/knowledge/connectors")

    assert response.status_code == 200
    connector = catalog.json()["connectors"][0]
    assert connector["configured"] is False
    assert connector["enabled"] is False
    assert connector["knowledge_bases"] == []


@pytest.mark.asyncio
async def test_disabling_bailian_does_not_call_remote_search(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("BAILIAN_KNOWLEDGE_API_KEY", "saved-key")
    knowledge.save_bailian_config(
        {
            "configured": True,
            "enabled": True,
            "workspace_id": "llm-workspace",
            "agent_id": "aid-service",
            "service_name": "产品资料",
        },
        knowledge._ima_config_path(),
    )

    class UnexpectedBailianClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("disabling must not call Bailian")

    monkeypatch.setattr(knowledge, "BailianClient", UnexpectedBailianClient)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/knowledge/bailian/config",
            json={
                "enabled": False,
                "workspace_id": "",
                "agent_id": "",
                "api_key": "",
            },
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
