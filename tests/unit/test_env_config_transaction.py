import os
import threading
from types import SimpleNamespace

import pytest

from openkitsune.utils.env_config import (
    commit_env_config,
    parse_env_content,
    read_env_file,
    update_env_content,
)


def test_parse_env_content_handles_bom_quotes_and_inline_comments(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_bytes(b'\xef\xbb\xbfTOKEN="value with # and \\"quotes\\""\nCOUNT=3 # note\n')

    assert read_env_file(env_path) == {
        "TOKEN": 'value with # and "quotes"',
        "COUNT": "3",
    }
    assert parse_env_content("\ufeffPLAIN=value\n") == {"PLAIN": "value"}


def test_update_env_content_quotes_values_and_requires_explicit_deletion() -> None:
    existing = "# keep\nTOKEN=old\nREMOVE=legacy\n"

    content = update_env_content(
        existing,
        {"TOKEN": 'value with # and "quotes"', "EMPTY": ""},
        delete_keys={"REMOVE"},
    )

    assert content == '# keep\nTOKEN="value with # and \\"quotes\\""\n'
    assert "REMOVE=" not in content
    assert "EMPTY=" not in content


def test_commit_env_config_rolls_back_env_and_process_state_on_runtime_failure(
    tmp_path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("TOKEN=old\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN", "old")

    class _Settings:
        def __init__(self) -> None:
            self.reloads = 0

        def reload(self) -> list[str]:
            self.reloads += 1
            return ["token"]

    settings = _Settings()
    runtime_state = SimpleNamespace(
        save_updates=lambda **_updates: (_ for _ in ()).throw(OSError("state full"))
    )

    with pytest.raises(OSError, match="state full"):
        commit_env_config(
            env_path,
            entries={"TOKEN": "new value #1"},
            settings=settings,
            runtime_state=runtime_state,
            runtime_updates={"persona_name": "jarvis"},
        )

    assert env_path.read_text(encoding="utf-8") == "TOKEN=old\n"
    assert os.environ["TOKEN"] == "old"
    assert settings.reloads == 2


def test_config_handler_uses_shared_quoted_env_writer(tmp_path, monkeypatch) -> None:
    from openkitsune.config import runtime_state, settings
    from openkitsune.tools.handlers.config import ConfigHandler

    load_calls: list[None] = []
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(runtime_state, "_state_file", tmp_path / "data" / "runtime_state.json")
    monkeypatch.setattr(runtime_state, "load", lambda: load_calls.append(None))
    monkeypatch.setattr(type(settings), "reload", lambda _self: ["anthropic_api_key"])

    result = ConfigHandler(agent=None)._set_config(
        {"updates": {"ANTHROPIC_API_KEY": "value with # fragment"}}
    )

    assert result.startswith("✅")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        'ANTHROPIC_API_KEY="value with # fragment"\n'
    )
    assert load_calls == []


def test_endpoint_manager_serializes_env_update_with_generic_config_transaction(tmp_path) -> None:
    from openkitsune.llm.endpoint_manager import EndpointManager
    from openkitsune.utils import atomic_io

    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=kept\n", encoding="utf-8")
    manager = EndpointManager(tmp_path)
    generic_entered = threading.Event()
    release_generic = threading.Event()
    endpoint_finished = threading.Event()

    def write_generic_config() -> None:
        with atomic_io.path_transaction_lock(env_path):
            existing = env_path.read_text(encoding="utf-8")
            generic_entered.set()
            assert release_generic.wait(timeout=5)
            atomic_io.safe_write(
                env_path,
                update_env_content(existing, {"GENERIC_SETTING": "enabled"}),
            )

    def write_endpoint_config() -> None:
        manager.save_endpoint(
            endpoint={
                "name": "primary",
                "provider": "openai",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
            },
            api_key="endpoint-secret",
        )
        endpoint_finished.set()

    generic_thread = threading.Thread(target=write_generic_config)
    endpoint_thread = threading.Thread(target=write_endpoint_config)
    generic_thread.start()
    try:
        assert generic_entered.wait(timeout=5)
        endpoint_thread.start()
        assert not endpoint_finished.wait(timeout=0.2)
        release_generic.set()
        generic_thread.join(timeout=5)
        endpoint_thread.join(timeout=5)
    finally:
        release_generic.set()
        generic_thread.join(timeout=5)
        if endpoint_thread.ident is not None:
            endpoint_thread.join(timeout=5)

    assert not generic_thread.is_alive()
    assert not endpoint_thread.is_alive()
    env = read_env_file(env_path)
    assert env["EXISTING"] == "kept"
    assert env["GENERIC_SETTING"] == "enabled"
    assert "endpoint-secret" in env.values()


def test_settings_recovery_uses_transactional_env_key_deletion(tmp_path, monkeypatch) -> None:
    from openkitsune import config

    env_path = tmp_path / ".env"
    env_path.write_text("# keep\nPOISON=broken\nOTHER=value\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    class _Settings:
        attempts = 0

        def __init__(self) -> None:
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise ValueError('invalid value for field "poison"')

    monkeypatch.setattr(config, "Settings", _Settings)

    recovered = config._create_settings_safe()

    assert isinstance(recovered, _Settings)
    assert env_path.read_text(encoding="utf-8") == "# keep\nOTHER=value\n"
    assert env_path.with_suffix(env_path.suffix + ".bak").exists()
