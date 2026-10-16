"""Model-visible history stays append-only across turns, recovery and wire conversion."""

import asyncio
from copy import deepcopy

import pytest

from openkitsune.llm.converters.messages import (
    convert_messages_to_openai,
    convert_messages_to_responses,
)
from openkitsune.llm.providers.anthropic import AnthropicProvider
from openkitsune.llm.types import (
    EndpointConfig,
    LLMRequest,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from openkitsune.sessions.model_transcript import ModelTranscript, is_human_message, new_stream_id


def user(text="hello"):
    return {"role": "user", "content": text}


async def opened(tmp_path, stream="test"):
    store = ModelTranscript(tmp_path / "model.sqlite3", stream)
    await store.open()
    return store


async def test_plan_context_dedup_clear_unavailable_and_restart(tmp_path, monkeypatch):
    from openkitsune.core._reasoning_runtime import ReasoningEngine
    from openkitsune.sessions.model_transcript import active_transcript

    store = await opened(tmp_path)
    token = active_transcript.set(store)
    messages = await store.admit([user()], {}, "", "1")
    payload = ["Step 1: pending"]
    monkeypatch.setattr(
        "openkitsune.tools.handlers.plan.get_active_todo_prompt", lambda _: payload[0]
    )
    try:
        await ReasoningEngine._sync_plan_context(None, messages, "test")
        baseline = deepcopy(messages)
        await ReasoningEngine._sync_plan_context(None, messages, "test")
        assert messages == baseline
        payload[0] = "Step 1: completed"
        await ReasoningEngine._sync_plan_context(None, messages, "test")
        assert messages[: len(baseline)] == baseline
        assert messages[-1]["_model_context"]["version"] == 2

        def unavailable(_):
            raise OSError("plan store unavailable")

        monkeypatch.setattr("openkitsune.tools.handlers.plan.get_active_todo_prompt", unavailable)
        await ReasoningEngine._sync_plan_context(None, messages, "test")
        assert messages[-1]["_model_context"]["status"] == "unavailable"
        payload[0] = ""
        monkeypatch.setattr(
            "openkitsune.tools.handlers.plan.get_active_todo_prompt", lambda _: payload[0]
        )
        await ReasoningEngine._sync_plan_context(None, messages, "test")
        assert messages[-1]["_model_context"]["status"] == "cleared"
        store.close()
        store = await opened(tmp_path)
        assert store.messages == messages
        compacted = store.retain_context([user("summary")])
        assert compacted[-1]["_model_context"]["status"] == "cleared"
    finally:
        active_transcript.reset(token)
        store.close()


async def test_two_turns_restart_and_state_dedup(tmp_path):
    store = await opened(tmp_path)
    first = await store.admit([user()], {"working_facts": "A"}, "TIME-1", "t1")
    first.append({"role": "assistant", "content": "answer", "reasoning_content": "reason"})
    await store.sync(first)
    store.close()
    store = await opened(tmp_path)
    try:
        second = await store.admit(
            [user("rewritten history"), user("next")], {"working_facts": "A"}, "TIME-2", "t2"
        )
        assert second[: len(first)] == first
        assert "rewritten history" not in str(second)
        assert str(second).count("TIME-1") == str(second).count("TIME-2") == 1
        assert sum("_model_context" in m for m in second) == 1
        assert [m["content"] for m in second if is_human_message(m)] == ["hello", "next"]
    finally:
        store.close()


async def test_retry_reuses_admission_and_rejects_changed_input(tmp_path):
    store = await opened(tmp_path)
    try:
        first = await store.admit([user()], {"working_facts": "A"}, "TIME-1", "t1")
        revision = store.revision
        again = await store.admit([user()], {"working_facts": "B"}, "TIME-2", "t1")
        assert again == first
        assert store.revision == revision
        with pytest.raises(ValueError, match="different input"):
            await store.admit([user("different")], {}, "", "t1")
    finally:
        store.close()


async def test_change_clear_and_compaction_do_not_resurrect_old_state(tmp_path):
    store = await opened(tmp_path)
    try:
        first = await store.admit([user()], {"working_facts": "A", "user_profile": "P"}, "", "1")
        second = await store.admit(
            [user("next")], {"working_facts": "B", "user_profile": "P"}, "", "2"
        )
        assert second[: len(first)] == first
        assert second[-1]["_model_context"]["version"] == 2
        cleared = await store.admit([user("clear")], {"working_facts": ""}, "", "3")
        assert "status: cleared" in cleared[-1]["content"]
        compressed = [user("summary")]
        await store.sync(compressed, reason="compression")
        latest = store.latest_context()
        assert latest["working_facts"]["_model_context"]["payload"] == ""
        assert latest["user_profile"]["_model_context"]["payload"] == "P"
        next_turn = await store.admit(
            [user("again")], {"working_facts": "", "user_profile": "P"}, "", "4"
        )
        assert next_turn == compressed + [{**user("again"), "_model_source": "human"}]
    finally:
        store.close()


async def test_retrieval_is_scoped_to_turn_not_stale_global_state(tmp_path):
    store = await opened(tmp_path)
    try:
        first = await store.admit([user()], {"retrieved_memory": "same evidence"}, "", "1")
        second = await store.admit([user("next")], {"retrieved_memory": "same evidence"}, "", "2")
        assert second[: len(first)] == first
        assert second[-1]["_model_context"]["scope"] == "turn:2"
        assert "only to its named turn" in second[-1]["content"]
    finally:
        store.close()


async def test_failed_commit_is_atomic_and_does_not_change_memory(tmp_path, monkeypatch):
    store = await opened(tmp_path)
    original = store._write
    try:

        def fail(*_):
            raise OSError("disk full")

        monkeypatch.setattr(store, "_write", fail)
        with pytest.raises(OSError, match="disk full"):
            await store.admit([user()], {"working_facts": "A"}, "time", "1")
        assert store.messages == [] and store.turns == {} and store.revision == 0
        monkeypatch.setattr(store, "_write", original)
        await store.admit([user()], {"working_facts": "A"}, "time", "1")
        assert len(store.messages) == 3
    finally:
        store.close()


async def test_orphan_tool_recovery_uses_durable_full_result(tmp_path):
    store = await opened(tmp_path)
    messages = await store.admit([user()], {}, "", "1")
    messages.append(
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {}},
                {"type": "tool_use", "id": "call-2", "name": "read_file", "input": {}},
            ],
        }
    )
    await store.sync(messages)
    await store.record_tool_result(
        {"type": "tool_result", "tool_use_id": "call-1", "content": "x" * 10000}
    )
    store.close()
    store = await opened(tmp_path)
    try:
        recovered = await store.admit([user("continue")], {"working_facts": "new"}, "time", "2")
        results = [
            b
            for m in recovered
            if isinstance(m.get("content"), list)
            for b in m["content"]
            if b["type"] == "tool_result"
        ]
        assert next(b for b in results if b["tool_use_id"] == "call-1")["content"] == "x" * 10000
        assert next(b for b in results if b["tool_use_id"] == "call-2")["is_error"]
        result_index = next(
            i
            for i, m in enumerate(recovered)
            if isinstance(m.get("content"), list) and m["content"][0]["type"] == "tool_result"
        )
        assert recovered[result_index - 1]["role"] == "assistant"
        assert recovered[result_index + 1]["content"] == "continue"
    finally:
        store.close()


