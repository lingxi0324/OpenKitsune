import asyncio
import time
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs

import httpx
import pytest

from openkitsune.account.oidc import DEVICE_GRANT_TYPE, AccountOIDCError, AccountOIDCManager


@pytest.fixture
def device_provider(monkeypatch):
    replies = []
    requests = []
    payload = {
        "device_code": "private-device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://account.example/device",
        "verification_uri_complete": "https://account.example/device?user_code=ABCD-EFGH",
        "expires_in": 600,
        "interval": 5,
    }

    def handler(request):
        requests.append(request)
        if request.url.path == "/oauth/device_authorization":
            return httpx.Response(200, json=payload)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            **kwargs,
            transport=httpx.MockTransport(handler),
        ),
    )
    manager = AccountOIDCManager(
        store=AsyncMock(), token_store=AsyncMock(), account_base_url="https://account.example"
    )
    manager._accept_tokens = AsyncMock()
    return manager, replies, requests, payload


async def ready_poll(manager, attempt):
    attempt.next_poll_at = 0
    return await manager.attempt_status(attempt.attempt_id)


async def test_device_login_requires_no_callback_listener_or_configuration(
    device_provider, monkeypatch
):
    manager, replies, requests, _ = device_provider
    listener = AsyncMock(side_effect=OSError("occupied"))
    monkeypatch.setattr(asyncio, "start_server", listener)
    attempt = await manager.start(flow="device")
    assert attempt.user_code == "ABCD-EFGH"
    assert attempt.authorization_url.endswith("?user_code=ABCD-EFGH")
    assert "private-device-secret" not in repr(attempt)
    assert "redirect_uri" not in parse_qs(requests[0].content.decode())
    listener.assert_not_called()
    await manager.attempt_status(attempt.attempt_id)
    assert len(requests) == 1  # wait for the provider's initial interval


async def test_pending_slow_down_and_timeout_backoff_are_respected(device_provider):
    manager, replies, requests, _ = device_provider
    attempt = await manager.start(flow="device")
    for response, interval in [
        (httpx.Response(400, json={"error": "authorization_pending"}), 5),
        (httpx.Response(400, json={"error": "slow_down"}), 10),
        (httpx.ReadTimeout("timeout"), 20),
        (httpx.Response(503), 40),
    ]:
        replies.append(response)
        assert (await ready_poll(manager, attempt))["status"] == "pending"
        assert attempt.poll_interval == interval
        count = len(requests)
        await manager.attempt_status(attempt.attempt_id)
        assert len(requests) == count


async def test_device_redemption_happens_once_with_concurrent_frontend_polls(device_provider):
    manager, replies, requests, _ = device_provider
    attempt = await manager.start(flow="device")
    replies.append(httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"}))
    attempt.next_poll_at = 0
    results = await asyncio.gather(*[manager.attempt_status(attempt.attempt_id) for _ in range(3)])
    assert all(item["status"] == "complete" for item in results)
    assert len(requests) == 2
    assert parse_qs(requests[-1].content.decode())["grant_type"] == [DEVICE_GRANT_TYPE]
    manager._accept_tokens.assert_awaited_once_with(
        {"access_token": "access", "refresh_token": "refresh"}, attempt.generation
    )
    assert attempt.device_code == ""


@pytest.mark.parametrize(
    ("error", "status"),
    [("access_denied", "failed"), ("expired_token", "expired"), ("invalid_grant", "failed")],
)
async def test_device_terminal_provider_responses(device_provider, error, status):
    manager, replies, _, _ = device_provider
    attempt = await manager.start(flow="device")
    replies.append(httpx.Response(400, json={"error": error}))
    assert (await ready_poll(manager, attempt))["status"] == status
    assert not attempt.device_code
    manager._accept_tokens.assert_not_called()


@pytest.mark.parametrize("action", ["cancel", "expire", "logout"])
async def test_cancel_expiry_logout_stop_polling(device_provider, action):
    manager, replies, requests, _ = device_provider
    attempt = await manager.start(flow="device")
    if action == "cancel":
        await manager.cancel(attempt.attempt_id)
    elif action == "expire":
        attempt.created_at = time.time() - 601
    else:
        manager._tokens.load_refresh_token.return_value = None
        await manager.logout()
    await ready_poll(manager, attempt)
    assert attempt.status in {"cancelled", "expired"}
    assert len(requests) == 1 and not attempt.device_code


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_in", 0),
        ("interval", -1),
        ("device_code", ""),
        ("verification_uri_complete", "javascript:alert(1)"),
    ],
)
async def test_invalid_device_response_is_not_used(device_provider, field, value):
    manager, _, _, payload = device_provider
    payload[field] = value
    with pytest.raises(AccountOIDCError, match="account_device_start_failed"):
        await manager.start(flow="device")


async def test_missing_complete_uri_uses_verification_uri(device_provider):
    manager, _, _, payload = device_provider
    payload.pop("verification_uri_complete")
    attempt = await manager.start(flow="device")
    assert attempt.authorization_url == payload["verification_uri"]
    assert attempt.user_code


async def test_old_account_service_reports_upgrade_instead_of_loopback(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            **kw, transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ),
    )
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    with pytest.raises(AccountOIDCError, match="account_device_not_supported"):
        await manager.start(flow="device")
    assert not manager._attempts and manager._server is None


async def test_new_device_login_supersedes_loopback_without_closing_future_listener(
    device_provider, monkeypatch
):
    manager, _, _, _ = device_provider
    server = Mock()
    server.wait_closed = AsyncMock()
    monkeypatch.setattr(asyncio, "start_server", AsyncMock(return_value=server))
    desktop = await manager.start()
    remote = await manager.start(flow="device")
    manager._expire_attempt(remote)
    server.close.assert_called_once()
    assert desktop.status == "expired"
    await manager.cancel(desktop.attempt_id)
    server.close.assert_called_once()


async def test_tokens_use_existing_identity_and_keyring_storage(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            **kw,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"sub": "user-1"})
            ),
        ),
    )
    tokens, store = AsyncMock(), AsyncMock()
    manager = AccountOIDCManager(store=store, token_store=tokens)
    manager._refresh_entitlements_locked = AsyncMock()
    tokens.load_refresh_token.return_value = None
    await manager._accept_tokens({"access_token": "access", "refresh_token": "refresh"}, manager._generation)
    tokens.save_refresh_token.assert_awaited_once_with("refresh")
    store.save_authenticated.assert_awaited_once()


async def test_interrupted_token_persistence_is_terminal(device_provider):
    manager, replies, requests, _ = device_provider
    attempt = await manager.start(flow="device")
    replies.append(httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"}))
    manager._accept_tokens.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await ready_poll(manager, attempt)
    assert attempt.status == "failed" and not attempt.device_code
    await ready_poll(manager, attempt)
    assert len(requests) == 2
