from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.routes.agents import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_agent_tool_categories_expose_user_configurable_system_groups():
    client = _client()

    response = client.get("/api/agents/tool-categories")

    assert response.status_code == 200
    categories = response.json()["categories"]
    ids = [category["id"] for category in categories]
    assert "research" in ids
    assert "filesystem" in ids
    assert "mcp" not in ids
    assert "skills" not in ids
    research = next(category for category in categories if category["id"] == "research")
    assert "web_search" in research["tools"]


def test_create_agent_profile_rejects_invalid_tool_mode_before_store_access():
    client = _client()

    response = client.post(
        "/api/agents/profiles",
        json={
            "id": "bad-tools-mode",
            "name": "Bad Tools Mode",
            "tools_mode": "selected",
        },
    )

    assert response.status_code == 400
    assert "tools_mode must be one of" in response.json()["detail"]


def test_update_agent_profile_rejects_invalid_mcp_mode_before_store_access():
    client = _client()

    response = client.put(
        "/api/agents/profiles/default",
        json={"mcp_mode": "selected"},
    )

    assert response.status_code == 400
    assert "mcp_mode must be one of" in response.json()["detail"]
