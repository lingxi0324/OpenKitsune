"""Contracts for IM adapter startup errors exposed to Setup Center."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from openkitsune.api.routes.im import router


@pytest.mark.asyncio
async def test_channel_list_exposes_startup_error_only_while_offline(monkeypatch):
    monkeypatch.setattr(
        "openkitsune.agents.profile.get_profile_store",
        lambda: SimpleNamespace(list_all=lambda: []),
    )

    adapter = SimpleNamespace(
        channel_type="feishu",
        bot_id="feishu-test",
        display_name="Test Feishu",
        agent_profile_id="default",
        is_running=False,
        _running=False,
    )
    gateway = SimpleNamespace(
        _adapters={"feishu:feishu-test": adapter},
        _failed_adapter_reasons={
            "feishu:feishu-test": "module 'lark_oapi' has no attribute 'LogLevel'"
        },
        adapters=[],
    )

    app = FastAPI()
    app.include_router(router)
    app.state.gateway = gateway
    app.state.session_manager = None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/im/channels")
        assert response.status_code == 200
        channel = next(
            item for item in response.json()["channels"] if item["channel"] == "feishu:feishu-test"
        )
        assert channel["status"] == "error"
        assert "lark_oapi" in channel["error"]
        assert "LogLevel" in channel["error"]

        adapter.is_running = True
        adapter._running = True
        response = await client.get("/api/im/channels")
        channel = next(
            item for item in response.json()["channels"] if item["channel"] == "feishu:feishu-test"
        )
        assert channel["status"] == "online"
        assert "error" not in channel


@pytest.mark.asyncio
async def test_channel_list_exposes_dependency_install_state(monkeypatch):
    import openkitsune.config as config

    monkeypatch.setattr(
        "openkitsune.agents.profile.get_profile_store",
        lambda: SimpleNamespace(list_all=lambda: []),
    )
    monkeypatch.setattr(
        "openkitsune.channels.runtime_status.resolve_bot_runtime_state",
        lambda channel, _gateway=None: {
            "status": "installing_dependencies" if channel == "feishu:feishu-test" else "unknown",
            "error": None,
            "progress": {
                "phase": "downloading",
                "percent": 37.5,
                "current_package": "lark-oapi",
            }
            if channel == "feishu:feishu-test"
            else None,
        },
    )
    monkeypatch.setattr(
        config.settings,
        "im_bots",
        [
            {
                "id": "feishu-test",
                "type": "feishu",
                "name": "Test Feishu",
                "enabled": True,
                "credentials": {"app_id": "cli_xxx", "app_secret": "secret"},
            }
        ],
        raising=False,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.gateway = SimpleNamespace(_adapters={}, adapters=[])
    app.state.session_manager = None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/im/channels")

    channel = next(
        item for item in response.json()["channels"] if item["channel"] == "feishu:feishu-test"
    )
    assert channel["status"] == "installing_dependencies"
    assert channel["progress"]["percent"] == 37.5
    assert channel["progress"]["current_package"] == "lark-oapi"
    assert "error" not in channel
