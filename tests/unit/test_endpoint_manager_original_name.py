from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from openkitsune.llm.client import LLMClient
from openkitsune.llm.endpoint_manager import EndpointManager


def test_separate_managers_do_not_lose_concurrent_endpoint_saves(tmp_path, monkeypatch):
    config_path = tmp_path / "data" / "llm_endpoints.json"
    first_manager = EndpointManager(tmp_path, config_path=config_path)
    second_manager = EndpointManager(tmp_path, config_path=config_path)
    first_before_write = threading.Event()
    second_finished = threading.Event()
    original_write = first_manager._write_json

    def delayed_first_write(data):
        first_before_write.set()
        second_finished.wait(timeout=0.2)
        original_write(data)

    monkeypatch.setattr(first_manager, "_write_json", delayed_first_write)

    def save_first():
        first_manager.save_endpoint(
            {"name": "first", "provider": "openai", "model": "a", "priority": 10}
        )

    def save_second():
        second_manager.save_endpoint(
            {"name": "second", "provider": "openai", "model": "b", "priority": 20}
        )
        second_finished.set()

    first_thread = threading.Thread(target=save_first)
    second_thread = threading.Thread(target=save_second)
    first_thread.start()
    assert first_before_write.wait(timeout=1)
    second_thread.start()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert [endpoint["name"] for endpoint in config["endpoints"]] == ["first", "second"]


def test_llm_client_priority_save_does_not_overwrite_concurrent_endpoint_save(
    tmp_path, monkeypatch
):
    from openkitsune.utils import atomic_io

    config_path = tmp_path / "data" / "llm_endpoints.json"
    manager = EndpointManager(tmp_path, config_path=config_path)
    manager.save_endpoint({"name": "existing", "provider": "openai", "model": "a", "priority": 10})

    client = LLMClient.__new__(LLMClient)
    client._config_path = config_path
    client._endpoints = [SimpleNamespace(name="existing", priority=30)]
    client_has_read = threading.Event()
    manager_finished = threading.Event()
    original_read = atomic_io.read_json_safe

    def delayed_client_read(path):
        data = original_read(path)
        client_has_read.set()
        manager_finished.wait(timeout=0.2)
        return data

    monkeypatch.setattr(atomic_io, "read_json_safe", delayed_client_read)

    def save_new_endpoint():
        manager.save_endpoint({"name": "new", "provider": "openai", "model": "b", "priority": 20})
        manager_finished.set()

    client_thread = threading.Thread(target=client._save_config)
    manager_thread = threading.Thread(target=save_new_endpoint)
    client_thread.start()
    assert client_has_read.wait(timeout=1)
    manager_thread.start()
    client_thread.join(timeout=2)
    manager_thread.join(timeout=2)

    assert not client_thread.is_alive()
    assert not manager_thread.is_alive()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert [endpoint["name"] for endpoint in config["endpoints"]] == ["new", "existing"]
    assert next(ep for ep in config["endpoints"] if ep["name"] == "existing")["priority"] == 30


def test_save_endpoint_can_rename_without_deleting_key(tmp_path):
    manager = EndpointManager(tmp_path, config_path=tmp_path / "data" / "llm_endpoints.json")
    saved = manager.save_endpoint(
        {
            "name": "old",
            "provider": "openai",
            "api_type": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o",
            "priority": 10,
        },
        api_key="sk-original",
    )

    renamed = manager.save_endpoint(
        {
            "name": "new",
            "provider": "openai",
            "api_type": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o-mini",
            "priority": 10,
        },
        original_name="old",
    )

    config = json.loads((tmp_path / "data" / "llm_endpoints.json").read_text(encoding="utf-8"))
    endpoints = config["endpoints"]

    assert [ep["name"] for ep in endpoints] == ["new"]
    assert renamed["api_key_env"] == saved["api_key_env"]
    assert f"{saved['api_key_env']}=sk-original" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_save_endpoint_rename_rejects_existing_name(tmp_path):
    manager = EndpointManager(tmp_path, config_path=tmp_path / "data" / "llm_endpoints.json")
    manager.save_endpoint({"name": "old", "provider": "openai", "model": "a", "priority": 10})
    manager.save_endpoint({"name": "taken", "provider": "openai", "model": "b", "priority": 20})

    with pytest.raises(ValueError, match="already exists"):
        manager.save_endpoint(
            {"name": "taken", "provider": "openai", "model": "c", "priority": 10},
            original_name="old",
        )


def test_save_endpoints_batch_shares_one_api_key_env(tmp_path):
    manager = EndpointManager(tmp_path, config_path=tmp_path / "data" / "llm_endpoints.json")

    saved = manager.save_endpoints(
        [
            {"name": "openai-gpt-4o", "provider": "openai", "model": "gpt-4o", "priority": 10},
            {
                "name": "openai-gpt-4o-mini",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "priority": 20,
            },
        ],
        api_key="sk-batch",
    )

    config = json.loads((tmp_path / "data" / "llm_endpoints.json").read_text(encoding="utf-8"))
    endpoints = config["endpoints"]

    assert [ep["name"] for ep in endpoints] == ["openai-gpt-4o", "openai-gpt-4o-mini"]
    assert len({ep["api_key_env"] for ep in saved}) == 1
    assert len({ep["api_key_env"] for ep in endpoints}) == 1
    assert "OPENAI_API_KEY=sk-batch" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_delete_endpoints_removes_batch_and_cleans_unused_shared_key(tmp_path):
    manager = EndpointManager(tmp_path, config_path=tmp_path / "data" / "llm_endpoints.json")
    manager.save_endpoints(
        [
            {"name": "openai-a", "provider": "openai", "model": "a", "priority": 10},
            {"name": "openai-b", "provider": "openai", "model": "b", "priority": 20},
        ],
        api_key="sk-batch",
    )

    removed = manager.delete_endpoints(["openai-a", "openai-b"])

    config = json.loads((tmp_path / "data" / "llm_endpoints.json").read_text(encoding="utf-8"))
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert [ep["name"] for ep in removed] == ["openai-a", "openai-b"]
    assert config["endpoints"] == []
    assert "OPENAI_API_KEY=" not in env_text


def test_delete_endpoints_keeps_key_when_other_endpoint_still_uses_it(tmp_path):
    manager = EndpointManager(tmp_path, config_path=tmp_path / "data" / "llm_endpoints.json")
    manager.save_endpoints(
        [
            {"name": "openai-a", "provider": "openai", "model": "a", "priority": 10},
            {"name": "openai-b", "provider": "openai", "model": "b", "priority": 20},
        ],
        api_key="sk-batch",
    )

    removed = manager.delete_endpoints(["openai-a"])

    config = json.loads((tmp_path / "data" / "llm_endpoints.json").read_text(encoding="utf-8"))
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert [ep["name"] for ep in removed] == ["openai-a"]
    assert [ep["name"] for ep in config["endpoints"]] == ["openai-b"]
    assert "OPENAI_API_KEY=sk-batch" in env_text
