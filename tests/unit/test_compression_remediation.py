import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.agent.context import ContextManager
from openkitsune.core._context_runtime import _CancelledError
from openkitsune.core.compression_contract import (
    CompressionAttempt,
    CompressionError,
    compression_attempt,
    validated_summary,
)
from openkitsune.core.microcompact import microcompact
from openkitsune.llm.request_budget import validate_request_body
from openkitsune.sessions.model_transcript import ModelTranscript, active_transcript


def manager():
    return ContextManager(SimpleNamespace(model="test", messages_create_async=AsyncMock()))


def response(text, stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop)


@pytest.mark.parametrize(
    "text,stop",
    [
        ("", "end_turn"),
        ("<analysis>draft</analysis>", "end_turn"),
        ("<summary>unfinished", "end_turn"),
        ("<summary></summary>", "end_turn"),
        ("<summary>ok</summary>", "max_tokens"),
        ("plain text", "end_turn"),
    ],
)
def test_invalid_summary_is_never_success(text, stop):
    with pytest.raises(CompressionError):
        validated_summary(response(text, stop), structured=True)


async def test_failed_boundary_retains_source_and_overflow_stops(monkeypatch):
    """摘要失败不再 raise（10-07 整改 + P0-1 fallback）：完成压缩且不破坏源。

    旧契约：摘要失败 → raise CompressionError。
    新契约：摘要失败 → 确定性 fallback 摘要继续压缩；预算仍无法容纳时
    事务层降级投影，源消息始终不被破坏。
    """
    cm = manager()
    cm._summarize_messages_chunked_for_boundary = AsyncMock(return_value="")
    messages = [
        {"role": "user", "content": "critical_port=4317 " * 250},
        {"role": "user", "content": "[上下文边界] new task"},
    ]
    original = deepcopy(messages)
    assert await cm.compress_if_needed(messages, force=True, max_tokens=10000) == original
    # 预算极小：压缩（含 fallback/降级）不抛错，且源消息不被破坏
    result = await cm.compress_if_needed(messages, force=True, max_tokens=600)
    assert messages == original
    assert cm.estimate_messages_tokens(result) <= cm.estimate_messages_tokens(original)


def test_microcompact_preserves_differences_errors_and_read_refs():
    messages = []
    for i, content in enumerate(
        ["A" * 4000 + "OLD", "A" * 4000 + "NEW", "B" * 9000 + " read_file(original.txt)"]
    ):
        messages += [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": str(i), "name": "read", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": str(i), "content": content}],
            },
        ]
    messages += [{"role": "assistant", "content": "recent"}] * 3
    original = deepcopy(messages)
    microcompact(messages)
    microcompact(messages)
    assert messages == original


async def test_cancel_propagates_from_summary_children():
    cm = manager()
    cm._cancellable_llm = AsyncMock(side_effect=_CancelledError("cancelled"))
    with pytest.raises(_CancelledError):
        await cm._summarize_messages_chunked([{"role": "user", "content": "data"}], 200)


async def test_failure_backoff_is_scoped_and_cancel_not_counted():
    cm = manager()
    cm._brain.messages_create_async.side_effect = OSError("offline")
    for conversation in ("a", "b"):
        token = compression_attempt.set(CompressionAttempt(conversation, "source"))
        try:
            for _ in range(3):
                with pytest.raises(CompressionError):
                    await cm._cancellable_llm(messages=[], max_tokens=100)
        finally:
            compression_attempt.reset(token)
    assert cm._brain.messages_create_async.await_count == 4
    cm._brain.messages_create_async.side_effect = asyncio.CancelledError()
    token = compression_attempt.set(CompressionAttempt("cancel", "source"))
    try:
        with pytest.raises(asyncio.CancelledError):
            await cm._cancellable_llm(messages=[], max_tokens=100)
    finally:
        compression_attempt.reset(token)
    assert not any(key[0] == "cancel" for key in cm._summary_failures)


