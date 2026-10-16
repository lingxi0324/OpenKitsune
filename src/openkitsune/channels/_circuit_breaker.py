"""In-process per-key circuit breaker for IM adapters (Fix-12).

Used to short-circuit messaging attempts when a remote endpoint repeatedly
fails for a specific recipient.  Goals:

- Prevent log floods (e.g. DingTalk webhook expired for one user causing 30
  retries per minute for hours).
- Prevent the agent from queueing additional work that will obviously fail.
- Recover automatically once the cool-down window passes.

Design constraints (intentionally narrow):

- Only counts **consecutive** failures; a single success resets the counter.
- The cool-down is short enough that transient outages self-heal, long
  enough to actually reduce noise (default 1h).
- Keeps state in memory only — restarts clear it.
- No global side effects: each adapter instantiates its own breaker.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _State:
    consecutive_failures: int = 0
    open_until: float = 0.0


class CircuitBreaker:
    """Thin per-key circuit breaker.

    Args:
        threshold: number of consecutive failures before opening the circuit.
        cooldown_seconds: time the circuit stays open after threshold trip.
    """

    def __init__(self, *, threshold: int = 3, cooldown_seconds: float = 3600.0) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def is_open(self, key: str) -> bool:
        """Return True when the circuit for ``key`` is currently open."""
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return False
            if state.open_until <= time.time():
                if state.open_until:
                    state.open_until = 0.0
                    state.consecutive_failures = 0
                return False
            return True

    def record_success(self, key: str) -> None:
        with self._lock:
            state = self._states.get(key)
            if state is not None:
                state.consecutive_failures = 0
                state.open_until = 0.0

    def record_failure(self, key: str) -> bool:
        """Record a failure for ``key``. Returns True when the circuit just
        transitioned to OPEN as a result of this failure (caller can use
        the return value to emit a one-shot warning instead of one per fail).
        """
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.consecutive_failures += 1
            if state.consecutive_failures >= self._threshold and state.open_until == 0.0:
                state.open_until = time.time() + self._cooldown
                return True
            return False

    def remaining_cooldown(self, key: str) -> float:
        with self._lock:
            state = self._states.get(key)
            if state is None or state.open_until == 0.0:
                return 0.0
            remaining = state.open_until - time.time()
            return max(0.0, remaining)

    def reset(self, key: str | None = None) -> None:
        """Clear state for one key (or all when ``key`` is None)."""
        with self._lock:
            if key is None:
                self._states.clear()
            else:
                self._states.pop(key, None)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Best-effort snapshot for observability/tests."""
        with self._lock:
            return {
                k: {
                    "consecutive_failures": v.consecutive_failures,
                    "open_until": v.open_until,
                }
                for k, v in self._states.items()
            }
