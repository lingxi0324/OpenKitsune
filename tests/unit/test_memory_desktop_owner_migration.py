"""Regression coverage for automatic desktop owner alignment on upgrade."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.api.routes.memory import router
from openkitsune.memory.manager import MemoryManager
from openkitsune.memory.owner_migration import align_desktop_owner
from openkitsune.memory.relational.store import RelationalMemoryStore
from openkitsune.memory.relational.types import MemoryEdge, MemoryNode
from openkitsune.memory.types import MemoryType, SemanticMemory


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", raising=False)
    mm = MemoryManager(
        tmp_path / "memory",
        tmp_path / "MEMORY.md",
        search_backend="fts5",
        desktop_owner_alignment=True,
    )
    yield mm
    mm.store.db.close()


def put(manager, content, *, user="default", workspace="default", **kwargs):
    memory = SemanticMemory(type=MemoryType.FACT, content=content, **kwargs)
    manager.store.save_semantic(memory, user_id=user, workspace_id=workspace, skip_dedup=True)
    return memory


def client(manager):
    app = FastAPI()
    app.include_router(router)
    app.state.agent = SimpleNamespace(memory_manager=manager)
    return TestClient(app)


def test_upgrade_restores_list_graph_and_session_ownership(manager, monkeypatch):
    historical = [put(manager, f"Historical memory {i}") for i in range(978)]
    put(manager, "Current desktop memory", user="desktop_user")
    manager.store.upsert_session_tenant("desktop:old", "default", "default")
    graph = RelationalMemoryStore(manager.store.db._conn)
    nodes = [MemoryNode(content=f"Graph memory {i}", session_id="desktop:old") for i in range(26)]
    graph.save_nodes_batch(nodes)
    edge = MemoryEdge(source_id=nodes[0].id, target_id=nodes[1].id)
    graph.save_edge(edge)

    assert client(manager).get("/api/memories").json()["total"] == 1
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test-desktop-launch")
    # Exercise the actual startup hook on the already persisted database.
    reopened = MemoryManager(
        manager.data_dir,
        manager.memory_md_path,
        search_backend="fts5",
        agent_id="OpenKitsune",
        desktop_owner_alignment=True,
    )
    assert client(reopened).get("/api/memories").json()["total"] == 979
    assert reopened.store.get_session_tenant("desktop:old") == ("desktop_user", "default")
    assert len(graph.get_all_nodes(user_id="desktop_user", workspace_id="default")) == 26
    assert graph._conn.execute("SELECT source_id, target_id FROM mdrm_edges").fetchone() == (
        edge.source_id,
        edge.target_id,
    )
    assert reopened._memories[historical[0].id].user_id == "desktop_user"

    backups = list(manager.data_dir.glob("openkitsune.db.bak.desktop_owner.*"))
    assert len(backups) == 1
    with closing(sqlite3.connect(str(backups[0]))) as backup:
        assert (
            backup.execute("SELECT COUNT(*) FROM memories WHERE user_id='default'").fetchone()[0]
            == 978
        )
    assert align_desktop_owner(reopened.store.db)["status"] == "clean"
    assert len(list(manager.data_dir.glob("openkitsune.db.bak.desktop_owner.*"))) == 1


def test_preserves_content_ids_inactive_state_and_other_workspaces(manager):
    expired = put(manager, "Expired historical fact", expires_at=datetime.now() - timedelta(days=1))
    active = put(manager, "Updated fact", user="desktop_user")
    old = put(manager, "Old fact", superseded_by=active.id)
    project = put(manager, "Separate project", workspace="proj-example")
    conn = manager.store.db._conn
    before = {m.id: manager.store.db.get_memory(m.id) for m in [expired, old, project]}
    report = align_desktop_owner(manager.store.db)
    assert report["status"] == "migrated"
    for memory in [expired, old, project]:
        after = manager.store.db.get_memory(memory.id)
        expected = before[memory.id]
        if memory is not project:
            expected["user_id"] = "desktop_user"
        assert after == expected
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 4
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM _memory_scope_audit WHERE migration_version='desktop_owner_alignment'"
        ).fetchone()[0]
        == 2
    )


@pytest.mark.parametrize("surface", ["memories", "session_tenants", "mdrm_nodes"])
@pytest.mark.parametrize("user", ["im-user-42", "anonymous", ""])
def test_shared_or_ambiguous_database_is_not_automatically_claimed(manager, surface, user):
    original = put(manager, "Unclaimed historical memory")
    if surface == "memories":
        other = put(manager, "Other user's memory", user=user or "default", workspace="project")
        if not user:
            manager.store.db._conn.execute("UPDATE memories SET user_id='' WHERE id=?", (other.id,))
            manager.store.db._conn.commit()
    elif surface == "session_tenants":
        manager.store.upsert_session_tenant("im:other", user, "project")
        if not user:
            manager.store.db._conn.execute("UPDATE session_tenants SET user_id=''")
            manager.store.db._conn.commit()
    else:
        graph = RelationalMemoryStore(manager.store.db._conn)
        graph.save_node(MemoryNode(content="Other graph", user_id=user, workspace_id="project"))
    assert align_desktop_owner(manager.store.db)["reason"] == "ambiguous_owners"
    assert manager.store.get_semantic(original.id).user_id == "default"
    assert not list(manager.data_dir.glob("openkitsune.db.bak.desktop_owner.*"))


def test_failed_migration_rolls_back_all_tables_and_retries(manager):
    memory = put(manager, "Must survive failure")
    manager.store.upsert_session_tenant("desktop:old", "default", "default")
    conn = manager.store.db._conn
    conn.execute(
        "CREATE TEMP TRIGGER reject_alignment BEFORE UPDATE ON session_tenants "
        "BEGIN SELECT RAISE(ABORT, 'injected migration failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected migration failure"):
        align_desktop_owner(manager.store.db)
    assert manager.store.get_semantic(memory.id).user_id == "default"
    assert manager.store.get_session_tenant("desktop:old") == ("default", "default")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM _memory_scope_audit WHERE migration_version='desktop_owner_alignment'"
        ).fetchone()[0]
        == 0
    )
    assert manager.store.get_meta("desktop_owner_alignment") is None
    conn.execute("DROP TRIGGER reject_alignment")
    assert align_desktop_owner(manager.store.db)["status"] == "migrated"


def test_backup_failure_keeps_owners_and_fallback_unchanged(manager, monkeypatch):
    memory = put(manager, "Backup must succeed first")
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test")
    monkeypatch.setattr(
        "openkitsune.memory.owner_migration.sqlite3.connect",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    manager._align_desktop_owner()
    assert manager.store.get_semantic(memory.id).user_id == "default"
    assert manager._current_owner() == ("default", "default")
    assert not manager.store.db._conn.in_transaction


def test_desktop_only_main_manager_and_future_background_sessions(manager, monkeypatch):
    memory = put(manager, "Desktop historical memory")
    manager._align_desktop_owner()
    assert manager.store.get_semantic(memory.id).user_id == "default"
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test")
    manager._desktop_owner_alignment_requested = False
    manager._align_desktop_owner()
    assert manager.store.get_semantic(memory.id).user_id == "default"
    manager._desktop_owner_alignment_requested = True
    manager = MemoryManager(
        manager.data_dir,
        manager.memory_md_path,
        search_backend="fts5",
        desktop_owner_alignment=True,
    )

    async def background_session():
        manager.start_session("desktop:new")
        fresh = SemanticMemory(type=MemoryType.FACT, content="New background memory")
        manager.save_user_memory(fresh)
        assert fresh.user_id == "desktop_user"
        assert manager.store.get_session_tenant("desktop:new") == ("desktop_user", "default")
        manager.start_session("im:new", user_id="im-user-42")
        assert manager._current_owner() == ("im-user-42", "default")
        manager.start_session("project:new", user_id="default", workspace_id="project")
        assert manager._current_owner() == ("default", "project")

    asyncio.run(background_session())


def test_graph_only_database_is_recovered(manager):
    graph = RelationalMemoryStore(manager.store.db._conn)
    node = MemoryNode(content="Graph without semantic rows")
    graph.save_node(node)
    report = align_desktop_owner(manager.store.db)
    assert report["counts"] == {"memories": 0, "session_tenants": 0, "mdrm_nodes": 1}
    assert graph.get_all_nodes(user_id="desktop_user", workspace_id="default")[0].id == node.id


def test_shared_managers_do_not_migrate_again_during_runtime(manager, monkeypatch):
    put(manager, "Initial historical memory")
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test")
    manager._align_desktop_owner()
    # A raw import after startup must wait until next startup; constructing a
    # shared agent during conversation processing must not run bulk writes.
    imported = put(manager, "Later imported memory")
    shared = MemoryManager(
        manager.data_dir,
        manager.memory_md_path,
        search_backend="fts5",
        desktop_owner_alignment=True,
    )
    assert shared._current_owner() == ("desktop_user", "default")
    assert shared.store.db.get_memory(imported.id)["user_id"] == "default"
    assert len(list(manager.data_dir.glob("openkitsune.db.bak.desktop_owner.*"))) == 1

    shared.store.db.close()
    restarted = MemoryManager(
        manager.data_dir,
        manager.memory_md_path,
        search_backend="fts5",
        desktop_owner_alignment=True,
    )
    try:
        assert restarted.store.db.get_memory(imported.id)["user_id"] == "desktop_user"
        assert len(list(manager.data_dir.glob("openkitsune.db.bak.desktop_owner.*"))) == 2
    finally:
        restarted.store.db.close()
