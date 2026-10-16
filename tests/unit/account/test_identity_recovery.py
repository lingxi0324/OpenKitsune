import asyncio
import hashlib
import json

import httpx
import pytest

from openkitsune.account.config import AccountFeatureConfig
from openkitsune.account.oidc import AccountOIDCError, AccountOIDCManager, KeyringTokenStore
from openkitsune.account.status_store import AccountStatusStore
from tests.fixtures.account import MemoryTokenStore, mock_account_transport


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def provider(calls):
    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "rotated",
                    "expires_in": 3600,
                },
            )
        if request.url.path == "/oauth/userinfo":
            return httpx.Response(200, json={"sub": "current", "name": "Current account"})
        if request.url.path == "/oauth/desktop-handoff":
            return httpx.Response(200, json={"ticket": "t" * 64})
        if request.url.path == "/oauth/desktop-install-proof":
            return httpx.Response(200, json={"proof": "p" * 64})
        return httpx.Response(200, json={})

    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["snapshot", "handoff", "install"])
async def test_orphan_credential_recovers_verified_owner_before_any_use(
    tmp_path, monkeypatch, entry
):
    calls = []
    mock_account_transport(monkeypatch, provider(calls))
    store, tokens = AccountStatusStore(tmp_path), MemoryTokenStore("legacy-refresh")
    # An old workspace cache is not proof that this token belongs to that user.
    await store.save_authenticated(
        account_user_id="old",
        profile_json=json.dumps({"sub": "old"}),
        session_id="old-session",
    )
    subject = AccountOIDCManager(store=store, token_store=tokens)
    if entry == "snapshot":
        assert (await subject.snapshot())["account_user_id"] == "current"
    elif entry == "handoff":
        assert await subject.marketplace_handoff("https://marketplace.openkitsune.cn") == "t" * 64
    else:
        assert await subject.marketplace_install_proof("instruction", "device") == "p" * 64
    assert calls[:2] == ["/oauth/token", "/oauth/userinfo"]
    assert tokens.value == "rotated"
    assert (await store.snapshot(credential_hash=digest("rotated")))["account_user_id"] == "current"
    # Restart / another workspace uses the same confirmed identity without a refresh race.
    calls.clear()
    restarted = AccountOIDCManager(store=AccountStatusStore(tmp_path), token_store=tokens)
    assert (await restarted.snapshot())["account_user_id"] == "current"
    assert calls == []


@pytest.mark.asyncio
async def test_unavailable_identity_preserves_credential_but_never_hands_it_off(
    tmp_path, monkeypatch
):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    mock_account_transport(monkeypatch, handle)
    tokens = MemoryTokenStore("legacy-refresh")
    subject = AccountOIDCManager(store=AccountStatusStore(tmp_path), token_store=tokens)
    assert (await subject.snapshot())["status"] == "unavailable"
    with pytest.raises(AccountOIDCError):
        await subject.marketplace_handoff("https://marketplace.openkitsune.cn")
    with pytest.raises(AccountOIDCError):
        await subject.marketplace_install_proof("instruction", "device")
    assert tokens.value == "legacy-refresh"
    assert set(calls) == {"/oauth/token"}


@pytest.mark.asyncio
async def test_invalid_legacy_credential_becomes_signed_out(tmp_path, monkeypatch):
    mock_account_transport(
        monkeypatch, lambda _: httpx.Response(400, json={"error": "invalid_grant"})
    )
    tokens = MemoryTokenStore("legacy-refresh")
    subject = AccountOIDCManager(store=AccountStatusStore(tmp_path), token_store=tokens)
    assert await subject.snapshot() == {"status": "signed_out"}
    assert await subject.marketplace_handoff("https://marketplace.openkitsune.cn") is None


@pytest.mark.asyncio
async def test_rotation_keeps_identity_bound_and_other_manager_logout_invalidates_access(
    tmp_path, monkeypatch
):
    mock_account_transport(monkeypatch, provider([]))
    tokens, store = MemoryTokenStore("legacy-refresh"), AccountStatusStore(tmp_path)
    first = AccountOIDCManager(store=store, token_store=tokens)
    await first.snapshot()
    first._access_expires_at = 0
    await first._valid_access_token()
    assert (await first.snapshot())["account_user_id"] == "current"
    second = AccountOIDCManager(store=store, token_store=tokens)
    await second.logout()
    assert await first.snapshot() == {"status": "signed_out"}
    assert await first.marketplace_handoff("https://marketplace.openkitsune.cn") is None
    with pytest.raises(AccountOIDCError, match="not signed in"):
        await first._valid_access_token()


@pytest.mark.asyncio
async def test_two_native_managers_serialize_shared_vault_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    tokens = MemoryTokenStore("legacy-refresh")
    monkeypatch.setattr(
        KeyringTokenStore, "load_refresh_token", lambda _: tokens.load_refresh_token()
    )
    monkeypatch.setattr(
        KeyringTokenStore, "save_refresh_token", lambda _, v: tokens.save_refresh_token(v)
    )
    calls = []
    handler = provider(calls)

    async def handle(request):
        await asyncio.sleep(0.02)
        return handler(request)

    mock_account_transport(monkeypatch, handle)
    managers = [
        AccountOIDCManager(store=AccountStatusStore(tmp_path / "identity")) for _ in range(2)
    ]
    snapshots = await asyncio.gather(*(m.snapshot() for m in managers))
    assert all(s["account_user_id"] == "current" for s in snapshots)
    assert calls.count("/oauth/token") == 1
    assert calls.count("/oauth/userinfo") == 1


def test_identity_scope_follows_os_user_and_provider_not_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    config = AccountFeatureConfig.from_env({})
    expected = config.identity_data_dir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path / "different-workspace"))
    assert AccountFeatureConfig.from_env({}).identity_data_dir() == expected
    other = AccountFeatureConfig.from_env({"OPENKITSUNE_ACCOUNT_BASE_URL": "https://other.example"})
    assert other.identity_data_dir() != expected


@pytest.mark.asyncio
async def test_logout_during_recovery_cannot_publish_identity(tmp_path, monkeypatch):
    started, resume = asyncio.Event(), asyncio.Event()
    handler = provider([])

    async def handle(request):
        if request.url.path == "/oauth/userinfo":
            started.set()
            await resume.wait()
        return handler(request)

    mock_account_transport(monkeypatch, handle)
    tokens, store = MemoryTokenStore("legacy-refresh"), AccountStatusStore(tmp_path)
    subject = AccountOIDCManager(store=store, token_store=tokens)
    recovery = asyncio.create_task(subject.snapshot())
    await started.wait()
    logout = asyncio.create_task(subject.logout())
    await asyncio.sleep(0)
    resume.set()
    await asyncio.gather(recovery, logout)
    assert tokens.value is None
    assert await store.snapshot() is None
    assert await subject.snapshot() == {"status": "signed_out"}
