"""Exercise owner propagation through real session, extraction and graph paths."""

import asyncio
import contextvars
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openkitsune.agent.core import Agent
from openkitsune.api.routes.memory import router
from openkitsune.memory.lifecycle import LifecycleManager
from openkitsune.memory.manager import MemoryManager
from openkitsune.memory.session_identity import memory_session_id, memory_session_user
from openkitsune.memory.types import ConversationTurn, Episode, MemoryType, SemanticMemory
from openkitsune.sessions.session import Session
from openkitsune.tools.handlers.memory import MemoryHandler


@pytest.fixture
def make_manager(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(MemoryManager, "_maybe_schedule_snapshot", lambda self: None)
    managers = []

    def make(name="memory", **kwargs):
        mm = MemoryManager(tmp_path / name, tmp_path / f"{name}.md", **kwargs)
        managers.append(mm)
        return mm

    yield make
    for mm in managers:
        mm.store.db.close()


def panel(mm):
    app = FastAPI()
    app.include_router(router)
    app.state.agent = SimpleNamespace(memory_manager=mm)
    return TestClient(app)


def visible_memories(mm):
    # A real HTTP request does not inherit the currently executing agent's
    # ContextVars (TestClient otherwise copies the test caller's context).
    return contextvars.Context().run(lambda: panel(mm).get("/api/memories").json())


def extractor():
    async def episode(turns, session_id, **kwargs):
        return Episode(session_id=session_id, summary="A completed conversation")

    async def extract(turn):
        return [{"type": "FACT", "content": turn.content, "importance": 0.8}]

    return SimpleNamespace(
        brain=None,
        generate_episode=AsyncMock(side_effect=episode),
        extract_from_turn_v2=AsyncMock(side_effect=extract),
        extract_from_conversation=AsyncMock(return_value=([], [])),
        extract_experience_from_conversation=AsyncMock(return_value=[]),
    )


@pytest.mark.parametrize("reason", ["ambiguous_owners", "backup_failed"])
def test_new_desktop_fallback_does_not_depend_on_historical_migration(
    make_manager, monkeypatch, reason
):
    mm = make_manager()
    old = SemanticMemory(content="Historical default memory", type=MemoryType.FACT)
    mm.store.save_semantic(old)
    if reason == "ambiguous_owners":
        mm.store.upsert_session_tenant("feishu__chat__alice", "alice", "default")
    else:

        def fail_backup(*args):
            raise OSError("backup disk full")

        monkeypatch.setattr("openkitsune.memory.owner_migration.align_desktop_owner", fail_backup)
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test-launch")
    desktop = make_manager(desktop_owner_alignment=True)
    # History remains untouched, but new implicit desktop sessions must agree
    # with the panel even when history cannot be safely migrated.
    assert desktop.store.db.get_memory(old.id)["user_id"] == "default"
    desktop.start_session("new-bootstrap-session")
    fresh = SemanticMemory(content="New local desktop fact", type=MemoryType.FACT)
    desktop.save_user_memory(fresh, scope="user")
    assert desktop.store.get_session_tenant("new-bootstrap-session") == ("desktop_user", "default")
    assert visible_memories(desktop)["total"] == 1
    assert fresh.user_id == "desktop_user"


@pytest.mark.asyncio
@pytest.mark.parametrize("user,workspace", [("desktop_user", "default"), ("alice", "project-a")])
async def test_session_end_graph_uses_captured_owner(make_manager, monkeypatch, user, workspace):
    mm = make_manager()
    mm.extractor = extractor()
    monkeypatch.setattr(mm, "_get_memory_mode", lambda: "mode2")
    mm.start_session("original-session", user_id=user, workspace_id=workspace)
    mm._session_turns = [
        ConversationTurn(role="user", content="Remember the violet orchard project")
    ]
    mm.end_session()
    pending = list(mm._pending_tasks)
    mm.start_session("another-session", user_id="bob", workspace_id="project-b")
    await asyncio.gather(*pending)
    nodes = mm.relational_store.get_all_nodes()
    assert nodes
    assert {(n.user_id, n.workspace_id, n.session_id) for n in nodes} == {
        (user, workspace, "original-session")
    }


@pytest.mark.asyncio
async def test_summary_backfill_keeps_session_owner_and_edges_isolated(make_manager, monkeypatch):
    mm = make_manager()
    monkeypatch.setattr(mm, "_get_memory_mode", lambda: "mode2")
    assert mm._ensure_relational()

    async def summarize(user):
        mm.start_session(f"session-{user}", user_id=user, workspace_id=f"project-{user}")
        result = mm.relational_encoder.encode_quick(
            [{"role": "user", "content": f"Detailed private conversation for {user}"}],
            session_id=f"session-{user}",
        )
        for node in result.nodes:
            node.user_id, node.workspace_id = user, f"project-{user}"
        mm.relational_store.save_nodes_batch(result.nodes)
        mm._relational_pending_nodes.extend(result.nodes)
        await asyncio.sleep(0)
        await mm.on_summary_generated(f"A complete conversation summary belonging to {user}")

    await asyncio.gather(summarize("alice"), summarize("bob"))
    nodes = {n.id: n for n in mm.relational_store.get_all_nodes()}
    summaries = [n for n in nodes.values() if n.action_verb == "summarized"]
    assert len(summaries) == 2
    for summary in summaries:
        user = "alice" if "alice" in summary.content else "bob"
        assert (summary.user_id, summary.workspace_id, summary.session_id) == (
            user,
            f"project-{user}",
            f"session-{user}",
        )
    for edge in mm.relational_store.get_all_edges(set(nodes)):
        assert nodes[edge.source_id].user_id == nodes[edge.target_id].user_id


@pytest.mark.asyncio
async def test_truncated_session_runs_nightly_extraction_into_visible_owner(make_manager):
    mm = make_manager()
    session = Session.create(channel="desktop", chat_id="conversation", user_id="desktop_user")
    safe_id = session.session_key.replace(":", "__")
    mm.start_session(safe_id, user_id=session.user_id)
    session.set_metadata("_memory_manager", mm)
    # The manager may already be handling another user when persistence trims
    # this session. The queue must take its owner from the Session itself.
    mm.start_session("im:other", user_id="alice")
    session._mark_dropped_for_extraction(
        [{"role": "user", "content": "The user's preferred office is the violet orchard"}]
    )
    lifecycle = LifecycleManager(mm.store, extractor())
    await lifecycle.process_unextracted_turns()
    data = visible_memories(mm)
    assert data["total"] == 1
    assert data["memories"][0]["user_id"] == "desktop_user"
    assert mm.store.count_memories(scope="pending_consolidation", user_id="pending") == 0


@pytest.mark.asyncio
async def test_existing_session_is_realigned_when_only_owner_changed(make_manager, monkeypatch):
    mm = make_manager()
    session = Session.create(channel="desktop", chat_id="conversation", user_id="desktop_user")
    safe_id = session.session_key.replace(":", "__")
    mm.start_session(safe_id, user_id="default")
    agent = Agent.__new__(Agent)
    agent.memory_manager = mm
    agent._resolve_memory_workspace_id = lambda s: "default"

    class PreparedMemory(Exception):
        pass

    def stop_after_memory(**kwargs):
        raise PreparedMemory

    monkeypatch.setattr("openkitsune.core.im_context.ensure_im_context", stop_after_memory)
    with pytest.raises(PreparedMemory):
        await agent._prepare_session_context("hello", [], session.id, session, None, "conversation")
    assert mm._current_owner() == ("desktop_user", "default")
    assert mm.store.get_session_tenant(safe_id) == ("desktop_user", "default")


@pytest.mark.asyncio
async def test_migration_tool_recall_nightly_extraction_and_restart_agree(
    make_manager, monkeypatch
):
    mm = make_manager()
    mm.store.save_semantic(SemanticMemory(content="The old office was in Reykjavik"))
    mm.store.upsert_session_tenant("old-session", "default", "default")
    mm.store.save_turn(
        session_id="old-session",
        turn_index=0,
        role="user",
        content="The legal department uses the copper ledger for invoices",
    )
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test-launch")
    mm = make_manager(desktop_owner_alignment=True)
    mm.start_session("new-session")
    monkeypatch.setattr(mm, "_get_memory_mode", lambda: "mode1")
    monkeypatch.setattr(MemoryHandler, "_compute_guide_marker_path", lambda self: None)
    handler = MemoryHandler(
        SimpleNamespace(memory_manager=mm, _current_user_message="Remember this")
    )
    handler._add_memory(
        {
            "content": "The user's observatory project is named VioletOrchard",
            "type": "fact",
            "importance": 0.8,
            "scope": "global",
        }
    )
    assert "VioletOrchard" in handler._search_memory({"query": "VioletOrchard"})
    assert visible_memories(mm)["total"] == 2
    lifecycle = LifecycleManager(mm.store, extractor())
    first = await lifecycle.consolidate_daily()
    assert first["unextracted_processed"] == 1
    second = await lifecycle.consolidate_daily()
    assert second["unextracted_processed"] == 0
    assert visible_memories(mm)["total"] == 3
    assert mm.store.count_memories(user_id="default") == 0
    mm.store.db.close()
    reopened = make_manager(desktop_owner_alignment=True)
    assert visible_memories(reopened)["total"] == 3
    assert reopened.store.get_session_tenant("old-session") == ("desktop_user", "default")
    assert reopened.store.get_session_tenant("new-session") == ("desktop_user", "default")


@pytest.mark.asyncio
async def test_nightly_dedup_never_removes_another_owner_or_scope(make_manager):
    mm = make_manager()
    identities = [
        ("user", "", "desktop_user", "default"),
        ("user", "", "alice", "default"),
        ("user", "", "desktop_user", "project-a"),
        ("session", "session-a", "desktop_user", "default"),
        ("session", "session-b", "desktop_user", "default"),
    ]
    for scope, scope_owner, user, workspace in identities:
        mm.store.save_semantic(
            SemanticMemory(content="The project operates a violet orchard observatory"),
            scope=scope,
            scope_owner=scope_owner,
            user_id=user,
            workspace_id=workspace,
            skip_dedup=True,
        )
    lifecycle = LifecycleManager(mm.store, extractor())
    assert await lifecycle.deduplicate_batch() == 0
    assert len(mm.store.load_all_memories()) == len(identities)


@pytest.mark.parametrize(
    "channel,user,expected",
    [
        ("desktop", "default", "desktop_user"),
        ("desktop", "desktop_user", "desktop_user"),
        ("feishu", "default", "default"),
        ("feishu", "alice", "alice"),
        ("feishu", "", "anonymous"),
    ],
)
def test_session_identity_never_guesses_from_id(channel, user, expected):
    session = SimpleNamespace(
        channel=channel, user_id=user, session_key="bot:desktop_user_in_chat_id:alice"
    )
    assert memory_session_user(session) == expected
    assert memory_session_id(session) == "bot__desktop_user_in_chat_id__alice"


def test_explicit_im_default_is_not_a_desktop_alias(make_manager, monkeypatch):
    monkeypatch.setenv("OPENKITSUNE_DESKTOP_SESSION_TOKEN", "test-launch")
    mm = make_manager(desktop_owner_alignment=True)
    mm.start_session("feishu__chat__default", user_id="default")
    assert mm._current_owner() == ("default", "default")
    mm.save_user_memory(SemanticMemory(content="Explicit IM default user fact"), scope="user")
    mm.store.db.close()
    restarted = make_manager(desktop_owner_alignment=True)
    assert (
        restarted.store.db._desktop_owner_alignment_report["reason"]
        == "non_desktop_default_sessions"
    )
    assert restarted.store.count_memories(scope="user", user_id="default") == 1
    assert visible_memories(restarted)["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_user,target_workspace",
    [
        ("alice", "default"),
        ("desktop_user", "project-a"),
    ],
)
async def test_llm_review_cannot_merge_across_owners(make_manager, target_user, target_workspace):
    mm = make_manager()
    source = SemanticMemory(content="Local desktop fact")
    target = SemanticMemory(content="Independent tenant fact")
    mm.store.save_semantic(source, user_id="desktop_user")
    mm.store.save_semantic(target, user_id=target_user, workspace_id=target_workspace)
    ext = extractor()
    ext.brain = SimpleNamespace(
        think=AsyncMock(
            return_value=SimpleNamespace(
                content=json.dumps(
                    [
                        {
                            "id": source.id,
                            "action": "merge",
                            "merged_with": target.id,
                            "new_content": "A wrongly merged fact",
                        },
                        {"id": target.id, "action": "keep"},
                    ]
                )
            )
        )
    )
    report = await LifecycleManager(mm.store, ext).review_memories_with_llm()
    assert report["merged"] == 0
    assert mm.store.db.get_memory(source.id)["content"] == source.content
    assert mm.store.db.get_memory(target.id)["content"] == target.content
