import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


class _Pool:
    def __init__(self):
        self.reasons: list[str] = []
        self.profiles: list[str] = []

    def notify_runtime_config_changed(self, reason: str) -> None:
        self.reasons.append(reason)

    def invalidate_profile(self, profile_id: str) -> int:
        self.profiles.append(profile_id)
        return 1


def test_invalidate_agent_pools_covers_desktop_and_orchestrator() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    desktop = _Pool()
    orchestrator = _Pool()
    state = SimpleNamespace(
        agent_pool=desktop,
        orchestrator=SimpleNamespace(_pool=orchestrator),
    )

    result = RuntimeConfigCoordinator(state).invalidate_agent_pools("identity")

    assert result.failed == {}
    assert result.invalidated == ["agent_pool", "orchestrator"]
    assert desktop.reasons == ["identity"]
    assert orchestrator.reasons == ["identity"]


def test_real_agent_pool_is_not_unwrapped_to_its_internal_entry_dict() -> None:
    from openkitsune.agents.factory import AgentInstancePool
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    pool = AgentInstancePool()
    assert isinstance(pool._pool, dict)

    result = RuntimeConfigCoordinator(SimpleNamespace(agent_pool=pool)).plugin_changed(
        "demo",
        "installed",
    )

    assert result.warnings == []
    assert result.invalidated == ["agent_pool"]
    assert pool._runtime_config_version == 1


def test_uninitialized_lazy_orchestrator_pool_is_skipped_without_warning() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    state = SimpleNamespace(
        agent_pool=_Pool(),
        orchestrator=SimpleNamespace(_pool=None),
    )

    result = RuntimeConfigCoordinator(state).plugin_changed("demo", "installed")

    assert result.warnings == []
    assert result.invalidated == ["agent_pool"]


def test_initialized_unsupported_orchestrator_pool_still_warns() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    state = SimpleNamespace(orchestrator=SimpleNamespace(_pool=object()))

    result = RuntimeConfigCoordinator(state).plugin_changed("demo", "installed")

    assert result.warnings == ["orchestrator: pool invalidation is not supported"]
    assert result.invalidated == []


def test_pool_invalidation_runs_in_registered_engine_thread() -> None:
    from openkitsune.core import engine_bridge
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    engine_thread_id: list[int] = []

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        engine_thread_id.append(threading.get_ident())
        ready.set()
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=_run_loop)
    thread.start()
    ready.wait(timeout=1)

    class _ThreadRecordingPool(_Pool):
        def notify_runtime_config_changed(self, reason: str) -> None:
            assert threading.get_ident() == engine_thread_id[0]
            super().notify_runtime_config_changed(reason)

    try:
        engine_bridge.set_engine_loop(loop)
        pool = _ThreadRecordingPool()
        result = RuntimeConfigCoordinator(SimpleNamespace(agent_pool=pool)).invalidate_agent_pools(
            "test"
        )
        assert result.failed == {}
        assert pool.reasons == ["test"]
    finally:
        engine_bridge.shutdown()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=1)


def test_refresh_identity_clears_compiled_cache_and_invalidates_pools(
    tmp_path, monkeypatch
) -> None:
    from openkitsune.prompt import builder, compiler
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    calls: list[str] = []
    monkeypatch.setattr(builder, "clear_prompt_section_cache", lambda: calls.append("clear"))
    monkeypatch.setattr(compiler, "compile_all", lambda _path: calls.append("compile"))

    class _Identity:
        def reload(self) -> None:
            calls.append("reload")

    class _Agent:
        identity = _Identity()
        _context = SimpleNamespace(system="old")

        def _invalidate_system_prompt_cache(self, reason: str) -> None:
            calls.append(f"invalidate:{reason}")

        def _build_system_prompt_compiled_sync(self) -> str:
            calls.append("build")
            return "new"

    desktop = _Pool()
    orchestrator = _Pool()
    state = SimpleNamespace(
        agent=_Agent(),
        agent_pool=desktop,
        orchestrator=SimpleNamespace(_pool=orchestrator),
    )

    result = RuntimeConfigCoordinator(state).refresh_identity(tmp_path)

    assert result.failed == {}
    assert calls == [
        "clear",
        "reload",
        "compile",
        "invalidate:identity_changed",
        "build",
    ]
    assert state.agent._context.system == "new"
    assert desktop.reasons == ["identity"]
    assert orchestrator.reasons == ["identity"]


def test_refresh_identity_can_reset_policy(tmp_path, monkeypatch) -> None:
    from openkitsune.core.policy_v2 import global_engine
    from openkitsune.prompt import builder, compiler
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    scopes: list[str] = []
    monkeypatch.setattr(builder, "clear_prompt_section_cache", lambda: None)
    monkeypatch.setattr(compiler, "compile_all", lambda _path: None)
    monkeypatch.setattr(
        global_engine,
        "reset_policy_v2_layer",
        lambda scope: scopes.append(scope),
    )

    result = RuntimeConfigCoordinator(SimpleNamespace(agent=None)).refresh_identity(
        tmp_path,
        refresh_policy=True,
    )

    assert result.failed == {}
    assert scopes == ["identity_editor"]
    assert "policy" in result.refreshed


def test_refresh_identity_crosses_engine_bridge_once(tmp_path, monkeypatch) -> None:
    from openkitsune.core import engine_bridge
    from openkitsune.prompt import builder, compiler
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    bridge_calls: list[None] = []

    def _call_in_engine(callback):
        bridge_calls.append(None)
        return callback()

    monkeypatch.setattr(engine_bridge, "call_in_engine", _call_in_engine)
    monkeypatch.setattr(builder, "clear_prompt_section_cache", lambda: None)
    monkeypatch.setattr(compiler, "compile_all", lambda _path: None)

    result = RuntimeConfigCoordinator(SimpleNamespace(agent=None)).refresh_identity(
        tmp_path,
        refresh_policy=True,
    )

    assert result.failed == {}
    assert bridge_calls == [None]


