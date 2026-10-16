from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from openkitsune.account.oidc import AccountOIDCManager
from openkitsune.api.auth import WebAccessConfig, create_auth_middleware
from openkitsune.api.routes.account_oidc import router


async def test_remote_device_login_keeps_credentials_in_backend(tmp_path, monkeypatch):
    app = FastAPI()
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._accept_tokens = AsyncMock()
    app.state.account_oidc_manager = manager
    config = WebAccessConfig(tmp_path)
    config.change_password("test-password")
    app.middleware("http")(create_auth_middleware(config))
    app.include_router(router)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.42", 50000)),
        base_url="https://arbitrary-server.example",
    )
    original = httpx.AsyncClient
    calls = []

    def provider(request):
        calls.append(request)
        if request.url.path.endswith("device_authorization"):
            return httpx.Response(
                200,
                json={
                    "device_code": "secret-for-backend-only",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://account.example/device",
                    "verification_uri_complete": "https://account.example/device?user_code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(provider))
    )
    headers = {"Authorization": f"Bearer {config.create_access_token()}"}
    async with client:
        assert (
            await client.post("/api/account/login/start", json={"flow": "device"})
        ).status_code == 401
        started = await client.post(
            "/api/account/login/start", headers=headers, json={"flow": "device"}
        )
        assert started.status_code == 200
        payload = started.json()
        assert payload["flow"] == "device" and payload["user_code"] == "ABCD-EFGH"
        assert "secret-for-backend-only" not in started.text and "set-cookie" not in started.headers
        attempt = manager._attempts[payload["attempt_id"]]
        path = f"/api/account/login/status/{attempt.attempt_id}"
        assert (await client.get(path)).status_code == 401
        assert (
            await client.post(f"/api/account/login/cancel/{attempt.attempt_id}")
        ).status_code == 401
        attempt.next_poll_at = 0
        result = await client.get(path, headers=headers)
        assert result.json()["status"] == "complete"
        assert result.headers["Cache-Control"] == "no-store"
        assert "access" not in result.text and "refresh" not in result.text
        manager._accept_tokens.assert_awaited_once()
        assert len(calls) == 2
    assert "/api/account/login/callback" not in app.openapi()["paths"]
