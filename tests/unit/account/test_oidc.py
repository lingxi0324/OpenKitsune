import asyncio
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from openkitsune.account.oidc import (
    CALLBACK_URI,
    CLIENT_ID,
    DEFAULT_ACCOUNT_BASE_URL,
    AccountOIDCError,
    AccountOIDCManager,
    KeyringTokenStore,
    LoginAttempt,
    _callback_page_html,
    _preferred_callback_language,
    clear_disabled_account_credentials,
    pkce_challenge,
)
from tests.fixtures.account import MemoryTokenStore


def test_pkce_challenge_rfc7636_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


async def test_loopback_callback_rejects_wrong_state_without_consuming_attempt():
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    attempt = LoginAttempt("attempt", "expected-state", "verifier", "https://account.example")
    with pytest.raises(AccountOIDCError, match="invalid OAuth state"):
        await manager.complete_callback(attempt, state="wrong", code="code")
    assert attempt.status == "pending"
    assert await manager.complete_callback(attempt, state="expected-state", code="code")
    manager._complete.assert_awaited_once_with(
        code="code", verifier="verifier", redirect_uri=CALLBACK_URI, generation=attempt.generation
    )


async def test_loopback_callback_is_single_use_even_with_concurrent_requests():
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    attempt = LoginAttempt("attempt", "state", "verifier", "https://account.example")
    results = await asyncio.gather(
        *[manager.complete_callback(attempt, state="state", code="code") for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(result is True for result in results) == 1
    assert any(isinstance(result, AccountOIDCError) for result in results)
    manager._complete.assert_awaited_once()


async def test_loopback_denial_does_not_exchange_tokens():
    manager = AccountOIDCManager(store=AsyncMock(), token_store=AsyncMock())
    manager._complete = AsyncMock()
    attempt = LoginAttempt("attempt", "state", "verifier", "https://account.example")
    assert not await manager.complete_callback(attempt, state="state", error="access_denied")
    assert attempt.status == "failed" and attempt.error == "account_authorization_denied"
    manager._complete.assert_not_awaited()


def test_loopback_contract_constants() -> None:
    assert CLIENT_ID == "openkitsune-desktop"
    parsed = urlsplit(CALLBACK_URI)
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 1455
    assert parse_qs("state=a&code=b") == {"state": ["a"], "code": ["b"]}


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("zh-CN,zh;q=0.9,en;q=0.8", "zh"),
        ("en-US,en;q=0.9,zh;q=0.2", "en"),
        ("fr-FR,fr;q=0.9", "en"),
        ("zh;q=0,en;q=0.8", "en"),
    ],
)
def test_callback_language_follows_browser_preference(
    accept_language: str,
    expected: str,
) -> None:
    assert _preferred_callback_language(accept_language) == expected


def test_callback_page_is_localized_and_handles_both_states() -> None:
    success = _callback_page_html(success=True, language="zh").decode()
    failure = _callback_page_html(success=False, language="en").decode()

    assert '<html lang="zh-CN">' in success
    assert "登录成功" in success
    assert "现在可以关闭此页面" in success
    assert '<main class="card error" role="alert"' in failure
    assert "Sign-in failed" in failure
    assert "Return to OpenKitsune and try signing in again" in failure
    assert "127.0.0.1" not in success


class _SnapshotStore:
    async def snapshot(self) -> dict:
        return {"status": "active", "account_user_id": "user-1"}


class _CallbackWriter:
    def __init__(self) -> None:
        self.response = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.response.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_callback_returns_localized_secure_html() -> None:
    manager = AccountOIDCManager(
        store=_SnapshotStore(),  # type: ignore[arg-type]
        token_store=MemoryTokenStore(None),
    )
    manager._complete = AsyncMock()  # type: ignore[method-assign]
    attempt = LoginAttempt(
        attempt_id="attempt-1",
        state="expected-state",
        verifier="verifier",
        authorization_url="https://account.example/authorize",
    )
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"GET /auth/callback?code=code-1&state=expected-state HTTP/1.1\r\n"
        b"Host: 127.0.0.1:1455\r\n"
        b"Accept-Language: zh-CN,zh;q=0.9,en;q=0.8\r\n\r\n"
    )
    reader.feed_eof()
    writer = _CallbackWriter()

    await manager._callback(reader, writer, attempt)  # type: ignore[arg-type]

    response = bytes(writer.response)
    assert response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: text/html; charset=utf-8\r\n" in response
    assert b"Content-Language: zh-CN\r\n" in response
    assert b"Content-Security-Policy: default-src 'none'" in response
    assert "你已成功登录 OpenKitsune。".encode() in response
    assert attempt.status == "complete"
    assert writer.closed is True


def test_account_base_url_defaults_to_hosted_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENKITSUNE_ACCOUNT_BASE_URL", raising=False)
    manager = AccountOIDCManager(
        store=_SnapshotStore(),  # type: ignore[arg-type]
        token_store=MemoryTokenStore(None),
    )

    assert manager._base_url == DEFAULT_ACCOUNT_BASE_URL == "https://account.openkitsune.cn"


@pytest.mark.asyncio
async def test_signed_out_custom_provider_logout_stays_in_product() -> None:
    manager = AccountOIDCManager(
        store=_SnapshotStore(),  # type: ignore[arg-type]
        token_store=MemoryTokenStore(None),
        account_base_url="https://accounts.vendor.example",
        client_id="vendor-desktop",
    )

    logout_url = await manager.logout()

    assert logout_url == ""


@pytest.mark.asyncio
async def test_disabled_mode_clears_known_credential_slots(monkeypatch) -> None:
    cleared: list[str] = []

    async def fake_clear(self: KeyringTokenStore) -> None:
        cleared.append(self.username)

    monkeypatch.setattr(
        "openkitsune.account.oidc.disabled_credential_usernames",
        lambda: {"openkitsune-desktop-refresh-token", "vendor-desktop-refresh-token"},
    )
    monkeypatch.setattr(KeyringTokenStore, "clear", fake_clear)

    await clear_disabled_account_credentials()

    assert sorted(cleared) == [
        "openkitsune-desktop-refresh-token",
        "vendor-desktop-refresh-token",
    ]


@pytest.mark.asyncio
async def test_snapshot_requires_refresh_token_even_when_offline_cache_exists() -> None:
    manager = AccountOIDCManager(
        store=_SnapshotStore(),  # type: ignore[arg-type]
        token_store=MemoryTokenStore(None),
    )

    assert await manager.snapshot() == {"status": "signed_out"}
