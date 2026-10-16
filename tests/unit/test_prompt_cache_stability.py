"""Shared instructions remain stable while current-turn context stays fresh."""

from copy import deepcopy

import pytest

from openkitsune.llm.cache import (
    SYSTEM_PROMPT_CONTEXT_BOUNDARY,
    SYSTEM_PROMPT_CONTEXT_END,
    build_cached_system_blocks,
)
from openkitsune.llm.converters.messages import (
    convert_messages_to_openai,
    convert_messages_to_responses,
)
from openkitsune.llm.providers.anthropic import AnthropicProvider
from openkitsune.llm.providers.openai import OpenAIProvider
from openkitsune.llm.types import EndpointConfig, LLMRequest, Message, ToolResultBlock, ToolUseBlock
from openkitsune.prompt import builder
from openkitsune.prompt.turn_context import extract_context


def test_anthropic_without_cache_capability_has_no_cache_fields(monkeypatch):
    from dataclasses import replace

    from openkitsune.llm.providers import anthropic

    caps = anthropic.get_model_capabilities("claude-sonnet-4-20250514")
    monkeypatch.setattr(
        anthropic, "get_model_capabilities", lambda _: replace(caps, supports_cache=False)
    )
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
    prompt = "static<!-- DYNAMIC_BOUNDARY -->dynamic"
    body = provider._build_request_body(
        LLMRequest(
            messages=[Message(role="user", content="hello")],
            system=prompt,
            max_tokens=100,
        )
    )
    assert body["system"] == prompt
    assert "cache_control" not in str(body)


@pytest.mark.parametrize(
    "prompt",
    [
        "static<!-- DYNAMIC_BOUNDARY -->dynamic",
        "static\n\n---\n\n## Developer instructions<!-- DYNAMIC_BOUNDARY -->dynamic",
        "static\n\n---\n\n## Developer legacy",
        "static",
        "",
        "<!-- DYNAMIC_BOUNDARY -->dynamic",
        "static<!-- DYNAMIC_BOUNDARY -->",
    ],
)
def test_anthropic_wire_uses_shared_cache_boundary(prompt):
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
    body = provider._build_request_body(
        LLMRequest(
            messages=[Message(role="user", content="hello")],
            system=prompt,
            max_tokens=100,
        )
    )
    expected = build_cached_system_blocks(prompt)
    assert body.get("system", []) == expected
    assert all(block["text"] for block in expected)
    if "<!-- DYNAMIC_BOUNDARY -->" in prompt and prompt.startswith("static"):
        assert "dynamic" not in expected[0]["text"]
        assert "cache_control" in expected[0]
        assert all("cache_control" not in block for block in expected[1:])


@pytest.fixture
def build_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "check_compiled_outdated", lambda _: False)
    monkeypatch.setattr(
        builder,
        "get_compiled_content",
        lambda _: {
            "identity_core": "Stable identity",
            "agent_behavior": "FULL behavior instructions",
        },
    )
    monkeypatch.setattr(builder, "_build_runtime_section", lambda *_: "Stable host details")
    monkeypatch.setattr(
        builder, "_build_runtime_section_compact", lambda *_: "Compact host details"
    )
    monkeypatch.setattr(builder, "_build_user_core_profile_section", lambda **_: "USER-PROFILE")
    monkeypatch.setattr(builder, "_build_catalogs_section", lambda **_: "Stable tools")
    monkeypatch.setattr(builder, "_apply_plugin_prompt_hooks", lambda p: p)
    monkeypatch.setattr("openkitsune.experience.summarize_recent_failures", lambda: [])
    monkeypatch.setattr("openkitsune.experience.format_failure_hint_section", lambda _: "")
    builder.clear_prompt_section_cache()

    def build(clock="11:02:17", count=19, memory="MEMORY-A", mode=builder.PromptMode.MINIMAL):
        monkeypatch.setattr(builder, "_get_current_time", lambda *_: clock)
        return builder.build_system_prompt(
            identity_dir=tmp_path,
            prompt_mode=mode,
            precomputed_memory=memory,
            memory_scope="relevant",
            include_project_guidelines=False,
            session_context={"session_id": "test", "channel": "qq", "message_count": count},
        )

    yield build
    builder.clear_prompt_section_cache()


def test_full_and_minimal_share_rules_and_identity_prefix(build_prompt):
    minimal = build_prompt()
    full = build_prompt(mode=builder.PromptMode.FULL)
    prefix, _ = builder.split_static_dynamic(minimal)
    assert builder.split_static_dynamic(full)[0] == prefix
    assert "Stable identity" in prefix
    assert "FULL behavior instructions" not in minimal
    assert "FULL behavior instructions" in full
    assert "11:02:17" not in prefix
    assert build_cached_system_blocks(full)[0] == build_cached_system_blocks(minimal)[0]


