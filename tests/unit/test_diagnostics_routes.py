"""End-to-end-ish tests for the new diagnostics routes.

These run against a minimal FastAPI app so we don't bring up the full
Agent/SessionManager stack; they just verify that the new routes are
wired and behave defensively when state is empty.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.routes import health
from openkitsune.core.link_diagnostics import record_link_diagnostic


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    return app


def test_last_link_diagnostic_returns_empty_when_unset():
    client = TestClient(_build_app())
    resp = client.get("/api/diagnostics/last-link")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_last_link_diagnostic_returns_state_value_when_present():
    app = _build_app()
    app.state.last_link_diagnostic = {
        "requested_url": "https://example.com/a",
        "final_url": "https://www.example.com/a",
        "status": "ok",
    }
    resp = TestClient(app).get("/api/diagnostics/last-link")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested_url"] == "https://example.com/a"
    assert body["final_url"] == "https://www.example.com/a"


def test_clear_session_caches_endpoint_returns_cleared_map():
    client = TestClient(_build_app())
    resp = client.post("/api/diagnostics/clear-session-caches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "cleared" in body
    assert body["cleared"].get("web_fetch") is True


def test_link_diagnostics_are_isolated_and_bounded():
    app = _build_app()
    first = record_link_diagnostic(app.state, {"requested_url": "https://a.example"}, "a")
    record_link_diagnostic(app.state, {"requested_url": "https://b.example"}, "b")
    client = TestClient(app)
    assert client.get("/api/diagnostics/last-link?conversation_id=a").json() == first
    assert client.get("/api/diagnostics/last-link?conversation_id=missing").json() == {}
    assert client.get("/api/diagnostics/last-link").json()["conversation_id"] == "b"
    assert first["recorded_at"]
    for i in range(210):
        record_link_diagnostic(app.state, {"requested_url": str(i)}, str(i))
    assert len(app.state.link_diagnostics) == 200


def test_expired_conversation_never_clears_default_agent(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    app = _build_app()
    app.state.agent = object()
    app.state.agent_pool = SimpleNamespace(get_existing=lambda cid: None)
    clear = Mock()
    monkeypatch.setattr("openkitsune.core.session_caches.clear_session_caches", clear)
    response = TestClient(app).post("/api/diagnostics/clear-session-caches?conversation_id=gone")
    assert response.status_code == 404
    clear.assert_not_called()


def test_clear_passes_conversation_and_preserves_rules(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from openkitsune.api.routes import chat

    app = _build_app()
    agent = object()
    app.state.agent_pool = SimpleNamespace(get_existing=lambda cid: agent if cid == "a" else None)
    monkeypatch.setattr(chat, "_resolve_agent", lambda value: value)
    clear = Mock(return_value={"web_fetch": True})
    monkeypatch.setattr("openkitsune.core.session_caches.clear_session_caches", clear)
    response = TestClient(app).post("/api/diagnostics/clear-session-caches?conversation_id=a")
    assert response.status_code == 200
    clear.assert_called_once_with(
        agent, conversation_id="a", preserve_domain_rules=True, preserve_diagnostics=True
    )


def test_runtime_targets_do_not_require_link_diagnostics(monkeypatch):
    from types import SimpleNamespace

    app = _build_app()
    monkeypatch.setattr(
        "openkitsune.agents.profile.get_profile_store",
        lambda: SimpleNamespace(get=lambda profile_id: None),
    )
    app.state.agent_pool = SimpleNamespace(
        get_stats=lambda: {
            "sessions": [
                {"session_id": "a", "agents": [{"profile_id": "writer"}, {"profile_id": "reader"}]}
            ]
        }
    )
    response = TestClient(app).get("/api/diagnostics/cache-targets")
    assert response.json() == {
        "targets": [
            {"conversation_id": "a", "profile_id": "writer", "conversation_title": "", "profile_name": ""},
            {"conversation_id": "a", "profile_id": "reader", "conversation_title": "", "profile_name": ""},
        ]
    }


def test_expired_default_runtime_is_not_reported_as_cleared():
    client = TestClient(_build_app())
    assert client.get("/api/diagnostics/cache-targets").json() == {"targets": []}
    response = client.post("/api/diagnostics/clear-session-caches?require_runtime=true")
    assert response.status_code == 404


def test_clear_selects_exact_agent_in_conversation(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from openkitsune.api.routes import chat

    app = _build_app()
    agent = object()
    lookup = Mock(return_value=agent)
    app.state.agent_pool = SimpleNamespace(get_existing=lookup)
    monkeypatch.setattr(chat, "_resolve_agent", lambda value: value)
    clear = Mock(return_value={"web_fetch": True})
    monkeypatch.setattr("openkitsune.core.session_caches.clear_session_caches", clear)
    response = TestClient(app).post(
        "/api/diagnostics/clear-session-caches?conversation_id=a&profile_id=writer"
    )
    assert response.status_code == 200
    lookup.assert_called_once_with("a", "writer")
    assert clear.call_args.args == (agent,)
