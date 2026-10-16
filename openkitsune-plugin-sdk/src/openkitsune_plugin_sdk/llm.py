"""LLM provider registration and host-model consumption contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class LLMSelectionPolicy(StrEnum):
    """How a plugin completion chooses an OpenKitsune endpoint."""

    INHERIT = "inherit"
    PREFER = "prefer"
    REQUIRE = "require"


@dataclass(frozen=True, slots=True)
class LLMModel:
    """Sanitized metadata for one host-configured LLM endpoint.

    Endpoint URLs and credentials are deliberately absent. ``endpoint`` is
    the stable value plugins pass back to :meth:`PluginLLM.complete`.
    """

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
class LLMUsage:
    """Normalized token usage returned to a plugin."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LLMCompletion:
    """Provider-neutral completion result returned by the host facade."""

    text: str
    endpoint: str
    model: str
    stop_reason: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    tool_calls: tuple[dict[str, Any], ...] = ()


class PluginLLMError(RuntimeError):
    """Base error for plugin-facing LLM operations."""

    code = "plugin_llm_error"


class PluginLLMUnavailableError(PluginLLMError):
    """The host has no usable LLM runtime."""

    code = "plugin_llm_unavailable"


class PluginLLMSelectionError(PluginLLMError):
    """A requested endpoint or selection policy is invalid."""

    code = "plugin_llm_endpoint_unavailable"


@runtime_checkable
class PluginLLM(Protocol):
    """Stable, read-only facade over OpenKitsune's configured LLM endpoints.

    Implementations must keep endpoint selection request-scoped. Calling
    :meth:`complete` must never change the user's global or conversation model
    override.
    """

    def list_models(self, *, capabilities: list[str] | tuple[str, ...] = ()) -> list[LLMModel]:
        """List sanitized configured endpoints matching all capabilities."""

    async def complete(
        self,
        messages: list[dict[str, Any]] | None = None,
        *,
        prompt: str | None = None,
        system: str = "",
        endpoint: str | None = None,
        policy: LLMSelectionPolicy | str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        enable_thinking: bool = False,
        thinking_depth: str | None = None,
        timeout: float | None = None,
        cancel_event: Any = None,
    ) -> LLMCompletion:
        """Run one completion through the host's shared LLM runtime."""


class LLMProvider(ABC):
    """Abstract base for LLM providers.

    Mirrors ``openkitsune.llm.providers.base.LLMProvider`` so plugin authors
    can implement new wire protocols without installing the full runtime.

    A plugin registers two things:

    1. A **provider class** (this) via ``api.register_llm_provider(api_type, cls)``
       — handles the actual API calls for a new ``api_type``.
    2. A **registry entry** via ``api.register_llm_registry(slug, registry)``
       — provides model discovery and default configuration.
    """

    @abstractmethod
    def __init__(self, config: Any) -> None:
        """Initialize with an EndpointConfig."""

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs: Any) -> Any:
        """Send a chat completion request and return the response."""

    @abstractmethod
    async def chat_stream(self, messages: list[dict], **kwargs: Any) -> Any:
        """Send a streaming chat completion request, yielding chunks."""


class ProviderRegistryInfo:
    """Metadata for a provider registry entry.

    Matches the shape expected by ``api.register_llm_registry()``.
    """

    def __init__(
        self,
        slug: str,
        name: str,
        api_type: str,
        default_base_url: str = "",
        api_key_env: str = "",
    ) -> None:
        self.slug = slug
        self.name = name
        self.api_type = api_type
        self.default_base_url = default_base_url
        self.api_key_env = api_key_env


class ProviderRegistry:
    """Skeleton provider registry for SDK usage.

    Plugin authors should subclass and implement ``list_models()`` to provide
    model discovery. The registry is registered via
    ``api.register_llm_registry(slug, registry_instance)``.
    """

    def __init__(self, info: ProviderRegistryInfo) -> None:
        self.info = info

    def list_models(self) -> list[dict]:
        """Return available models. Override in subclass."""
        return []
