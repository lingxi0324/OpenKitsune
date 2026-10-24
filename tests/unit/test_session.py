"""L1 Unit Tests: Session state machine, message management."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest

from openkitsune.sessions.manager import SessionManager
from openkitsune.sessions.session import (
    Session,
    SessionConfig,
    SessionContext,
    SessionState,
    TaskCheckpoint,
    is_duplicate_message,
)


class TestSessionCreation:
    def test_default_state_is_active(self):
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        assert s.state == SessionState.ACTIVE

    def test_context_starts_empty(self):
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        assert s.context.messages == []
        assert s.context.current_task is None

    def test_custom_channel(self):
        s = Session(id="s1", channel="telegram", chat_id="tg-123", user_id="u1")
        assert s.channel == "telegram"
        assert s.chat_id == "tg-123"

    def test_session_key_uses_bot_instance_namespace(self):
        s = Session(
            id="s1",
            channel="feishu",
            bot_instance_id="feishu:writer",
            chat_id="chat-1",
            user_id="user-1",
            thread_id="topic-1",
        )

        assert s.session_key == "feishu:writer:chat-1:user-1:topic-1"

    def test_from_dict_legacy_session_defaults_bot_instance_to_channel(self):
        s = Session.from_dict(
            {
                "id": "s1",
                "channel": "feishu",
                "chat_id": "chat-1",
                "user_id": "user-1",
                "state": "active",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
            }
        )

        assert s.bot_instance_id == "feishu"
        assert s.session_key == "feishu:chat-1:user-1"

    def test_from_dict_ignores_legacy_timeout_minutes(self):
        s = Session.from_dict(
            {
                "id": "s1",
                "channel": "cli",
                "chat_id": "chat-1",
                "user_id": "user-1",
                "state": "active",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
                "config": {"timeout_minutes": 1},
            }
        )

        assert "timeout_minutes" not in s.to_dict()["config"]

    def test_session_manager_splits_same_chat_by_bot_instance(self, tmp_path):
        manager = SessionManager(storage_path=tmp_path / "sessions")

        writer = manager.get_session(
            "feishu",
            "chat-1",
            "user-1",
            bot_instance_id="feishu:writer",
        )
        reviewer = manager.get_session(
            "feishu",
            "chat-1",
            "user-1",
            bot_instance_id="feishu:reviewer",
        )

        assert writer.session_key == "feishu:writer:chat-1:user-1"
        assert reviewer.session_key == "feishu:reviewer:chat-1:user-1"
        assert writer is not reviewer

    def test_context_focus_terms_are_session_scoped_and_serialized(self):
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        s.add_message("user", "继续修改 src/openkitsune/memory/retrieval.py 的 retrieval gate")

        assert "src/openkitsune/memory/retrieval.py" in s.context.focus_terms

        restored = Session.from_dict(s.to_dict())
        assert restored.context.focus_terms == s.context.focus_terms


class TestAgentProfileScopedHistory:
    def test_add_message_stamps_active_agent_profile(self):
        ctx = SessionContext(agent_profile_id="english")

        added = ctx.add_message("user", "submit English homework")

        assert added is True
        assert ctx.messages[-1]["agent_profile_id"] == "english"

    def test_duplicate_detection_keeps_same_text_from_different_profiles(self):
        ctx = SessionContext(agent_profile_id="english")

        assert ctx.add_message("user", "done") is True
        ctx.agent_profile_id = "politics"

        assert ctx.add_message("user", "done") is True
        assert [m["agent_profile_id"] for m in ctx.messages] == ["english", "politics"]

    def test_profileless_turn_is_deduped_against_tagged_history(self):
        """回填回归：SQLite turn 未携带 agent_profile_id 时，
        必须能与已盖章（agent_profile_id="default"）的同内容消息去重，
        否则崩溃恢复会把同一轮重复 append 进会话历史。"""
        existing = [
            {
                "role": "user",
                "content": "你好",
                "timestamp": "2026-10-24T12:28:57.033135",
                "agent_profile_id": "default",
            },
            {
                "role": "assistant",
                "content": "回复",
                "timestamp": "2026-10-24T12:29:54.953969",
                "agent_profile_id": "default",
            },
        ]
        user_turn = {
            "role": "user",
            "content": "你好",
            "timestamp": "2026-10-24T12:28:57.033135",
            "tool_calls": None,
            "tool_results": None,
        }
        assistant_turn = {
            "role": "assistant",
            "content": "回复",
            "timestamp": "2026-10-24T12:29:54.953969",
            "tool_calls": None,
            "tool_results": None,
        }
        assert is_duplicate_message(existing, user_turn) is True
        assert is_duplicate_message(existing, assistant_turn) is True

    def test_filter_messages_for_agent_excludes_other_profile_turns(self):
        ctx = SessionContext(agent_profile_id="english")
        ctx.add_message("user", "English homework")
        ctx.add_message("assistant", "English feedback")
        ctx.agent_profile_id = "politics"
        ctx.add_message("user", "Politics textbook")
        ctx.add_message("assistant", "Politics answer")

        english = ctx.get_messages_for_agent("english")
        politics = ctx.get_messages_for_agent("politics")

        assert [m["content"] for m in english] == ["English homework", "English feedback"]
        assert [m["content"] for m in politics] == ["Politics textbook", "Politics answer"]

    def test_legacy_untagged_history_is_not_replayed_after_profile_switch(self):
        ctx = SessionContext(agent_profile_id="english")
        ctx.messages.extend(
            [
                {"role": "user", "content": "politics question"},
                {"role": "assistant", "content": "politics answer"},
            ]
        )
        ctx.agent_switch_history.append({"from": "default", "to": "english"})

        assert ctx.get_messages_for_agent("english") == []

    def test_legacy_single_profile_history_is_preserved_without_switches(self):
        ctx = SessionContext(agent_profile_id="english")
        ctx.messages.append({"role": "user", "content": "old English context"})

        assert ctx.get_messages_for_agent("english") == ctx.messages

    def test_legacy_single_profile_history_stays_visible_after_new_tagged_turn(self):
        ctx = SessionContext(agent_profile_id="english")
        ctx.messages.append({"role": "user", "content": "old English context"})
        ctx.add_message("assistant", "new English feedback")

        scoped = ctx.get_messages_for_agent("english")

        assert [m["content"] for m in scoped] == [
            "old English context",
            "new English feedback",
        ]

    def test_sub_agent_records_are_scoped_to_parent_profile(self):
        ctx = SessionContext(agent_profile_id="english")
        ctx.sub_agent_records = [
            {"parent_agent_profile_id": "english", "work_summary": "grammar review"},
            {"parent_agent_profile_id": "politics", "work_summary": "civics review"},
        ]

        records = ctx.get_sub_agent_records_for_agent("english")

        assert [r["work_summary"] for r in records] == ["grammar review"]


class TestSessionPersistence:
    def test_save_sessions_creates_queryable_sqlite_catalog(self, tmp_path):
        manager = SessionManager(storage_path=tmp_path / "sessions")
        session = manager.get_session("cli", "chat-1", "user-1")
        session.add_message("user", "hello")

        assert manager._save_sessions() is True

        sessions_file = tmp_path / "sessions" / "sessions.json"
        index_file = tmp_path / "sessions" / "sessions.index.sqlite3"
        assert (
            json.loads(sessions_file.read_text(encoding="utf-8"))[0]["context"]["messages"][0][
                "content"
            ]
            == "hello"
        )
        assert index_file.exists()
        with sqlite3.connect(index_file) as conn:
            row = conn.execute(
                "SELECT channel, chat_id, title, byte_offset, byte_length FROM sessions"
            ).fetchone()
        assert row[:3] == ("cli", "chat-1", "hello")
        assert row[3] >= 1
        assert row[4] > 0

    def test_incremental_summary_update_preserves_history_document(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "chat-1", "desktop_user")
        session.add_message("user", "history remains readable")
        session.set_metadata("conversation_title", "Original title")
        assert manager._save_sessions() is True

        sessions_file = storage_path / "sessions.json"
        original_bytes = sessions_file.read_bytes()
        original_stat = sessions_file.stat()
        original_entry = manager._catalog_store.get_entry(session.session_key)
        assert original_entry is not None

        session.set_metadata("conversation_title", "Updated searchable title")
        session.set_metadata("selected_endpoint", "minimax")
        session.set_metadata("endpoint_policy", "strict")
        session.set_metadata(
            "ui_org_state",
            {"orgMode": True, "orgId": "org_ops", "orgNodeId": "pm"},
        )

        assert manager.persist_summary(session) is True

        updated_entry = manager._catalog_store.get_entry(session.session_key)
        assert updated_entry is not None
        assert (updated_entry.offset, updated_entry.length) == (
            original_entry.offset,
            original_entry.length,
        )
        assert sessions_file.read_bytes() == original_bytes
        assert sessions_file.stat().st_mtime_ns == original_stat.st_mtime_ns
        assert (
            manager._catalog_store.read_document(updated_entry)["context"]["messages"][0]["content"]
            == "history remains readable"
        )
        assert manager._catalog_store.list_summaries(query="updated searchable").total == 1
        assert manager._catalog_store.list_summaries(query="original title").total == 0

        reloaded = SessionManager(storage_path=storage_path)
        restored = reloaded.get_session(
            "desktop", "chat-1", "desktop_user", create_if_missing=False
        )
        assert restored is not None
        assert restored.context.messages[0]["content"] == "history remains readable"
        assert restored.get_metadata("conversation_title") == "Updated searchable title"
        assert restored.get_metadata("selected_endpoint") == "minimax"
        assert restored.get_metadata("endpoint_policy") == "strict"
        assert restored.get_metadata("ui_org_state") == {
            "orgMode": True,
            "orgId": "org_ops",
            "orgNodeId": "pm",
        }

    def test_existing_catalog_schema_is_reused_on_full_save(self, tmp_path, monkeypatch):
        manager = SessionManager(storage_path=tmp_path / "sessions")
        session = manager.get_session("desktop", "chat-1", "desktop_user")
        session.add_message("user", "first")

        initialize_calls = 0
        real_initialize = manager._catalog_store._initialize_schema

        def recording_initialize(conn):
            nonlocal initialize_calls
            initialize_calls += 1
            return real_initialize(conn)

        monkeypatch.setattr(manager._catalog_store, "_initialize_schema", recording_initialize)

        assert manager._save_sessions() is True
        session.add_message("assistant", "second")
        assert manager._save_sessions() is True

        assert initialize_calls == 1

    def test_save_sessions_serializes_concurrent_writes(self, tmp_path, monkeypatch):
        manager = SessionManager(storage_path=tmp_path / "sessions")
        session = manager.get_session("cli", "chat-1", "user-1")
        session.add_message("user", "hello")

        failures = []
        start = threading.Barrier(8)
        counter_lock = threading.Lock()
        active_writes = 0
        max_active_writes = 0

        real_write = manager._catalog_store.write

        def spy(documents):
            nonlocal active_writes, max_active_writes
            with counter_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
            try:
                time.sleep(0.001)
                return real_write(documents)
            finally:
                with counter_lock:
                    active_writes -= 1

        def worker(worker_id: int) -> None:
            start.wait()
            for i in range(20):
                if not manager._save_sessions():
                    failures.append((worker_id, i))

        monkeypatch.setattr(manager._catalog_store, "write", spy)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        sessions_file = tmp_path / "sessions" / "sessions.json"
        data = json.loads(sessions_file.read_text(encoding="utf-8"))

        assert failures == []
        assert max_active_writes == 1
        assert len(data) == 1
        assert data[0]["context"]["messages"][0]["content"] == "hello"
        assert not sessions_file.with_suffix(sessions_file.suffix + ".tmp").exists()

    def test_persist_keeps_dirty_on_atomic_write_failure(self, tmp_path, monkeypatch):
        manager = SessionManager(storage_path=tmp_path / "sessions")
        manager._dirty = True
        monkeypatch.setattr(manager, "_save_sessions", lambda: False)

        manager.persist()

        assert manager._dirty is True

    def test_index_write_failure_keeps_deferred_offsets_aligned_for_retry(
        self, tmp_path, monkeypatch
    ):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        first = manager.get_session("desktop", "first", "desktop_user")
        first.add_message("user", "short")
        second = manager.get_session("desktop", "second", "desktop_user")
        second.add_message("user", "second history")
        assert manager._save_sessions() is True

        reloaded = SessionManager(storage_path=storage_path)
        restored_first = reloaded.get_session(
            "desktop", "first", "desktop_user", create_if_missing=False
        )
        assert restored_first is not None
        restored_first.add_message("assistant", "a much longer response that moves later offsets")
        second_key = "desktop:second:desktop_user"
        old_entry = reloaded._catalog_store.get_entry(second_key)
        assert old_entry is not None

        real_replace = reloaded._catalog_store._replace_with_retry
        failed = False

        def fail_primary_install(source, target, retries=3):
            nonlocal failed
            if source == reloaded._catalog_store.building_index_file and not failed:
                failed = True
                raise PermissionError("index unavailable")
            return real_replace(source, target, retries)

        monkeypatch.setattr(reloaded._catalog_store, "_replace_with_retry", fail_primary_install)

        assert reloaded._save_sessions() is False
        new_entry = reloaded._catalog_store.get_entry(second_key)
        assert new_entry is not None
        assert new_entry.offset > old_entry.offset

        monkeypatch.setattr(reloaded._catalog_store, "_replace_with_retry", real_replace)
        assert reloaded._save_sessions() is True

        retried = SessionManager(storage_path=storage_path)
        restored_second = retried.get_session(
            "desktop", "second", "desktop_user", create_if_missing=False
        )
        assert restored_second is not None
        assert restored_second.context.messages[0]["content"] == "second history"

    def test_restart_defers_full_session_hydration_until_lookup(self, tmp_path, monkeypatch):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        first = manager.get_session("desktop", "first", "desktop_user")
        first.add_message("user", "first history")
        second = manager.get_session("desktop", "second", "desktop_user")
        second.add_message("user", "second history")
        assert manager._save_sessions() is True

        original_from_dict = Session.from_dict
        hydration_calls = 0

        def recording_from_dict(data):
            nonlocal hydration_calls
            hydration_calls += 1
            return original_from_dict(data)

        monkeypatch.setattr(Session, "from_dict", recording_from_dict)
        reloaded = SessionManager(storage_path=storage_path)

        assert reloaded._sessions == {}
        assert not hasattr(reloaded, "_session_catalog")
        assert hydration_calls == 0
        assert {item["chat_id"] for item in reloaded.list_session_summaries()} == {
            "first",
            "second",
        }

        restored = reloaded.get_session("desktop", "first", "desktop_user", create_if_missing=False)

        assert restored is not None
        assert hydration_calls == 1
        assert restored.context.messages[0]["content"] == "first history"
        assert list(reloaded._sessions) == ["desktop:first:desktop_user"]

    def test_get_session_by_id_caches_a_deferred_session(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "first", "desktop_user")
        session.add_message("user", "first history")
        session_id = session.id
        assert manager._save_sessions() is True

        reloaded = SessionManager(storage_path=storage_path)
        restored = reloaded.get_session_by_id(session_id)

        assert restored is not None
        assert restored.context.messages[0]["content"] == "first history"
        assert reloaded._sessions[restored.session_key] is restored

    def test_cold_session_remains_available_and_hydrates_on_demand(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "cold", "desktop_user")
        session.add_message("user", "old history")
        session.last_active = datetime.now() - timedelta(days=90)
        assert manager._save_sessions() is True

        reloaded = SessionManager(storage_path=storage_path)

        assert reloaded._sessions == {}
        assert [summary["chat_id"] for summary in reloaded.list_session_summaries()] == ["cold"]

        restored = reloaded.get_session("desktop", "cold", "desktop_user", create_if_missing=False)
        assert restored is not None
        assert restored.context.messages[0]["content"] == "old history"

    def test_legacy_expired_session_reactivates_when_opened(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "legacy-expired", "desktop_user")
        session.add_message("user", "legacy history")
        session.last_active = datetime.now() - timedelta(days=90)
        session.mark_expired()
        assert manager._save_sessions() is True

        reloaded = SessionManager(storage_path=storage_path)
        summaries = reloaded.list_session_summaries()
        assert summaries[0]["state"] == SessionState.IDLE.value

        restored = reloaded.get_session(
            "desktop", "legacy-expired", "desktop_user", create_if_missing=False
        )
        assert restored is not None
        assert restored.state == SessionState.ACTIVE

    @pytest.mark.asyncio
    async def test_cold_cleanup_evicts_memory_but_keeps_session_reloadable(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "cold", "desktop_user")
        session.add_message("user", "reload me")
        session.last_active = datetime.now() - timedelta(days=90)
        assert manager._save_sessions() is True

        assert await manager.cleanup_expired() == 1
        assert manager._sessions == {}
        assert [summary["chat_id"] for summary in manager.list_session_summaries()] == ["cold"]

        restored = manager.get_session("desktop", "cold", "desktop_user", create_if_missing=False)
        assert restored is not None
        assert restored.context.messages[0]["content"] == "reload me"

    @pytest.mark.asyncio
    async def test_cold_cleanup_keeps_loaded_session_when_persistence_fails(
        self, tmp_path, monkeypatch
    ):
        manager = SessionManager(storage_path=tmp_path / "sessions")
        session = manager.get_session("desktop", "cold", "desktop_user")
        session.add_message("user", "unsaved history")
        session.last_active = datetime.now() - timedelta(days=90)
        manager.mark_dirty()
        monkeypatch.setattr(manager, "_save_sessions", lambda: False)

        assert await manager.cleanup_expired() == 0
        assert manager._sessions[session.session_key] is session
        assert manager._dirty is True

    def test_catalog_build_failure_keeps_cold_sessions_available(self, tmp_path, monkeypatch):
        from openkitsune.sessions.catalog import SessionCatalogStore

        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "cold", "desktop_user")
        session.add_message("user", "fallback history")
        session.last_active = datetime.now() - timedelta(days=90)
        assert manager._save_sessions() is True
        (storage_path / "sessions.index.sqlite3").unlink()

        def fail_catalog_write(*_args, **_kwargs):
            raise OSError("index unavailable")

        monkeypatch.setattr(SessionCatalogStore, "write", fail_catalog_write)
        reloaded = SessionManager(storage_path=storage_path)

        restored = reloaded.get_session("desktop", "cold", "desktop_user", create_if_missing=False)
        assert restored is not None
        assert restored.context.messages[0]["content"] == "fallback history"

    def test_legacy_json_index_is_removed_when_sqlite_catalog_is_built(self, tmp_path):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        session = manager.get_session("desktop", "legacy", "desktop_user")
        session.add_message("user", "legacy catalog")
        assert manager._save_sessions() is True

        sqlite_index = storage_path / "sessions.index.sqlite3"
        legacy_index = storage_path / "sessions.index.json"
        sqlite_index.unlink()
        legacy_index.write_text('{"version":1,"sessions":[]}', encoding="utf-8")

        reloaded = SessionManager(storage_path=storage_path)

        assert sqlite_index.exists()
        assert not legacy_index.exists()
        assert [summary["chat_id"] for summary in reloaded.list_session_summaries()] == ["legacy"]

    def test_save_rebuilds_corrupt_sqlite_catalog_without_dropping_deferred_sessions(
        self, tmp_path
    ):
        storage_path = tmp_path / "sessions"
        manager = SessionManager(storage_path=storage_path)
        first = manager.get_session("desktop", "first", "desktop_user")
        first.add_message("user", "first history")
        second = manager.get_session("desktop", "second", "desktop_user")
        second.add_message("user", "second history")
        assert manager._save_sessions() is True

        reloaded = SessionManager(storage_path=storage_path)
        restored_first = reloaded.get_session(
            "desktop", "first", "desktop_user", create_if_missing=False
        )
        assert restored_first is not None
        restored_first.add_message("assistant", "updated first history")
        (storage_path / "sessions.index.sqlite3").write_bytes(b"not a sqlite database")

        assert reloaded._save_sessions() is True

        restarted = SessionManager(storage_path=storage_path)
        restored_second = restarted.get_session(
            "desktop", "second", "desktop_user", create_if_missing=False
        )
        assert restored_second is not None
        assert restored_second.context.messages[0]["content"] == "second history"
        assert {item["chat_id"] for item in restarted.list_session_summaries()} == {
            "first",
            "second",
        }


class TestSessionState:
    def test_all_states_exist(self):
        assert SessionState.ACTIVE.value == "active"
        assert SessionState.IDLE.value == "idle"
        assert SessionState.EXPIRED.value == "expired"
        assert SessionState.CLOSED.value == "closed"

    def test_state_is_settable(self):
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        s.state = SessionState.IDLE
        assert s.state == SessionState.IDLE
        s.state = SessionState.EXPIRED
        assert s.state == SessionState.EXPIRED


class TestSessionContext:
    def test_add_messages(self):
        ctx = SessionContext()
        ctx.messages.append({"role": "user", "content": "hello"})
        ctx.messages.append({"role": "assistant", "content": "hi"})
        assert len(ctx.messages) == 2

    def test_variables_dict(self):
        ctx = SessionContext()
        ctx.variables["key"] = "value"
        assert ctx.variables["key"] == "value"

    def test_to_dict_returns_independent_snapshot(self):
        ctx = SessionContext()
        ctx.messages.append({"role": "user", "content": {"text": "hello"}})
        snapshot = ctx.to_dict()

        ctx.messages[0]["content"]["text"] = "changed"

        assert snapshot["messages"][0]["content"]["text"] == "hello"

    def test_task_lifecycle(self):
        ctx = SessionContext()
        assert ctx.current_task is None
        ctx.current_task = "Write a poem"
        assert ctx.current_task == "Write a poem"
        ctx.current_task = None
        assert ctx.current_task is None

    def test_summary_field(self):
        ctx = SessionContext()
        assert ctx.summary is None
        ctx.summary = "User asked about Python"
        assert ctx.summary == "User asked about Python"

    def test_duplicate_detection_matches_same_content_with_near_timestamp(self):
        existing = [
            {"role": "user", "content": "same prompt", "timestamp": "2026-06-25T18:06:53.993669"}
        ]
        candidate = {
            "role": "user",
            "content": "same prompt",
            "timestamp": "2026-06-25T18:06:53.999736",
        }

        assert is_duplicate_message(existing, candidate)

    def test_duplicate_detection_allows_same_content_after_window(self):
        existing = [
            {"role": "user", "content": "same prompt", "timestamp": "2026-06-25T18:06:53"},
            {"role": "assistant", "content": "done", "timestamp": "2026-06-25T18:07:10"},
        ]
        candidate = {
            "role": "user",
            "content": "same prompt",
            "timestamp": "2026-06-25T18:08:00",
        }

        assert not is_duplicate_message(existing, candidate)

    def test_add_message_writer_reuses_session_message_timestamp(self, tmp_path):
        written: list[tuple[str, str | None]] = []

        def writer(_safe_id, _turn_index, role, _content, metadata):
            written.append((role, metadata.get("timestamp")))

        manager = SessionManager(storage_path=tmp_path)
        manager.set_turn_writer(writer)
        session = manager.get_session("desktop", "conv1", "desktop_user")
        assert session is not None

        session.add_message("user", "hello")

        assert written == [("user", session.context.messages[-1]["timestamp"])]

    def test_session_manager_backfill_skips_near_duplicate_turn(self, tmp_path):
        session = Session(
            id="test_near_dup",
            channel="test",
            chat_id="1",
            user_id="u",
            context=SessionContext(
                messages=[
                    {
                        "role": "user",
                        "content": "same prompt",
                        "timestamp": "2026-06-25T18:06:53.993669",
                    },
                ]
            ),
        )
        (tmp_path / "sessions.json").write_text(
            json.dumps([session.to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )
        manager = SessionManager(storage_path=tmp_path)
        manager.set_turn_loader(
            lambda _safe_id: [
                {
                    "role": "user",
                    "content": "same prompt",
                    "timestamp": "2026-06-25T18:06:53.999736",
                },
            ]
        )

        count = manager.backfill_sessions_from_store()

        loaded = manager.get_session("test", "1", "u", create_if_missing=False)
        assert count == 0
        assert loaded is not None
        assert [m["content"] for m in loaded.context.messages] == ["same prompt"]


class TestSessionConfig:
    def test_default_config(self):
        config = SessionConfig()
        assert isinstance(config, SessionConfig)


class TestMetadataTrimming:
    """_trim_old_metadata: 日常体积控制，裁剪重型元数据但不删消息 (#309)."""

    def _make_session(self, max_history: int = 2000) -> Session:
        return Session(
            id="s1",
            channel="desktop",
            chat_id="c1",
            user_id="u1",
            config=SessionConfig(max_history=max_history),
        )

    def test_default_max_history_is_2000(self):
        config = SessionConfig()
        assert config.max_history == 2000

    def test_from_dict_no_config_defaults_to_2000(self):
        s = Session.from_dict(
            {
                "id": "s1",
                "channel": "desktop",
                "chat_id": "c1",
                "user_id": "u1",
                "state": "active",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
            }
        )
        assert s.config.max_history == 2000

    def test_from_dict_upgrades_old_small_values(self):
        """旧 session 序列化值 100/500 应被迁移至 >= 500."""
        s = Session.from_dict(
            {
                "id": "s1",
                "channel": "desktop",
                "chat_id": "c1",
                "user_id": "u1",
                "state": "active",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
                "config": {"max_history": 100},
            }
        )
        assert s.config.max_history >= 500

    def test_messages_never_deleted_below_hard_cap(self):
        """低于 hard cap 时，add_message 只 trim 元数据，不删除消息。"""
        s = self._make_session(max_history=2000)
        for i in range(200):
            s.add_message(
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
                chain_summary=f"chain-{i}",
                tool_summary=f"tool-{i}",
            )
        assert len(s.context.messages) == 200

    def test_trim_strips_heavy_metadata_from_old_messages(self):
        """超过 preserve window 的旧消息应丢失 chain_summary 等重型字段。"""
        s = self._make_session()
        for i in range(80):
            s.add_message(
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
                chain_summary=f"chain-{i}",
                tool_summary=f"tool-{i}",
                artifacts=[f"artifact-{i}"],
            )
        old_msg = s.context.messages[0]
        assert "chain_summary" not in old_msg
        assert "tool_summary" not in old_msg
        assert "artifacts" not in old_msg
        recent_msg = s.context.messages[-1]
        assert recent_msg.get("chain_summary") == f"chain-{80 - 1}"

    def test_trim_preserves_base_content(self):
        """trim 后旧消息的 role/content/timestamp 必须完好。"""
        s = self._make_session()
        for i in range(80):
            s.add_message(
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
                chain_summary="big data",
            )
        for msg in s.context.messages:
            assert "content" in msg
            assert "role" in msg

    def test_recent_messages_keep_full_metadata(self):
        """最近 _METADATA_PRESERVE_WINDOW 条消息保留全部元数据。"""
        s = self._make_session()
        window = Session._METADATA_PRESERVE_WINDOW
        for i in range(window + 20):
            s.add_message(
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
                chain_summary=f"chain-{i}",
            )
        for msg in s.context.messages[-window:]:
            assert "chain_summary" in msg


class TestHardCapTruncation:
    """_truncate_history: 仅 hard cap (2000) 极端兜底 (#309)."""

    def _make_session(self, max_history: int = 100) -> Session:
        return Session(
            id="s1",
            channel="desktop",
            chat_id="c1",
            user_id="u1",
            config=SessionConfig(max_history=max_history),
        )

    def test_hard_cap_triggers_above_max_history(self):
        s = self._make_session(max_history=100)
        for i in range(101):
            s.add_message("user" if i % 2 == 0 else "assistant", f"msg-{i}")
        assert len(s.context.messages) <= 100

    def test_hard_cap_keeps_95_percent(self):
        s = self._make_session(max_history=200)
        for i in range(201):
            s.add_message("user" if i % 2 == 0 else "assistant", f"msg-{i}")
        # 95% of 200 = 190, plus possible system summary = 191
        assert len(s.context.messages) >= 190
        assert len(s.context.messages) <= 192

    def test_hard_cap_preserves_recent_messages(self):
        s = self._make_session(max_history=100)
        for i in range(120):
            s.add_message("user" if i % 2 == 0 else "assistant", f"msg-{i}")
        contents = [m.get("content", "") for m in s.context.messages]
        assert "msg-119" in contents

    def test_hard_cap_produces_summary_on_truncation(self):
        s = self._make_session(max_history=100)
        for i in range(101):
            s.add_message("user" if i % 2 == 0 else "assistant", f"msg-{i}")
        system_msgs = [m for m in s.context.messages if m.get("role") == "system"]
        assert len(system_msgs) >= 1
        assert "[历史背景" in system_msgs[0].get("content", "")


class TestSessionTimestamps:
    def test_created_at_set(self):
        before = datetime.now()
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        after = datetime.now()
        assert before <= s.created_at <= after

    def test_last_active_set(self):
        s = Session(id="s1", channel="cli", chat_id="c1", user_id="u1")
        assert s.last_active is not None


class TestTaskCheckpoint:
    """task_checkpoints — 借鉴 claude-code 的任务连续性。"""

    def _ckpt(self, **overrides) -> TaskCheckpoint:
        base = {
            "checkpoint_id": "ckpt-001",
            "task_id": "task-1",
            "conversation_id": "conv-1",
            "iteration": 2,
            "created_at": 1234567890.0,
            "summary": "已读取 8 个文件",
            "next_step_hint": "运行测试验证",
            "exit_reason": "iteration_complete",
            "artifacts": ["a.py"],
            "messages_offset": 12,
        }
        base.update(overrides)
        return TaskCheckpoint(**base)

    def test_to_from_dict_roundtrip(self):
        original = self._ckpt()
        restored = TaskCheckpoint.from_dict(original.to_dict())
        assert restored.to_dict() == original.to_dict()

    def test_from_dict_handles_missing_fields(self):
        ckpt = TaskCheckpoint.from_dict({"checkpoint_id": "x"})
        assert ckpt.checkpoint_id == "x"
        assert ckpt.iteration == 0
        assert ckpt.exit_reason == "running"
        assert ckpt.artifacts == []

    def test_append_writes_to_context(self):
        ctx = SessionContext()
        result = ctx.append_task_checkpoint(self._ckpt())
        assert ctx.task_checkpoints == [result]
        assert result["task_id"] == "task-1"
        assert result["exit_reason"] == "iteration_complete"

    def test_append_accepts_dict(self):
        ctx = SessionContext()
        ctx.append_task_checkpoint(
            {
                "checkpoint_id": "raw",
                "task_id": "t",
                "conversation_id": "c",
                "iteration": 1,
                "created_at": 1.0,
                "exit_reason": "completed",
            }
        )
        assert len(ctx.task_checkpoints) == 1
        assert ctx.task_checkpoints[0]["checkpoint_id"] == "raw"

    def test_append_rejects_invalid_type(self):
        ctx = SessionContext()
        with pytest.raises(TypeError):
            ctx.append_task_checkpoint("not-a-checkpoint")  # type: ignore[arg-type]

    def test_append_caps_at_max_keep(self):
        ctx = SessionContext()
        for i in range(60):
            ctx.append_task_checkpoint(self._ckpt(checkpoint_id=f"c{i}"), max_keep=50)
        assert len(ctx.task_checkpoints) == 50
        assert ctx.task_checkpoints[0]["checkpoint_id"] == "c10"
        assert ctx.task_checkpoints[-1]["checkpoint_id"] == "c59"

    def test_latest_filters_by_task(self):
        ctx = SessionContext()
        ctx.append_task_checkpoint(self._ckpt(checkpoint_id="a", task_id="X"))
        ctx.append_task_checkpoint(self._ckpt(checkpoint_id="b", task_id="Y"))
        ctx.append_task_checkpoint(self._ckpt(checkpoint_id="c", task_id="X"))
        assert ctx.latest_task_checkpoint()["checkpoint_id"] == "c"
        assert ctx.latest_task_checkpoint("X")["checkpoint_id"] == "c"
        assert ctx.latest_task_checkpoint("Y")["checkpoint_id"] == "b"
        assert ctx.latest_task_checkpoint("Z") is None

    def test_serialization_roundtrip_via_session_context(self):
        ctx = SessionContext()
        ctx.append_task_checkpoint(self._ckpt())
        restored = SessionContext.from_dict(ctx.to_dict())
        assert restored.task_checkpoints == ctx.task_checkpoints
