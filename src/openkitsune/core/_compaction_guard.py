"""Compaction guard — 上下文压缩的反抖动守卫。

对标 Hermes ``agent/context_compressor.py`` 的反抖动闭环，为 OpenKitsune 的
``compress_if_needed`` 提供有状态门禁，防止两类系统性失败：

- **防重复（thrash）**：摘要失败后立刻重试、不可压缩场景每轮重复压缩、
  fallback 摘要连续触发 → 无限 LLM 成本与对话膨胀；
- **防残缺（deadlock）**：熔断若为永久性，则会话永远不再压缩，最终撞上
  provider 硬限制被拒 —— 因此熔断必须是有界探针（恢复窗口到期放行一次，
  再无效则重新熔断），最坏情况是每个恢复窗口一次压缩尝试。

状态默认进程内；当调用方提供 ``store``（具备 ``get_compression_state`` /
``set_compression_state`` **或** ``get_meta`` / ``set_meta`` 的持久化对象）时，
冷却/熔断计数跨进程与跨重启保留，避免网关每轮重建 ContextManager 后熔断
形同虚设。

与 Hermes 的对应关系（用于评审对照）：
- ``summary_failure_cooldown``  ↔ ``_summary_failure_cooldown_until``
- ``ineffective_count``          ↔ ``_ineffective_compression_count``（2 strikes 熔断）
- ``fallback_streak``            ↔ ``_fallback_compression_streak``（2 次熔断）
- ``recovery_deadline``          ↔ ``_anti_thrash_recovery_deadline``（持久化墙钟）
- ``structural_no_op_backoff``   ↔ ``_structural_no_op_backoff_until``
- ``feasibility_skip``           ↔ ``_feasibility_skip``（有 strike 时中间区过小跳过 LLM）
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 默认参数（可被 config.py 覆盖，见 Settings.context_compaction_*）
_DEFAULT_FAILURE_COOLDOWN_SECONDS = 600.0   # 摘要失败后冷却：避免每轮重试
_DEFAULT_MAX_INEFFECTIVE_STRIKES = 2        # 无效压缩连续次数 → 熔断
_DEFAULT_MAX_FALLBACK_STREAK = 2            # fallback 摘要连续次数 → 熔断
_DEFAULT_RECOVERY_SECONDS = 3600.0          # 熔断后恢复窗口（到期放行一次探针）
_DEFAULT_STRUCTURAL_BACKOFF_SECONDS = 300.0 # 结构性 no-op 后的短退避
_DEFAULT_FEASIBILITY_SKIP_FRACTION = 0.25   # 中间区 < soft_limit×此比例 → 跳过 LLM


class CompactionGuard:
    """进程内（可选持久化）的压缩反抖动状态机。

    非线程安全的普通对象；由 ContextManager 单实例持有。所有时间戳使用
    wall-clock（``time.time``）以兼容持久化恢复（与 Hermes #100185 一致：
    持久化的恢复截止必须用墙钟而非 monotonic，否则跨进程恢复会重启窗口）。

    持久化：当 ``store`` 参数传入具备 ``get_compression_state`` /
    ``set_compression_state`` 的对象（如 ``UnifiedStore``）时，冷却/熔断
    计数跨进程与跨重启保留，避免网关每轮重建 ContextManager 后熔断形同
    虚设。

    与 Hermes 的对应关系（用于评审对照）：
    - ``summary_failure_cooldown``  ↔ ``_summary_failure_cooldown_until``
    - ``ineffective_count``          ↔ ``_ineffective_compression_count``（2 strikes 熔断）
    - ``fallback_streak``            ↔ ``_fallback_compression_streak``（2 次熔断）
    - ``recovery_deadline``          ↔ ``_anti_thrash_recovery_deadline``（持久化墙钟）
    - ``structural_no_op_backoff``   ↔ ``_structural_no_op_backoff_until``
    - ``feasibility_skip``           ↔ ``_feasibility_skip``（有 strike 时中间区过小跳过 LLM）
    """

    def __init__(
        self,
        *,
        failure_cooldown_seconds: float = _DEFAULT_FAILURE_COOLDOWN_SECONDS,
        max_ineffective_strikes: int = _DEFAULT_MAX_INEFFECTIVE_STRIKES,
        max_fallback_streak: int = _DEFAULT_MAX_FALLBACK_STREAK,
        recovery_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        structural_backoff_seconds: float = _DEFAULT_STRUCTURAL_BACKOFF_SECONDS,
        feasibility_skip_fraction: float = _DEFAULT_FEASIBILITY_SKIP_FRACTION,
        store: Any | None = None,
        state_key: str = "compaction_guard",
    ) -> None:
        self.failure_cooldown_seconds = max(1.0, float(failure_cooldown_seconds))
        self.max_ineffective_strikes = max(1, int(max_ineffective_strikes))
        self.max_fallback_streak = max(1, int(max_fallback_streak))
        self.recovery_seconds = max(1.0, float(recovery_seconds))
        self.structural_backoff_seconds = max(0.0, float(structural_backoff_seconds))
        self.feasibility_skip_fraction = min(
            1.0, max(0.05, float(feasibility_skip_fraction))
        )
        self._store = store
        self._state_key = state_key
        # 进程内状态；存在 store 时由 load() 覆盖
        self._summary_failure_cooldown_until = 0.0
        self._ineffective_count = 0
        self._fallback_streak = 0
        self._recovery_deadline = 0.0
        self._structural_no_op_backoff_until = 0.0
        self._last_failure_error: str = ""
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从 store 加载状态。对标 Hermes 的 _read_ctx 加载 cooldown/lock/lineage。

        支持两种持久化接口：
        1. 原生：get_compaction_state / set_compaction_state
        2. 通用：get_meta / set_meta（UnifiedStore）
        """
        if self._store is None:
            return
        loader = getattr(self._store, "get_compaction_state", None)
        if not callable(loader):
            loader = getattr(self._store, "get_meta", None)
        if not callable(loader):
            return
        try:
            raw = loader(self._state_key)
            state = raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning("[CompactionGuard] state load failed: %s", exc)
            return
        now = time.time()
        self._summary_failure_cooldown_until = float(
            state.get("summary_failure_cooldown_until") or 0.0
        )
        self._ineffective_count = max(0, int(state.get("ineffective_count") or 0))
        self._fallback_streak = max(0, int(state.get("fallback_streak") or 0))
        # 熔断恢复窗口：只接受未来的 deadline（过去/零值视为未武装，重新计时）
        deadline = float(state.get("recovery_deadline") or 0.0)
        self._recovery_deadline = deadline if deadline > now else 0.0
        self._last_failure_error = str(state.get("last_failure_error") or "")

    def _persist(self) -> None:
        if self._store is None:
            return
        setter = getattr(self._store, "set_compaction_state", None)
        if not callable(setter):
            setter = getattr(self._store, "set_meta", None)
        if not callable(setter):
            return
        try:
            setter(
                self._state_key,
                {
                    "summary_failure_cooldown_until": self._summary_failure_cooldown_until,
                    "ineffective_count": self._ineffective_count,
                    "fallback_streak": self._fallback_streak,
                    "recovery_deadline": self._recovery_deadline,
                    "last_failure_error": self._last_failure_error[:500],
                },
            )
        except Exception as exc:
            logger.warning("[CompactionGuard] state persist failed: %s", exc)

    # ------------------------------------------------------------------
    # 门禁查询
    # ------------------------------------------------------------------

    def should_compress(self, *, force: bool = False) -> tuple[bool, str | None]:
        """返回 ``(should_compress, block_reason)``。

        ``force=True``（手动压缩）清除摘要失败冷却并绕过熔断 —— 与 Hermes 的
        ``/compress`` 语义一致：显式用户请求始终可以尝试完整压缩。

        block_reason 取值：``"cooldown:<s>"``、``"structural_backoff:<s>"``、
        ``"ineffective"``（熔断未到恢复窗口）、``None``（放行）。
        """
        if force:
            # 手动压缩：清除冷却与熔断 strike，恢复窗口同时复位
            if self._summary_failure_cooldown_until > 0.0:
                self._summary_failure_cooldown_until = 0.0
                self._last_failure_error = ""
                self._persist()
            return True, None
        now = time.time()
        # 1) 摘要失败冷却
        if now < self._summary_failure_cooldown_until:
            remaining = int(self._summary_failure_cooldown_until - now)
            return False, f"cooldown:{remaining}"
        # 2) 结构性 no-op 短退避
        if now < self._structural_no_op_backoff_until:
            remaining = int(self._structural_no_op_backoff_until - now)
            return False, f"structural_backoff:{remaining}"
        # 3) 熔断（无效压缩 / fallback 连续）—— 有界探针：恢复窗口到期放行一次
        if self._tripped():
            if self._maybe_arm_recovery_probe():
                return True, None
            return False, "ineffective"
        # 4) 未熔断：解除任何已武装的恢复窗口（避免残留 deadline 干扰后续判定）
        if self._recovery_deadline > 0.0:
            self._recovery_deadline = 0.0
            self._persist()
        return True, None

    def _tripped(self) -> bool:
        return (
            self._ineffective_count >= self.max_ineffective_strikes
            or self._fallback_streak >= self.max_fallback_streak
        )

    def block_reason(self) -> str | None:
        """只读版本的阻断原因（不触发恢复窗口计时），供日志/遥测。"""
        if not self._tripped():
            return None
        return (
            "cooldown"
            if time.time() < self._summary_failure_cooldown_until
            else "ineffective"
        )

    # ------------------------------------------------------------------
    # 恢复探针（有界熔断的核心）
    # ------------------------------------------------------------------

    def _maybe_arm_recovery_probe(self) -> bool:
        """熔断后管理恢复窗口；到期放行一次探针并将 strike 降为 1。

        返回 True 表示应放行这次压缩（探针），False 表示仍处于熔断窗口。
        与 Hermes 一致：恢复窗口用墙钟并持久化 —— 网关每轮重建
        ContextManager 后，恢复的是同一个窗口而不是重新计时。
        """
        now = time.time()
        if self._recovery_deadline <= 0.0 or (
            self._recovery_deadline - now > self.recovery_seconds
        ):
            # 未武装或时钟回退：从此刻起武装一个完整窗口
            self._recovery_deadline = now + self.recovery_seconds
            self._persist()
            return False
        if now >= self._recovery_deadline:
            # 窗口到期：放行一次探针，strike 降到 1（若探针再次无效则立即重新熔断）
            self._recovery_deadline = 0.0
            if self._ineffective_count >= self.max_ineffective_strikes:
                self._ineffective_count = 1
            if self._fallback_streak >= self.max_fallback_streak:
                self._fallback_streak = 1
            logger.info(
                "[CompactionGuard] recovery window elapsed — allowing one probe "
                "(ineffective=%d fallback=%d)",
                self._ineffective_count,
                self._fallback_streak,
            )
            self._persist()
            return True
        return False

    def evaluation_is_probe(self) -> bool:
        """当前是否处于恢复探针窗口内（供日志区分普通压缩与探针）。"""
        if not self._tripped():
            return False
        now = time.time()
        return 0.0 < self._recovery_deadline <= now

    # ------------------------------------------------------------------
    # 事件记录
    # ------------------------------------------------------------------

    def record_summary_failure(self, error: str = "", *, use_fallback: bool = False) -> None:
        """记录一次摘要失败（非 fallback 完成路径）。

        - 设置失败冷却（防每轮重试）；
        - 若走了确定性 fallback，累计 fallback streak（连续 2 次 → 熔断）。
        """
        self._summary_failure_cooldown_until = time.time() + self.failure_cooldown_seconds
        self._last_failure_error = str(error or "")[:500]
        if use_fallback:
            self._fallback_streak += 1
        self._persist()

    def record_summary_success(self) -> None:
        """摘要成功（LLM 摘要或确定性 fallback 完成且投影有效）：清冷却与 fallback streak。"""
        self._summary_failure_cooldown_until = 0.0
        self._last_failure_error = ""
        self._fallback_streak = 0
        self._persist()

    def record_effective(self) -> None:
        """压缩有效：清零无效计数。"""
        if self._ineffective_count:
            self._ineffective_count = 0
            self._persist()

    def record_ineffective(self) -> None:
        """压缩无效（投影未减少或减少不足）：累计 strike，达上限即熔断。"""
        self._ineffective_count += 1
        if self._ineffective_count >= self.max_ineffective_strikes:
            logger.warning(
                "[CompactionGuard] tripped: %d consecutive ineffective compactions",
                self._ineffective_count,
            )
        self._persist()

    def record_structural_no_op(self, reason: str) -> None:
        """记录结构性 no-op（窗口为空/消息太少），进入短退避。"""
        self._structural_no_op_backoff_until = time.time() + self.structural_backoff_seconds
        logger.debug("[CompactionGuard] structural no-op (%s), backing off", reason)

    # ------------------------------------------------------------------
    # 可行性跳过（pre-LLM）
    # ------------------------------------------------------------------

    def feasibility_skip(self, middle_tokens: int, soft_limit: int) -> bool:
        """中间可压缩区过小且已有无效记录时，跳过 LLM 摘要。

        规则（对标 Hermes ``_feasibility_skip``）：仅当 ``ineffective_count >= 1``
        且中间区 tokens < ``soft_limit × feasibility_skip_fraction`` 时跳过 ——
        此时 LLM 摘要收益为零或为负（摘要可能不小于原文 → 触发"未减少"异常）。
        """
        if self._ineffective_count < 1:
            return False
        if middle_tokens >= int(soft_limit * self.feasibility_skip_fraction):
            return False
        logger.warning(
            "[CompactionGuard] feasibility skip: middle=%d tokens < %.0f%% of soft limit %d "
            "(ineffective_count=%d) — skipping LLM summarization",
            middle_tokens,
            self.feasibility_skip_fraction * 100,
            soft_limit,
            self._ineffective_count,
        )
        return True

    # ------------------------------------------------------------------
    # 状态快照（诊断/遥测）
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "summary_failure_cooldown_until": self._summary_failure_cooldown_until,
            "ineffective_count": self._ineffective_count,
            "fallback_streak": self._fallback_streak,
            "recovery_deadline": self._recovery_deadline,
            "structural_no_op_backoff_until": self._structural_no_op_backoff_until,
            "tripped": self._tripped(),
            "last_failure_error": self._last_failure_error,
        }

    def reset(self) -> None:
        """重置全部状态（会话重置 / 新会话）。"""
        self._summary_failure_cooldown_until = 0.0
        self._ineffective_count = 0
        self._fallback_streak = 0
        self._recovery_deadline = 0.0
        self._structural_no_op_backoff_until = 0.0
        self._last_failure_error = ""
        self._persist()
