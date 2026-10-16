from types import SimpleNamespace

import pytest

from openkitsune.api.routes import mcp as mcp_routes


def _request_with_mcp(client, catalog=None):
    agent = SimpleNamespace(mcp_client=client, mcp_catalog=catalog)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=agent)))


@pytest.mark.asyncio
async def test_toggle_does_not_change_memory_when_metadata_write_fails(tmp_path, monkeypatch):
    config_dir = tmp_path / "server"
    config_dir.mkdir()
    server = SimpleNamespace(enabled=True, config_dir=config_dir)

    class _Catalog:
        invalidated = False

        def get_server(self, _name):
            return server

        def invalidate_cache(self):
            self.invalidated = True

    catalog = _Catalog()
    client = SimpleNamespace(is_connected=lambda _name: False)
    agent = SimpleNamespace(mcp_client=client, mcp_catalog=catalog)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=agent)))

    from openkitsune.utils import atomic_io

    monkeypatch.setattr(
        atomic_io,
        "atomic_json_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = await mcp_routes.toggle_mcp_server(
        request,
        "demo",
        mcp_routes.MCPToggleRequest(enabled=False),
    )

    assert result["status"] == "error"
    assert server.enabled is True
    assert catalog.invalidated is False


@pytest.mark.asyncio
async def test_toggle_preserves_operation_status_when_runtime_refresh_fails(tmp_path, monkeypatch):
    config_dir = tmp_path / "server"
    config_dir.mkdir()
    server = SimpleNamespace(enabled=True, config_dir=config_dir)

    class _Catalog:
        def get_server(self, _name):
            return server

        def invalidate_cache(self):
            return None

    catalog = _Catalog()
    client = SimpleNamespace(is_connected=lambda _name: False)
    agent = SimpleNamespace(mcp_client=client, mcp_catalog=catalog)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=agent)))

    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    runtime = RuntimeApplyResult(failed={"agent_pool": "refresh failed"})
    coordinator = SimpleNamespace(mcp_changed=lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        "openkitsune.runtime_config_coordinator.get_runtime_config_coordinator",
        lambda _request: coordinator,
    )

    result = await mcp_routes.toggle_mcp_server(
        request,
        "demo",
        mcp_routes.MCPToggleRequest(enabled=False),
    )

    assert result["status"] == "failed"
    assert result["operation_status"] == "ok"
    assert result["runtime"]["status"] == "failed"
    assert server.enabled is False


@pytest.mark.asyncio
async def test_connect_separates_operation_connection_and_runtime_status(monkeypatch):
    class _Client:
        def list_connected(self):
            return []

        def list_servers(self):
            return ["demo"]

        def list_tools(self, _server_name):
            return [SimpleNamespace(name="search", description="Search")]

        async def connect(self, _server_name):
            return SimpleNamespace(success=True, tool_count=1, error=None)

    async def _prepare(*_args):
        return None

    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    runtime = RuntimeApplyResult(failed={"agent_pool": "refresh failed"})
    coordinator = SimpleNamespace(mcp_changed=lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        "openkitsune.tools.mcp_workspace.prepare_chrome_devtools_args",
        _prepare,
    )
    monkeypatch.setattr(
        "openkitsune.runtime_config_coordinator.get_runtime_config_coordinator",
        lambda _request: coordinator,
    )

    result = await mcp_routes.connect_mcp_server(
        _request_with_mcp(_Client()),
        mcp_routes.MCPConnectRequest(server_name="demo"),
    )

    assert result["operation_status"] == "ok"
    assert result["connection_status"] == "connected"
    assert result["status"] == "failed"
    assert result["runtime"]["failed"] == {"agent_pool": "refresh failed"}


@pytest.mark.asyncio
async def test_disconnect_separates_operation_connection_and_runtime_status(monkeypatch):
    class _Client:
        def list_connected(self):
            return ["demo"]

        async def disconnect(self, _server_name):
            return None

    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    runtime = RuntimeApplyResult(warnings=["pool refresh deferred"])
    runtime_changes: list[tuple[str, str]] = []

    def _mcp_changed(server_name, reason):
        runtime_changes.append((server_name, reason))
        return runtime

    coordinator = SimpleNamespace(mcp_changed=_mcp_changed)
    monkeypatch.setattr(
        "openkitsune.runtime_config_coordinator.get_runtime_config_coordinator",
        lambda _request: coordinator,
    )

    result = await mcp_routes.disconnect_mcp_server(
        _request_with_mcp(_Client()),
        mcp_routes.MCPConnectRequest(server_name="demo"),
    )

    assert result["operation_status"] == "ok"
    assert result["connection_status"] == "disconnected"
    assert result["status"] == "partial"
    assert result["runtime"]["warnings"] == ["pool refresh deferred"]
    assert runtime_changes == [("demo", "disconnected")]


@pytest.mark.asyncio
async def test_already_connected_uses_unified_operation_contract():
    class _Client:
        def list_connected(self):
            return ["demo"]

        def list_tools(self, _server_name):
            return []

    result = await mcp_routes.connect_mcp_server(
        _request_with_mcp(_Client()),
        mcp_routes.MCPConnectRequest(server_name="demo"),
    )

    assert result["status"] == "ok"
    assert result["operation_status"] == "ok"
    assert result["connection_status"] == "already_connected"


@pytest.mark.asyncio
async def test_reset_invalidates_classifier_once(monkeypatch):
    from openkitsune.tools.mcp import MCPClient

    client = MCPClient()
    client._connections = {"one": {}, "two": {}}
    disconnected: list[str] = []
    invalidations: list[None] = []

    async def _disconnect_runtime(name):
        disconnected.append(name)
        client._connections.pop(name)
        return True

    monkeypatch.setattr(client, "_disconnect_runtime", _disconnect_runtime)
    monkeypatch.setattr(
        client,
        "_invalidate_policy_classifier_cache",
        lambda: invalidations.append(None),
    )

    await client.reset()

    assert disconnected == ["one", "two"]
    assert invalidations == [None]


@pytest.mark.asyncio
async def test_connect_invalidates_classifier_only_for_new_connection(monkeypatch):
    from openkitsune.tools.mcp import MCPClient

    client = MCPClient()
    invalidations: list[None] = []

    async def _connect_runtime(_name):
        return SimpleNamespace(success=True)

    monkeypatch.setattr(client, "_connect_runtime", _connect_runtime)
    monkeypatch.setattr(
        client,
        "_invalidate_policy_classifier_cache",
        lambda: invalidations.append(None),
    )

    await client.connect("demo")
    client._connections["demo"] = {}
    await client.connect("demo")

    assert invalidations == [None]


def test_remove_server_invalidates_only_when_runtime_entries_exist(monkeypatch):
    from openkitsune.tools.mcp import MCPClient, MCPServerConfig, MCPTool

    client = MCPClient()
    client.add_server(MCPServerConfig(name="demo"))
    client._tools["demo:search"] = MCPTool(name="search", description="", input_schema={})
    invalidations: list[None] = []
    monkeypatch.setattr(
        client,
        "_invalidate_policy_classifier_cache",
        lambda: invalidations.append(None),
    )

    client.remove_server("demo")
    client.remove_server("demo")

    assert invalidations == [None]
