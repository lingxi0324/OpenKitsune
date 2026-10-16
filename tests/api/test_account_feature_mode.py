from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from openkitsune.api.server import create_app


@pytest.fixture(autouse=True)
def isolated_account_credentials(tmp_path, monkeypatch):
    from openkitsune.config import settings

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path / "home"))
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr("openkitsune.account.oidc.KeyringTokenStore.clear", AsyncMock())


def test_disabled_account_mode_only_exposes_capability(monkeypatch) -> None:
    monkeypatch.setenv("@@OPENKITSUNE_ACCOUNT_MODE@@", "disabled")
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/api/account/capability" in paths
    assert "/api/account/status" not in paths
    assert "/api/account/login/start" not in paths
    assert "/api/internal/openkitsune/users/status" not in paths
    assert app.state.account_oidc_manager is None
    assert app.state.account_status_store is None

    with TestClient(app) as client:
        response = client.get("/api/account/capability")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "mode": "disabled",
        "provider": None,
        "display_name": None,
        "supports_entitlements": False,
    }


def test_custom_account_mode_mounts_provider_routes(monkeypatch) -> None:
    monkeypatch.setenv("@@OPENKITSUNE_ACCOUNT_MODE@@", "custom")
    monkeypatch.setenv("OPENKITSUNE_ACCOUNT_BASE_URL", "https://accounts.vendor.example")
    monkeypatch.setenv("OPENKITSUNE_ACCOUNT_CLIENT_ID", "vendor-desktop")
    monkeypatch.setenv("OPENKITSUNE_ACCOUNT_DISPLAY_NAME", "Vendor Account")
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/api/account/status" in paths
    assert "/api/account/login/start" in paths
    assert "/api/internal/openkitsune/users/status" in paths
    assert app.state.account_oidc_manager._base_url == "https://accounts.vendor.example"
    assert app.state.account_oidc_manager._client_id == "vendor-desktop"
    assert app.state.account_capability["display_name"] == "Vendor Account"
