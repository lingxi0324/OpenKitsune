"""Upgrade old UI history and cancellation snapshots without losing either."""

import json
from copy import deepcopy
from datetime import datetime

import pytest

from openkitsune.config import settings
from openkitsune.core._reasoning_runtime import ReasoningEngine
from openkitsune.core.cancel_cleanup import persist_working_messages
from openkitsune.sessions.manager import SessionManager
from openkitsune.sessions.model_transcript import ModelTranscript, is_human_message


async def test_legacy_session_remains_visible_and_imports_once(tmp_path):
    # Handwritten old schema: no model metadata, no timestamp on the first message.
    history = [
        {"role": "user", "content": "Remember project Alpha"},
        {"role": "assistant", "content": "Project Alpha recorded", "timestamp": "2025-01-01"},
    ]
    now = datetime.now().isoformat()
    legacy = {
        "id": "old-session",
        "channel": "telegram",
        "chat_id": "123",
        "user_id": "u",
        "created_at": now,
        "last_active": now,
        "context": {"messages": history, "summary": "Project Alpha"},
    }
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps([legacy]), encoding="utf-8")
    manager = SessionManager(storage_path=tmp_path)
    assert any(s.id == "old-session" for s in manager.list_sessions())
    session = manager.get_session("telegram", "123", "u", create_if_missing=False)
    assert manager.get_history("telegram", "123", "u") == history
    assert session.context.summary == "Project Alpha"
    original = path.read_bytes()  # The existing loader may normalize old session fields.
    store = await manager.open_model_transcript(
        data_dir=tmp_path, conversation_id="123", session=session
    )
    try:
        first = await store.admit(
            [*deepcopy(history), {"role": "user", "content": "continue"}],
            {"working_facts": "Alpha"},
            "NOW",
            "t1",
        )
        assert [m["content"] for m in first[:2]] == [m["content"] for m in history]
    finally:
        store.close()
    # Reading/admitting does not rewrite the old user-visible data.
    assert path.read_bytes() == original
    restarted = SessionManager(storage_path=tmp_path)
    restored = restarted.get_session("telegram", "123", "u", create_if_missing=False)
    assert restarted.get_history("telegram", "123", "u") == history
    store = await restarted.open_model_transcript(
        data_dir=tmp_path, conversation_id="123", session=restored
    )
    try:
        second = await store.admit(
            [*deepcopy(history), {"role": "user", "content": "next"}], {}, "LATER", "t2"
        )
        assert second[: len(first)] == first
        assert [m["content"] for m in second if is_human_message(m)] == [
            "Remember project Alpha",
            "continue",
            "next",
        ]
    finally:
        store.close()


async def test_legacy_cancel_migration_is_atomic_and_retryable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "project_root", tmp_path)
    snapshot = [
        {"role": "user", "content": "write file"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call", "name": "write_file", "input": {}}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call", "content": "already written"}
            ],
        },
    ]
    path = persist_working_messages("legacy", snapshot, base_dir=settings.data_dir)
    original = path.read_bytes()
    engine = ReasoningEngine.__new__(ReasoningEngine)
    seen = []

    async def drive(messages, **kwargs):
        seen.append(deepcopy(messages))
        yield {"type": "done"}

    engine._reason_stream_with_state = drive
    incoming = [{"role": "user", "content": "continue"}]
    write = ModelTranscript._write

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ModelTranscript, "_write", fail)
    with pytest.raises(OSError, match="disk full"):
        async for _ in engine.reason_stream(incoming, conversation_id="legacy", turn_id="t1"):
            pass
    assert path.read_bytes() == original
    assert seen == []
    monkeypatch.setattr(ModelTranscript, "_write", write)
    for _ in range(2):
        events = [
            event
            async for event in engine.reason_stream(
                incoming, conversation_id="legacy", turn_id="t1"
            )
        ]
        assert events[-1]["type"] == "done"
    assert not path.exists()
    assert len(seen) == 1  # Completed request retry never executes the model again.
    assert [m["content"] for m in seen[0] if is_human_message(m)] == ["write file", "continue"]
    assert seen[0][1:3] == snapshot[1:3]