def typed(messages):
    result = []
    classes = {"text": TextBlock, "tool_use": ToolUseBlock, "tool_result": ToolResultBlock}
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            content = [
                classes[b["type"]](**{k: v for k, v in b.items() if k != "type"}) for b in content
            ]
        result.append(
            Message(
                role=message["role"],
                content=content,
                reasoning_content=message.get("reasoning_content"),
            )
        )
    return result


@pytest.mark.parametrize("api", ["deepseek", "openai", "google", "responses", "anthropic"])
async def test_final_wire_prefix_is_stable_across_turns_and_tools(tmp_path, api):
    def wire(messages):
        if api == "responses":
            return convert_messages_to_responses(typed(messages), "stable")[0]
        if api == "anthropic":
            provider = AnthropicProvider(
                EndpointConfig(
                    name="test",
                    provider="anthropic",
                    api_type="anthropic",
                    model="claude-sonnet-4-20250514",
                    api_key="test",
                    base_url="https://example.invalid",
                )
            )
            result = provider._build_request_body(
                LLMRequest(messages=typed(messages), system="stable")
            )["messages"]
            # Cache breakpoints move as the history grows; their transport metadata is not content.
            for message in result:
                if isinstance(message.get("content"), list):
                    for block in message["content"]:
                        block.pop("cache_control", None)
                if isinstance(message.get("content"), str):
                    message["content"] = [{"type": "text", "text": message["content"]}]
            return result
        return convert_messages_to_openai(
            typed(messages), "stable", provider=api, enable_thinking=True
        )

    store = await opened(tmp_path)
    try:
        first = await store.admit([user()], {"working_facts": "A"}, "T1", "1")
        first_wire = deepcopy(wire(first))
        first.extend(
            [
                {
                    "role": "assistant",
                    "reasoning_content": "read",
                    "content": [{"type": "tool_use", "id": "c1", "name": "read_file", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "data"}],
                },
            ]
        )
        await store.sync(first)
        continuation_wire = deepcopy(wire(first))
        assert continuation_wire[: len(first_wire)] == first_wire
        first.append({"role": "assistant", "content": "answer"})
        await store.sync(first)
        second = await store.admit([user("next")], {"working_facts": "B"}, "T2", "2")
        assert wire(second)[: len(continuation_wire)] == continuation_wire
    finally:
        store.close()


