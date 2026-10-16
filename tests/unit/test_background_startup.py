import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.startup import cancel_startup_tasks, run_optional_startup


async def test_cancelled_optional_startup_never_publishes_ready():
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    published = []

    async def start():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(run_optional_startup(start, lambda *v: published.append(v)))
    await asyncio.wait_for(entered.wait(), 1)
    await cancel_startup_tasks([task])
    assert task.cancelled()
    assert cancelled.is_set()
    assert published == []


async def test_optional_failure_is_reported_without_failing_chat():
    published = []

    async def start():
        raise RuntimeError("channel offline")

    await run_optional_startup(start, lambda *v: published.append(v))
    assert published[0][0] is None
    assert str(published[0][1]) == "channel offline"


async def test_agent_ready_does_not_wait_for_warmup(monkeypatch):
    from openkitsune.agent import Agent

    agent = Agent.__new__(Agent)
    agent._initialized = False
    agent._initialize_lock = asyncio.Lock()
    entered = asyncio.Event()

    async def initialize(**_kwargs):
        agent._initialized = True

    async def warm():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_initialize_unlocked", initialize)
    monkeypatch.setattr(agent, "_warm_optional_services", warm)
    monkeypatch.setattr(agent, "_connect_startup_mcp_servers", AsyncMock())
    await asyncio.wait_for(agent.initialize(defer_optional=True), 1)
    assert agent._initialized
    assert not entered.is_set()
    agent.start_background_services()
    tasks = list(agent._optional_startup_tasks)
    agent.start_background_services()
    assert agent._optional_startup_tasks == tasks
    await asyncio.wait_for(entered.wait(), 1)
    assert agent.optional_startup_status["warmup"] == "starting"
    await cancel_startup_tasks(tasks)


