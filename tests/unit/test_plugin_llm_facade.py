from __future__ import annotations

import pytest

from openkitsune.llm.types import LLMResponse, StopReason, TextBlock, ToolUseBlock, Usage
from openkitsune.plugins.llm_facade import PluginLLMFacade


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(
            id="msg-1",
            content=[
                TextBlock(text="done"),
                ToolUseBlock(id="tool-1", name="lookup", input={"q": "akita"}),
            ],
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=12, output_tokens=5),
            model="model-b",
            endpoint_name="endpoint-b",
        )


class FakeBrain:
    def __init__(self) -> None:
        self.llm_client = FakeClient()
        self.switch_calls: list[dict] = []

    def list_available_models(self):
        return [
            {
                "name": "endpoint-a",
                "model": "model-a",
                "provider": "provider-a",
                "priority": 1,
                "is_healthy": True,
                "is_current": True,
                "local": True,
                "capabilities": ["text"],
                "note": "primary",
                "api_key": "must-not-leak",
                "base_url": "https://secret.invalid/v1",
            },
            {
                "name": "endpoint-b",
                "model": "model-b",
                "provider": "provider-b",
                "priority": 2,
                "is_healthy": True,
                "is_current": False,
                "capabilities": ["text", "tools"],
            },
        ]

    def switch_model(self, **kwargs):
        self.switch_calls.append(kwargs)
        raise AssertionError("PluginLLMFacade must not mutate model overrides")


def _facade() -> tuple[PluginLLMFacade, FakeBrain]:
    brain = FakeBrain()
    return PluginLLMFacade("test-plugin", lambda: brain), brain


def test_list_models_is_sanitized_and_filters_capabilities():
    facade, _brain = _facade()

    models = facade.list_models(capabilities=["tools"])

    assert len(models) == 1
    assert models[0].endpoint == "endpoint-b"
    assert models[0].capabilities == ("text", "tools")
    assert models[0].local is False
    assert not hasattr(models[0], "api_key")
    assert not hasattr(models[0], "base_url")

    all_models = facade.list_models()
    assert all_models[0].local is True


@pytest.mark.asyncio
async def test_complete_passes_request_scoped_selection_and_normalizes_response():
    facade, brain = _facade()

    result = await facade.complete(
        prompt="hello",
        endpoint="endpoint-b",
        policy="require",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look something up",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    call = brain.llm_client.calls[0]
    assert call["endpoint_name"] == "endpoint-b"
    assert call["endpoint_policy"] == "require"
    assert call["messages"][0].content == "hello"
    assert call["tools"][0].name == "lookup"
    assert result.text == "done"
    assert result.endpoint == "endpoint-b"
    assert result.usage.total_tokens == 17
    assert result.tool_calls[0]["name"] == "lookup"
    assert brain.switch_calls == []


@pytest.mark.asyncio
async def test_endpoint_without_policy_defaults_to_prefer():
    facade, brain = _facade()

    await facade.complete(prompt="hello", endpoint="endpoint-a")

    assert brain.llm_client.calls[0]["endpoint_policy"] == "prefer"


@pytest.mark.asyncio
async def test_no_endpoint_defaults_to_inherit():
    facade, brain = _facade()

    await facade.complete(prompt="hello")

    assert brain.llm_client.calls[0]["endpoint_name"] is None
    assert brain.llm_client.calls[0]["endpoint_policy"] == "inherit"


@pytest.mark.asyncio
async def test_unknown_endpoint_is_rejected_before_call():
    facade, brain = _facade()

    with pytest.raises((ValueError, RuntimeError), match="not configured"):
        await facade.complete(prompt="hello", endpoint="missing")

    assert brain.llm_client.calls == []


@pytest.mark.parametrize(
    ("endpoint", "policy"),
    [
        ("endpoint-a", "inherit"),
        (None, "require"),
        (None, "unknown"),
    ],
)
def test_invalid_selection_combinations_are_rejected(endpoint, policy):
    facade, _brain = _facade()

    with pytest.raises((ValueError, RuntimeError)):
        facade._selection(endpoint, policy)


def test_missing_brain_is_reported_as_unavailable():
    facade = PluginLLMFacade("test-plugin", lambda: None)

    with pytest.raises(RuntimeError, match="not available"):
        facade.list_models()
