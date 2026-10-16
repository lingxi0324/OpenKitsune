import hashlib
import json
import time

import httpx
import pytest

from openkitsune.account.oidc import AccountOIDCManager
from openkitsune.account.status_store import AccountStatusStore
from tests.fixtures.account import MemoryTokenStore, mock_account_transport


@pytest.mark.asyncio
async def test_refresh_identity_is_versioned_and_bound_to_current_grant(tmp_path, monkeypatch):
    store = AccountStatusStore(tmp_path)
    tokens = MemoryTokenStore("refresh")
    digest = hashlib.sha256(b"refresh").hexdigest()
    await store.save_authenticated(
        account_user_id="current",
        session_id="session",
        credential_hash=digest,
        profile_json=json.dumps({"sub": "current", "identity_version": 1, "email_verified": False}),
    )
    manager = AccountOIDCManager(store=store, token_store=tokens)
    manager._access_token = "access"
    manager._access_expires_at = time.time() + 3600
    # Prevent the access cache's owner check from needing a token rotation.
    manager._account_user_id = "current"
    profile = {"sub": "current", "identity_version": 2, "email_verified": True}
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
            )
        return httpx.Response(200, json=profile)

    mock_account_transport(monkeypatch, handle)
    assert (await manager.snapshot())["profile"]["email_verified"] is False
    assert not calls
    assert (await manager.snapshot(force=True))["profile"]["email_verified"] is True
    profile.update(identity_version=1, email_verified=False)
    assert (await manager.snapshot(force=True))["profile"]["email_verified"] is True
    profile.update(identity_version=3, email_verified=False)
    assert (await manager.snapshot(force=True))["profile"]["email_verified"] is False
    profile.update(sub="other", identity_version=4)
    assert (await manager.snapshot(force=True))["status"] == "unavailable"
    assert (await store.snapshot(credential_hash=digest))["account_user_id"] == "current"
    profile.update(sub="current", identity_version=None)
    assert (await manager.snapshot(force=True))["status"] == "unavailable"
    assert tokens.value == "refresh"


@pytest.mark.asyncio
async def test_identity_outage_preserves_snapshot_and_credential(tmp_path, monkeypatch):
    store = AccountStatusStore(tmp_path)
    tokens = MemoryTokenStore("refresh")
    digest = hashlib.sha256(b"refresh").hexdigest()
    await store.save_authenticated(
        account_user_id="current",
        session_id="s",
        credential_hash=digest,
        profile_json=json.dumps({"sub": "current", "identity_version": 4}),
    )
    mock_account_transport(monkeypatch, lambda _: httpx.Response(503))
    result = await AccountOIDCManager(store=store, token_store=tokens).snapshot(force=True)
    assert result["status"] == "unavailable"
    assert result["profile"]["identity_version"] == 4
    assert tokens.value == "refresh"
    assert (await store.snapshot(credential_hash=digest))["status"] == "active"
