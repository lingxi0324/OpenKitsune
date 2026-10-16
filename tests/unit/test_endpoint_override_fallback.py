import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from openkitsune.agent.reasoning import ReasoningEngine
from openkitsune.llm.client import EndpointOverride, LLMClient
from openkitsune.llm.types import (
    AllEndpointsFailedError,
    EndpointConfig,
    LLMResponse,
    Message,
    StopReason,
    TextBlock,
    Usage,
)


class FakeLLMClient:
    def __init__(self, ok: bool):
        self.ok = ok
        self.calls: list[dict] = []
        self._providers = {"good-endpoint": SimpleNamespace(model="good-model")}

    def switch_model(self, **kwargs):
        self.calls.append(kwargs)
        if self.ok:
            return True, "switched"
        return False, "端点 'missing-endpoint' 不存在。可用端点: good-endpoint"


def _engine_with(client: FakeLLMClient) -> ReasoningEngine:
    engine = object.__new__(ReasoningEngine)
    engine._brain = SimpleNamespace(_llm_client=client)
    return engine


def test_endpoint_override_failure_falls_back_to_auto():
    client = FakeLLMClient(ok=False)
    engine = _engine_with(client)

    switched = engine._apply_endpoint_override(
        "missing-endpoint",
        conversation_id="conv-1",
        reason="test stale endpoint",
    )

    assert switched is False
    assert client.calls[0]["endpoint_name"] == "missing-endpoint"
    assert client.calls[0]["conversation_id"] == "conv-1"
    assert client.calls[0]["policy"] == "prefer"


def test_endpoint_override_success_is_preserved():
    client = FakeLLMClient(ok=True)
    engine = _engine_with(client)

    switched = engine._apply_endpoint_override(
        "good-endpoint",
        conversation_id="conv-1",
        reason="test valid endpoint",
    )

    assert switched is True
    assert client.calls[0]["endpoint_name"] == "good-endpoint"


def test_endpoint_override_policy_is_forwarded():
    client = FakeLLMClient(ok=True)
    engine = _engine_with(client)

    switched = engine._apply_endpoint_override(
        "good-endpoint",
        conversation_id="conv-1",
        reason="test required endpoint",
        endpoint_policy="require",
    )

    assert switched is True
    assert client.calls[0]["policy"] == "require"


def _provider(
    name: str,
    *,
    healthy: bool = True,
    capabilities: list[str] | None = None,
) -> SimpleNamespace:
    config = EndpointConfig(
        name=name,
        provider="openai",
        api_type="openai",
        base_url="https://example.invalid/v1",
        model=f"{name}-model",
        capabilities=capabilities or ["text", "tools"],
    )
    return SimpleNamespace(
        name=name,
        config=config,
        model=config.model,
        is_healthy=healthy,
        cooldown_remaining=30 if not healthy else 0,
        error_category="transient",
        reset_cooldown=lambda: None,
    )


class StreamProvider:
    def __init__(
        self,
        name: str,
        *,
        priority: int,
        capabilities: list[str],
        healthy: bool = True,
    ) -> None:
        self.name = name
        self.config = EndpointConfig(
            name=name,
            provider="openai",
            api_type="openai",
            base_url="https://example.invalid/v1",
            model=f"{name}-model",
            priority=priority,
            capabilities=capabilities,
        )
        self.model = self.config.model
        self.is_healthy = healthy
        self.cooldown_remaining = 0 if healthy else 30
        self.error_category = "transient"
        self.calls = 0

    def reset_cooldown(self) -> None:
        self.is_healthy = True
        self.cooldown_remaining = 0

    async def chat_stream(self, request):
        self.calls += 1
        yield {"type": "message_start", "message": {"id": "msg-1"}}
        yield {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}


def _llm_client_with_required_override(
    selected: SimpleNamespace,
    fallback: SimpleNamespace,
    *,
    policy: str = "require",
) -> LLMClient:
    client = object.__new__(LLMClient)
    client._providers = {selected.name: selected, fallback.name: fallback}
    client._endpoint_override = None
    client._conversation_overrides = {
        "conv-1": EndpointOverride(
            endpoint_name=selected.name,
            expires_at=datetime.now() + timedelta(minutes=5),
            policy=policy,
        )
    }
    return client


def test_required_endpoint_does_not_fall_back_when_unhealthy():
    selected = _provider("local", healthy=False)
    fallback = _provider("glm", healthy=True)
    client = _llm_client_with_required_override(selected, fallback)

    eligible = client._filter_eligible_endpoints(
        require_tools=True,
        conversation_id="conv-1",
    )

    assert [provider.name for provider in eligible] == ["local"]


def test_preferred_endpoint_can_fall_back_when_unhealthy():
    selected = _provider("local", healthy=False)
    fallback = _provider("glm", healthy=True)
    client = _llm_client_with_required_override(selected, fallback, policy="prefer")

    eligible = client._filter_eligible_endpoints(
        require_tools=True,
        conversation_id="conv-1",
    )

    assert [provider.name for provider in eligible] == ["glm"]


