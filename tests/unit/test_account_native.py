import asyncio
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from openkitsune.account.oidc import (
    NATIVE_CALLBACK_URIS,
    AccountOIDCError,
    AccountOIDCManager,
    pkce_challenge,
)


@pytest.mark.parametrize("redirect", sorted(NATIVE_CALLBACK_URIS))
async def test_native_pkce_never_listens_on_backend_loopback(redirect, monkeypatch):
    listener = AsyncMock(side_effect=AssertionError("must not listen"))
    monkeypatch.setattr(asyncio, "start_server", listener)
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    attempt = await manager.start(flow="native", redirect_uri=redirect)
    query = parse_qs(urlsplit(attempt.authorization_url).query)
    verifier = attempt.verifier
    assert query["code_challenge"] == [pkce_challenge(verifier)]
    assert query["redirect_uri"] == [redirect]
    with pytest.raises(AccountOIDCError, match="state"):
        await manager.complete_native_callback(attempt.attempt_id, state="wrong", code="code")
    assert attempt.status == "pending"
    results = await asyncio.gather(
        *[
            manager.complete_native_callback(attempt.attempt_id, state=attempt.state, code="code")
            for _ in range(2)
        ]
    )
    assert all(result["status"] == "complete" for result in results)
    manager._complete.assert_awaited_once_with(
        code="code", verifier=verifier, redirect_uri=redirect, generation=attempt.generation
    )
    assert not attempt.verifier
    listener.assert_not_awaited()


@pytest.mark.parametrize(
    "redirect",
    [
        None,
        "https://evil.example/callback",
        "http://127.0.0.1:1455/auth/callback",
        "com.openkitsune.mobile:/other",
    ],
)
async def test_native_redirect_allowlist(redirect):
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    with pytest.raises(AccountOIDCError, match="redirect"):
        await manager.start(flow="native", redirect_uri=redirect)
    assert not manager._attempts


@pytest.mark.parametrize(
    "condition", ["expired", "cancelled", "denied", "ambiguous", "other_instance"]
)
async def test_native_rejects_unusable_or_foreign_attempts(condition):
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    attempt = await manager.start(flow="native", redirect_uri=next(iter(NATIVE_CALLBACK_URIS)))
    kwargs = {"state": attempt.state, "code": "code"}
    if condition == "expired":
        attempt.created_at -= 3600
    if condition == "cancelled":
        await manager.cancel(attempt.attempt_id)
    if condition == "ambiguous":
        kwargs["error"] = "access_denied"
    if condition == "other_instance":
        manager._attempts.clear()
    if condition == "denied":
        result = await manager.complete_native_callback(
            attempt.attempt_id, state=attempt.state, error="access_denied"
        )
        assert result["status"] == "failed"
    elif condition in {"expired", "cancelled"}:
        result = await manager.complete_native_callback(attempt.attempt_id, **kwargs)
        assert result["status"] == condition
    else:
        with pytest.raises(AccountOIDCError):
            await manager.complete_native_callback(attempt.attempt_id, **kwargs)
    manager._complete.assert_not_awaited()
