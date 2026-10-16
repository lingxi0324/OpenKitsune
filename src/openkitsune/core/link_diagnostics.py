"""Bounded runtime diagnostics, keyed by conversation rather than by agent."""

from datetime import UTC, datetime
from typing import Any


def record_link_diagnostic(state: Any, source: dict, conversation_id: str) -> dict:
    diagnostic = {
        **source,
        "conversation_id": conversation_id,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    records = getattr(state, "link_diagnostics", None)
    if not isinstance(records, dict):
        records = {}
        state.link_diagnostics = records
    records.pop(conversation_id, None)
    records[conversation_id] = diagnostic
    while len(records) > 200:
        records.pop(next(iter(records)))
    state.last_link_diagnostic = diagnostic
    return diagnostic
