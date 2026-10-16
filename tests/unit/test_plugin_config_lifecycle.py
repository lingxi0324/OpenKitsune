import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from openkitsune.api.routes import plugins as plugin_routes


@pytest.fixture
def plugin_workspace(tmp_path, monkeypatch):
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    (tmp_path / "data" / "plugins" / "demo").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio
async def test_management_api_migrates_legacy_config_to_plugin_api_data_dir(
    plugin_workspace,
):
    legacy = plugin_workspace / "data" / "plugins" / "demo" / "config.json"
    canonical = plugin_workspace / "data" / "plugin_data" / "demo" / "config.json"
    legacy.write_text(json.dumps({"token": "legacy"}), encoding="utf-8")

    response = await plugin_routes.get_plugin_config("demo")

    assert response == {"ok": True, "data": {"token": "legacy"}}
    assert json.loads(canonical.read_text(encoding="utf-8")) == {"token": "legacy"}
    assert not legacy.exists()
    assert plugin_routes._plugin_config_store("demo").config_path == canonical


@pytest.mark.asyncio
async def test_management_api_updates_canonical_config_with_atomic_writer(
    plugin_workspace, monkeypatch
):
    from openkitsune.plugins import config_store

    canonical = plugin_workspace / "data" / "plugin_data" / "demo" / "config.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(json.dumps({"existing": True}), encoding="utf-8")
    writes = []
    real_atomic_write = config_store.atomic_json_write

    def recording_write(path, data, **kwargs):
        writes.append((path, dict(data)))
        real_atomic_write(path, data, **kwargs)

    monkeypatch.setattr(config_store, "atomic_json_write", recording_write)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=None)))

    response = await plugin_routes.update_plugin_config(
        "demo",
        {"new": "value"},
        request,
    )

    assert writes == [(canonical, {"existing": True, "new": "value"})]
    assert json.loads(canonical.read_text(encoding="utf-8")) == {
        "existing": True,
        "new": "value",
    }
    assert response["status"] == "partial"
    assert response["runtime"]["plugin_config_apply"] == "next_reload"
    assert "plugin_instance" not in response["runtime"]["refreshed"]
    assert response["ok"] is True
    assert response["operation_status"] == "ok"


@pytest.mark.asyncio
async def test_saved_plugin_config_is_not_reported_as_save_failure_when_runtime_apply_fails(
    plugin_workspace, monkeypatch
):
    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    runtime = RuntimeApplyResult(failed={"plugin_config_hook": "hook failed"})
    coordinator = SimpleNamespace(apply_plugin_config=lambda *_args: None)

    async def apply_plugin_config(*_args):
        return runtime

    coordinator.apply_plugin_config = apply_plugin_config
    monkeypatch.setattr(
        "openkitsune.runtime_config_coordinator.get_runtime_config_coordinator",
        lambda _request: coordinator,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=None)))

    response = await plugin_routes.update_plugin_config("demo", {"saved": True}, request)

    assert response["ok"] is True
    assert response["saved"] is True
    assert response["operation_status"] == "ok"
    assert response["status"] == "failed"
    assert response["runtime"]["failed"] == {"plugin_config_hook": "hook failed"}


def test_plugin_api_migrates_legacy_config_before_management_api_is_opened(
    plugin_workspace,
):
    from openkitsune.plugins.api import PluginAPI
    from openkitsune.plugins.config_store import PluginConfigStore
    from openkitsune.plugins.manifest import BASIC_PERMISSIONS, PluginManifest

    plugins_dir = plugin_workspace / "data" / "plugins"
    legacy = plugin_workspace / "data" / "plugins" / "demo" / "config.json"
    canonical_dir = plugin_workspace / "data" / "plugin_data" / "demo"
    legacy.write_text(json.dumps({"startup": "ready"}), encoding="utf-8")
    config_store = PluginConfigStore.for_plugin(plugins_dir, "demo")
    api = PluginAPI(
        plugin_id="demo",
        manifest=PluginManifest(
            id="demo",
            name="Demo",
            version="1.0.0",
            plugin_type="python",
            permissions=list(BASIC_PERMISSIONS),
        ),
        granted_permissions=list(BASIC_PERMISSIONS),
        data_dir=canonical_dir,
        config_store=config_store,
    )

    assert api._config_store is config_store
    assert config_store.config_path == canonical_dir / "config.json"
    assert config_store.legacy_path == legacy
    assert api.get_config() == {"startup": "ready"}
    assert json.loads((canonical_dir / "config.json").read_text(encoding="utf-8")) == {
        "startup": "ready"
    }
    assert not legacy.exists()


