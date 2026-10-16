from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.routes import marketplace


@pytest.fixture
def catalog_client(monkeypatch):
    monkeypatch.delenv("OPENKITSUNE_MARKETPLACE_URL", raising=False)
    app = FastAPI()
    app.include_router(marketplace.router)
    get = AsyncMock(
        return_value=httpx.Response(
            200,
            request=httpx.Request("GET", "https://marketplace.openkitsune.cn/api/v1/resources"),
            json={
                "items": [{"id": "one", "slug": "demo", "name": "Demo", "resource_type": "skill"}],
                "total": 1,
                "facets": {"categories": [{"value": "coding", "count": 1}]},
            },
        )
    )
    monkeypatch.setattr(marketplace.httpx.AsyncClient, "get", get)
    return TestClient(app), get


def test_public_catalog_filters_skills_without_forwarding_credentials(catalog_client):
    client, get = catalog_client
    response = client.get(
        "/api/marketplace/skills?q=demo&category=coding&sort=new&limit=10&offset=20",
        headers={"Authorization": "Bearer private", "Cookie": "session=private"},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["slug"] == "demo"
    assert response.json()["origin"] == "https://marketplace.openkitsune.cn"
    get.assert_awaited_once_with(
        "https://marketplace.openkitsune.cn/api/v1/resources",
        params={
            "type": "skill",
            "q": "demo",
            "category": "coding",
            "sort": "new",
            "limit": 10,
            "offset": 20,
        },
    )


@pytest.mark.parametrize("query", ["limit=101", "offset=-1", "sort=unknown", "q=" + "a" * 301])
def test_catalog_rejects_invalid_queries(catalog_client, query):
    client, get = catalog_client
    assert client.get(f"/api/marketplace/skills?{query}").status_code == 422
    get.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": [], "total": -1},
        {
            "items": [{"id": "one", "slug": "demo", "name": "Demo", "resource_type": "plugin"}],
            "total": 1,
        },
    ],
)
def test_invalid_catalog_is_unavailable_not_empty(catalog_client, payload):
    client, get = catalog_client
    get.return_value = httpx.Response(
        200, request=httpx.Request("GET", "https://marketplace.openkitsune.cn"), json=payload
    )
    response = client.get("/api/marketplace/skills")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "marketplace_catalog_unavailable"


def test_catalog_timeout_is_not_an_empty_market(catalog_client):
    client, get = catalog_client
    get.side_effect = httpx.ReadTimeout("offline")
    assert client.get("/api/marketplace/skills").status_code == 502


def test_catalog_uses_explicit_development_origin(catalog_client, monkeypatch):
    client, get = catalog_client
    monkeypatch.setenv("OPENKITSUNE_MARKETPLACE_URL", "http://127.0.0.1:8090")
    assert client.get("/api/marketplace/skills").json()["origin"] == "http://127.0.0.1:8090"
    assert get.call_args.args[0] == "http://127.0.0.1:8090/api/v1/resources"
