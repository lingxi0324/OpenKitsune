"""Delivery boundary helpers for scheduled task notifications."""

from __future__ import annotations

from typing import Any

from .task import TaskDeliveryPolicy

NON_IM_DELIVERY_CHANNELS = frozenset({"desktop", "api", "cli", "sse", "in-app", "scheduler"})


def is_im_delivery_channel(channel: str | None) -> bool:
    """Return whether a channel name represents an externally deliverable IM target."""

    normalized = (channel or "").strip().lower()
    return bool(normalized) and normalized not in NON_IM_DELIVERY_CHANNELS


def coerce_delivery_policy(
    value: TaskDeliveryPolicy | str | None,
    default: TaskDeliveryPolicy = TaskDeliveryPolicy.OWNER_ONLY,
) -> TaskDeliveryPolicy:
    """Normalize API/storage values into a TaskDeliveryPolicy enum."""

    if isinstance(value, TaskDeliveryPolicy):
        return value
    if value is None:
        return default
    try:
        return TaskDeliveryPolicy(str(value))
    except ValueError:
        return default


def allows_global_im_fallback(task: Any) -> bool:
    """Return whether a task may search known IM sessions outside its owner target."""

    return (
        coerce_delivery_policy(getattr(task, "delivery_policy", None))
        == TaskDeliveryPolicy.FALLBACK_ALLOWED
    )
