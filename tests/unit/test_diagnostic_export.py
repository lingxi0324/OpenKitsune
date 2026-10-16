import io
import json
import zipfile

import httpx
import pytest
from fastapi import FastAPI

from openkitsune.api.auth import WebAccessConfig, create_auth_middleware
from openkitsune.api.routes import bug_report


@pytest.fixture
def diagnostic_app(monkeypatch, tmp_path):
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(bug_report, "_resolve_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(bug_report, "_resolve_global_logs_dir", lambda: tmp_path / "global_logs")
    monkeypatch.setattr(bug_report, "_resolve_openkitsune_home_dir", lambda: tmp_path / "home")
    monkeypatch.setattr(bug_report, "_get_recent_llm_debug_files", lambda count: [])
    monkeypatch.setattr(bug_report, "_collect_system_info", lambda: {"os": "test-host"})
    monkeypatch.setattr(bug_report, "_collect_endpoint_summary", lambda: {})
    monkeypatch.setattr(bug_report, "_add_windows_crash_artifacts", lambda zf: None)
    monkeypatch.delenv("OPENKITSUNE_WEB_PASSWORD", raising=False)
    config = WebAccessConfig(tmp_path)
    config.change_password("test-diagnostic-password")
    app = FastAPI()
    app.middleware("http")(create_auth_middleware(config))
    app.include_router(bug_report.router)
    return app, config


async def test_export_downloads_zip_with_redacted_runtime(diagnostic_app, tmp_path):
    app, config = diagnostic_app
    data = tmp_path / "data"
    data.mkdir()
    (data / "runtime_state.json").write_text(
        json.dumps({"im_bots": [{"credentials": {"app_secret": "must-not-leak"}}]}),
        encoding="utf-8",
    )
    (data / "backend.heartbeat").write_text("alive", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.10", 1234)),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/diagnostics/export",
            headers={"Authorization": f"Bearer {config.create_access_token()}"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert json.loads(zf.read("system_info.json"))["os"] == "test-host"
        assert zf.read("state/backend.heartbeat") == b"alive"
        for name in ("state/runtime_state.json", "state/sanitized_config.json"):
            assert b"must-not-leak" not in zf.read(name)
            assert b"[REDACTED]" in zf.read(name)
    assert not (tmp_path / "feedback").exists()


async def test_export_requires_remote_authentication(diagnostic_app, monkeypatch):
    app, _ = diagnostic_app

    def must_not_pack():
        pytest.fail("Unauthenticated requests must not collect diagnostics")

    monkeypatch.setattr(bug_report, "_build_diagnostic_zip", must_not_pack)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.10", 1234)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/diagnostics/export")
    assert response.status_code == 401


async def test_export_rejects_oversized_zip(diagnostic_app, monkeypatch):
    app, config = diagnostic_app
    monkeypatch.setattr(bug_report, "MAX_ZIP_SIZE", 1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.10", 1234)),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/diagnostics/export",
            headers={"Authorization": f"Bearer {config.create_access_token()}"},
        )
    assert response.status_code == 413
