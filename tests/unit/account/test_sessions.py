import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from openkitsune.account.oidc import AccountOIDCError, AccountOIDCManager
from tests.fixtures.account import MemoryTokenStore, mock_account_transport


def manager(monkeypatch, handler, token="refresh-a"):
    mock_account_transport(monkeypatch, handler)
    store = AsyncMock()
    store.snapshot.return_value = {"status": "active", "account_user_id": "a"}
    store.session_is_active.return_value = True
    return AccountOIDCManager(store=store, token_store=MemoryTokenStore(token))


@pytest.mark.asyncio
async def test_concurrent_refresh_rotates_only_once(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={
                "access_token": "access-b",
                "refresh_token": "refresh-b",
                "expires_in": 3600,
            },
        )

    subject = manager(monkeypatch, handler)
    result = await asyncio.gather(*[subject._valid_access_token() for _ in range(6)])
    assert result == ["access-b"] * 6
    assert len(calls) == 1
    assert subject._tokens.value == "refresh-b"


@pytest.mark.asyncio
async def test_logout_revokes_product_credential_without_browser_logout(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200)

    subject = manager(monkeypatch, handler)
    assert await subject.logout() == ""
    assert subject._tokens.value is None
    assert len(calls) == 1
    assert calls[0].url.path == "/oauth/revoke"
    assert b"token=refresh-a" in calls[0].content
    assert b"client_id=openkitsune-desktop" in calls[0].content


@pytest.mark.asyncio
async def test_failed_revocation_is_not_reported_as_success(monkeypatch):
    subject = manager(monkeypatch, lambda _: httpx.Response(503))
    with pytest.raises(AccountOIDCError):
        await subject.logout()
    assert subject._tokens.value == "refresh-a"


@pytest.mark.asyncio
async def test_handoff_uses_current_refresh_and_returns_only_ticket(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ticket": "t" * 64, "expires_in": 120})

    subject = manager(monkeypatch, handler)
    assert await subject.marketplace_handoff("https://marketplace.openkitsune.cn") == "t" * 64
    assert calls[0].url.path == "/oauth/desktop-handoff"
    assert b'"refresh_token":"refresh-a"' in calls[0].content


@pytest.mark.asyncio
async def test_signed_out_handoff_does_not_contact_provider(monkeypatch):
    def handler(_):
        pytest.fail("Signed-out browsing must not trigger provider login")

    subject = manager(monkeypatch, handler, token=None)
    assert await subject.marketplace_handoff("https://marketplace.openkitsune.cn") is None


@pytest.mark.asyncio
async def test_delayed_login_cannot_restore_identity_after_logout(monkeypatch):
    started = asyncio.Event()
    resume = asyncio.Event()

    async def handler(request):
        if request.url.path == "/oauth/token":
            started.set()
            await resume.wait()
            return httpx.Response(
                200,
                json={
                    "access_token": "access-b",
                    "refresh_token": "refresh-b",
                    "expires_in": 3600,
                },
            )
        if request.url.path == "/oauth/userinfo":
            return httpx.Response(200, json={"sub": "b"})
        return httpx.Response(200, json={})

    subject = manager(monkeypatch, handler)
    task = asyncio.create_task(subject._complete(code="code", verifier="verifier", generation=0))
    await started.wait()
    await subject.logout()
    resume.set()
    with pytest.raises(AccountOIDCError):
        await task
    assert subject._tokens.value is None
    subject._store.save_authenticated.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_outage_does_not_erase_refresh_token(monkeypatch):
    subject = manager(monkeypatch, lambda _: httpx.Response(503))
    with pytest.raises(AccountOIDCError):
        await subject._valid_access_token()
    assert subject._tokens.value == "refresh-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, {}])
async def test_failed_login_profile_revokes_new_grant_and_preserves_previous(monkeypatch, profile):
    revoked = []

    def handler(request):
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
        if request.url.path == "/oauth/userinfo":
            return httpx.Response(503) if profile is None else httpx.Response(200, json=profile)
        if request.url.path == "/oauth/revoke":
            revoked.append(request.content)
            return httpx.Response(200)
        pytest.fail("unexpected account request")

    subject = manager(monkeypatch, handler)
    with pytest.raises(AccountOIDCError):
        await subject._complete(code="code", verifier="verifier")
    assert revoked == [b"token=new-refresh&client_id=openkitsune-desktop"]
    assert subject._tokens.value == "refresh-a"
    subject._store.save_authenticated.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_attempt_timeout_does_not_close_new_listener(monkeypatch):
    from openkitsune.account.oidc import LoginAttempt

    subject = manager(monkeypatch, lambda _: httpx.Response(200))
    subject._generation = 2
    server = subject._server = AsyncMock()
    old = LoginAttempt("old", "s", "v", "https://example.com", generation=1)
    monkeypatch.setattr("openkitsune.account.oidc.asyncio.sleep", AsyncMock())
    subject._expire_attempt(old)
    server.close.assert_not_called()
    assert subject._generation == 2
