from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from openkitsune.api.routes.files import router as files_router
from openkitsune.api.routes.sessions import router as sessions_router
from openkitsune.api.schemas import AttachmentInfo
from openkitsune.api.working_directories import (
    authorize_working_directory,
    resolve_chat_attachments,
    resolve_session_file,
)
from openkitsune.core.policy_v2 import PolicyContext, reset_current_context, set_current_context
from openkitsune.core.working_directory import (
    WorkingDirectoryError,
    config_workspace,
    current_working_directory,
    resolve_working_path,
    session_working_directory,
)
from openkitsune.sessions import Session, SessionManager


def test_legacy_session_defaults_to_configuration_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "openkitsune.core.working_directory.config_workspace",
        lambda: tmp_path.resolve(),
    )
    payload = Session.create("desktop", "legacy", "desktop_user").to_dict()
    payload.pop("working_directory")

    restored = Session.from_dict(payload)

    assert restored.working_directory == str(tmp_path.resolve())
    assert restored.to_dict()["working_directory"] == str(tmp_path.resolve())


def test_disabled_feature_forces_configuration_workspace(tmp_path, monkeypatch):
    config_root = tmp_path / "config"
    requested = tmp_path / "requested"
    config_root.mkdir()
    requested.mkdir()
    monkeypatch.setattr(
        "openkitsune.core.working_directory.config_workspace",
        lambda: config_root.resolve(),
    )
    monkeypatch.setattr(
        "openkitsune.core.working_directory.working_directory_feature_enabled",
        lambda: False,
    )

    session = Session.create(
        "desktop",
        "feature-off",
        "desktop_user",
        working_directory=str(requested),
    )
    context = PolicyContext(
        session_id="feature-off-context",
        working_directory=requested,
        workspace_roots=(requested,),
    )

    assert session.working_directory == str(config_root.resolve())
    assert session_working_directory(session) == config_root.resolve()
    assert context.working_directory == config_root.resolve()