def test_rebuild_agent_prompt_uses_identity_fallback_and_invalidates_cache() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    calls: list[str] = []

    class _Identity:
        def get_compiled_prompt(self) -> str:
            calls.append("identity_prompt")
            return "fallback prompt"

    class _Agent:
        identity = _Identity()
        _context = SimpleNamespace(system="old")

        def _invalidate_system_prompt_cache(self, reason: str) -> None:
            calls.append(f"invalidate:{reason}")

    agent = _Agent()
    result = RuntimeConfigCoordinator(SimpleNamespace(agent=agent)).rebuild_agent_prompt()

    assert result.failed == {}
    assert result.refreshed == ["global_agent_prompt"]
    assert result.details["agent_prompt_source"] == "identity"
    assert agent._context.system == "fallback prompt"
    assert calls == ["invalidate:identity_changed", "identity_prompt"]


def test_rebuild_agent_prompt_reports_builder_failure() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    class _Agent:
        _context = SimpleNamespace(system="old")

        def _build_system_prompt_compiled_sync(self) -> str:
            raise RuntimeError("prompt build failed")

    result = RuntimeConfigCoordinator(SimpleNamespace(agent=_Agent())).rebuild_agent_prompt()

    assert result.status == "failed"
    assert result.failed["agent_prompt"] == "prompt build failed"


def test_invalidate_org_node_evicts_cached_agent() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    evictions: list[tuple[str, str]] = []
    cache = SimpleNamespace(evict=lambda org_id, node_id: evictions.append((org_id, node_id)))

    result = RuntimeConfigCoordinator(SimpleNamespace(org_agent_cache=cache)).invalidate_org_node(
        "org-1", "node-1", "identity_changed"
    )

    assert result.failed == {}
    assert evictions == [("org-1", "node-1")]
    assert result.apply_mode.value == "next_task"


@pytest.mark.asyncio
async def test_im_apply_false_is_reported_as_failure(monkeypatch) -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    async def _reject(_bot):
        return False

    main_stub = ModuleType("openkitsune.main")
    main_stub.apply_im_bot = _reject
    monkeypatch.setitem(sys.modules, "openkitsune.main", main_stub)

    result = await RuntimeConfigCoordinator(SimpleNamespace()).apply_im_bot(
        {"id": "bot-1", "enabled": True},
        "enable",
    )

    assert result.status == "failed"
    assert result.failed["im_gateway"] == "IM runtime did not accept the bot"


@pytest.mark.asyncio
async def test_plugin_config_hook_failure_is_reported(monkeypatch) -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    class _HookRegistry:
        async def dispatch(self, *_args, **_kwargs):
            raise RuntimeError("hook failed")

    manager = SimpleNamespace(_hook_registry=_HookRegistry())
    result = await RuntimeConfigCoordinator(SimpleNamespace()).apply_plugin_config(
        "demo",
        {"enabled": True},
        manager,
    )

    assert result.status == "failed"
    assert result.failed["plugin_config_hook"] == "hook failed"


@pytest.mark.asyncio
async def test_plugin_config_without_matching_hook_defers_until_reload() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    class _HookRegistry:
        async def dispatch(self, *_args, **_kwargs):
            return []

    manager = SimpleNamespace(_hook_registry=_HookRegistry())
    result = await RuntimeConfigCoordinator(SimpleNamespace()).apply_plugin_config(
        "demo",
        {"enabled": True},
        manager,
    )

    assert result.status == "partial"
    assert "plugin_instance" not in result.refreshed
    assert result.details["plugin_config_apply"] == "next_reload"
    assert result.warnings


@pytest.mark.asyncio
async def test_plugin_config_reports_refresh_only_when_hook_runs() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    class _HookRegistry:
        async def dispatch(self, *_args, **_kwargs):
            return [None]

    manager = SimpleNamespace(_hook_registry=_HookRegistry())
    result = await RuntimeConfigCoordinator(SimpleNamespace()).apply_plugin_config(
        "demo",
        {"enabled": True},
        manager,
    )

    assert result.status == "ok"
    assert "plugin_instance" in result.refreshed
    assert result.details["plugin_config_apply"] == "hook"


def test_runtime_tools_change_does_not_claim_category_was_refreshed() -> None:
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    result = RuntimeConfigCoordinator(SimpleNamespace()).plugin_changed("demo", "enabled")

    assert "plugins" not in result.refreshed
    assert result.details["runtime_category"] == "plugins"
    assert result.details["runtime_reason"] == "demo:enabled"


def test_runtime_tools_change_leaves_classifier_invalidation_to_registry(monkeypatch) -> None:
    from openkitsune.core.policy_v2 import global_engine
    from openkitsune.runtime_config_coordinator import RuntimeConfigCoordinator

    classifier_calls: list[None] = []
    monkeypatch.setattr(
        global_engine,
        "invalidate_classifier_cache",
        lambda: classifier_calls.append(None),
    )
    pool = _Pool()

    result = RuntimeConfigCoordinator(SimpleNamespace(agent_pool=pool)).plugin_changed(
        "demo",
        "reloaded",
    )

    assert classifier_calls == []
    assert "policy_classifier" not in result.details
    assert "policy_classifier" not in result.invalidated
    assert pool.reasons == ["plugins:demo:reloaded"]
