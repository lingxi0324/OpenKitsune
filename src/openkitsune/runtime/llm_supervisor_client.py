"""RC-5 S3: production :class:`SupervisorLLMClient` over the gateway ``LLMClient``.

This is the production-grade promotion of the spike/Q2 ``GatewayLLMClient``
(``_rc5_biz/q2_live/q2_harness.py`` / ``_rc5_biz/gap5_spike/``). The spike's
adapter was a harness convenience; this module is the real seam the
``OrgCommandService.submit`` gray-launch path injects into
:func:`openkitsune.runtime.supervisor_factory.build_supervisor_for_command`.

Why a separate, narrow adapter (the two-protocol trap, RC-5 §2)
---------------------------------------------------------------
The orchestration brain (:class:`~openkitsune.runtime.llm_supervisor_brain.LLMSupervisorBrain`)
depends only on the narrow :class:`~openkitsune.runtime.llm_supervisor_brain.SupervisorLLMClient`
``complete`` protocol -- NOT on the wide gateway ``LLMClient`` /
``agent.brain.Brain`` surfaces. Keeping this adapter thin means the brain
carries zero coupling to the gateway; tests inject a scripted fake, production
injects this.

Design notes
------------
* **No-thinking endpoint lock (cost + JSON stability).** The orchestration
  prompts want pure JSON; thinking-mode chain-of-thought prefixes pollute the
  JSON head and trigger parse retries (see ``_rc5_biz/sprint_s1/s1_report.md``
  §3). We resolve ``settings.orgs_supervisor_llm_endpoint`` (``auto`` chooses
  the current workspace's highest-priority healthy text endpoint) and lock it
  via a **per-conversation** override so the process-wide default model is
  never clobbered. Thinking is disabled by request parameter, not by an
  endpoint naming convention. An explicitly configured endpoint remains
  strict.
* **Cancel bridge (RC-4).** ``cancel_event`` is forwarded straight into
  ``LLMClient.chat`` so a user "stop" aborts the in-flight ``httpx`` request
  immediately (validated by the Q2 cancel probe).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from openkitsune.llm.types import ConfigurationError, Message

if TYPE_CHECKING:  # pragma: no cover -- import-cycle / type-only
    from openkitsune.llm.client import LLMClient

__all__ = [
    "DEFAULT_SUPERVISOR_LLM_ENDPOINT",
    "GatewaySupervisorLLMClient",
]

#: Automatic selection avoids coupling organization orchestration to one
#: provider, model generation, or deployment-specific endpoint name.
DEFAULT_SUPERVISOR_LLM_ENDPOINT = "auto"


class GatewaySupervisorLLMClient:
    """Adapt the gateway :class:`~openkitsune.llm.client.LLMClient` to the narrow
    ``SupervisorLLMClient`` ``complete`` seam.

    Args:
        client: the gateway LLM client (typically
            :func:`openkitsune.llm.client.get_default_client`).
        endpoint: ``"auto"``/``None`` chooses the current workspace's
            highest-priority healthy text endpoint. A concrete name is locked
            strictly and never silently replaced.
        max_tokens: output cap per orchestration call.
        conversation_id: scope for the per-conversation endpoint override so
            the process-wide default model is never mutated. Auto-minted when
            omitted.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        endpoint: str | None = DEFAULT_SUPERVISOR_LLM_ENDPOINT,
        max_tokens: int = 2048,
        conversation_id: str | None = None,
    ) -> None:
        self._client = client
        self._endpoint = endpoint or None
        self._resolved_endpoint: str | None = None
        self._max_tokens = max_tokens
        self._conversation_id = conversation_id or f"orgsup-{uuid.uuid4().hex[:12]}"
        self._endpoint_locked = False
        self._endpoint_lock_error: str | None = None

    def _ensure_endpoint_lock(self) -> None:
        """Resolve and require a one-time lock onto the Supervisor endpoint.

        Uses a per-conversation override (``conversation_id``) so flipping the
        orchestration model never affects the global default client used by
        chat / agents. Automatic selection happens once per command; explicit
        endpoint lock failures are cached and raised so the supervisor
        terminates with a precise configuration error.
        """
        if self._endpoint_lock_error is not None:
            raise ConfigurationError(self._endpoint_lock_error)
        if self._endpoint_locked:
            return
        requested_endpoint = (self._endpoint or DEFAULT_SUPERVISOR_LLM_ENDPOINT).strip()
        if requested_endpoint.lower() == DEFAULT_SUPERVISOR_LLM_ENDPOINT:
            requested_endpoint = self._client.get_default_endpoint_name() or ""
            if not requested_endpoint:
                self._endpoint_lock_error = (
                    "Supervisor 自动选择失败：当前工作区没有可用的健康文本端点，"
                    "请先配置并启用一个 LLM 端点，或在高级设置中关闭 LLM Supervisor"
                )
                raise ConfigurationError(self._endpoint_lock_error)
        self._resolved_endpoint = requested_endpoint
        try:
            ok, msg = self._client.switch_model(
                requested_endpoint,
                conversation_id=self._conversation_id,
                policy="require",
                reason="organization supervisor (thinking disabled)",
            )
            if not ok:
                self._endpoint_lock_error = (
                    f"指定的 Supervisor 端点 {requested_endpoint!r} 不可用：{msg}"
                )
                raise ConfigurationError(self._endpoint_lock_error)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 -- convert to a structural failure
            self._endpoint_lock_error = (
                f"指定的 Supervisor 端点 {requested_endpoint!r} 无法锁定：{exc}"
            )
            raise ConfigurationError(self._endpoint_lock_error) from exc
        self._endpoint_locked = True

    async def complete(
        self,
        *,
        role: str,
        system: str,
        user: str,
        cancel_event: asyncio.Event | None = None,
    ) -> str:
        """Run one orchestration LLM call and return the text body.

        ``role`` (``facts`` / ``plan`` / ``progress_ledger``) is accepted for
        the cheap-model-tiering seam but currently routed uniformly to the
        locked endpoint; per-role tiering is the deferred cost follow-up.
        """
        self._ensure_endpoint_lock()
        resp = await self._client.chat(
            messages=[Message(role="user", content=user)],
            system=system,
            max_tokens=self._max_tokens,
            temperature=0.0,
            enable_thinking=False,
            conversation_id=self._conversation_id,
            cancel_event=cancel_event,
        )
        return resp.text
