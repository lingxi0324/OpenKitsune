"""Shared response contract for operations with runtime propagation."""

from __future__ import annotations

from typing import Any, Protocol


class RuntimeResult(Protocol):
    """Minimal RuntimeApplyResult surface needed by API routes."""

    @property
    def status(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


def runtime_operation_response(
    runtime: RuntimeResult,
    payload: dict[str, Any] | None = None,
    *,
    ok: bool | None = None,
) -> dict[str, Any]:
    """Return a successful operation separately from its runtime apply result.

    Payload fields are preserved, except for the reserved contract fields which
    always reflect the supplied runtime result.
    """
    response = dict(payload or {})
    if ok is not None:
        response["ok"] = ok
    response.update(
        {
            "status": runtime.status,
            "operation_status": "ok",
            "runtime": runtime.to_dict(),
        }
    )
    return response
