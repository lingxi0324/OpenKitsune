from openkitsune_plugin_sdk.llm import (
    LLMModel,
    LLMSelectionPolicy,
    PluginLLMSelectionError,
    PluginLLMUnavailableError,
)
from openkitsune_plugin_sdk.testing import MockPluginAPI, MockPluginLLM


async def test_mock_plugin_llm_records_calls_and_returns_queued_response():
    llm = MockPluginLLM(
        [
            LLMModel(
                endpoint="configured",
                model="model-1",
                local=True,
                healthy=True,
                capabilities=("text", "tools"),
            )
        ]
    )
    llm.queue_response("hello", endpoint="configured", model="model-1")
    api = MockPluginAPI(granted_permissions=["brain.access"], llm=llm)

    result = await api.get_llm().complete(
        prompt="hi",
        endpoint="configured",
        policy=LLMSelectionPolicy.REQUIRE,
    )

    assert result.text == "hello"
    assert llm.calls[0]["endpoint"] == "configured"
    assert llm.list_models(capabilities=["tools"])[0].endpoint == "configured"
    assert llm.list_models()[0].local is True


def test_mock_plugin_api_enforces_brain_access_for_llm():
    api = MockPluginAPI(granted_permissions=[], llm=MockPluginLLM())

    assert api.get_llm() is None


def test_plugin_llm_errors_expose_stable_codes():
    assert PluginLLMUnavailableError("offline").code == "plugin_llm_unavailable"
    assert PluginLLMSelectionError("missing").code == "plugin_llm_endpoint_unavailable"
