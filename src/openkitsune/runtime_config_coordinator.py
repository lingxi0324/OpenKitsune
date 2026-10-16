"""Coordinate runtime effects after configuration has been persisted.

Configuration owners remain responsible for validation and durable writes.
This module only propagates an already-committed change to live components and
reports when the new value becomes observable.
"""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openkitsune.config_lifecycle import ConfigApplyMode

logger = logging.getLogger(__name__)
_PROFILE_REFERENCE_CHANGE_LOCK = threading.RLock()


def profile_reference_change_lock() -> threading.RLock:
    """Serialize profile deletion with persisted IM and organization reference changes."""
    return _PROFILE_REFERENCE_CHANGE_LOCK


@dataclass
class RuntimeApplyResult:
    """Structured outcome returned by runtime configuration operations."""

    apply_mode: ConfigApplyMode = ConfigApplyMode.IMMEDIATE
    refreshed: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    restart_required: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.failed:
            return "partial" if self.refreshed or self.invalidated else "failed"
        return "partial" if self.warnings else "ok"

    def merge(self, other: RuntimeApplyResult) -> RuntimeApplyResult:
        precedence = {
            ConfigApplyMode.IMMEDIATE: 0,
            ConfigApplyMode.NEXT_TASK: 1,
            ConfigApplyMode.COMPONENT_RELOAD: 2,
            ConfigApplyMode.PROCESS_RESTART: 3,
        }
        if precedence[other.apply_mode] > precedence[self.apply_mode]:
            self.apply_mode = other.apply_mode
        for value in other.refreshed:
            if value not in self.refreshed:
                self.refreshed.append(value)
        for value in other.invalidated:
            if value not in self.invalidated:
                self.invalidated.append(value)
        self.warnings.extend(other.warnings)
        self.failed.update(other.failed)
        self.restart_required = self.restart_required or other.restart_required
        self.details.update(other.details)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "apply_mode": self.apply_mode.value,
            "refreshed": self.refreshed,
            "invalidated": self.invalidated,
            "warnings": self.warnings,
            "failed": self.failed,
            "restart_required": self.restart_required,
            **self.details,
        }


