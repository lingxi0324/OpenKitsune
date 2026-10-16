from types import SimpleNamespace

from openkitsune.channels.runtime_status import (
    clear_bot_runtime_state,
    resolve_bot_runtime_state,
    set_bot_runtime_state,
)


def test_dependency_install_state_is_visible_before_gateway_exists() -> None:
    channel = "feishu:installing-test"
    try:
        set_bot_runtime_state(channel, "installing_dependencies")
        assert resolve_bot_runtime_state(channel) == {
            "status": "installing_dependencies",
            "error": None,
        }
    finally:
        clear_bot_runtime_state(channel)


def test_dependency_progress_is_visible_and_cleared_before_adapter_start() -> None:
    channel = "feishu:progress-test"
    try:
        set_bot_runtime_state(
            channel,
            "installing_dependencies",
            progress={"phase": "downloading", "percent": 42.5},
        )
        assert resolve_bot_runtime_state(channel)["progress"] == {
            "phase": "downloading",
            "percent": 42.5,
        }

        set_bot_runtime_state(channel, "starting")
        assert "progress" not in resolve_bot_runtime_state(channel)
    finally:
        clear_bot_runtime_state(channel)


def test_running_adapter_overrides_stale_startup_error() -> None:
    channel = "feishu:online-test"
    adapter = SimpleNamespace(is_running=True, _running=True)
    gateway = SimpleNamespace(
        _adapters={channel: adapter},
        _failed_adapter_reasons={channel: "stale failure"},
    )
    try:
        set_bot_runtime_state(channel, "error", "old import failure")
        assert resolve_bot_runtime_state(channel, gateway) == {
            "status": "online",
            "error": None,
        }
    finally:
        clear_bot_runtime_state(channel)


def test_gateway_failure_is_reported_as_error_not_offline() -> None:
    channel = "feishu:failed-test"
    adapter = SimpleNamespace(is_running=False, _running=False)
    gateway = SimpleNamespace(
        _adapters={channel: adapter},
        _failed_adapter_reasons={channel: "authentication rejected"},
    )

    assert resolve_bot_runtime_state(channel, gateway) == {
        "status": "error",
        "error": "authentication rejected",
    }
