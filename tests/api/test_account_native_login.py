from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from openkitsune.account.oidc import AccountOIDCManager
from openkitsune.api.auth import WebAccessConfig, create_auth_middleware
from openkitsune.api.routes.account_oidc import router


async def test_native_callback_requires_instance_authentication_and_never_returns_tokens(tmp_path):
    app = FastAPI()
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    app.state.account_oidc_manager = manager
    config = WebAccessConfig(tmp_path)
    config.change_password("test-password")
    app.middleware("http")(create_auth_middleware(config))
    app.include_router(router)
    headers = {"Authorization": f"Bearer {config.create_access_token()}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.42", 50000)),
        base_url="https://private-instance.test",
    ) as client:
        start = await client.post(
            "/api/account/login/start",
            headers=headers,
            json={
                "flow": "native",
                "redirect_uri": "https://account.openkitsune.cn/oauth/mobile/callback",
            },
        )
        assert start.status_code == 200
        payload = start.json()
        attempt = manager._attempts[payload["attempt_id"]]
        assert attempt.verifier not in start.text
        path = f"/api/account/login/native/callback/{attempt.attempt_id}"
        body = {"state": attempt.state, "code": "one-time-code"}
        assert (await client.post(path, json=body)).status_code == 401
        assert (
            await client.post(path, headers=headers, json={**body, "state": "wrong"})
        ).status_code == 400
        result = await client.post(path, headers=headers, json=body)
        assert result.json() == {"status": "complete", "error": None}
        assert result.headers["cache-control"] == "no-store"
        assert "token" not in result.text
        assert (await client.post(path, headers=headers, json=body)).json()["status"] == "complete"
        manager._complete.assert_awaited_once()
