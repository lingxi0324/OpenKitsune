"""Fix-12 回归测试：CircuitBreaker + desktop channel no-op 提示。"""

from __future__ import annotations

import logging
import time

import pytest

from openkitsune.channels._circuit_breaker import CircuitBreaker


# ---------------------------------------------------------------------------
# CircuitBreaker basic behaviour
# ---------------------------------------------------------------------------


def test_breaker_init_validates_args():
    with pytest.raises(ValueError):
        CircuitBreaker(threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_seconds=0)


def test_breaker_starts_closed():
    cb = CircuitBreaker()
    assert cb.is_open("user-1") is False


def test_breaker_opens_after_threshold():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=60)
    assert cb.record_failure("user-1") is False  # 1
    assert cb.record_failure("user-1") is False  # 2
    assert cb.record_failure("user-1") is True  # 3 — tripped
    assert cb.is_open("user-1") is True


def test_breaker_isolation_per_key():
    cb = CircuitBreaker(threshold=2, cooldown_seconds=60)
    cb.record_failure("user-1")
    cb.record_failure("user-1")
    assert cb.is_open("user-1") is True
    assert cb.is_open("user-2") is False


def test_breaker_success_resets_counter():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=60)
    cb.record_failure("user-1")
    cb.record_failure("user-1")
    cb.record_success("user-1")
    cb.record_failure("user-1")
    cb.record_failure("user-1")
    assert cb.is_open("user-1") is False  # only 2 failures since last success


def test_breaker_only_trips_once_in_cooldown():
    cb = CircuitBreaker(threshold=2, cooldown_seconds=60)
    cb.record_failure("user-1")
    assert cb.record_failure("user-1") is True
    # Subsequent failures while open should not re-trip (return False).
    assert cb.record_failure("user-1") is False
    assert cb.record_failure("user-1") is False


def test_breaker_auto_recovers_after_cooldown(monkeypatch):
    cb = CircuitBreaker(threshold=2, cooldown_seconds=0.01)
    cb.record_failure("user-1")
    cb.record_failure("user-1")
    assert cb.is_open("user-1") is True
    time.sleep(0.05)
    assert cb.is_open("user-1") is False
    assert cb.record_failure("user-1") is False  # counter reset


def test_breaker_remaining_cooldown_decreases():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=60)
    cb.record_failure("user-1")
    rem1 = cb.remaining_cooldown("user-1")
    assert 0 < rem1 <= 60
    time.sleep(0.05)
    rem2 = cb.remaining_cooldown("user-1")
    assert rem2 < rem1


def test_breaker_reset_specific_key():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=60)
    cb.record_failure("user-1")
    cb.record_failure("user-2")
    cb.reset("user-1")
    assert cb.is_open("user-1") is False
    assert cb.is_open("user-2") is True


def test_breaker_reset_all():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=60)
    cb.record_failure("user-1")
    cb.record_failure("user-2")
    cb.reset()
    assert cb.snapshot() == {}


def test_breaker_snapshot_format():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=60)
    cb.record_failure("user-1")
    snap = cb.snapshot()
    assert "user-1" in snap
    assert snap["user-1"]["consecutive_failures"] == 1


# ---------------------------------------------------------------------------
# Gateway noop-channel detection (Fix-12 part 2)
# ---------------------------------------------------------------------------


def test_noop_channels_constant_includes_known_in_app():
    from openkitsune.channels.gateway import _NOOP_CHANNELS

    assert "desktop" in _NOOP_CHANNELS
    assert "api" in _NOOP_CHANNELS
    assert "cli" in _NOOP_CHANNELS
    # IM adapters should NOT be in this set
    assert "feishu" not in _NOOP_CHANNELS
    assert "telegram" not in _NOOP_CHANNELS
    assert "dingtalk" not in _NOOP_CHANNELS