def test_plugin_config_updates_serialize_the_complete_read_modify_write(
    plugin_workspace, monkeypatch
):
    from openkitsune.plugins import config_store

    canonical = plugin_workspace / "data" / "plugin_data" / "demo" / "config.json"
    store_a = config_store.PluginConfigStore(canonical)
    store_b = config_store.PluginConfigStore(canonical)
    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    writes: list[dict] = []
    real_atomic_write = config_store.atomic_json_write

    def controlled_write(path, data, **kwargs):
        writes.append(dict(data))
        if len(writes) == 1:
            first_write_entered.set()
            assert release_first_write.wait(timeout=2)
        real_atomic_write(path, data, **kwargs)

    monkeypatch.setattr(config_store, "atomic_json_write", controlled_write)
    first = threading.Thread(target=store_a.update, args=({"first": 1},))
    second = threading.Thread(target=store_b.update, args=({"second": 2},))

    first.start()
    assert first_write_entered.wait(timeout=2)
    second.start()
    assert writes == [{"first": 1}]
    release_first_write.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert json.loads(canonical.read_text(encoding="utf-8")) == {"first": 1, "second": 2}


@pytest.mark.asyncio
async def test_plugin_llm_catalog_is_sanitized_and_reports_saved_selection(plugin_workspace):
    canonical = plugin_workspace / "data" / "plugin_data" / "demo" / "config.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(json.dumps({"llm_endpoint": "primary"}), encoding="utf-8")

    model = SimpleNamespace(
        endpoint="primary",
        model="model-a",
        provider="openai-compatible",
        priority=1,
        local=False,
        healthy=True,
        current=True,
        capabilities=("text",),
        note="",
    )
    llm = SimpleNamespace(list_models=lambda **_kwargs: [model])
    api = SimpleNamespace(get_llm=lambda: llm)
    manager = SimpleNamespace(
        loaded_plugins={"demo": SimpleNamespace(api=api)},
    )
    agent = SimpleNamespace(_plugin_manager=manager)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=agent)))

    response = await plugin_routes.get_plugin_llm_models("demo", request)

    assert response["data"]["selected_endpoint"] == "primary"
    assert response["data"]["models"] == [
        {
            "endpoint": "primary",
            "model": "model-a",
            "provider": "openai-compatible",
            "priority": 1,
            "local": False,
            "healthy": True,
            "current": True,
            "capabilities": ["text"],
            "note": "",
        }
    ]


@pytest.mark.asyncio
async def test_plugin_config_rejects_unknown_llm_endpoint(plugin_workspace):
    llm = SimpleNamespace(
        list_models=lambda **_kwargs: [SimpleNamespace(endpoint="primary")]
    )
    api = SimpleNamespace(get_llm=lambda: llm)
    manager = SimpleNamespace(
        loaded_plugins={"demo": SimpleNamespace(api=api)},
    )
    agent = SimpleNamespace(_plugin_manager=manager)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent=agent)))

    with pytest.raises(HTTPException) as exc_info:
        await plugin_routes.update_plugin_config(
            "demo", {"llm_endpoint": "missing"}, request
        )

    assert getattr(exc_info.value, "status_code", None) == 400