class RuntimeConfigCoordinator:
    """Apply committed configuration changes to process-owned runtime state."""

    def __init__(self, app_state: Any):
        self._state = app_state

    @staticmethod
    def _supports_pool_invalidation(pool: Any, *, profile_id: str | None) -> bool:
        if profile_id is not None and hasattr(pool, "invalidate_profile"):
            return True
        return hasattr(pool, "notify_runtime_config_changed") or hasattr(
            pool, "notify_skills_changed"
        )

    def _agent_pools(self, *, profile_id: str | None = None) -> list[tuple[str, Any]]:
        pools: list[tuple[str, Any]] = []
        seen: set[int] = set()
        for name in ("agent_pool", "orchestrator"):
            owner = getattr(self._state, name, None)
            if owner is None:
                continue

            if self._supports_pool_invalidation(owner, profile_id=profile_id):
                pool = owner
            elif hasattr(owner, "_pool"):
                pool = owner._pool
                if pool is None:
                    # Lazy pool owners have no cached agent instances before initialization.
                    continue
            else:
                pool = owner
            if pool is None or id(pool) in seen:
                continue
            seen.add(id(pool))
            pools.append((name, pool))
        return pools

    def invalidate_agent_pools(
        self,
        reason: str,
        *,
        profile_id: str | None = None,
        names: set[str] | None = None,
    ) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(
            lambda: self._invalidate_agent_pools_in_engine(
                reason,
                profile_id=profile_id,
                names=names,
            )
        )

    def _invalidate_agent_pools_in_engine(
        self,
        reason: str,
        *,
        profile_id: str | None = None,
        names: set[str] | None = None,
    ) -> RuntimeApplyResult:
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.NEXT_TASK)
        for name, pool in self._agent_pools(profile_id=profile_id):
            if names is not None and name not in names:
                continue
            try:
                if profile_id is not None and hasattr(pool, "invalidate_profile"):
                    pool.invalidate_profile(profile_id)
                elif hasattr(pool, "notify_runtime_config_changed"):
                    pool.notify_runtime_config_changed(reason)
                elif hasattr(pool, "notify_skills_changed"):
                    pool.notify_skills_changed()
                else:
                    result.warnings.append(f"{name}: pool invalidation is not supported")
                    continue
                result.invalidated.append(name)
            except Exception as exc:
                result.failed[name] = str(exc)
                logger.warning("Runtime pool invalidation failed (%s): %s", name, exc)
        return result

    def clear_prompt_cache(self) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(self._clear_prompt_cache_in_engine)

    def _clear_prompt_cache_in_engine(self) -> RuntimeApplyResult:
        result = RuntimeApplyResult()
        try:
            from openkitsune.prompt.builder import clear_prompt_section_cache

            clear_prompt_section_cache()
            result.invalidated.append("prompt_cache")
        except Exception as exc:
            result.failed["prompt_cache"] = str(exc)
        return result

    def refresh_policy(self, reason: str) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(lambda: self._refresh_policy_in_engine(reason))

    def _refresh_policy_in_engine(self, reason: str) -> RuntimeApplyResult:
        result = RuntimeApplyResult()
        try:
            from openkitsune.core.policy_v2.global_engine import reset_policy_v2_layer

            reset_policy_v2_layer(scope=reason)
            result.refreshed.append("policy")
        except Exception as exc:
            result.failed["policy"] = str(exc)
            logger.exception("Policy runtime refresh failed (%s)", reason)
        return result

    def refresh_identity(
        self,
        identity_dir: Path,
        *,
        reason: str = "identity",
        refresh_policy: bool = False,
    ) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(
            lambda: self._refresh_identity_in_engine(
                identity_dir,
                reason=reason,
                refresh_policy=refresh_policy,
            )
        )

    def _refresh_identity_in_engine(
        self,
        identity_dir: Path,
        *,
        reason: str,
        refresh_policy: bool,
    ) -> RuntimeApplyResult:
        result = self._clear_prompt_cache_in_engine()
        agent = getattr(self._state, "agent", None)
        local_agent = getattr(agent, "_local_agent", agent)

        try:
            from openkitsune.prompt.compiler import compile_all

            identity = getattr(local_agent, "identity", None)
            if identity is not None:
                identity.reload()
                result.refreshed.append("global_identity")
            compile_all(identity_dir)
            result.refreshed.append("compiled_prompt")
            result.merge(self._rebuild_agent_prompt_in_engine())
        except Exception as exc:
            result.failed["identity"] = str(exc)
            logger.exception("Identity runtime refresh failed")

        result.merge(self._invalidate_agent_pools_in_engine(reason))
        if refresh_policy:
            result.merge(self._refresh_policy_in_engine("identity_editor"))
        return result

    def rebuild_agent_prompt(self) -> RuntimeApplyResult:
        """Rebuild the live global Agent prompt from the latest compiled identity."""
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(self._rebuild_agent_prompt_in_engine)

    def _rebuild_agent_prompt_in_engine(self) -> RuntimeApplyResult:
        result = RuntimeApplyResult()
        owner = getattr(self._state, "agent", None)
        agent = getattr(owner, "_local_agent", owner)
        if agent is None:
            return result

        try:
            if hasattr(agent, "_invalidate_system_prompt_cache"):
                agent._invalidate_system_prompt_cache(reason="identity_changed")

            source: str | None = None
            if hasattr(agent, "_build_system_prompt_compiled_sync"):
                prompt = agent._build_system_prompt_compiled_sync()
                source = "compiled"
            elif hasattr(agent, "_build_system_prompt"):
                prompt = agent._build_system_prompt()
                source = "system"
            else:
                identity = getattr(agent, "identity", None)
                if identity is None or not hasattr(identity, "get_compiled_prompt"):
                    result.warnings.append(
                        "Agent does not support rebuilding its compiled identity prompt"
                    )
                    return result
                prompt = identity.get_compiled_prompt()
                source = "identity"

            context = getattr(agent, "_context", None)
            if context is None:
                result.warnings.append(
                    "Agent context is unavailable; compiled identity applies on next initialization"
                )
                return result
            context.system = prompt
            result.refreshed.append("global_agent_prompt")
            result.details["agent_prompt_source"] = source
        except Exception as exc:
            result.failed["agent_prompt"] = str(exc)
            logger.exception("Agent prompt rebuild failed after identity compilation")
        return result

    def refresh_llm(self, *, config_path: Path | None = None) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(lambda: self._refresh_llm_in_engine(config_path=config_path))

    def _refresh_llm_in_engine(self, *, config_path: Path | None) -> RuntimeApplyResult:
        from openkitsune.llm.runtime_config import apply_llm_runtime_config

        agent = getattr(self._state, "agent", None)
        gateway = getattr(self._state, "gateway", None)
        desktop_pool = getattr(self._state, "agent_pool", None)
        raw = apply_llm_runtime_config(
            agent=agent,
            gateway=gateway,
            pool=desktop_pool,
            config_path=config_path,
            reason="llm_config",
        )
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.NEXT_TASK)
        for key, label in (
            ("main_reloaded", "llm_main"),
            ("default_reloaded", "llm_supervisor"),
            ("compiler_reloaded", "llm_compiler"),
            ("stt_reloaded", "gateway_stt"),
        ):
            if raw.get(key):
                result.refreshed.append(label)
        if raw.get("pool_invalidated"):
            result.invalidated.append("agent_pool")
        result.warnings.extend(str(item) for item in raw.get("warnings", []))
        if raw.get("status") == "failed":
            result.failed["llm"] = str(raw.get("reason", "reload failed"))
        result.details["llm"] = raw
        result.merge(
            self._invalidate_agent_pools_in_engine(
                "llm_config",
                names={"orchestrator"},
            )
        )
        return result

    async def refresh_skills(self, *, rescan: bool = False) -> RuntimeApplyResult:
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.NEXT_TASK)
        try:
            from openkitsune.agent.security_actions import maybe_refresh_skills
            from openkitsune.core.engine_bridge import to_engine

            await to_engine(
                maybe_refresh_skills(
                    {"status": "ok", "kind": "skill_external_allowlist"},
                    lambda: getattr(self._state, "agent", None),
                )
            )
            result.refreshed.append("skills")
            # propagate_skill_change owns pool invalidation. If no global Agent
            # exists yet, persisted configuration is consumed on startup.
            if rescan:
                result.details["rescan"] = True
        except Exception as exc:
            result.failed["skills"] = str(exc)
            logger.exception("Skill runtime refresh failed")
        return result

    def runtime_tools_changed(
        self,
        category: str,
        reason: str,
    ) -> RuntimeApplyResult:
        """Refresh runtime tool consumers after plugin/MCP changes.

        The plugin and MCP registries own policy-classifier invalidation because
        only they know whether their live tool set actually changed. This
        coordinator refreshes downstream consumers of those registries.
        """
        from openkitsune.core.engine_bridge import call_in_engine

        return call_in_engine(
            lambda: self._runtime_tools_changed_in_engine(
                category,
                reason,
            )
        )

    def _runtime_tools_changed_in_engine(
        self,
        category: str,
        reason: str,
    ) -> RuntimeApplyResult:
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.NEXT_TASK)
        result.merge(self._invalidate_agent_pools_in_engine(f"{category}:{reason}"))
        result.details["runtime_category"] = category
        result.details["runtime_reason"] = reason
        return result

    def plugin_changed(
        self,
        plugin_id: str,
        reason: str,
    ) -> RuntimeApplyResult:
        result = self.runtime_tools_changed(
            "plugins",
            f"{plugin_id}:{reason}",
        )
        result.details["plugin_id"] = plugin_id
        return result

    def mcp_changed(
        self,
        server_name: str,
        reason: str,
    ) -> RuntimeApplyResult:
        result = self.runtime_tools_changed(
            "mcp",
            f"{server_name}:{reason}",
        )
        result.details["server"] = server_name
        return result

    async def apply_im_bot(self, bot: dict[str, Any], operation: str) -> RuntimeApplyResult:
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.COMPONENT_RELOAD)
        try:
            if operation in {"create", "update", "enable", "rollback"} and bot.get("enabled", True):
                from openkitsune.core.engine_bridge import to_engine
                from openkitsune.main import apply_im_bot

                applied = await to_engine(apply_im_bot(bot))
                if not applied:
                    result.failed["im_gateway"] = "IM runtime did not accept the bot"
                else:
                    result.refreshed.append("im_gateway")
            else:
                from openkitsune.core.engine_bridge import to_engine
                from openkitsune.main import remove_im_bot

                await to_engine(remove_im_bot(bot))
                result.refreshed.append("im_gateway")
        except Exception as exc:
            result.failed["im_gateway"] = str(exc)
            logger.exception("IM runtime update failed (%s)", operation)
        return result

    async def apply_plugin_config(
        self,
        plugin_id: str,
        config: dict[str, Any],
        plugin_manager: Any,
    ) -> RuntimeApplyResult:
        """Notify the loaded plugin instance, then invalidate dependent Agent runtimes."""
        result = RuntimeApplyResult(apply_mode=ConfigApplyMode.COMPONENT_RELOAD)
        hook_registry = getattr(plugin_manager, "_hook_registry", None)
        if hook_registry is not None:
            try:
                from openkitsune.core.engine_bridge import to_engine

                hook_results = await to_engine(
                    hook_registry.dispatch(
                        "on_config_change",
                        fail_on_error=True,
                        target_plugin_id=plugin_id,
                        plugin_id=plugin_id,
                        config=config,
                    )
                )
                if hook_results:
                    result.refreshed.append("plugin_instance")
                    result.details["plugin_config_apply"] = "hook"
                else:
                    result.warnings.append(
                        "Plugin has no active config-change hook; changes apply on next reload"
                    )
                    result.details["plugin_config_apply"] = "next_reload"
            except Exception as exc:
                result.failed["plugin_config_hook"] = str(exc)
                logger.exception("Plugin config hook failed (%s)", plugin_id)
        else:
            result.warnings.append(
                "Plugin runtime is unavailable; config changes apply on next reload"
            )
            result.details["plugin_config_apply"] = "next_reload"
        result.merge(self.plugin_changed(plugin_id, "config_changed"))
        return result

    def reload_desktop(self) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        def _reload() -> RuntimeApplyResult:
            result = RuntimeApplyResult(apply_mode=ConfigApplyMode.COMPONENT_RELOAD)
            try:
                from openkitsune.tools.desktop.config import reset_config

                reset_config()
                result.refreshed.append("desktop")
            except Exception as exc:
                result.failed["desktop"] = str(exc)
            return result

        return call_in_engine(_reload)

    async def sync_scheduler(
        self,
        callback: Callable[[], Any | Awaitable[Any]],
    ) -> RuntimeApplyResult:
        result = RuntimeApplyResult()
        try:
            from openkitsune.core.engine_bridge import to_engine

            async def _sync() -> None:
                value = callback()
                if inspect.isawaitable(value):
                    await value

            await to_engine(_sync())
            result.refreshed.append("scheduler")
        except Exception as exc:
            result.failed["scheduler"] = str(exc)
            logger.exception("Scheduler runtime sync failed")
        return result

    def invalidate_org_node(
        self,
        org_id: str,
        node_id: str,
        reason: str,
    ) -> RuntimeApplyResult:
        from openkitsune.core.engine_bridge import call_in_engine

        def _invalidate() -> RuntimeApplyResult:
            result = RuntimeApplyResult(apply_mode=ConfigApplyMode.NEXT_TASK)
            cache = getattr(self._state, "org_agent_cache", None)
            if cache is None:
                result.warnings.append("organization Agent cache is not initialized")
                return result
            try:
                cache.evict(org_id, node_id)
                result.invalidated.append(f"org_node:{org_id}:{node_id}")
                result.details["reason"] = reason
            except Exception as exc:
                result.failed["org_agent_cache"] = str(exc)
            return result

        return call_in_engine(_invalidate)

    def request_process_restart(self, reason: str) -> RuntimeApplyResult:
        result = RuntimeApplyResult(
            apply_mode=ConfigApplyMode.PROCESS_RESTART,
            restart_required=True,
            details={"restart_reason": reason},
        )
        return result


def get_runtime_config_coordinator(request: Any) -> RuntimeConfigCoordinator:
    """Return the app-scoped coordinator, creating it lazily for tests."""
    state = request.app.state
    coordinator = getattr(state, "runtime_config_coordinator", None)
    if coordinator is None:
        coordinator = RuntimeConfigCoordinator(state)
        state.runtime_config_coordinator = coordinator
    return coordinator