async def test_single_writer_and_stream_isolation(tmp_path):
    first = await opened(tmp_path)
    other = ModelTranscript(first.path, "test")
    task = asyncio.create_task(other.open())
    await asyncio.sleep(0)
    assert not task.done()
    await first.admit([user()], {}, "", "1")
    first.close()
    await task
    assert other.messages[0]["content"] == "hello"
    other.close()
    isolated = await opened(tmp_path, "other-agent")
    assert isolated.messages == []
    isolated.close()
    assert new_stream_id("c", "p", "", True) != new_stream_id("c", "p", "", True)
    assert new_stream_id("c", "p", "reset", False) != new_stream_id("c", "p", "", False)


async def test_plugin_context_changes_append_without_modifying_user(tmp_path):
    store = await opened(tmp_path)
    try:
        messages = await store.admit([user()], {}, "", "1")
        await store.update_context(messages, "plugin_context", "A")
        first = deepcopy(messages)
        await store.update_context(messages, "plugin_context", "A")
        assert messages == first
        await store.update_context(messages, "plugin_context", "B")
        assert messages[: len(first)] == first
        assert messages[0]["content"] == "hello"
        await store.update_context(messages, "plugin_context", "")
        assert "status: cleared" in messages[-1]["content"]
    finally:
        store.close()


async def test_unavailable_is_not_clear_and_partial_reply_survives_restart(tmp_path):
    store = await opened(tmp_path)
    await store.admit([user()], {"working_facts": "A"}, "T1", "1")
    await store.record_frame("text", "partial answer")
    await store.record_frame("thinking", "partial reasoning")
    store.close()
    store = await opened(tmp_path)
    try:
        messages = await store.admit([user("continue")], {"working_facts": None}, "T2", "2")
        partial = next(m for m in messages if m.get("_model_interrupted"))
        assert partial["content"] == "partial answer"
        assert partial["reasoning_content"] == "partial reasoning"
        assert store.partial == {"text": "", "thinking": ""}
        assert "status: unavailable" in messages[-1]["content"]
        assert "last-known history" in messages[-1]["content"]
        assert not is_human_message(messages[-1])
        from openkitsune.core.response_handler import ResponseHandler

        assert ResponseHandler.get_last_user_request(messages) == "continue"
    finally:
        store.close()


