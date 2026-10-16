"""A mobile/desktop installation must be authorized by the selected instance."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from openkitsune.account.oidc import AccountOIDCError, AccountOIDCManager
from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
)

TOKEN = "a" * 64
ENDPOINT = "https://marketplace.openkitsune.cn"


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )


def request_with_account():
    account = SimpleNamespace(marketplace_install_proof=AsyncMock(return_value="scoped-proof"))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(account_oidc_manager=account)))


def instruction():
    return {
        "id": "job-one",
        "resource_id": "resource",
        "resource_name": "Example",
        "resource_slug": "example",
        "resource_type": "skill",
        "version_id": "v1",
        "version": "1.0.0",
        "digest_sha256": "b" * 64,
        "signature": "signature",
        "size_bytes": 100,
        "download_url": "https://cdn.example/package.zip",
        "verification": {"algorithm": "Ed25519", "digest_algorithm": "SHA-256"},
    }


async def test_installation_proof_never_exports_account_tokens(monkeypatch):
    account = AccountOIDCManager(
        store=AsyncMock(),
        token_store=SimpleNamespace(load_refresh_token=AsyncMock(return_value="private-refresh")),
        account_base_url="https://account.openkitsune.cn",
    )
    account._identity_locked = AsyncMock(return_value={"status": "active"})

    def handle(req):
        assert str(req.url) == "https://account.openkitsune.cn/oauth/desktop-install-proof"
        assert json.loads(req.content) == {
            "client_id": "openkitsune-desktop",
            "target_client_id": "marketplace",
            "refresh_token": "private-refresh",
            "installation_token": TOKEN,
            "device_id": "instance-one",
        }
        return httpx.Response(200, json={"proof": "p" * 64})

    transport(monkeypatch, handle)
    assert await account.marketplace_install_proof(TOKEN, "instance-one") == "p" * 64
    account._tokens.load_refresh_token.return_value = None
    with pytest.raises(AccountOIDCError, match="marketplace_account_required"):
        await account.marketplace_install_proof(TOKEN, "instance-one")


async def test_prepare_and_confirm_get_fresh_proofs_and_start_only_once(tmp_path, monkeypatch):
    manager = MarketplaceInstallManager(tmp_path)
    manager._inspect = AsyncMock(return_value={"install_action": "install", "_installation_snapshot": "unchanged", "_installation_scope": "test"})
    request = request_with_account()
    actions = []

    def handle(req):
        body = json.loads(req.content)
        assert body == {
            "token": TOKEN,
            "device_id": manager.device_id,
            "account_proof": "scoped-proof",
        }
        actions.append(req.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"data": instruction()})

    transport(monkeypatch, handle)
    manager._run = AsyncMock()
    first = await manager.prepare(TOKEN, ENDPOINT, account=request.app.state.account_oidc_manager)
    assert first == await manager.prepare(TOKEN, ENDPOINT, account=request.app.state.account_oidc_manager)
    assert "token" not in first and "download_url" not in first
    assert "scoped-proof" not in (manager.jobs_dir / "job-one.json").read_text()
    await manager.confirm(first["id"], request, account=request.app.state.account_oidc_manager)
    with pytest.raises(MarketplaceInstallError, match="marketplace_install_busy"):
        await manager.confirm(first["id"], request, account=request.app.state.account_oidc_manager)
    await asyncio.sleep(0)
    assert actions == ["consume", "authorize", "authorize"]
    assert request.app.state.account_oidc_manager.marketplace_install_proof.await_count == 3
    manager._run.assert_awaited_once()


async def test_account_switch_after_preview_cannot_start_installation(tmp_path, monkeypatch):
    manager = MarketplaceInstallManager(tmp_path)
    manager._inspect = AsyncMock(return_value={"install_action": "install", "_installation_snapshot": "unchanged", "_installation_scope": "test"})
    request = request_with_account()

    def handle(req):
        if req.url.path.endswith("/authorize"):
            return httpx.Response(403, json={"error": "account_mismatch"})
        return httpx.Response(200, json={"data": instruction()})

    transport(monkeypatch, handle)
    job = await manager.prepare(TOKEN, ENDPOINT, account=request.app.state.account_oidc_manager)
    with pytest.raises(MarketplaceInstallError, match="marketplace_account_mismatch"):
        await manager.confirm(job["id"], request, account=request.app.state.account_oidc_manager)
    assert manager._jobs[job["id"]]["status"] == "ready"
    assert not manager._tasks


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "marketplace_account_required"),
        (403, "marketplace_account_mismatch"),
        (404, "marketplace_instruction_unavailable"),
        (503, "marketplace_connection_failed"),
    ],
)
async def test_authorization_errors_remain_actionable(tmp_path, monkeypatch, status, code):
    manager = MarketplaceInstallManager(tmp_path)
    manager._inspect = AsyncMock(return_value={"install_action": "install", "_installation_snapshot": "unchanged", "_installation_scope": "test"})
    transport(monkeypatch, lambda req: httpx.Response(status, json={"error": "denied"}))
    with pytest.raises(MarketplaceInstallError, match=code):
        await manager.prepare(TOKEN, ENDPOINT, account=request_with_account().app.state.account_oidc_manager)
    assert not manager._jobs


async def test_no_account_and_untrusted_source_never_receive_proof(tmp_path, monkeypatch):
    manager = MarketplaceInstallManager(tmp_path)
    manager._inspect = AsyncMock(return_value={"install_action": "install", "_installation_snapshot": "unchanged", "_installation_scope": "test"})
    request = request_with_account()
    with pytest.raises(MarketplaceInstallError, match="marketplace_endpoint_invalid"):
        await manager.prepare(TOKEN, "https://untrusted.example", account=request.app.state.account_oidc_manager)
    request.app.state.account_oidc_manager.marketplace_install_proof.assert_not_called()
    request.app.state.account_oidc_manager = None
    with pytest.raises(MarketplaceInstallError, match="marketplace_account_required"):
        await manager.prepare(TOKEN, ENDPOINT, account=request.app.state.account_oidc_manager)
