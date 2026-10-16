"""Shared safety rules for built-in plugins consuming the Plugin LLM facade."""

from __future__ import annotations

from typing import Any


def _require_llm(api: Any) -> Any:
    getter = getattr(api, "get_llm", None)
    llm = getter() if callable(getter) else None
    if llm is None:
        raise RuntimeError("plugin_llm_unavailable: OpenKitsune text model is unavailable")
    return llm


def llm_selection_kwargs(endpoint: str | None) -> dict[str, str]:
    """Map one plugin setting to the fixed inherit/require selection contract."""
    endpoint_name = str(endpoint or "").strip()
    if endpoint_name:
        return {"endpoint": endpoint_name, "policy": "require"}
    return {"policy": "inherit"}


def _public_model(model: Any) -> dict[str, Any]:
    return {
        "endpoint": str(getattr(model, "endpoint", "") or ""),
        "model": str(getattr(model, "model", "") or ""),
        "provider": str(getattr(model, "provider", "") or ""),
        "priority": int(getattr(model, "priority", 0) or 0),
        "local": bool(getattr(model, "local", False)),
        "healthy": bool(getattr(model, "healthy", False)),
        "current": bool(getattr(model, "current", False)),
        "capabilities": list(getattr(model, "capabilities", ()) or ()),
        "note": str(getattr(model, "note", "") or ""),
    }


def llm_catalog_payload(api: Any, *, selected_endpoint: str = "") -> dict[str, Any]:
    """Return the standard sanitized model catalog response for plugin routes."""
    try:
        llm = _require_llm(api)
        models = [_public_model(model) for model in llm.list_models(capabilities=["text"])]
    except Exception:
        return {
            "available": False,
            "reason": "plugin_llm_unavailable",
            "selected_endpoint": str(selected_endpoint or "").strip(),
            "models": [],
        }
    return {
        "available": True,
        "selected_endpoint": str(selected_endpoint or "").strip(),
        "models": models,
    }


def validate_llm_endpoint(api: Any, endpoint: str | None) -> str:
    """Validate a saved endpoint against the current sanitized host catalog."""
    endpoint_name = str(endpoint or "").strip()
    if not endpoint_name:
        return ""
    llm = _require_llm(api)
    configured = {str(model.endpoint) for model in llm.list_models(capabilities=["text"])}
    if endpoint_name not in configured:
        raise ValueError(
            f"plugin_llm_endpoint_unavailable: endpoint {endpoint_name!r} is not configured"
        )
    return endpoint_name


async def complete_text(api: Any, *, endpoint: str | None = None, **kwargs: Any) -> Any:
    """Run one text completion through the strict built-in plugin contract."""
    llm = _require_llm(api)
    return await llm.complete(**kwargs, **llm_selection_kwargs(endpoint))


__all__ = [
    "complete_text",
    "llm_catalog_payload",
    "llm_selection_kwargs",
    "validate_llm_endpoint",
]
