"""Node model preferences reach the client without changing shared routing state."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.agent.brain import Brain
from openkitsune.llm.client import LLMClient
from openkitsune.llm.types import (
    AllEndpointsFailedError,
    EndpointConfig,
    LLMResponse,
    StopReason,
    TextBlock,
    Usage,
)
from openkitsune.orgs._default_agent_builder import DefaultAgentBuilder
from openkitsune.orgs._runtime_agent_pipeline import AgentCache, AgentSpec, ProfileResolver
from openkitsune.orgs._runtime_node_tools import run_with_tools
from openkitsune.orgs.org_models import OrgNode


@pytest.fixture
def routing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "openkitsune.llm.client.get_default_config_path", lambda: tmp_path / "absent.json"
    )
    client = LLMClient(endpoints=[])
    for name in ("default", "a", "b"):
        config = EndpointConfig(
            name=name,
            provider="openai",
            api_type="openai",
            base_url="https://example.invalid/v1",
            model=name,
            capabilities=["text", "tools"],
        )
        client._providers[name] = SimpleNamespace(
            name=name,
            model=name,
            config=config,
            is_healthy=True,
            cooldown_remaining=0,
            error_category="transient",
        )
    calls = []

    async def try_endpoints(providers, request, **kwargs):
        calls.append([p.name for p in providers])
        # Yield while other nodes use the same Brain/client.
        await asyncio.sleep(0)
        return LLMResponse(
            id="msg",
            content=[TextBlock(text=providers[0].name)],
            usage=Usage(),
            model=providers[0].name,
            stop_reason=StopReason.END_TURN,
        )

    monkeypatch.setattr(client, "_try_endpoints", try_endpoints)
    brain = Brain.__new__(Brain)
    brain._llm_client = client
    brain.max_tokens = 1024
    monkeypatch.setattr(brain, "is_thinking_enabled", lambda: False)
    monkeypatch.setattr(brain, "_dump_llm_request", lambda *a, **k: "probe")
    monkeypatch.setattr(brain, "_dump_llm_response", lambda *a, **k: None)
    monkeypatch.setattr(brain, "_record_usage", lambda *a: None)
    monkeypatch.setattr(brain, "set_trace_context", lambda *a: None)
    return brain, client, calls


def resolve(*nodes):
    # Exercise the same serialization roundtrip as saved org node configuration.
    org = SimpleNamespace(nodes=[OrgNode.from_dict(n.to_dict()) for n in nodes], edges=[])
    resolver = ProfileResolver(lookup=SimpleNamespace(get_org=lambda _: org))
    return [resolver.resolve(org_id="org", node_id=n.id) for n in nodes]


@pytest.mark.asyncio
async def test_members_use_independent_endpoints_with_shared_brain(routing):
    brain, client, calls = routing
    specs = resolve(
        OrgNode(id="writer", preferred_endpoint="a", endpoint_policy="require"),
        OrgNode(id="reviewer", preferred_endpoint="b", endpoint_policy="require"),
        OrgNode(id="automatic"),
    )
    builder = DefaultAgentBuilder(brain_provider=lambda: brain)
    results = await asyncio.gather(*(builder.build(spec).run("hello") for spec in specs))
    assert results == ["a", "b", "default"]
    assert calls[:2] == [["a"], ["b"]]
    assert client._endpoint_override is None
    assert client._conversation_overrides == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("policy,expected", [("prefer", "default"), ("require", "a")])
async def test_unhealthy_endpoint_policy_reaches_provider_selection(routing, policy, expected):
    brain, client, calls = routing
    client._providers["a"].is_healthy = False
    client._providers["a"].cooldown_remaining = 30
    (spec,) = resolve(OrgNode(id="writer", preferred_endpoint="a", endpoint_policy=policy))
    agent = DefaultAgentBuilder(brain_provider=lambda: brain).build(spec)
    assert await agent.run("hello") == expected
    if policy == "require":
        assert calls == [["a"]]  # No backup provider can be called.
    else:
        assert "a" not in calls[0]


@pytest.mark.asyncio
async def test_missing_required_endpoint_fails_without_calling_backup(routing):
    brain, _, calls = routing
    (spec,) = resolve(OrgNode(id="writer", preferred_endpoint="missing", endpoint_policy="require"))
    agent = DefaultAgentBuilder(brain_provider=lambda: brain).build(spec)
    with pytest.raises(AllEndpointsFailedError, match="missing"):
        await agent.run("hello")
    assert calls == []


@pytest.mark.asyncio
async def test_cached_member_uses_edited_endpoint_policy_and_clear(routing):
    brain, _, calls = routing
    cache = AgentCache(builder=DefaultAgentBuilder(brain_provider=lambda: brain))
    spec = AgentSpec(org_id="org", node_id="writer", role="writer", preferred_endpoint="a")
    first = cache.get_or_create(spec)
    assert cache.get_or_create(spec) is first
    for edited, expected in (
        (replace(spec, endpoint_policy="require"), "a"),
        (replace(spec, preferred_endpoint="b", endpoint_policy="require"), "b"),
        (replace(spec, preferred_endpoint=None), "default"),
    ):
        agent = cache.get_or_create(edited)
        assert agent is not first
        assert await agent.run("hello") == expected
    assert calls[:2] == [["a"], ["b"]]


@pytest.mark.asyncio
async def test_streaming_and_nonstream_fallback_keep_node_endpoint(routing, monkeypatch):
    brain, client, calls = routing
    captured = []

    async def stream(**kwargs):
        captured.append(kwargs)
        yield {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "streamed"},
        }

    monkeypatch.setattr(client, "chat_stream", stream)
    spec = AgentSpec(
        org_id="org",
        node_id="writer",
        role="writer",
        preferred_endpoint="b",
        endpoint_policy="require",
    )
    agent = DefaultAgentBuilder(brain_provider=lambda: brain, event_emitter=lambda *a: None).build(
        spec
    )
    args = {
        "tool_defs": [],
        "system_prompt": "write",
        "text": "hello",
        "command_id_for_events": "cmd",
        "tool_host": None,
        "cancel_event": None,
    }
    assert await agent._produce_text(**args) == "streamed"
    assert captured[0]["endpoint_name"] == "b"
    assert captured[0]["endpoint_policy"] == "require"
    assert not calls

    async def broken_stream(**kwargs):
        raise RuntimeError("stream unavailable")
        yield  # noqa: B018

    monkeypatch.setattr(client, "chat_stream", broken_stream)
    assert await agent._produce_text(**args) == "b"
    assert calls == [["b"]]


@pytest.mark.asyncio
async def test_parent_review_uses_parent_endpoint(routing):
    brain, client, calls = routing
    spec = AgentSpec(
        org_id="org",
        node_id="reviewer",
        role="reviewer",
        preferred_endpoint="b",
        endpoint_policy="require",
    )
    agent = DefaultAgentBuilder(brain_provider=lambda: brain).build(spec)
    await agent.review_child_output(child_node_id="writer", task="write", output="written")
    assert calls == [["b"]]
    assert client._endpoint_override is None


@pytest.mark.asyncio
async def test_all_tool_rounds_keep_endpoint(monkeypatch):
    response = SimpleNamespace(
        content=[{"type": "tool_use", "id": "call", "name": "test", "input": {}}],
        stop_reason="tool_use",
    )
    final = SimpleNamespace(content=[SimpleNamespace(text="done")])
    brain = SimpleNamespace(messages_create_async=AsyncMock(side_effect=[response, final]))
    monkeypatch.setattr(
        "openkitsune.orgs._runtime_node_tools.execute_node_tool", AsyncMock(return_value="ok")
    )
    result, rounds = await run_with_tools(
        brain=brain,
        system_prompt="test",
        user_content="hello",
        tools=[{"name": "test", "input_schema": {"type": "object", "properties": {}}}],
        org_id="org",
        node_id="writer",
        command_id="cmd",
        endpoint_name="a",
        endpoint_policy="require",
    )
    assert result is final
    assert rounds >= 1
    assert brain.messages_create_async.await_count == 2
    for call in brain.messages_create_async.await_args_list:
        assert call.kwargs["endpoint_name"] == "a"
        assert call.kwargs["endpoint_policy"] == "require"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_endpoint_restores_default_policy(value):
    (spec,) = resolve(OrgNode(id="writer", preferred_endpoint=value, endpoint_policy="require"))
    assert spec.preferred_endpoint is None
    assert spec.endpoint_policy == "prefer"