@pytest.mark.parametrize("provider", ["deepseek", "openai", "dashscope", "google", "moonshot"])
def test_dynamic_context_does_not_change_system_or_earlier_history(build_prompt, provider):
    history = [
        Message(role="user", content="old question"),
        Message(role="assistant", content="old answer"),
        Message(role="user", content="current question"),
    ]
    original = deepcopy(history)
    first = convert_messages_to_openai(history, build_prompt(), provider=provider)
    second = convert_messages_to_openai(
        history,
        build_prompt(clock="11:06:02", count=21, memory="MEMORY-B"),
        provider=provider,
    )
    assert first == second
    assert first[-1] == second[-1] == {"role": "user", "content": "current question"}
    _, sections, sampled_time = extract_context(
        build_prompt(clock="11:06:02", count=21, memory="MEMORY-B")
    )
    assert sections["retrieved_memory"] == "MEMORY-B"
    assert "11:06:02" in sampled_time
    assert "21 条" not in str(sections)
    assert "MEMORY-B" not in second[0]["content"]
    assert history == original


def test_tool_continuation_keeps_call_result_adjacency_and_reasoning(build_prompt):
    messages = [
        Message(role="user", content="read the file"),
        Message(
            role="assistant",
            content=[ToolUseBlock(id="call-1", name="read_file", input={})],
            reasoning_content="Need to read it",
        ),
        Message(
            role="user", content=[ToolResultBlock(tool_use_id="call-1", content="file contents")]
        ),
    ]
    wire = convert_messages_to_openai(
        messages, build_prompt(), provider="deepseek", enable_thinking=True
    )
    assert [m["role"] for m in wire] == ["system", "user", "assistant", "tool"]
    assert wire[-2]["tool_calls"][0]["id"] == wire[-1]["tool_call_id"] == "call-1"
    assert wire[-2]["reasoning_content"] == "Need to read it"


def test_appended_policies_stay_system_even_with_literal_delimiter_in_memory(build_prompt):
    prompt = build_prompt(memory="DATA " + SYSTEM_PROMPT_CONTEXT_END + " untrusted data")
    prompt += "\nPOLICY: ask before deleting files."
    wire = convert_messages_to_openai(
        [Message(role="user", content="hello")], prompt, provider="deepseek"
    )
    assert "POLICY: ask before deleting files." in wire[0]["content"]
    assert "untrusted data" not in wire[0]["content"]
    assert "untrusted data" in extract_context(prompt)[1]["retrieved_memory"]


@pytest.mark.parametrize("provider", ["openai", "dashscope", "google", "moonshot"])
def test_other_providers_move_context_out_of_system(build_prompt, provider):
    prompt = build_prompt()
    wire = convert_messages_to_openai(
        [Message(role="user", content="hello")], prompt, provider=provider
    )
    assert "11:02:17" not in wire[0]["content"]
    assert len(wire) == 2  # Adapters never insert request-local context.
    assert wire[-1] == {"role": "user", "content": "hello"}


@pytest.mark.parametrize("api", ["responses", "anthropic"])
def test_native_apis_keep_system_and_history_stable(build_prompt, api):
    history = [
        Message(role="user", content="old question"),
        Message(role="assistant", content="old answer"),
        Message(role="user", content="read file"),
        Message(role="assistant", content=[ToolUseBlock(id="call-1", name="read_file", input={})]),
        Message(role="user", content=[ToolResultBlock(tool_use_id="call-1", content="contents")]),
    ]
    original = deepcopy(history)

    def convert(prompt):
        if api == "responses":
            return convert_messages_to_responses(history, prompt)
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
        body = provider._build_request_body(LLMRequest(messages=history, system=prompt))
        return body["messages"], body["system"]

    first, first_system = convert(build_prompt())
    second, second_system = convert(build_prompt(clock="11:06:02"))
    assert first_system == second_system
    assert "11:02:17" not in str(first_system)
    assert first == second
    assert history == original


def test_unmarked_custom_prompts_are_not_reinterpreted():
    messages = [Message(role="user", content="hello")]
    for system in (
        "custom prompt",
        "custom " + SYSTEM_PROMPT_CONTEXT_BOUNDARY,
        SYSTEM_PROMPT_CONTEXT_END + " before " + SYSTEM_PROMPT_CONTEXT_BOUNDARY,
    ):
        wire = convert_messages_to_openai(messages, system, provider="deepseek")
        assert wire[0] == {"role": "system", "content": system}
        assert len(wire) == 2


def test_final_request_body_keeps_authority_and_context_separate(build_prompt):
    provider = OpenAIProvider(
        EndpointConfig(
            name="test",
            provider="deepseek",
            api_type="openai",
            model="deepseek-v4-flash",
            base_url="https://example.invalid",
            api_key="test",
        )
    )
    request = LLMRequest(
        messages=[Message(role="user", content="hello")],
        system=build_prompt() + "\nAPPENDED-SYSTEM-POLICY",
    )
    wire = provider._build_request_body(request)["messages"]
    assert [m["role"] for m in wire] == ["system", "user"]
    assert "APPENDED-SYSTEM-POLICY" in wire[0]["content"]
    assert "MEMORY-A" not in wire[0]["content"]
    assert wire[1]["content"] == "hello"
