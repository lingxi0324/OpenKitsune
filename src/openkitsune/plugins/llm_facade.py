"""Request-scoped LLM access for Python plugins.

The facade exposes configured endpoint metadata and completions without
exposing credentials or the mutable model-switching surface on ``Brain``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openkitsune.llm.types import Message, Tool

_MAX_COMPLETION_TOKENS = 131_072
_VALID_THINKING_DEPTHS = {"low", "medium", "high", "max"}
_VALID_SELECTION_POLICIES = {"inherit", "prefer", "require"}


@dataclass(frozen=True, slots=True)
class _HostLLMModel:
    endpoint: str
    model: str
    provider: str = ""
    priority: int = 0
    local: bool = False
    healthy: bool = False
    current: bool = False
    capabilities: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class _HostLLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class _HostLLMCompletion:
    text: str
    endpoint: str
    model: str
    stop_reason: str = ""
    usage: Any = field(default_factory=_HostLLMUsage)
    tool_calls: tuple[dict[str, Any], ...] = ()


def _sdk_symbol(name: str, fallback: Any) -> Any:
    """Use SDK 0.7.1 types when installed, while keeping old hosts usable."""
    try:
        from openkitsune_plugin_sdk import llm as sdk_llm

        return getattr(sdk_llm, name, fallback)
    except ImportError:
        return fallback


def _selection_error(message: str) -> Exception:
    return _sdk_symbol("PluginLLMSelectionError", ValueError)(message)


def _unavailable_error(message: str) -> Exception:
    return _sdk_symbol("PluginLLMUnavailableError", RuntimeError)(message)


class PluginLLMFacade:
    """A plugin-scoped view over the host Brain's shared LLM client."""

    __slots__ = ("_brain_resolver", "_plugin_id")

    def __init__(self, plugin_id: str, brain_resolver: Callable[[], Any]) -> None:
        self._plugin_id = plugin_id
        self._brain_resolver = brain_resolver

    def _brain(self) -> Any:
        brain = self._brain_resolver()
        if brain is None:
            raise _unavailable_error("OpenKitsune host Brain is not available")
        return brain

    def _client(self) -> Any:
        brain = self._brain()
        client = getattr(brain, "llm_client", None)
        if client is None:
            client = getattr(brain, "_llm_client", None)
        if client is None or not callable(getattr(client, "chat", None)):
            raise _unavailable_error("OpenKitsune host LLM client is not available")
        return client

    def list_models(
        self,
        *,
        capabilities: list[str] | tuple[str, ...] = (),
    ) -> list[Any]:
        """Return sanitized configured endpoint metadata."""
        brain = self._brain()
        list_models = getattr(brain, "list_available_models", None)
        if not callable(list_models):
            raise _unavailable_error("OpenKitsune host cannot list configured models")

        required = {
            str(capability).strip().lower()
            for capability in capabilities
            if str(capability).strip()
        }
        model_type = _sdk_symbol("LLMModel", _HostLLMModel)
        result: list[Any] = []
        for raw in list_models() or []:
            if not isinstance(raw, dict):
                continue
            model_capabilities = tuple(
                str(item).strip().lower()
                for item in (raw.get("capabilities") or [])
                if str(item).strip()
            )
            if required and not required.issubset(set(model_capabilities)):
                continue
            endpoint = str(raw.get("name") or "").strip()
            if not endpoint:
                continue
            result.append(
                model_type(
                    endpoint=endpoint,
                    model=str(raw.get("model") or ""),
                    provider=str(raw.get("provider") or ""),
                    priority=int(raw.get("priority") or 0),
                    local=bool(raw.get("local", False)),
                    healthy=bool(raw.get("is_healthy", False)),
                    current=bool(raw.get("is_current", False)),
                    capabilities=model_capabilities,
                    note=str(raw.get("note") or ""),
                )
            )
        return result

    @staticmethod
    def _selection(
        endpoint: str | None,
        policy: Any,
    ) -> tuple[str | None, str]:
        endpoint_name = str(endpoint or "").strip() or None
        if policy is None:
            normalized = "prefer" if endpoint_name else "inherit"
        else:
            normalized = str(getattr(policy, "value", policy)).strip().lower()
            if normalized not in _VALID_SELECTION_POLICIES:
                choices = ", ".join(sorted(_VALID_SELECTION_POLICIES))
                raise _selection_error(
                    f"Unknown LLM selection policy {policy!r}; expected one of: {choices}"
                )

        if normalized == "inherit" and endpoint_name:
            raise _selection_error("policy='inherit' cannot specify an endpoint")
        if normalized != "inherit" and not endpoint_name:
            raise _selection_error(f"policy={normalized!r} requires a configured endpoint name")
        return endpoint_name, normalized

    @staticmethod
    def _messages(
        messages: list[dict[str, Any]] | None,
        prompt: str | None,
    ) -> list[Message]:
        if messages is not None and prompt is not None:
            raise ValueError("Pass either messages or prompt, not both")
        if prompt is not None:
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("prompt must be a non-empty string")
            return [Message(role="user", content=prompt)]
        if not messages:
            raise ValueError("messages or prompt is required")

        result: list[Message] = []
        for index, raw in enumerate(messages):
            if not isinstance(raw, dict):
                raise TypeError(f"messages[{index}] must be a dict")
            role = str(raw.get("role") or "").strip().lower()
            if role not in {"user", "assistant", "system", "tool"}:
                raise ValueError(f"messages[{index}].role is invalid: {role!r}")
            content = raw.get("content")
            if not isinstance(content, (str, list)):
                raise TypeError(f"messages[{index}].content must be a string or content-block list")
            result.append(Message(role=role, content=content))
        return result

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[Tool] | None:
        if not tools:
            return None
        result: list[Tool] = []
        for index, raw in enumerate(tools):
            if not isinstance(raw, dict):
                raise TypeError(f"tools[{index}] must be a dict")
            function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
            name = str(function.get("name") or "").strip()
            if not name:
                raise ValueError(f"tools[{index}] has no name")
            schema = function.get("input_schema", function.get("parameters"))
            if schema is None:
                schema = {"type": "object", "properties": {}}
            if not isinstance(schema, dict):
                raise TypeError(f"tools[{index}] schema must be a dict")
            result.append(
                Tool(
                    name=name,
                    description=str(function.get("description") or ""),
                    input_schema=schema,
                )
            )
        return result

    async def complete(
        self,
        messages: list[dict[str, Any]] | None = None,
        *,
        prompt: str | None = None,
        system: str = "",
        endpoint: str | None = None,
        policy: Any = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        enable_thinking: bool = False,
        thinking_depth: str | None = None,
        timeout: float | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Any:
        """Complete one request without changing any persistent model override."""
        endpoint_name, selection_policy = self._selection(endpoint, policy)
        if endpoint_name and endpoint_name not in {item.endpoint for item in self.list_models()}:
            raise _selection_error(f"Endpoint {endpoint_name!r} is not configured in OpenKitsune")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise TypeError("max_tokens must be an integer")
        if not 1 <= max_tokens <= _MAX_COMPLETION_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {_MAX_COMPLETION_TOKENS}")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise TypeError("temperature must be numeric")
        if not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if thinking_depth is not None and thinking_depth not in _VALID_THINKING_DEPTHS:
            raise ValueError(
                f"thinking_depth must be one of: {', '.join(sorted(_VALID_THINKING_DEPTHS))}"
            )
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        call = self._client().chat(
            messages=self._messages(messages, prompt),
            system=str(system or ""),
            tools=self._tools(tools),
            max_tokens=max_tokens,
            temperature=float(temperature),
            enable_thinking=bool(enable_thinking),
            thinking_depth=thinking_depth,
            cancel_event=cancel_event,
            endpoint_name=endpoint_name,
            endpoint_policy=selection_policy,
        )
        response = await asyncio.wait_for(call, timeout=timeout) if timeout else await call

        usage = getattr(response, "usage", None)
        stop_reason = getattr(response, "stop_reason", "")
        if hasattr(stop_reason, "value"):
            stop_reason = stop_reason.value
        tool_calls = tuple(
            {
                "id": str(getattr(item, "id", "")),
                "name": str(getattr(item, "name", "")),
                "input": dict(getattr(item, "input", {}) or {}),
            }
            for item in (getattr(response, "tool_calls", None) or [])
        )
        usage_type = _sdk_symbol("LLMUsage", _HostLLMUsage)
        completion_type = _sdk_symbol("LLMCompletion", _HostLLMCompletion)
        return completion_type(
            text=str(getattr(response, "text", "") or ""),
            endpoint=str(getattr(response, "endpoint_name", "") or ""),
            model=str(getattr(response, "model", "") or ""),
            stop_reason=str(stop_reason or ""),
            usage=usage_type(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_creation_input_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            ),
            tool_calls=tool_calls,
        )


__all__ = ["PluginLLMFacade"]