async def test_real_reasoning_loop_replays_normal_turns_and_completed_retries(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from openkitsune.config import settings
    from openkitsune.core._reasoning_runtime import Decision, DecisionType, ReasoningEngine
    from openkitsune.core.agent_state import AgentState
    from openkitsune.llm.cache import SYSTEM_PROMPT_CONTEXT_BOUNDARY, SYSTEM_PROMPT_CONTEXT_END
    from openkitsune.prompt.turn_context import encode_context

    monkeypatch.setattr(settings, "project_root", tmp_path)
    plan = ["plan version 1"]
    monkeypatch.setattr("openkitsune.tools.handlers.plan.get_active_todo_prompt", lambda _: plan[0])
    requests = []

    def engine():
        context = Mock()
        context.estimate_messages_tokens.return_value = 0
        context.estimate_tools_tokens.return_value = 0
        context.get_max_context_tokens.return_value = 0
        context.compress_if_needed = AsyncMock(side_effect=lambda messages, **_: messages)
        context.calculate_context_pressure.return_value = SimpleNamespace(
            messages_tokens=0,
            system_tokens=0,
            tools_tokens=0,
            trigger_tokens=0,
            soft_limit=10000,
            hard_limit=12000,
            max_tokens=16000,
        )
        # 与真实 ContextManager 默认一致：不触发任务恢复卡注入路径
        context.context_preparation_pending = False
        context.normalize_turn_roles = lambda messages, **_: messages
        instance = ReasoningEngine(
            brain=SimpleNamespace(
                model="test", max_tokens=4096, get_current_endpoint_info=lambda: {}
            ),
            tool_executor=SimpleNamespace(),
            context_manager=context,
            response_handler=Mock(),
            agent_state=AgentState(),
        )
        instance._save_react_trace = Mock()
        instance._handle_final_answer = AsyncMock(return_value="visible answer")

        async def respond(messages, **kwargs):
            requests.append((deepcopy(messages), kwargs["system_prompt"]))
            yield {
                "type": "decision",
                "decision": Decision(
                    type=DecisionType.FINAL_ANSWER,
                    text_content="raw answer",
                    assistant_content=[{"type": "text", "text": "raw answer"}],
                    thinking_content="reasoning",
                ),
            }

        instance._reason_stream_iter = respond
        return instance

    async def run_turn(instance, text, turn, clock):
        system = (
            "stable"
            + SYSTEM_PROMPT_CONTEXT_BOUNDARY
            + encode_context({"working_facts": "A"}, clock)
            + SYSTEM_PROMPT_CONTEXT_END
        )
        return [
            event
            async for event in instance.reason_stream(
                [user(text)],
                tools=[],
                conversation_id="conversation",
                turn_id=turn,
                system_prompt=system,
                base_system_prompt=system,
                mode="ask",
                force_tool_retries=0,
            )
        ]

    first = await run_turn(engine(), "one", "1", "T1")
    assert not any(e["type"] == "error" for e in first), first
    plan[0] = "plan version 2"
    second = await run_turn(engine(), "two", "2", "T2")
    assert not any(e["type"] == "error" for e in second), second
    assert len(requests) == 2
    assert requests[0][1] == requests[1][1] == "stable"
    assert requests[1][0][: len(requests[0][0])] == requests[0][0]
    assert requests[0][0][-1]["_model_context"]["payload"] == "plan version 1"
    assert requests[1][0][-1]["_model_context"]["payload"] == "plan version 2"
    assistant = next(m for m in requests[1][0] if m["role"] == "assistant")
    assert assistant["content"] == [{"type": "text", "text": "raw answer"}]
    assert assistant["reasoning_content"] == "reasoning"
    retry = await run_turn(engine(), "two", "2", "NEW-TIME")
    assert len(requests) == 2
    assert retry == [{"type": "text_delta", "content": "visible answer"}, {"type": "done"}]


async def test_session_reset_uses_empty_history_and_restart_retains_identity(tmp_path):
    from openkitsune.sessions.manager import SessionManager
    from openkitsune.sessions.session import Session

    session = Session(id="s1", channel="desktop", chat_id="c1", user_id="u1")
    store = await SessionManager.open_model_transcript(
        data_dir=tmp_path, conversation_id="c1", session=session
    )
    await store.admit([user()], {"working_facts": "A"}, "T1", "1")
    store.close()
    restored = Session.from_dict(session.to_dict())
    store = await SessionManager.open_model_transcript(
        data_dir=tmp_path, conversation_id="c1", session=restored
    )
    assert store.messages[0]["content"] == "hello"
    store.close()
    restored.context.clear_messages()
    store = await SessionManager.open_model_transcript(
        data_dir=tmp_path, conversation_id="c1", session=restored
    )
    assert store.messages == []
    store.close()


async def test_multimodal_and_provider_metadata_are_not_rewritten(tmp_path):
    store = await opened(tmp_path)
    incoming = [
        user(
            [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "AAA="},
                }
            ]
        )
    ]
    original = deepcopy(incoming)
    messages = await store.admit(incoming, {}, "", "1")
    messages.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "read",
                    "input": {},
                    "provider_extra": {"signature": "opaque"},
                }
            ],
        }
    )
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": [{"type": "image", "source": {"type": "base64", "data": "BBBB"}}],
                }
            ],
        }
    )
    await store.sync(messages)
    store.close()
    store = await opened(tmp_path)
    assert store.messages == messages
    assert incoming == original
    store.close()