async def test_state_rehydration_checked_before_adopting_baseline(tmp_path):
    """压缩失败不再 raise（10-07 整改）：降级返回 best effort，源不被破坏。"""
    store = ModelTranscript(tmp_path / "events.sqlite3", "s")
    await store.open()
    token = active_transcript.set(store)
    try:
        original = await store.admit(
            [{"role": "user", "content": "task"}], {"working_facts": "X" * 12000}, "", "t"
        )
        cm = manager()
        result = await cm.compress_if_needed(original, max_tokens=1000)
        assert store.messages == original
        assert store.pending_compaction == {}
        # 降级/fallback 返回的投影不膨胀
        assert cm.estimate_messages_tokens(result) <= cm.estimate_messages_tokens(original)
    finally:
        active_transcript.reset(token)
        store.close()


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [{"role": "user", "content": "x" * 5000}], "max_tokens": 100},
        {"messages": [], "tools": [{"schema": "x" * 5000}], "max_tokens": 100},
    ],
)
def test_final_provider_budget_includes_output_and_tools(body):
    with pytest.raises(ValueError, match="context window"):
        validate_request_body(
            body, SimpleNamespace(name="small", context_window=1000, max_tokens=100)
        )


def test_oversized_output_reserve_is_clamped_on_small_windows():
    """整改 2026-10-10：chat 请求 max_tokens=2000 打到小窗口端点不再误报。

    输出预留被钳制到 ``window // 4``，校验只拦截真实的输入超限；
    仅 max_tokens 大于窗口不构成溢出。
    """
    validate_request_body(
        {"messages": [], "max_tokens": 2000},
        SimpleNamespace(name="small", context_window=1000, max_tokens=100),
    )


async def test_cold_output_read_is_scoped_and_paged(tmp_path):
    from openkitsune.memory.unified_store import UnifiedStore
    from openkitsune.tools.handlers.filesystem import FilesystemHandler

    store = UnifiedStore(db_path=tmp_path / "memory.db")
    blob = store.save_tool_output_blob("owner", "read", "a" * 20000 + "END")
    memory = SimpleNamespace(
        get_cold_tool_output=lambda value: store.get_tool_output_blob(value, session_id="owner")
    )
    handler = FilesystemHandler(SimpleNamespace(memory_manager=memory))
    uri = f"memory://tool-output/{blob}"
    first = await handler._read_file({"path": uri, "limit": 100})
    assert "PAGE_HAS_MORE" in first and "offset=101" in first
    last = await handler._read_file({"path": uri, "offset": 20001, "limit": 100})
    assert last.endswith("END")
    memory.get_cold_tool_output = lambda value: store.get_tool_output_blob(
        value, session_id="other"
    )
    assert "unavailable in this session" in await handler._read_file({"path": uri})
    store.close()


async def test_summary_route_and_small_window_chunking(monkeypatch):
    cm = manager()
    cm.get_max_context_tokens = lambda **_: 2600
    cm._brain.messages_create_async.return_value = response("<summary>valid latest state</summary>")
    token = compression_attempt.set(CompressionAttempt("selected-conversation", "source"))
    try:
        summary = await cm._summarize_messages_chunked(
            [{"role": "user", "content": "long text " * 1800}], 200
        )
    finally:
        compression_attempt.reset(token)
    assert "valid latest state" in summary
    assert cm._brain.messages_create_async.await_count > 1
    for call in cm._brain.messages_create_async.call_args_list:
        assert call.kwargs["conversation_id"] == "selected-conversation"
        assert (
            cm.estimate_tokens(call.kwargs["system"])
            + cm.estimate_messages_tokens(call.kwargs["messages"])
            + call.kwargs["max_tokens"]
            < 2600
        )


@pytest.mark.parametrize("reactive", [False, True])
async def test_adopted_projection_replays_after_restart(tmp_path, reactive):
    cm = manager()
    cm.get_max_context_tokens = lambda **_: 4000
    cm._summarize_messages_chunked_for_boundary = AsyncMock(return_value="critical_port=4317")
    path = tmp_path / "events.db"
    store = ModelTranscript(path, "s")
    await store.open()
    token = active_transcript.set(store)
    try:
        source = await store.admit(
            [
                {"role": "user", "content": "critical_port=4317 " * 1100},
                {"role": "user", "content": "[上下文边界] continue"},
            ],
            {},
            "",
            "turn",
        )
        if reactive:
            candidate = await cm.reactive_compact(source, conversation_id="s")
        else:
            candidate = await cm.compress_if_needed(source, force=True, conversation_id="s")
        assert candidate != source
        assert store.pending_compaction["quality"] == "validated"
        await store.sync(candidate)
        assert store.pending_compaction == {}
    finally:
        active_transcript.reset(token)
        store.close()
    restored = ModelTranscript(path, "s")
    await restored.open()
    try:
        assert restored.messages == candidate
        assert "critical_port=4317" in str(restored.messages)
    finally:
        restored.close()