def test_session_create_rejects_working_directory_change(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(
        "openkitsune.api.working_directories.authorize_working_directory",
        lambda _request, raw: Path(raw).resolve(strict=True),
    )
    app = FastAPI()
    app.include_router(sessions_router)
    app.state.session_manager = SessionManager(storage_path=tmp_path / "sessions")
    client = TestClient(app)

    created = client.post(
        "/api/sessions",
        json={"conversationId": "locked", "workingDirectory": str(first)},
    )
    changed = client.post(
        "/api/sessions",
        json={"conversationId": "locked", "workingDirectory": str(second)},
    )

    assert created.status_code == 200
    assert created.json()["workingDirectory"] == str(first.resolve())
    assert changed.status_code == 409
    assert changed.json()["detail"] == "working_directory_locked"


def test_web_directory_browser_is_limited_to_configured_roots(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    child = root / "child"
    outside = tmp_path / "outside"
    child.mkdir(parents=True)
    outside.mkdir()
    monkeypatch.setattr(
        "openkitsune.api.working_directories.configured_working_roots",
        lambda: (root.resolve(),),
    )
    app = FastAPI()
    app.include_router(sessions_router)
    client = TestClient(app)

    roots = client.get("/api/working-directories")
    children = client.get("/api/working-directories", params={"parent": str(root)})
    denied = client.get("/api/working-directories", params={"parent": str(outside)})

    assert roots.status_code == 200
    assert roots.json()["directories"] == [{"name": "approved", "path": str(root.resolve())}]
    assert children.status_code == 200
    assert children.json()["directories"] == [{"name": "child", "path": str(child.resolve())}]
    assert denied.status_code == 403


def test_loopback_request_can_use_directory_outside_configured_roots(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    monkeypatch.setattr(
        "openkitsune.api.working_directories.configured_working_roots",
        lambda: (approved.resolve(),),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/sessions",
            "headers": [],
            "client": ("127.0.0.1", 49152),
            "server": ("127.0.0.1", 18900),
            "scheme": "http",
            "query_string": b"",
        }
    )

    assert authorize_working_directory(request, str(outside)) == outside.resolve()


def test_remote_request_cannot_use_directory_outside_configured_roots(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    monkeypatch.setattr(
        "openkitsune.api.working_directories.configured_working_roots",
        lambda: (approved.resolve(),),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/sessions",
            "headers": [],
            "client": ("192.0.2.10", 49152),
            "server": ("127.0.0.1", 18900),
            "scheme": "http",
            "query_string": b"",
        }
    )

    with pytest.raises(Exception) as exc_info:
        authorize_working_directory(request, str(outside))
    assert getattr(exc_info.value, "status_code", None) == 403


def test_session_file_search_skips_ignored_directories(tmp_path):
    root = tmp_path / "project"
    ignored = root / ".git"
    ignored.mkdir(parents=True)
    (root / "visible.py").write_text("print('ok')", encoding="utf-8")
    (ignored / "secret.py").write_text("secret", encoding="utf-8")
    manager = SessionManager(storage_path=tmp_path / "sessions")
    manager.get_session(
        "desktop",
        "search-session",
        "desktop_user",
        working_directory=str(root),
    )
    app = FastAPI()
    app.include_router(sessions_router)
    app.state.session_manager = manager

    response = TestClient(app).get("/api/sessions/search-session/files/search", params={"q": ".py"})

    assert response.status_code == 200
    assert [item["relativePath"] for item in response.json()["files"]] == ["visible.py"]


def _session_files_client(tmp_path: Path, root: Path, conversation_id: str = "tree-session"):
    manager = SessionManager(storage_path=tmp_path / "sessions")
    manager.get_session(
        "desktop",
        conversation_id,
        "desktop_user",
        working_directory=str(root),
    )
    app = FastAPI()
    app.include_router(sessions_router)
    app.state.session_manager = manager
    return TestClient(app)


def test_session_file_tree_lists_directories_before_files_and_skips_ignored(tmp_path):
    root = tmp_path / "project"
    (root / "zeta").mkdir(parents=True)
    (root / "Alpha").mkdir()
    (root / ".git").mkdir()
    (root / "zeta" / "nested.txt").write_text("nested", encoding="utf-8")
    (root / "beta.txt").write_text("beta", encoding="utf-8")
    (root / "Alpha.txt").write_text("alpha", encoding="utf-8")
    client = _session_files_client(tmp_path, root)

    response = client.get("/api/sessions/tree-session/files/tree")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent"] == ""
    assert [entry["name"] for entry in payload["entries"]] == [
        "Alpha",
        "zeta",
        "Alpha.txt",
        "beta.txt",
    ]
    assert payload["entries"][0]["hasChildren"] is False
    assert payload["entries"][1]["hasChildren"] is True
    assert payload["truncated"] is False


def test_session_file_tree_lists_only_requested_directory_level(tmp_path):
    root = tmp_path / "project"
    nested = root / "src" / "services"
    nested.mkdir(parents=True)
    (root / "root.txt").write_text("root", encoding="utf-8")
    (nested / "worker.py").write_text("worker", encoding="utf-8")
    client = _session_files_client(tmp_path, root)

    response = client.get(
        "/api/sessions/tree-session/files/tree",
        params={"parent": "src/services"},
    )

    assert response.status_code == 200
    assert response.json()["parent"] == "src/services"
    assert [entry["relativePath"] for entry in response.json()["entries"]] == [
        "src/services/worker.py"
    ]


@pytest.mark.parametrize("parent", ["../outside", "src/../../outside"])
def test_session_file_tree_rejects_parent_traversal(tmp_path, parent):
    root = tmp_path / "project"
    root.mkdir()
    client = _session_files_client(tmp_path, root)

    response = client.get("/api/sessions/tree-session/files/tree", params={"parent": parent})

    assert response.status_code == 403


def test_session_file_tree_rejects_absolute_parent(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    client = _session_files_client(tmp_path, root)

    response = client.get(
        "/api/sessions/tree-session/files/tree",
        params={"parent": str(tmp_path.resolve())},
    )

    assert response.status_code == 403


def test_session_file_tree_omits_symbolic_links(tmp_path):
    root = tmp_path / "project"
    target = root / "target"
    target.mkdir(parents=True)
    (target / "visible.txt").write_text("visible", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are not available on this platform")
    client = _session_files_client(tmp_path, root)

    response = client.get("/api/sessions/tree-session/files/tree")
    linked_response = client.get(
        "/api/sessions/tree-session/files/tree",
        params={"parent": "linked"},
    )

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == ["target"]
    assert linked_response.status_code == 403


def test_session_file_tree_reports_deleted_working_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    client = _session_files_client(tmp_path, root)
    root.rmdir()

    response = client.get("/api/sessions/tree-session/files/tree")

    assert response.status_code == 409


def test_working_directory_attachment_rejects_escape_and_forged_local_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    session = Session.create(
        "desktop",
        "attachments",
        "desktop_user",
        working_directory=str(root),
    )

    with pytest.raises(Exception) as escape:
        resolve_session_file(session, "../outside.txt")
    assert getattr(escape.value, "status_code", None) == 403

    forged = AttachmentInfo(type="file", name="outside.txt", local_path=str(outside))
    with pytest.raises(Exception) as local_path:
        resolve_chat_attachments([forged], session)
    assert getattr(local_path.value, "status_code", None) == 403


def test_uploaded_attachment_resolves_server_path_without_client_local_path(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    uploaded = upload_dir / "upload-1_report.pdf"
    uploaded.write_bytes(b"pdf")
    monkeypatch.setattr("openkitsune.api.routes.upload.UPLOAD_DIR", upload_dir)
    session = Session.create(
        "desktop", "attachments", "desktop_user", working_directory=str(tmp_path)
    )
    attachment = AttachmentInfo(
        type="document",
        name="report.pdf",
        upload_id=uploaded.name,
        url=f"/api/uploads/{uploaded.name}",
    )

    resolve_chat_attachments([attachment], session)

    assert attachment.local_path == str(uploaded.resolve())


@pytest.mark.asyncio
async def test_contextvar_keeps_concurrent_working_directories_isolated(tmp_path):
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()

    async def resolve_in_context(index: int) -> tuple[Path, Path]:
        ctx = PolicyContext(
            session_id=f"session-{index}",
            working_directory=roots[index],
            workspace_roots=(roots[index],),
        )
        token = set_current_context(ctx)
        try:
            await asyncio.sleep(0)
            return current_working_directory(), resolve_working_path("same-name.txt")
        finally:
            reset_current_context(token)

    results = await asyncio.gather(resolve_in_context(0), resolve_in_context(1))

    assert results[0] == (roots[0].resolve(), (roots[0] / "same-name.txt").resolve())
    assert results[1] == (roots[1].resolve(), (roots[1] / "same-name.txt").resolve())


def test_deleted_working_directory_does_not_fallback(tmp_path):
    from openkitsune.tools.file import FileTool

    root = tmp_path / "deleted"
    root.mkdir()
    ctx = PolicyContext(
        session_id="deleted-session",
        working_directory=root,
        workspace_roots=(root,),
    )
    token = set_current_context(ctx)
    root.rmdir()
    try:
        with pytest.raises(WorkingDirectoryError):
            FileTool(base_path=str(tmp_path))._resolve_path("result.txt")
    finally:
        reset_current_context(token)


def test_legacy_mock_session_without_real_working_directory_uses_config_workspace():
    session = MagicMock()

    assert session_working_directory(session) == config_workspace()


def test_file_tool_uses_explicit_base_without_policy_context(tmp_path):
    from openkitsune.tools.file import FileTool

    assert FileTool(base_path=str(tmp_path))._resolve_path("result.txt") == (
        tmp_path / "result.txt"
    ).resolve()


def test_policy_context_overrides_file_tool_base(tmp_path):
    from openkitsune.tools.file import FileTool

    explicit_base = tmp_path / "explicit"
    session_root = tmp_path / "session"
    explicit_base.mkdir()
    session_root.mkdir()
    ctx = PolicyContext(
        session_id="context-overrides-base",
        working_directory=session_root,
        workspace_roots=(session_root,),
    )
    token = set_current_context(ctx)
    try:
        assert FileTool(base_path=str(explicit_base))._resolve_path("result.txt") == (
            session_root / "result.txt"
        ).resolve()
    finally:
        reset_current_context(token)


def test_conversation_scoped_file_download_does_not_fallback_or_cross_roots(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_file = first / "result.txt"
    second_file = second / "result.txt"
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")

    manager = SessionManager(storage_path=tmp_path / "sessions")
    manager.get_session(
        "desktop",
        "first-session",
        "desktop_user",
        working_directory=str(first),
    )
    manager.get_session(
        "desktop",
        "second-session",
        "desktop_user",
        working_directory=str(second),
    )
    app = FastAPI()
    app.include_router(files_router)
    app.state.session_manager = manager
    client = TestClient(app)

    own = client.get(
        "/api/files",
        params={"conversation_id": "first-session", "path": str(first_file)},
    )
    cross = client.get(
        "/api/files",
        params={"conversation_id": "first-session", "path": str(second_file)},
    )
    missing = client.get(
        "/api/files",
        params={"conversation_id": "missing", "path": str(first_file)},
    )

    assert own.status_code == 200
    assert own.content == b"first"
    assert cross.status_code == 403
    assert missing.status_code == 404


def test_terminal_sessions_are_namespaced_by_conversation(tmp_path):
    from openkitsune.tools.terminal import TerminalSessionManager

    manager = TerminalSessionManager(default_cwd=str(tmp_path))

    first = manager.get_or_create(1, namespace="conversation-a")
    second = manager.get_or_create(1, namespace="conversation-b")

    assert first is not second
    assert first.namespace == "conversation-a"
    assert second.namespace == "conversation-b"
    assert first.output_file != second.output_file
