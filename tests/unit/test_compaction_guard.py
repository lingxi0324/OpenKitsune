"""CompactionGuard 反抖动状态机测试。

覆盖：初始放行、失败冷却、force 清冷却、无效压缩熔断、恢复探针、
fallback streak 熔断、结构退避、可行性跳过、持久化钩子。
"""

import time
from types import SimpleNamespace

import pytest

from openkitsune.core._compaction_guard import CompactionGuard


def _guard(**overrides) -> CompactionGuard:
    params = dict(
        failure_cooldown_seconds=100.0,
        max_ineffective_strikes=2,
        max_fallback_streak=2,
        recovery_seconds=10.0,
        structural_backoff_seconds=50.0,
        feasibility_skip_fraction=0.25,
    )
    params.update(overrides)
    return CompactionGuard(**params)


# ----------------------------------------------------------------------
# 初始放行
# ----------------------------------------------------------------------


def test_initial_state_should_compress() -> None:
    g = _guard()
    assert g.should_compress() == (True, None)
    assert g.snapshot()["tripped"] is False


# ----------------------------------------------------------------------
# 摘要失败冷却
# ----------------------------------------------------------------------


def test_failure_sets_cooldown() -> None:
    g = _guard(failure_cooldown_seconds=100.0)
    g.record_summary_failure("boom")
    ok, reason = g.should_compress()
    assert ok is False
    assert reason is not None and reason.startswith("cooldown:")


def test_cooldown_expires() -> None:
    g = _guard(failure_cooldown_seconds=1.0)
    g.record_summary_failure("boom")
    assert g.should_compress()[0] is False
    g._summary_failure_cooldown_until = 0.0  # 模拟到期
    assert g.should_compress() == (True, None)


def test_force_clears_cooldown() -> None:
    g = _guard()
    g.record_summary_failure("boom")
    ok, reason = g.should_compress(force=True)
    assert ok is True
    assert reason is None
    assert g._summary_failure_cooldown_until == 0.0


# ----------------------------------------------------------------------
# 无效压缩熔断 + 恢复探针
# ----------------------------------------------------------------------


def test_two_ineffective_trips_breaker() -> None:
    g = _guard(recovery_seconds=10.0)
    g.record_ineffective()
    assert g.should_compress()[0] is True  # 1 次 strike 不熔断
    g.record_ineffective()
    ok, reason = g.should_compress()
    assert ok is False
    assert reason == "ineffective"


def test_recovery_probe_allows_one_attempt_then_retrips() -> None:
    g = _guard(recovery_seconds=5.0)
    g.record_ineffective()
    g.record_ineffective()
    assert g.should_compress()[0] is False  # 熔断窗口内

    # 窗口到期 → 放行一次探针，strike 降为 1
    g._recovery_deadline = time.time() - 1
    ok, reason = g.should_compress()
    assert ok is True
    assert reason is None
    assert g._ineffective_count == 1

    # 探针若再次无效 → 立即重新熔断
    g.record_ineffective()
    assert g.should_compress()[0] is False


def test_recovery_window_is_persistent_across_instances() -> None:
    """熔断恢复窗口用墙钟 + 持久化：重建实例后恢复的是同一窗口而不是重计。"""
    store = SimpleNamespace(_state={})

    def get(key):
        return store._state.get(key)

    def set_(key, value):
        store._state[key] = value

    store.get_compaction_state = get
    store.set_compaction_state = set_

    g1 = _guard(recovery_seconds=10.0)
    g1._store = store
    g1.record_ineffective()
    g1.record_ineffective()
    g1.should_compress()  # 触发熔断（武装恢复窗口）
    deadline = g1._recovery_deadline
    assert deadline > time.time()

    # 模拟重启：新实例从 store 恢复同一 deadline
    g2 = _guard(recovery_seconds=10.0)
    g2._store = store
    g2._load()
    assert abs(g2._recovery_deadline - deadline) < 1e-6
    assert g2.should_compress()[0] is False  # 窗口内仍阻断


# ----------------------------------------------------------------------
# fallback streak 熔断
# ----------------------------------------------------------------------


def test_two_fallbacks_trip_breaker_success_clears() -> None:
    g = _guard()
    g.record_summary_failure("e1", use_fallback=True)
    # 1 次 fallback：不熔断，但冷却生效（fallback 也视为摘要失败）
    ok, reason = g.should_compress()
    assert ok is False
    assert reason is not None and reason.startswith("cooldown:")
    g._summary_failure_cooldown_until = 0.0  # 冷却到期
    assert g.should_compress()[0] is True  # streak=1 未熔断

    g.record_summary_failure("e2", use_fallback=True)
    g._summary_failure_cooldown_until = 0.0
    assert g.should_compress()[0] is False  # 2 次 fallback 熔断

    # 真实 LLM 摘要成功 → 清 streak 与冷却
    g.record_summary_success()
    assert g._fallback_streak == 0
    assert g._summary_failure_cooldown_until == 0.0
    assert g.should_compress()[0] is True


def test_fallback_without_use_flag_does_not_streak() -> None:
    g = _guard()
    g.record_summary_failure("e", use_fallback=False)
    assert g._fallback_streak == 0
    assert g.should_compress()[0] is False  # 冷却阻断


# ----------------------------------------------------------------------
# 结构退避
# ----------------------------------------------------------------------


def test_structural_no_op_backoff() -> None:
    g = _guard(structural_backoff_seconds=50.0)
    g.record_structural_no_op("no_early_groups")
    ok, reason = g.should_compress()
    assert ok is False
    assert reason is not None and reason.startswith("structural_backoff:")
    g._structural_no_op_backoff_until = 0.0
    assert g.should_compress()[0] is True


# ----------------------------------------------------------------------
# 可行性跳过
# ----------------------------------------------------------------------


def test_feasibility_skip_only_after_strike() -> None:
    g = _guard(feasibility_skip_fraction=0.25)
    # 无 strike 不跳过
    assert g.feasibility_skip(100, soft_limit=1000) is False
    g.record_ineffective()
    # 中间区 100 < 1000*0.25=250 → 跳过
    assert g.feasibility_skip(100, soft_limit=1000) is True
    # 中间区足够大 → 不跳过
    assert g.feasibility_skip(300, soft_limit=1000) is False


# ----------------------------------------------------------------------
# 记录接口
# ----------------------------------------------------------------------


def test_effective_clears_strikes() -> None:
    g = _guard()
    g.record_ineffective()
    g.record_effective()
    assert g._ineffective_count == 0


def test_reset_clears_all_state() -> None:
    g = _guard()
    g.record_ineffective()
    g.record_ineffective()
    g.record_summary_failure("e", use_fallback=True)
    g.reset()
    snap = g.snapshot()
    assert snap["ineffective_count"] == 0
    assert snap["fallback_streak"] == 0
    assert snap["tripped"] is False
    assert g.should_compress() == (True, None)
