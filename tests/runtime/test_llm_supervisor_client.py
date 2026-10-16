"""Tests for the gateway-backed supervisor LLM endpoint lock."""

from __future__ import annotations

import pytest

from openkitsune.llm.types import ConfigurationError
from openkitsune.runtime.llm_supervisor_client import GatewaySupervisorLLMClient


class _MissingEndpointGateway:
    def __init__(self) -> None:
        self.switch_calls: list[dict[str, object]] = []
        self.chat_calls = 0

    def switch_model(
        self,
        endpoint_name: str,
        *,
        conversation_id: str | None = None,
        policy: str = "prefer",
        reason: str = "",
    ) -> tuple[bool, str]:
        self.switch_calls.append(
            {
                "endpoint_name": endpoint_name,
                "conversation_id": conversation_id,
                "policy": policy,
                "reason": reason,
            }
        )
        return False, f"endpoint {endpoint_name!r} does not exist"

    async def chat(self, **_kwargs):
        self.chat_calls += 1
        raise AssertionError("default routing must not run")


class _AutoEndpointGateway(_MissingEndpointGateway):
    def __init__(self, endpoint: str | None = "workspace-primary") -> None:
        super().__init__()
        self.endpoint = endpoint
        self.chat_kwargs: dict[str, object] | None = None

    def get_default_endpoint_name(self) -> str | None:
        return self.endpoint

    def switch_model(
        self,
        endpoint_name: str,
        *,
        conversation_id: str | None = None,
        policy: str = "prefer",
        reason: str = "",
    ) -> tuple[bool, str]:
        self.switch_calls.append(
            {
                "endpoint_name": endpoint_name,
                "conversation_id": conversation_id,
                "policy": policy,
                "reason": reason,
            }
        )
        return True, "ok"

    async def chat(self, **kwargs):
        self.chat_calls += 1
        self.chat_kwargs = kwargs

        class _Response:
            text = ""

        return _Response()


def test_supervisor_endpoint_default_is_provider_agnostic_auto_mode() -> None:
    from openkitsune.config import Settings

    assert Settings.model_fields["orgs_supervisor_llm_endpoint"].get_default() == "auto"


async def test_missing_required_supervisor_endpoint_does_not_use_default_model() -> None:
    gateway = _MissingEndpointGateway()
    client = GatewaySupervisorLLMClient(
        gateway,  # type: ignore[arg-type]
        endpoint="supervisor-json-model",
        conversation_id="orgsup-test",
    )

    with pytest.raises(ConfigurationError, match="Supervisor 端点.*不可用"):
        await client.complete(
            role="progress_ledger",
            system="system",
            user="user",
        )

    assert gateway.chat_calls == 0
    assert gateway.switch_calls == [
        {
            "endpoint_name": "supervisor-json-model",
            "conversation_id": "orgsup-test",
            "policy": "require",
            "reason": "organization supervisor (thinking disabled)",
        }
    ]


async def test_auto_supervisor_endpoint_locks_workspace_default() -> None:
    gateway = _AutoEndpointGateway()
    client = GatewaySupervisorLLMClient(
        gateway,  # type: ignore[arg-type]
        endpoint="auto",
        conversation_id="orgsup-auto",
    )

    assert await client.complete(role="facts", system="system", user="user") == ""
    assert await client.complete(role="plan", system="system", user="user") == ""
    assert gateway.switch_calls == [
        {
            "endpoint_name": "workspace-primary",
            "conversation_id": "orgsup-auto",
            "policy": "require",
            "reason": "organization supervisor (thinking disabled)",
        }
    ]
    assert gateway.chat_calls == 2
    assert gateway.chat_kwargs is not None
    assert gateway.chat_kwargs["enable_thinking"] is False


async def test_auto_supervisor_endpoint_requires_an_available_text_endpoint() -> None:
    gateway = _AutoEndpointGateway(endpoint=None)
    client = GatewaySupervisorLLMClient(
        gateway,  # type: ignore[arg-type]
        endpoint=None,
        conversation_id="orgsup-empty",
    )

    with pytest.raises(ConfigurationError, match="没有可用的健康文本端点"):
        await client.complete(role="facts", system="system", user="user")

    assert gateway.switch_calls == []
    assert gateway.chat_calls == 0
