"""复合状态 (stage_idx, gate_idx) + 12 门接口回归测试。

覆盖：
1. 10×12 组合中恰 60 个奇偶一致合法态；
2. 越界 / 失衡态被 ``TaskState.is_valid`` 拦截；
3. ``advance`` / ``rollback`` 同频推进与边界；
4. ``ensure_ready_for_reasoning`` 入口校验；
5. ``TaskStatus`` → ``Stage`` 映射与状态转换同步；
6. 12 门注册、审计日志、失败回退目标、完整性四门。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openkitsune.agent.state import ReasoningPhase
from openkitsune.agent.state import TaskState as V2TaskState
from openkitsune.core.agent_state import (
    STAGE_HOLD_STATUSES,
    STAGE_TO_GATES,
    STATUS_TO_STAGE,
    Stage,
    TaskState,
    TaskStatus,
)
from openkitsune.core.gates import (
    COMPLETENESS_GATES,
    GATE_DESCRIPTIONS,
    GATE_ORDER,
    FailureAction,
    GateRegistry,
    check_completeness,
)

STAGE_MAX = 9
GATE_MAX = 11


def _state(stage: int = 0, gate: int = 0) -> TaskState:
    return TaskState(task_id="t", stage_idx=stage, gate_idx=gate)


# ═══════════════════════════════════════════════════════════════
# 1. 复合状态：60 合法态 / 失衡态 / 越界
# ═══════════════════════════════════════════════════════════════


class TestCompositeState:
    def test_exactly_60_legal_states(self) -> None:
        """10×12=120 组合中恰 60 个同奇偶合法态（不重不漏）。"""
        legal = [
            (stage, gate)
            for stage in range(STAGE_MAX + 1)
            for gate in range(GATE_MAX + 1)
            if _state(stage, gate).is_valid()
        ]
        assert len(legal) == 60
        assert len(set(legal)) == 60
        assert all((stage % 2) == (gate % 2) for stage, gate in legal)

    @pytest.mark.parametrize("stage,gate", [(0, 1), (1, 0), (8, 11), (9, 10)])
    def test_parity_mismatch_rejected(self, stage: int, gate: int) -> None:
        assert _state(stage, gate).is_valid() is False

    @pytest.mark.parametrize("stage,gate", [(-1, 0), (0, -1), (10, 10), (0, 12)])
    def test_out_of_range_rejected(self, stage: int, gate: int) -> None:
        assert _state(stage, gate).is_valid() is False

    def test_advance_keeps_parity(self) -> None:
        state = _state(0, 0)
        assert state.advance() == (1, 1)
        assert state.is_valid() is True

    def test_advance_stops_at_final_stage(self) -> None:
        state = _state(STAGE_MAX, STAGE_MAX)
        with pytest.raises(ValueError):
            state.advance()
        assert (state.stage_idx, state.gate_idx) == (STAGE_MAX, STAGE_MAX)

    def test_rollback_syncs_both_indices(self) -> None:
        state = _state(2, 2)
        assert state.rollback() == (1, 1)
        assert state.is_valid() is True

    def test_rollback_at_origin_rejected(self) -> None:
        with pytest.raises(ValueError):
            _state(0, 0).rollback()

    def test_ensure_ready_accepts_valid_state(self) -> None:
        state = _state(0, 0)
        state.ensure_ready_for_reasoning()
        assert state.status is TaskStatus.REASONING

    def test_ensure_ready_rejects_imbalance(self) -> None:
        state = _state(0, 1)
        with pytest.raises(ValueError):
            state.ensure_ready_for_reasoning()
        assert state.status is TaskStatus.IDLE


# ═══════════════════════════════════════════════════════════════
# 2. TaskStatus → Stage 映射与转换同步
# ═══════════════════════════════════════════════════════════════


class TestStageMapping:
    def test_every_status_mapped_or_held(self) -> None:
        for status in TaskStatus:
            assert status in STATUS_TO_STAGE or status in STAGE_HOLD_STATUSES

    def test_stage_enum_and_gate_map_complete(self) -> None:
        assert {int(stage) for stage in Stage} == set(range(10))
        assert set(STAGE_TO_GATES) == set(Stage)
        for gate_ids in STAGE_TO_GATES.values():
            assert gate_ids
            for gate_id in gate_ids:
                assert gate_id in GATE_ORDER

    def test_transition_syncs_composite_indices(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # IDLE → REASONING = S2
        assert (state.stage_idx, state.gate_idx) == (2, 2)
        state.transition(TaskStatus.ACTING)  # S4
        assert (state.stage_idx, state.gate_idx) == (4, 4)
        state.transition(TaskStatus.OBSERVING)  # S5
        assert (state.stage_idx, state.gate_idx) == (5, 5)
        assert state.is_valid() is True

    def test_hold_status_keeps_position(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # S2
        state.transition(TaskStatus.MODEL_SWITCHING)
        assert (state.stage_idx, state.gate_idx) == (2, 2)
        state.transition(TaskStatus.REASONING)
        assert (state.stage_idx, state.gate_idx) == (2, 2)

    def test_long_react_loop_stays_bounded(self) -> None:
        """长循环反复 REASONING→ACTING→OBSERVING 不会越界。"""
        state = _state()
        state.ensure_ready_for_reasoning()
        for _ in range(50):
            state.transition(TaskStatus.ACTING)
            state.transition(TaskStatus.OBSERVING)
            state.transition(TaskStatus.REASONING)
            assert state.is_valid() is True
            assert 0 <= state.stage_idx <= STAGE_MAX
            assert 0 <= state.gate_idx <= GATE_MAX

    def test_stage_entry_runs_bound_gate(self) -> None:
        gate = GateRegistry.get("G4")
        assert gate is not None
        before = len(gate.audit_log)
        state = _state()
        state.ensure_ready_for_reasoning()  # S2
        state.transition(TaskStatus.ACTING)  # 进入 S4 → G4
        assert len(gate.audit_log) > before
        assert gate.audit_log[-1].passed is True

    def test_check_gate_strict_context(self) -> None:
        state = _state()
        record = state.check_gate("G2", {"spec_complete": False})
        assert record.passed is False
        assert record.rollback_target == "1"
        with pytest.raises(ValueError):
            state.check_gate("G99")


class TestV2CompositeSync:
    """v2 agent.state.TaskState 的阶段坐标同步（与 core 同口径）。"""

    def test_phase_transition_syncs_indices(self) -> None:
        state = V2TaskState(task_id="v2")
        state.transition(ReasoningPhase.COMPILING)  # S1
        assert (state.stage_idx, state.gate_idx) == (1, 1)
        state.transition(ReasoningPhase.THINK)  # S2
        assert (state.stage_idx, state.gate_idx) == (2, 2)
        state.transition(ReasoningPhase.ACT)  # S4
        assert (state.stage_idx, state.gate_idx) == (4, 4)
        state.transition(ReasoningPhase.OBSERVE)  # S5
        assert (state.stage_idx, state.gate_idx) == (5, 5)
        state.transition(ReasoningPhase.VERIFY)  # S6
        assert (state.stage_idx, state.gate_idx) == (6, 6)
        state.transition(ReasoningPhase.DONE)  # S8
        assert (state.stage_idx, state.gate_idx) == (8, 8)
        assert state.is_valid() is True

    def test_awaiting_user_keeps_position(self) -> None:
        state = V2TaskState(task_id="v2")
        state.transition(ReasoningPhase.THINK)  # S2
        state.transition(ReasoningPhase.AWAITING_USER)
        assert (state.stage_idx, state.gate_idx) == (2, 2)
        state.transition(ReasoningPhase.THINK)
        assert (state.stage_idx, state.gate_idx) == (2, 2)

    def test_v2_bounds(self) -> None:
        assert V2TaskState(task_id="v2", stage_idx=1, gate_idx=0).is_valid() is False
        assert V2TaskState(task_id="v2", stage_idx=10, gate_idx=10).is_valid() is False


class TestGateFailureConsumer:
    """Gate 失败三态的运行时消费（TaskState + Orchestrator）。"""

    def test_rollback_moves_composite_coords(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # S2
        record = state.check_gate("G2", {"spec_complete": False})
        assert state.apply_gate_result(record) == "rollback"
        assert (state.stage_idx, state.gate_idx) == (1, 1)
        assert state.pending_gate_failure is record

    def test_suspend_sets_flag_and_clears(self) -> None:
        state = _state()
        record = state.check_gate("G10", {"all_archived": False})
        assert state.apply_gate_result(record) == "suspend"
        assert state.suspended is True
        assert state.suspend_reason
        state.clear_suspension()
        assert state.suspended is False
        assert state.pending_gate_failure is None

    def test_confirm_enters_waiting_user(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # REASONING → WAITING_USER 合法
        record = state.check_gate("G0", {"goal_defined": False})
        assert state.apply_gate_result(record) == "confirm"
        assert state.status is TaskStatus.WAITING_USER

    def test_confirm_keeps_status_when_transition_illegal(self) -> None:
        state = _state()  # IDLE 不能直接转 WAITING_USER
        record = state.check_gate("G0", {"goal_defined": False})
        assert state.apply_gate_result(record) == "confirm"
        assert state.status is TaskStatus.IDLE
        assert state.pending_gate_failure is record

    def test_pass_is_noop(self) -> None:
        state = _state()
        record = state.check_gate("G2", {"spec_complete": True})
        assert state.apply_gate_result(record) == "pass"
        assert state.pending_gate_failure is None

    def test_transition_strict_mode_consumes_failure(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # REASONING → ACTING 合法
        state.transition(TaskStatus.ACTING, gate_ctx={"data_consolidated": False})
        assert state.pending_gate_failure is not None
        assert state.pending_gate_failure.gate == "G4"
        assert (state.stage_idx, state.gate_idx) == (3, 3)

    def test_orchestrator_consumes_gate_failure(self) -> None:
        from openkitsune.agents.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()
        state = _state()
        state.ensure_ready_for_reasoning()
        record = state.check_gate("G0", {"goal_defined": False})
        assert orchestrator.consume_gate_failure(state, record) == "confirm"
        assert state.status is TaskStatus.WAITING_USER


# ═══════════════════════════════════════════════════════════════
# 3. 12 门注册 / 审计 / 回退
# ═══════════════════════════════════════════════════════════════


class TestGateRegistry:
    def test_twelve_gates_registered(self) -> None:
        assert [f"G{i}" for i in range(12)] == GATE_ORDER
        assert len(GateRegistry.get_all()) == 12
        for gate_id in GATE_ORDER:
            assert GateRegistry.get(gate_id) is not None
        assert set(GATE_DESCRIPTIONS) == set(GATE_ORDER)

    def test_gates_cover_all_stages(self) -> None:
        stages = {gate.bound_stage for gate in GateRegistry.get_all()}
        assert stages == set(range(STAGE_MAX + 1))

    def test_check_appends_audit_record(self) -> None:
        gate = GateRegistry.get("G2")
        assert gate is not None
        before = len(gate.audit_log)
        record = gate.check({"spec_complete": True})
        assert record.gate == "G2"
        assert record.passed is True
        assert gate.audit_log[-1] is record
        assert len(gate.audit_log) == min(before + 1, gate.MAX_AUDIT_RECORDS)

    def test_failure_records_rollback_target(self) -> None:
        gate = GateRegistry.get("G6")
        assert gate is not None
        record = gate.check({"audit_record_complete": False})
        assert record.passed is False
        assert record.rollback_target == "5"
        assert "rollback to stage 5" in record.reason

    def test_failure_actions_cover_three_states(self) -> None:
        """12 门的失败处理覆盖 回退/挂起/请求确认 三态。"""
        actions = {gate.on_fail().action for gate in GateRegistry.get_all()}
        assert actions == set(FailureAction)

    def test_confirm_and_suspend_actions(self) -> None:
        g0 = GateRegistry.get("G0")
        g10 = GateRegistry.get("G10")
        assert g0 is not None and g10 is not None
        assert g0.check({"goal_defined": False}).action == FailureAction.CONFIRM.value
        assert g10.check({"all_archived": False}).action == FailureAction.SUSPEND.value

    def test_open_gate_passes_without_context(self) -> None:
        """未提供上下文时按放行优先（不阻塞既有运行路径）。"""
        for gate in GateRegistry.get_all():
            assert gate.check(None).passed is True


class TestCompletenessGates:
    def test_completeness_gate_members(self) -> None:
        assert set(COMPLETENESS_GATES) == {"G1", "G4", "G7", "G10"}

    def test_completeness_pass_and_unknown_gate(self) -> None:
        assert check_completeness("G7", {"gaps_filled": True}) is True
        with pytest.raises(ValueError):
            check_completeness("G2", {})


# ═══════════════════════════════════════════════════════════════
# 4. 推理循环转换点的门接线
# ═══════════════════════════════════════════════════════════════


class TestRuntimeGateWiring:
    def test_guard_gate_pass(self) -> None:
        state = _state()
        record = state.guard_gate("G4", {"data_consolidated": True})
        assert record.passed is True
        assert state.pending_gate_failure is None

    def test_guard_gate_failure_applies_rollback(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()  # S2
        record = state.guard_gate("G4", {"data_consolidated": False})
        assert record.passed is False
        assert state.pending_gate_failure is record
        assert (state.stage_idx, state.gate_idx) == (3, 3)

    def test_ensure_ready_gate_ctx_checks_g0(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning({"goal_defined": False})
        assert state.status is TaskStatus.REASONING
        assert state.pending_gate_failure is not None
        assert state.pending_gate_failure.gate == "G0"

    def test_ensure_ready_without_ctx_skips_gate(self) -> None:
        state = _state()
        state.ensure_ready_for_reasoning()
        assert state.pending_gate_failure is None

    def test_reasoning_runtime_transition_points_wired(self) -> None:
        """9 个转换点：REASONING/VERIFYING/ACTING/WAITING_USER/OBSERVING/FAILED。"""
        runtime = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "openkitsune"
            / "core"
            / "_reasoning_runtime.py"
        )
        source = runtime.read_text(encoding="utf-8")
        assert "from .gates import" in source
        for gate_id in ("G2", "G3", "G4", "G6", "G9"):
            assert re.search(rf'guard_gate\(\s*"{gate_id}"', source), gate_id
        assert source.count('guard_gate("G9"') == 3  # 正常终局 + 循环终止 + max_iterations
        assert "ensure_ready_for_reasoning(" in source
        assert "goal_defined" in source
        # 除 MODEL_SWITCHING（规范 5.2 无绑定门）外，其余 7 个转换点
        # 都必须把门上下文交给 transition 内的 _enforce_stage_gates。
        assert source.count("gate_ctx=_gate_context(") >= 7
