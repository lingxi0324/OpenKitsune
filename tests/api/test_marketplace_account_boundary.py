from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.routes.account_oidc import router
from openkitsune.api.routes.marketplace import router as marketplace_router


def client(monkeypatch, mode="openkitsune"):
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "desktop-secret")
    app = FastAPI()
    app.include_router(router)
    app.include_router(marketplace_router)
    app.state.account_capability = {"mode": mode}
    app.state.account_oidc_manager = SimpleNamespace(
        marketplace_handoff=AsyncMock(return_value=None),
        snapshot=AsyncMock(return_value={"status": "signed_out"}),
    )
    return TestClient(app, client=("127.0.0.1", 12345)), app.state.account_oidc_manager


def test_handoff_requires_native_process_secret(monkeypatch):
    web, account = client(monkeypatch)
    response = web.post(
        "/api/account/marketplace/handoff", json={"origin": "https://marketplace.openkitsune.cn"}
    )
    assert response.status_code == 403
    account.marketplace_handoff.assert_not_awaited()


def test_handoff_rejects_forwarded_remote_request_even_with_secret(monkeypatch):
    web, account = client(monkeypatch)
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={
            "X-OpenKitsune-Desktop-Token": "desktop-secret",
            "X-Forwarded-For": "203.0.113.1",
        },
    )
    assert response.status_code == 403
    account.marketplace_handoff.assert_not_awaited()


def test_handoff_rejects_unconfigured_target(monkeypatch):
    web, account = client(monkeypatch)
    for origin in [
        "https://evil.example",
        "http://localhost:9999",
        "https://marketplace.openkitsune.cn@evil.example",
    ]:
        response = web.post(
            "/api/account/marketplace/handoff",
            json={"origin": origin},
            headers={"X-OpenKitsune-Desktop-Token": "desktop-secret"},
        )
        assert response.status_code == 400
    account.marketplace_handoff.assert_not_awaited()


def test_custom_account_never_exports_identity_to_official_market(monkeypatch):
    web, account = client(monkeypatch, "custom")
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={"X-OpenKitsune-Desktop-Token": "desktop-secret"},
    )
    assert response.json() == {"ticket": None}
    account.marketplace_handoff.assert_not_awaited()


def test_signed_out_native_opens_public_marketplace(monkeypatch):
    web, account = client(monkeypatch)
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={"X-OpenKitsune-Desktop-Token": "desktop-secret"},
    )
    assert response.json() == {"ticket": None, "account": {"status": "signed_out"}}
    account.marketplace_handoff.assert_awaited_once()


def test_install_job_routes_require_native_process_secret(monkeypatch):
    web, _ = client(monkeypatch)
    assert web.get("/api/marketplace/installs").status_code == 403
    assert web.get("/api/marketplace/installs/job").status_code == 403
    assert web.post("/api/marketplace/installs/job/cancel").status_code == 403
    assert web.post("/api/marketplace/installs/job/confirm").status_code == 403
    assert web.post(
        "/api/marketplace/installs/prepare",
        json={"token": "a" * 64, "endpoint": "https://marketplace.openkitsune.cn"},
    ).status_code == 403


def test_install_history_accepts_valid_instance_token(monkeypatch):
    web, _ = client(monkeypatch)
    web.app.state.web_access_config = SimpleNamespace(
        validate_access_token=lambda value: value == "instance-access"
    )
    web.app.state.marketplace_install_manager = SimpleNamespace(
        list_jobs=lambda: [{"id": "job", "status": "installing"}]
    )
    response = web.get(
        "/api/marketplace/installs", headers={"Authorization": "Bearer instance-access"}
    )
    assert response.status_code == 200
    assert response.json()["data"] == [{"id": "job", "status": "installing"}]


def test_mobile_install_requires_valid_explicit_instance_token(monkeypatch):
    web, account = client(monkeypatch)
    web.app.state.web_access_config = SimpleNamespace(
        validate_access_token=lambda value: value == "instance-access"
    )
    installs = web.app.state.marketplace_install_manager = SimpleNamespace(
        get=AsyncMock(return_value={"id": "job", "stage": "dependency_installing"}),
        prepare=AsyncMock(return_value={"id": "job", "status": "ready"}),
    )
    for headers in [{}, {"Authorization": "Bearer invalid"}, {"Cookie": "token=instance-access"}]:
        assert web.get("/api/marketplace/installs/job", headers=headers).status_code == 403
    headers = {"Authorization": "Bearer instance-access", "X-Forwarded-For": "192.0.2.1"}
    assert web.get("/api/marketplace/installs/job", headers=headers).json()["data"]["stage"] == "dependency_installing"
    result = web.post("/api/marketplace/installs/prepare", headers=headers,
                      json={"token": "a" * 64, "endpoint": "https://marketplace.openkitsune.cn"})
    assert result.status_code == 200
    installs.prepare.assert_awaited_once_with("a" * 64, "https://marketplace.openkitsune.cn", account=account)
    # The mobile token permits instance installation, never desktop browser SSO.
    assert web.post("/api/account/marketplace/handoff", headers=headers,
                    json={"origin": "https://marketplace.openkitsune.cn"}).status_code == 403


def test_standalone_backend_accepts_same_user_native_credential(monkeypatch):
    web, account = client(monkeypatch)
    monkeypatch.delenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN")
    monkeypatch.setattr("openkitsune.account.desktop.load_native_account_token", lambda: "native-token")
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={"X-OpenKitsune-Desktop-Token": "native-token"},
    )
    assert response.status_code == 200
    account.marketplace_handoff.assert_awaited_once()


def test_reused_backend_accepts_new_desktop_without_matching_launch_token(monkeypatch):
    web, account = client(monkeypatch)
    monkeypatch.setattr("openkitsune.account.desktop.load_native_account_token", lambda: "native-token")
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={"X-OpenKitsune-Desktop-Token": "native-token"},
    )
    assert response.status_code == 200
    account.marketplace_handoff.assert_awaited_once()


def test_native_credential_does_not_authorize_forwarded_web_access(monkeypatch):
    web, account = client(monkeypatch)
    monkeypatch.setattr("openkitsune.account.desktop.load_native_account_token", lambda: "native-token")
    response = web.post(
        "/api/account/marketplace/handoff",
        json={"origin": "https://marketplace.openkitsune.cn"},
        headers={"X-OpenKitsune-Desktop-Token": "native-token", "Forwarded": "for=203.0.113.1"},
    )
    assert response.status_code == 403
    account.marketplace_handoff.assert_not_awaited()