def test_request_preference_is_scoped_and_takes_priority_over_global_override():
    global_selected = _provider("global", healthy=True)
    plugin_selected = _provider("plugin", healthy=True)
    fallback = _provider("fallback", healthy=True)
    client = _llm_client_with_required_override(global_selected, fallback, policy="prefer")
    client._providers[plugin_selected.name] = plugin_selected
    before_overrides = dict(client._conversation_overrides)

    eligible = client._filter_eligible_endpoints(
        require_tools=True,
        conversation_id="conv-1",
        prefer_endpoint="plugin",
        request_endpoint="plugin",
        request_policy="prefer",
    )

    assert [provider.name for provider in eligible][0] == "plugin"
    assert client._conversation_overrides == before_overrides
    assert client._endpoint_override is None


@pytest.mark.asyncio
async def test_chat_inherits_existing_routing_when_request_has_no_endpoint(monkeypatch):
    selected = _provider("selected", healthy=True)
    fallback = _provider("fallback", healthy=True)
    client = LLMClient(endpoints=[])
    client._providers = {selected.name: selected, fallback.name: fallback}
    client._conversation_overrides = {
        "conv-1": EndpointOverride(
            endpoint_name=selected.name,
            expires_at=datetime.now() + timedelta(minutes=5),
            policy="prefer",
        )
    }
    captured: dict = {}

    async def fake_try_endpoints(providers, request, allow_failover=True, cancel_event=None):
        captured["providers"] = providers
        return LLMResponse(
            id="msg-1",
            content=[TextBlock(text="ok")],
            stop_reason=StopReason.END_TURN,
            usage=Usage(),
            model=providers[0].model,
        )

    monkeypatch.setattr(client, "_try_endpoints", fake_try_endpoints)

    response = await client.chat(
        [Message(role="user", content="hello")],
        conversation_id="conv-1",
        endpoint_policy="inherit",
    )

    assert response.text == "ok"
    assert [provider.name for provider in captured["providers"]][0] == "selected"


def test_request_required_endpoint_is_used_without_mutating_overrides_or_health():
    selected = _provider("plugin", healthy=False)
    fallback = _provider("fallback", healthy=True)
    client = _llm_client_with_required_override(selected, fallback, policy="prefer")
    before_overrides = dict(client._conversation_overrides)

    eligible = client._filter_eligible_endpoints(
        require_tools=True,
        request_endpoint="plugin",
        request_policy="require",
    )

    assert [provider.name for provider in eligible] == ["plugin"]
    assert selected.is_healthy is False
    assert client._conversation_overrides == before_overrides


@pytest.mark.asyncio
async def test_request_required_endpoint_blocks_capability_fallback():
    selected = _provider("plugin", healthy=True, capabilities=["text"])
    fallback = _provider("fallback", healthy=True, capabilities=["text", "tools"])
    client = _llm_client_with_required_override(selected, fallback, policy="prefer")
    request = SimpleNamespace(enable_thinking=False)

    with pytest.raises(AllEndpointsFailedError, match="Required endpoint 'plugin'"):
        await client._resolve_providers_with_fallback(
            request=request,
            require_tools=True,
            request_endpoint="plugin",
            request_policy="require",
        )


@pytest.mark.asyncio
async def test_prefer_endpoint_switch_emits_stream_notice_metadata():
    LLMClient._auth_failed_endpoints.clear()
    LLMClient._auth_logged_endpoints.clear()
    selected = StreamProvider(
        "opencode-free",
        priority=2,
        capabilities=["text", "tools"],
    )
    actual = StreamProvider(
        "lmstudio-thinking",
        priority=1,
        capabilities=["text", "tools", "thinking"],
    )

    client = object.__new__(LLMClient)
    client._providers = {selected.name: selected, actual.name: actual}
    client._settings = {}
    client._endpoint_override = None
    client._conversation_overrides = {
        "conv-1": EndpointOverride(
            endpoint_name=selected.name,
            expires_at=datetime.now() + timedelta(minutes=5),
            policy="prefer",
        )
    }
    client._last_success_endpoint = None
    client._endpoint_lock = asyncio.Lock()

    events = [
        event
        async for event in client._chat_stream_impl(
            messages=[Message(role="user", content="hi")],
            tools=[],
            enable_thinking=True,
            conversation_id="conv-1",
        )
    ]

    assert events[0] == {
        "type": "endpoint_meta",
        "endpoint_name": "lmstudio-thinking",
        "selected_endpoint": "opencode-free",
        "prefer_switched": True,
        "switch_reason": "capability_mismatch",
        "missing_capabilities": ["thinking"],
    }
    assert actual.calls == 1
    assert selected.calls == 0


@pytest.mark.asyncio
async def test_required_endpoint_missing_hard_capability_blocks_fallback():
    selected = _provider("local", healthy=True, capabilities=["text"])
    fallback = _provider("glm", healthy=True, capabilities=["text", "tools"])
    client = _llm_client_with_required_override(selected, fallback)
    request = SimpleNamespace(enable_thinking=False)

    with pytest.raises(AllEndpointsFailedError) as exc_info:
        await client._resolve_providers_with_fallback(
            request=request,
            require_tools=True,
            conversation_id="conv-1",
        )

    assert "Required endpoint 'local' does not support" in str(exc_info.value)