async def test_external_writer_lock_rejects_without_leaking_local_lock(tmp_path):
    import hashlib

    from filelock import FileLock, Timeout

    lock_dir = tmp_path / "model-transcript-locks"
    lock_dir.mkdir()
    external = FileLock(lock_dir / (hashlib.sha256(b"test").hexdigest() + ".lock"))
    external.acquire()
    try:
        with pytest.raises(Timeout):
            await opened(tmp_path)
    finally:
        external.release()
    store = await opened(tmp_path)
    store.close()


async def test_stream_close_flushes_then_releases_writer_and_context(tmp_path, monkeypatch):
    from openkitsune.config import settings
    from openkitsune.core._reasoning_runtime import ReasoningEngine
    from openkitsune.sessions.model_transcript import active_transcript, commit_model_messages

    monkeypatch.setattr(settings, "project_root", tmp_path)
    engine = ReasoningEngine.__new__(ReasoningEngine)
    closed = []

    async def drive(messages, **_):
        await commit_model_messages(messages)
        try:
            await active_transcript.get().record_frame("text", "partial")
            yield {"type": "text_delta", "content": "partial"}
        finally:
            closed.append(True)

    engine._reason_stream_with_state = drive
    iterator = engine.reason_stream([user()], conversation_id="c1", turn_id="1")
    assert (await anext(iterator))["content"] == "partial"
    await iterator.aclose()
    assert closed == [True]
    assert active_transcript.get() is None
    store = ModelTranscript(
        settings.data_dir / "model-transcripts.sqlite3", new_stream_id("c1", "default", "", False)
    )
    await store.open()
    assert store.partial["text"] == "partial"
    store.close()


async def test_tool_argument_json_keeps_key_order_across_restart(tmp_path):
    store = await opened(tmp_path)
    messages = await store.admit([user()], {}, "", "1")
    messages.extend(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "c", "name": "read", "input": {"z": 1, "a": 2}}
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "c", "content": "ok"}],
            },
        ]
    )
    await store.sync(messages)
    first = convert_messages_to_openai(typed(messages), "system")
    store.close()
    store = await opened(tmp_path)
    assert convert_messages_to_openai(typed(store.messages), "system") == first
    store.close()


async def test_pending_question_is_answered_instead_of_cancelled(tmp_path):
    store = await opened(tmp_path)
    messages = await store.admit([user("start")], {}, "", "1")
    messages.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "q1",
                    "name": "ask_user",
                    "input": {"question": "Which directory?"},
                }
            ],
        }
    )
    await store.sync(messages)
    await store.complete_turn(
        [{"type": "ask_user", "question": "Which directory?"}], exit_reason="ask_user"
    )
    assert await store.admit([user("start")], {}, "", "1") == messages
    answer = await store.admit([user("D:/work")], {}, "", "2")
    result = answer[-2]["content"][0]
    assert result["tool_use_id"] == "q1"
    assert result["content"] == "D:/work"
    assert result["is_error"] is False
    store.close()
