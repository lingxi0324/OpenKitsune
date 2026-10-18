"""
Gate interface + 12 校验门实例（规范第 5 章）

实现层不含玄学术语，Gate 标识为英文常量；
干支词仅出现在 src/openkitsune/agent/lifecycle_constraints.py 溯源表。

Usage:
    from openkitsune.core.gates import GateRegistry, GATE_ORDER, GATE_DESCRIPTIONS, check_completeness
    
    # In ORCHESTRATOR:
    #   GateRegistry.register(my_gate)
    #   result = GateRegistry.get("G0").check(ctx)
    #   if not result.passed:
    #       rollback = result.rollback_target  # or GateRegistry.get("G0").on_fail()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable
import time
import uuid


class AuditRecord:
    """Gate 判定审计日志，判定依据可追溯。"""

    gate: str
    stage: int
    timestamp: float
    passed: bool
    reason: str
    rollback_target: str | None = None
    context: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"AuditRecord(gate={self.gate}, stage={self.stage}, "
            f"passed={self.passed}, reason={self.reason!r})"
        )


class Rollback:
    """Gate 失败回退目标。"""

    def __init__(self, target_stage: int, reason: str = "") -> None:
        self.target_stage = target_stage
        self.reason = reason


class GateCondition(Protocol):
    def __call__(self, ctx: dict | None = None) -> bool: ...


class Gate:
    """规范第 5 章 Gate 接口。

    实现：
    - bound_stage: 绑定的 stage_idx 或 "transition"
    - condition: 可判定的通过条件
    - on_pass: 推进回调
    - on_fail: 回退回调 → 返回 Rollback
    - audit_log: 判定依据可追溯
    """

    def __init__(
        self,
        id: str,
        bound_stage: int | str,
        condition: GateCondition,
        on_pass: Callable[[], None],
        on_fail: Callable[[], Rollback],
        audit_log: list[AuditRecord] | None = None,
    ):
        self.id = id
        self.bound_stage = bound_stage
        self.condition = condition
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.audit_log = audit_log or []

    def check(self, ctx: dict | None = None) -> AuditRecord:
        """执行判定，记录审计日志，调用 on_pass/on_fail。"""
        passed = self.condition(ctx)
        record = AuditRecord(
            gate=self.id,
            stage=int(self.bound_stage) if isinstance(self.bound_stage, int) else 0,
            timestamp=time.monotonic(),
            passed=passed,
            reason=f"{'PASS' if passed else 'FAIL'}: {self.id} gate check",
        )
        self.audit_log.append(record)
        if passed:
            self.on_pass()
        else:
            rb = self.on_fail()
            record.rollback_target = str(rb.target_stage)
            record.reason = f"{record.reason}, rollback to stage {rb.target_stage}"
        return record


# ═══════════════════════════════════════════════════════════════
# Gate 实例工厂
# ═══════════════════════════════════════════════════════════════


def make_gate(
    id: str,
    bound_stage: int | str,
    condition: GateCondition,
    on_pass: Callable[[], None],
    on_fail: Callable[[], Rollback],
) -> Gate:
    """工厂：避免重复写 Gate(...) 实例化。"""
    return Gate(
        id=id,
        bound_stage=bound_stage,
        condition=condition,
        on_pass=on_pass,
        on_fail=on_fail,
    )


# ═══════════════════════════════════════════════════════════════
# 12 校验门实例（规范 5.2 十二门分布）
# ═══════════════════════════════════════════════════════════════


class GateRegistry:
    """12 门注册表，由 ORCHESTRATOR 在初始化时注册。"""

    _gates: dict[str, Gate] = {}

    @classmethod
    def register(cls, gate: Gate) -> None:
        cls._gates[gate.id] = gate

    @classmethod
    def get(cls, gate_id: str) -> Gate | None:
        return cls._gates.get(gate_id)

    @classmethod
    def get_all(cls) -> list[Gate]:
        return list(cls._gates.values())

    @classmethod
    def get_by_stage(cls, stage: int) -> list[Gate]:
        """返回指定 stage 绑定的所有门（可能多门绑同一 stage）。"""
        return [g for g in cls._gates.values() if int(g.bound_stage) == stage]


# ---- G0: GOAL_CONFIRMATION (入口) ----
def _g0_condition(ctx: dict | None = None) -> bool:
    return bool(ctx and ctx.get("goal_defined")) if ctx else True


def _g0_pass() -> None:
    pass


def _g0_fail() -> Rollback:
    return Rollback(target_stage=0, reason="GOAL_CONFIRMATION: 目标未定义，挂起请求确认")


g0 = make_gate(
    id="G0",
    bound_stage=0,
    condition=_g0_condition,
    on_pass=_g0_pass,
    on_fail=_g0_fail,
)
GateRegistry.register(g0)


# ---- G1: INPUT_READINESS (S0→S1) ----
def _g1_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("input_ready", True) and ctx.get("tools_available", True))


def _g1_pass() -> None:
    pass


def _g1_fail() -> Rollback:
    return Rollback(target_stage=0, reason="INPUT_READINESS: 补齐资源后重试")


g1 = make_gate(
    id="G1",
    bound_stage=0,
    condition=_g1_condition,
    on_pass=_g1_pass,
    on_fail=_g1_fail,
)
GateRegistry.register(g1)


# ---- G2: START_COMMITMENT (S1→S2) ----
def _g2_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("spec_complete", False))


def _g2_pass() -> None:
    pass


def _g2_fail() -> Rollback:
    return Rollback(target_stage=1, reason="START_COMMITMENT: 规格不完备，回退补规格")


g2 = make_gate(
    id="G2",
    bound_stage=1,
    condition=_g2_condition,
    on_pass=_g2_pass,
    on_fail=_g2_fail,
)
GateRegistry.register(g2)


# ---- G3: PROGRESS_MONITOR (S2→S3) ----
def _g3_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("plan_executable", False))


def _g3_pass() -> None:
    pass


def _g3_fail() -> Rollback:
    return Rollback(target_stage=2, reason="PROGRESS_MONITOR: 方案不可执行，回退重规划")


g3 = make_gate(
    id="G3",
    bound_stage=2,
    condition=_g3_condition,
    on_pass=_g3_pass,
    on_fail=_g3_fail,
)
GateRegistry.register(g3)


# ---- G4: DATA_CONSOLIDATION (S3→S4) ----
def _g4_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("data_consolidated", False))


def _g4_pass() -> None:
    pass


def _g4_fail() -> Rollback:
    return Rollback(target_stage=3, reason="DATA_CONSOLIDATION: 散料未汇拢，回退补素材")


g4 = make_gate(
    id="G4",
    bound_stage=3,
    condition=_g4_condition,
    on_pass=_g4_pass,
    on_fail=_g4_fail,
)
GateRegistry.register(g4)


# ---- G5: SYNTHESIS (S4→S5) ----
def _g5_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("synthesis_complete", False))


def _g5_pass() -> None:
    pass


def _g5_fail() -> Rollback:
    return Rollback(target_stage=4, reason="SYNTHESIS: 执行产物未提炼，回退重提炼")


g5 = make_gate(
    id="G5",
    bound_stage=4,
    condition=_g5_condition,
    on_pass=_g5_pass,
    on_fail=_g5_fail,
)
GateRegistry.register(g5)


# ---- G6: EVIDENCE_AUDIT (S5→S6) ----
def _g6_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("audit_record_complete", False))


def _g6_pass() -> None:
    pass


def _g6_fail() -> Rollback:
    return Rollback(target_stage=5, reason="EVIDENCE_AUDIT: 证据多源交叉验证缺失，回退补审计")


g6 = make_gate(
    id="G6",
    bound_stage=5,
    condition=_g6_condition,
    on_pass=_g6_pass,
    on_fail=_g6_fail,
)
GateRegistry.register(g6)


# ---- G7: GAP_FILLING (S6→S7) ----
def _g7_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("gaps_filled", True))


def _g7_pass() -> None:
    pass


def _g7_fail() -> Rollback:
    return Rollback(target_stage=6, reason="GAP_FILLING: 覆盖缺口未补全，回退补验证")


g7 = make_gate(
    id="G7",
    bound_stage=6,
    condition=_g7_condition,
    on_pass=_g7_pass,
    on_fail=_g7_fail,
)
GateRegistry.register(g7)


# ---- G8: RIGOR_TRIAGE (S7 内部) ----
def _g8_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("redundancy_trimmed", True))


def _g8_pass() -> None:
    pass


def _g8_fail() -> Rollback:
    return Rollback(target_stage=7, reason="RIGOR_TRIAGE: 冗余未剔除，挂起人工确认")


g8 = make_gate(
    id="G8",
    bound_stage=7,
    condition=_g8_condition,
    on_pass=_g8_pass,
    on_fail=_g8_fail,
)
GateRegistry.register(g8)


# ---- G9: CONFORMANCE (S7→S8) ----
def _g9_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("conforms_spec", False))


def _g9_pass() -> None:
    pass


def _g9_fail() -> Rollback:
    return Rollback(target_stage=7, reason="CONFORMANCE: 定稿不合规格，回退修正")


g9 = make_gate(
    id="G9",
    bound_stage=7,
    condition=_g9_condition,
    on_pass=_g9_pass,
    on_fail=_g9_fail,
)
GateRegistry.register(g9)


# ---- G10: FINALIZATION (S8→S9) ----
def _g10_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("all_archived", True))


def _g10_pass() -> None:
    pass


def _g10_fail() -> Rollback:
    return Rollback(target_stage=8, reason="FINALIZATION: 收束归档未完成，补归档后重试")


g10 = make_gate(
    id="G10",
    bound_stage=8,
    condition=_g10_condition,
    on_pass=_g10_pass,
    on_fail=_g10_fail,
)
GateRegistry.register(g10)


# ---- G11: RETROSPECT_LOCK (S9→S0) ----
def _g11_condition(ctx: dict | None = None) -> bool:
    if not ctx:
        return True
    return bool(ctx.get("experience_logged", False))


def _g11_pass() -> None:
    pass


def _g11_fail() -> Rollback:
    return Rollback(target_stage=9, reason="RETROSPECT_LOCK: 复盘未入库，挂起补复盘")


g11 = make_gate(
    id="G11",
    bound_stage=9,
    condition=_g11_condition,
    on_pass=_g11_pass,
    on_fail=_g11_fail,
)
GateRegistry.register(g11)


# ─── 完整性四门共享策略（四库尽归土·信） ───
COMPLETENESS_GATES = {
    "G1": g1,
    "G4": g4,
    "G7": g7,
    "G10": g10,
}


def check_completeness(gate_id: str, ctx: dict | None = None) -> bool:
    """完整性四门统一入口。"""
    gate = COMPLETENESS_GATES.get(gate_id)
    if gate is None:
        raise ValueError(f"Unknown completeness gate: {gate_id}")
    record = gate.check(ctx)
    return record.passed


# ─── 门序常量 ───
GATE_ORDER = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11"]

GATE_DESCRIPTIONS: dict[str, str] = {
    "G0": "GOAL_CONFIRMATION (任务入口) — 目标明确、成功标准已定义",
    "G1": "INPUT_READINESS (S0→S1) — 输入/上下文/工具就绪",
    "G2": "START_COMMITMENT (S1→S2) — 规格确认，正式开工",
    "G3": "PROGRESS_MONITOR (S2→S3) — 方案落实、推进启动",
    "G4": "DATA_CONSOLIDATION (S3→S4) — 散料汇拢为可执行数据集",
    "G5": "SYNTHESIS (S4→S5) — 执行产物提炼为可验证结论",
    "G6": "EVIDENCE_AUDIT (S5→S6) — 证据多源交叉验证、口径标注",
    "G7": "GAP_FILLING (S6→S7) — 覆盖缺口、边界细节补全",
    "G8": "RIGOR_TRIAGE (S7 内部) — 冗余删除、弱证据剔除、取舍留痕",
    "G9": "CONFORMANCE (S7→S8) — 规格符合、格式定型、可交付",
    "G10": "FINALIZATION (S8→S9) — 收束归档、无遗落项",
    "G11": "RETROSPECT_LOCK (S9→S0) — 复盘入库、经验已沉淀",
}


# 导出
__all__ = [
    "AuditRecord",
    "Rollback",
    "Gate",
    "GateCondition",
    "GateRegistry",
    "check_completeness",
    "COMPLETENESS_GATES",
    "GATE_ORDER",
    "GATE_DESCRIPTIONS",
    "g0", "g1", "g2", "g3", "g4", "g5",
    "g6", "g7", "g8", "g9", "g10", "g11",
]