async def test_prepare_skips_discarded_ui_compression_after_migration(tmp_path, monkeypatch):
    from openkitsune.agent.core import Agent
    from openkitsune.config import settings
    from openkitsune.sessions.manager import SessionManager

    monkeypatch.setattr(settings, "project_root", tmp_path)
    store = await SessionManager.open_model_transcript(
        data_dir=settings.data_dir, conversation_id="s"
    )
    await store.admit([{"role": "user", "content": "saved"}], {}, "", "t")
    store.close()
    agent = Agent.__new__(Agent)
    agent._compress_context = AsyncMock(side_effect=AssertionError("duplicate compression"))
    messages = [{"role": "user", "content": "next"}]
    assert (
        await agent._compress_context_for_prepare(messages, session_id="s", conversation_id="s")
        == messages
    )
    agent._compress_context.assert_not_called()


async def test_cancelled_child_stops_siblings():
    from openkitsune.core.compression_contract import gather_summaries

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def cancel():
        await started.wait()
        raise _CancelledError("stop")

    with pytest.raises(_CancelledError):
        await asyncio.wait_for(gather_summaries([pending(), cancel()]), 1)
    assert stopped.is_set()


def test_orientation_is_separate_and_does_not_rewrite_state():
    messages = [{"role": "user", "_model_source": "runtime_context", "content": "state"}]
    original = deepcopy(messages)
    result = ContextManager.rewrite_after_compression(messages, task_description="goal" * 200)
    assert messages == original and result[0] == original[0]
    assert result[-1]["_model_source"] == "task_orientation"
    assert "goal" * 200 in result[-1]["content"]


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"type": {"type": "string"}}},
        {"type": ["string", "null"]},
    ],
)
def test_final_budget_handles_nested_tool_schema_types(schema, monkeypatch):
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "context_max_window", 0)
    body = {
        "messages": [],
        "tools": [{"type": "function", "function": {"name": "example", "parameters": schema}}],
        "max_tokens": 100,
    }
    config = SimpleNamespace(name="schema", context_window=4096, max_tokens=100)
    validate_request_body(body, config)

    # Nested schemas still count towards the budget rather than being skipped.
    schema["description"] = "x" * 20000
    with pytest.raises(ValueError, match="context window"):
        validate_request_body(body, config)


def test_final_budget_does_not_count_base64_as_text_tokens():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + "a" * 100000},
                    }
                ],
            }
        ],
        "max_tokens": 100,
    }
    validate_request_body(body, SimpleNamespace(name="vision", context_window=4096, max_tokens=100))


async def test_overflow_failure_cannot_fall_through_to_destructive_truncation():
    from openkitsune.core._reasoning_runtime import ReasoningEngine

    engine = ReasoningEngine.__new__(ReasoningEngine)
    engine._memory_manager = None
    engine._context_manager = SimpleNamespace(
        reactive_compact=AsyncMock(side_effect=CompressionError("no valid summary"))
    )
    engine._strip_heavy_content = lambda _: pytest.fail("destructive fallback executed")
    store = ModelTranscript(None, "s")
    token = active_transcript.set(store)
    state = SimpleNamespace(session_id="s")
    original = [{"role": "user", "content": "critical constraint"}]
    messages = deepcopy(original)
    try:
        assert (
            await engine._handle_llm_error(
                ValueError("context window exceeded"), object(), state, messages, "model"
            )
            is None
        )
        assert messages == original
    finally:
        active_transcript.reset(token)


@pytest.mark.parametrize("provider_name", ["anthropic", "openai", "openai_responses"])
def test_real_provider_build_rejects_oversized_final_request(provider_name):
    from openkitsune.llm.providers.anthropic import AnthropicProvider
    from openkitsune.llm.providers.openai import OpenAIProvider
    from openkitsune.llm.providers.openai_responses import OpenAIResponsesProvider
    from openkitsune.llm.types import EndpointConfig, LLMRequest, Message

    provider_cls = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "openai_responses": OpenAIResponsesProvider,
    }[provider_name]
    provider = provider_cls(
        EndpointConfig(
            name="test",
            provider="test",
            model="test",
            api_key="unused",
            context_window=4096,
            api_type="anthropic" if provider_name == "anthropic" else "openai",
            base_url="https://example.invalid",
        )
    )
    request = LLMRequest(messages=[Message(role="user", content="x" * 20000)], max_tokens=100)
    with pytest.raises(ValueError, match="context window"):
        provider._build_request_body(request)
