from unittest.mock import AsyncMock

import httpx
import pytest

from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
)


@pytest.mark.asyncio
async def test_anonymous_install_cannot_exchange_a_bearer_link(tmp_path):
    manager = MarketplaceInstallManager(tmp_path)
    with pytest.raises(MarketplaceInstallError, match="marketplace_account_required"):
        await manager.prepare("a" * 64, "https://marketplace.openkitsune.cn")


@pytest.mark.asyncio
async def test_switching_account_after_preview_blocks_install(tmp_path, monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(403, json={"error": "account_mismatch"})

    native_client = httpx.AsyncClient
    monkeypatch.setattr(
        "openkitsune.integrations.marketplace.installer.httpx.AsyncClient",
        lambda **kw: native_client(transport=httpx.MockTransport(handle), **kw),
    )
    manager = MarketplaceInstallManager(tmp_path)
    manager._run = AsyncMock()
    manager._jobs["job"] = {
        "id": "job",
        "status": "ready",
        "token": "a" * 64,
        "endpoint": "https://marketplace.openkitsune.cn",
        "account_user_id": "old-account",
    }
    account = AsyncMock()
    account.marketplace_install_proof.return_value = "proof-for-new-account"
    with pytest.raises(MarketplaceInstallError, match="marketplace_account_mismatch"):
        await manager.confirm("job", None, account=account)
    assert manager._jobs["job"]["status"] == "ready"
    manager._run.assert_not_awaited()
    assert requests[0].url.path.endswith("/authorize")
    assert b"proof-for-new-account" in requests[0].content
    assert b"refresh_token" not in requests[0].content


@pytest.mark.asyncio
async def test_revoked_account_blocks_reopening_existing_preview(tmp_path, monkeypatch):
    manager = MarketplaceInstallManager(tmp_path)
    manager._jobs["job"] = {
        "id": "job",
        "status": "ready",
        "token": "a" * 64,
        "endpoint": "https://marketplace.openkitsune.cn",
    }
    manager._authorize = AsyncMock(
        side_effect=MarketplaceInstallError("marketplace_account_required")
    )
    with pytest.raises(MarketplaceInstallError, match="marketplace_account_required"):
        await manager.prepare("a" * 64, "https://marketplace.openkitsune.cn", account=AsyncMock())
    manager._authorize.assert_awaited_once()