def test_package_imports_do_not_load_agent_runtime_or_model_sdk():
    code = """
import sys
import openkitsune.agent
from openkitsune.agent.errors import UserCancelledError
from openkitsune.agents.profile import AgentProfile
assert 'openkitsune.core._agent_runtime' not in sys.modules
assert 'anthropic' not in sys.modules
assert 'Agent' in dir(openkitsune.agent)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


async def test_chat_readiness_is_independent_of_gateway():
    from openkitsune.api.server import create_app

    app = create_app(agent=SimpleNamespace(), session_manager=SimpleNamespace())
    assert app.state.readiness["chat_ready"] is True
    assert app.state.readiness["ready"] is True
    assert app.state.readiness["im_ready"] is False
    assert create_app().state.readiness["chat_ready"] is False


@pytest.mark.parametrize("available", [True, False])
def test_startup_dependency_check_does_not_import_or_install(monkeypatch, available):
    import openkitsune.runtime_channel_deps as deps

    monkeypatch.setattr(deps, "inject_module_paths_runtime", lambda: None)
    monkeypatch.setattr(deps, "_patch_backports_zstd", lambda: None)
    monkeypatch.setattr(deps, "patch_simplejson_jsondecodeerror", lambda **_: None)
    monkeypatch.setattr(deps.importlib.util, "find_spec", lambda _: object() if available else None)

    def unexpected(*_args, **_kwargs):
        pytest.fail("startup must not execute SDK imports or invoke pip")

    monkeypatch.setattr(deps.importlib, "import_module", unexpected)
    monkeypatch.setattr(deps, "_select_pip_python", unexpected)
    result = deps.ensure_channel_dependencies(
        workspace_env={"FEISHU_ENABLED": "true"},
        install_missing=False,
        import_check=False,
    )
    assert result["installed"] == []
    assert (result["status"] == "ok") == available
    if not available:
        assert "lark-oapi" in result["errors"]


async def test_sticker_warmup_and_first_request_share_initialization(tmp_path, monkeypatch):
    from openkitsune.tools.sticker import StickerEngine

    engine = StickerEngine(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def download():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return True

    monkeypatch.setattr(engine, "_download_index", download)
    first = asyncio.create_task(engine.initialize())
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(engine.initialize())
    release.set()
    assert await asyncio.gather(first, second) == [True, True]
    assert calls == 1


@pytest.mark.parametrize("outcome", ["cancel", "error", "ready", "degraded"])
def test_serve_publishes_chat_ready_without_waiting_for_im(tmp_path, monkeypatch, outcome):
    import signal

    import openkitsune.api.server as server
    import openkitsune.config as config
    import openkitsune.logging as logging_config

    monkeypatch.setattr(logging_config, "setup_logging", lambda **_: None)
    import openkitsune.main as main
    import openkitsune.runtime_env as runtime_env

    events = []
    snapshots = []
    shutdown = None
    agent = SimpleNamespace(
        skill_registry=SimpleNamespace(count=0),
        initialize=AsyncMock(),
        start_background_services=lambda: events.append("warmup"),
        shutdown=AsyncMock(),
    )

    async def api_start(**kwargs):
        nonlocal shutdown
        shutdown = kwargs["shutdown_event"]
        events.append("http")
        return asyncio.create_task(asyncio.Event().wait())

    def get_agent():
        events.append("agent")
        return agent

    async def start_im(_agent):
        events.append("im")
        assert snapshots[-1]["chat_ready"] is True
        assert snapshots[-1]["ready"] is True
        assert snapshots[-1]["im_ready"] is False
        if outcome == "error":
            raise RuntimeError("IM offline")
        if outcome != "cancel":
            return ["demo"] if outcome == "ready" else []
        shutdown.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("im-cancelled")

    async def stop_im(**_kwargs):
        if outcome == "cancel":
            assert "im-cancelled" in events

    def update_refs(_, **kwargs):
        snapshots.append(kwargs["readiness"])
        if kwargs["readiness"].get("im_status") in {"error", "ready", "degraded"}:
            shutdown.set()

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(main, "settings", SimpleNamespace(user_workspace_path=tmp_path))
    monkeypatch.setattr(
        main,
        "_message_gateway",
        SimpleNamespace(
            set_shutdown_event=lambda _: None,
            get_failed_adapters=lambda: ["demo"] if outcome == "degraded" else [],
        ),
    )
    monkeypatch.setattr(main, "get_agent", get_agent)
    monkeypatch.setattr(main, "init_core_services", AsyncMock())
    monkeypatch.setattr(main, "start_im_channels", start_im)
    monkeypatch.setattr(main, "stop_im_channels", stop_im)
    monkeypatch.setattr(config, "_restart_requested", False)
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    monkeypatch.setattr(runtime_env, "log_runtime_environment_report", lambda: None)
    monkeypatch.setattr("openkitsune.api.host_resolution.resolve_api_host", lambda **_: "127.0.0.1")
    monkeypatch.setattr(server, "start_api_server", api_start)
    monkeypatch.setattr(server, "update_runtime_refs", update_refs)
    monkeypatch.setattr(
        "openkitsune.llm.client.get_default_client", lambda: SimpleNamespace(close=AsyncMock())
    )
    main.serve(dev=False)
    assert events.index("http") < events.index("agent") < events.index("im")
    agent.initialize.assert_awaited_once_with(defer_optional=True)
    agent.shutdown.assert_awaited_once()
    assert snapshots[-1]["im_status"] == ("starting" if outcome == "cancel" else outcome)
    assert snapshots[-1]["chat_ready"] is True
    assert snapshots[-1]["im_ready"] == (outcome == "ready")


async def test_mcp_connect_serializes_warmup_and_first_tool_request(monkeypatch):
    from openkitsune.tools.mcp import MCPClient, MCPConnectResult

    client = MCPClient()
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0
    maximum = 0

    async def connect(_name):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        entered.set()
        await release.wait()
        active -= 1
        return MCPConnectResult(success=True, tool_count=0)

    monkeypatch.setattr(client, "_connect_runtime", connect)
    first = asyncio.create_task(client.connect("demo"))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(client.connect("demo"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert maximum == 1


@pytest.mark.parametrize("transport", ["stdio", "streamable_http", "sse"])
@pytest.mark.parametrize("sdk_symbols_available", [True, False], ids=["sdk-present", "sdk-absent"])
async def test_mcp_cancelled_transport_cleans_up_and_propagates(
    monkeypatch, transport, sdk_symbols_available
):
    import openkitsune.tools.mcp as mcp

    entered = asyncio.Event()
    cleaned = []

    class Transport:
        async def __aenter__(self):
            entered.set()
            await asyncio.Event().wait()

        async def __aexit__(self, *_args):
            cleaned.append(True)

    client = mcp.MCPClient()
    monkeypatch.setattr(mcp, "MCP_HTTP_AVAILABLE", True)
    monkeypatch.setattr(mcp, "MCP_SSE_AVAILABLE", True)
    # Optional SDK exports may be absent even when other transports are installed.
    # These lifecycle tests provide their own SDK boundary instead of importing it.
    for factory in ("stdio_client", "streamablehttp_client", "sse_client"):
        if not sdk_symbols_available:
            monkeypatch.delattr(mcp, factory, raising=False)
        monkeypatch.setattr(mcp, factory, lambda *_args, **_kwargs: Transport(), raising=False)
    if not sdk_symbols_available:
        monkeypatch.delattr(mcp, "StdioServerParameters", raising=False)
    monkeypatch.setattr(mcp, "StdioServerParameters", SimpleNamespace, raising=False)
    monkeypatch.setattr(client, "_resolve_command", lambda _: "unused")
    monkeypatch.setattr("openkitsune.runtime_manager.build_user_subprocess_environment", lambda _: {})
    monkeypatch.setattr("openkitsune.utils.path_helper.get_macos_enriched_env", lambda env: env)
    config = mcp.MCPServerConfig(
        name="demo", command="unused", url="http://unused", transport=transport
    )
    connect = getattr(client, f"_connect_{transport}")
    task = asyncio.create_task(connect("demo", config))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned == [True]
    assert not client.is_connected("demo")


def test_lazy_package_exports_preserve_public_symbols():
    import openkitsune.agent as agent
    import openkitsune.agents as agents

    for package in (agent, agents):
        for name in package.__all__:
            assert getattr(package, name) is not None, name
