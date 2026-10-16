from __future__ import annotations

from dataclasses import dataclass

import pytest

from openkitsune.plugins.llm_support import (
    complete_text,
    llm_catalog_payload,
    llm_selection_kwargs,
    validate_llm_endpoint,
)


@dataclass
class FakeModel:
    endpoint: str
    model: str
    provider: str = "test"
    priority: int = 1
    local: bool = False
    healthy: bool = True
    current: bool = True
    capabilities: tuple[str, ...] = ("text",)
    note: str = ""


class FakeLLM:
    def __init__(self) -> None:
        self.models = [FakeModel(endpoint="primary", model="model-1", local=True)]
        self.calls: list[dict] = []

    def list_models(self, *, capabilities=()):
        return list(self.models)

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Completion",
            (),
            {"text": "done", "endpoint": "primary", "model": "model-1", "usage": None},
        )()


class FakeAPI:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def get_llm(self):
        return self.llm


def test_selection_kwargs_maps_auto_and_explicit_endpoint():
    assert llm_selection_kwargs("") == {"policy": "inherit"}
    assert llm_selection_kwargs(" primary ") == {
        "endpoint": "primary",
        "policy": "require",
    }


def test_catalog_payload_is_sanitized():
    payload = llm_catalog_payload(FakeAPI(FakeLLM()), selected_endpoint="primary")

    assert payload["available"] is True
    assert payload["selected_endpoint"] == "primary"
    assert payload["models"] == [
        {
            "endpoint": "primary",
            "model": "model-1",
            "provider": "test",
            "priority": 1,
            "local": True,
            "healthy": True,
            "current": True,
            "capabilities": ["text"],
            "note": "",
        }
    ]


def test_catalog_payload_reports_unavailable_facade():
    assert llm_catalog_payload(FakeAPI(), selected_endpoint="") == {
        "available": False,
        "reason": "plugin_llm_unavailable",
        "selected_endpoint": "",
        "models": [],
    }


def test_validate_endpoint_rejects_stale_value():
    with pytest.raises(ValueError, match="plugin_llm_endpoint_unavailable"):
        validate_llm_endpoint(FakeAPI(FakeLLM()), "removed")


@pytest.mark.asyncio
async def test_complete_text_forwards_strict_selection():
    llm = FakeLLM()
    result = await complete_text(
        FakeAPI(llm),
        endpoint="primary",
        prompt="hello",
        system="system",
        max_tokens=123,
    )

    assert result.text == "done"
    assert llm.calls == [
        {
            "prompt": "hello",
            "system": "system",
            "max_tokens": 123,
            "endpoint": "primary",
            "policy": "require",
        }
    ]
