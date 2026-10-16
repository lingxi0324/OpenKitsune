"""Shared runtime status registry for configured IM bots."""

from __future__ import annotations

from typing import Any

_states: dict[str, str] = {}
_errors: dict[str, str] = {}
_progress: dict[str, dict[str, Any]] = {}


def set_bot_runtime_state(
    channel: str,
    status: str,
    error: str | None = None,
    progress: dict[str, Any] | None = None,
) -> None:
    _states[channel] = status
    if error:
        _errors[channel] = error
    elif status != "error":
        _errors.pop(channel, None)
    if status == "installing_dependencies" and progress is not None:
        _progress[channel] = dict(progress)
    elif status != "installing_dependencies":
        _progress.pop(channel, None)


def clear_bot_runtime_state(channel: str) -> None:
    _states.pop(channel, None)
    _errors.pop(channel, None)
    _progress.pop(channel, None)


def resolve_bot_runtime_state(channel: str, gateway: Any | None = None) -> dict[str, str | None]:
    """Resolve adapter health, startup transitions, and errors in one place."""
    adapter = None
    if gateway is not None:
        adapters = getattr(gateway, "_adapters", {}) or {}
        if isinstance(adapters, dict):
            adapter = adapters.get(channel)
        if adapter is not None and (
            getattr(adapter, "is_running", False) or getattr(adapter, "_running", False)
        ):
            return {"status": "online", "error": None}

        failed_reasons = getattr(gateway, "_failed_adapter_reasons", {}) or {}
        if channel in failed_reasons:
            return {"status": "error", "error": str(failed_reasons[channel])}

    status = _states.get(channel)
    error = _errors.get(channel)
    if error:
        return {"status": "error", "error": error}
    if status in {"installing_dependencies", "starting"}:
        result: dict[str, Any] = {"status": status, "error": None}
        if status == "installing_dependencies" and channel in _progress:
            result["progress"] = dict(_progress[channel])
        return result
    if adapter is not None:
        return {"status": "offline", "error": None}
    return {"status": status or "unknown", "error": None}
