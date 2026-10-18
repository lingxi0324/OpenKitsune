"""Agent 流程/推理逻辑整改（河洛映射）端到端测试。

从用户入口到复盘收束的完整运行路径演练，不依赖 mock：
1. 图构建流 —— 生命周期图（init→…→finalize→reflect→END）与推理图
   （reason→act→observe→verify→finalize）双图构建即通过闭环/路由/完整性自检；
2. 完整回合流 —— TaskState 生命周期 × 推理阶段同步推进，每个落点
   校验双维度奇偶一致（is_valid）与 state_code 只读派生；
3. 制衡回退流 —— VERIFY 发现草稿缺陷 → rollback_for(generation_verification)
   强制回退 THINK 重推，恢复后走完回合（生成-验证分离闭环）；
4. 非法拒绝流 —— 非法状态组合抛 StateConstraintError、非法阶段迁移抛 ValueError；
5. 门守卫流 —— READY 先验缺失拦截 / 检索后放行；CLOSE 审计完整方可闭环；
6. Agent API 流 —— bare-init Agent 挂生命周期图后，describe_lifecycle /
   supports_lifecycle_node / RiskGateDecision 路由均按映射工作。
"""

from __future__ import annotations

import pytest

from openkitsune.agent.core import (
    NODE_REFLECT,
    RiskGateDecision,
    build_agent_lifecycle_graph,
)
from openkitsune.agent.lifecycle_constraints import (
    Gate,
    GuardViolation,
    StateConstraintError,
    assert_gate,
    assert_valid,
    apply_rollback_to,
    derive_lifecycle_for,
    is_valid,
    semantic_consistent,
)
from openkitsune.agent.reasoning import build_reasoning_graph
from openkitsune.agent.state import ReasoningPhase, TaskState
from openkitsune.runtime.models import TaskLifecycleState


# ═══════════════════════════════════════════════════════════════
# 1. 图构建流：双图闭环
# ═══════════════════════════════════════════════════════════════


class TestGraphBuildFlow:
    def test_both_graphs_build_and_are_closed(self) -> None:
        """生命周期图 + 推理图构建即通过全部内置校验（闭环/覆盖/完整性）。"""
        life = build_agent_lifecycle_graph()  # 内含 assert_closure + assert_complete_mapping
        reason = build_reasoning_graph()  # 内含路由覆盖/函数性校验
        assert life.entry_point == "init"
        assert reason.entry_point == "reason"
        # 收敛路径含复盘节点（终而复始）
        assert NODE_REFLECT in life.nodes
        assert life.successors("finalize") == ["reflect"]
        assert life.successors("reflect") == ["__end__"]


# ═══════════════════════════════════════════════════════════════
# 2. 完整回合流（happy path：门序驱动推进）
# ═══════════════════════════════════════════════════════════════


class TestFullTurnFlow:
    def _advance(self, st: TaskState, phase: ReasoningPhase) -> None:
        """真实接入路径：transition 自动同步生命周期 + 语义一致校验。"""
        st.transition(phase)  # 内置门序同步（COMPILING→PLANNING … VERIFY→VERIFYING）
        assert semantic_consistent(st.lifecycle, st.phase)
        assert st.state_code == f"{st.lifecycle.value}.{st.phase.value}"

    def test_complete_task_turn(self) -> None:
        """从汇编到复盘：推理 6 段 × 生命周期门序同步，全程语义一致。"""
        st = TaskState(task_id="e2e-1")
        self._advance(st, ReasoningPhase.COMPILING)   # → PLANNING
        assert st.lifecycle is TaskLifecycleState.PLANNING
        self._advance(st, ReasoningPhase.THINK)       # → WAITING_DEPS
        assert st.lifecycle is TaskLifecycleState.WAITING_DEPS
        self._advance(st, ReasoningPhase.ACT)         # → EXECUTING
        assert st.lifecycle is TaskLifecycleState.EXECUTING
        self._advance(st, ReasoningPhase.OBSERVE)     # → STALLED
        assert st.lifecycle is TaskLifecycleState.STALLED
        self._advance(st, ReasoningPhase.VERIFY)      # → VERIFYING
        assert st.lifecycle is TaskLifecycleState.VERIFYING

        # 门守卫：复盘前审计完整（CLOSE 门放行）
        assert_gate(Gate.CLOSE, {"audit_log_complete": True})
        self._advance(st, ReasoningPhase.DONE)        # → DONE
        st.mark_done(success=True)
        assert st.lifecycle is TaskLifecycleState.DONE
        assert st.phase is ReasoningPhase.DONE

        # 终态复位：DONE 唯一出边回 IDLE（推理迁移表闭环）
        st.phase = ReasoningPhase.DONE
        st.transition(ReasoningPhase.IDLE)
        assert st.phase is ReasoningPhase.IDLE

    def test_derive_lifecycle_full_mapping(self) -> None:
        """推进门 → 生命周期主门 全映射（6 段无遗漏）。"""
        assert derive_lifecycle_for(ReasoningPhase.COMPILING) is TaskLifecycleState.PLANNING
        assert derive_lifecycle_for(ReasoningPhase.THINK) is TaskLifecycleState.WAITING_DEPS
        assert derive_lifecycle_for(ReasoningPhase.ACT) is TaskLifecycleState.EXECUTING
        assert derive_lifecycle_for(ReasoningPhase.OBSERVE) is TaskLifecycleState.STALLED
        assert derive_lifecycle_for(ReasoningPhase.VERIFY) is TaskLifecycleState.VERIFYING
        assert derive_lifecycle_for(ReasoningPhase.DONE) is TaskLifecycleState.DONE

    def test_semantic_window_rule(self) -> None:
        """门距窗口：同门或相邻推进门一致，脱节即不一致。"""
        assert semantic_consistent(TaskLifecycleState.RECEIVED, ReasoningPhase.COMPILING)  # WHY↔READY 相邻
        assert semantic_consistent(TaskLifecycleState.VERIFYING, ReasoningPhase.VERIFY)  # 同门 EVIDENCE
        assert not semantic_consistent(
            TaskLifecycleState.EXECUTING, ReasoningPhase.COMPILING, window=1
        )  # FLOW↔READY 距 2


# ═══════════════════════════════════════════════════════════════
# 3. 制衡回退流（recovery path）
# ═══════════════════════════════════════════════════════════════


class TestBalanceRecoveryFlow:
    def test_generation_verification_rollback_then_recover(self) -> None:
        """验证发现草稿缺陷 → 强制回退 THINK 重推 → 重推后正常收束。"""
        st = TaskState(task_id="e2e-2")
        st.transition(ReasoningPhase.COMPILING)   # → PLANNING
        st.transition(ReasoningPhase.THINK)       # → WAITING_DEPS
        st.transition(ReasoningPhase.ACT)         # → EXECUTING
        st.transition(ReasoningPhase.OBSERVE)     # → STALLED
        st.transition(ReasoningPhase.VERIFY)      # → VERIFYING

        # 验证未过：apply_rollback_to 一体化回退（阶段+生命周期同步）
        target = apply_rollback_to(st, "generation_verification")
        assert target is ReasoningPhase.THINK
        assert st.phase is ReasoningPhase.THINK
        assert st.lifecycle is TaskLifecycleState.WAITING_DEPS  # 门序同步回退
        assert semantic_consistent(st.lifecycle, st.phase)

        # 重推后再次执行 → 观察 → 验证通过 → 收束（transition 自动同步）
        st.transition(ReasoningPhase.ACT)         # → EXECUTING
        st.transition(ReasoningPhase.OBSERVE)     # → STALLED
        st.transition(ReasoningPhase.VERIFY)      # → VERIFYING
        st.transition(ReasoningPhase.DONE)
        st.mark_done(success=True)
        assert st.lifecycle is TaskLifecycleState.DONE

    def test_verification_intent_rollback_reparse(self) -> None:
        """产物越界：回退 COMPILING 重解析意图。"""
        st = TaskState(task_id="e2e-3")
        st.lifecycle = TaskLifecycleState.VERIFYING
        st.phase = ReasoningPhase.VERIFY
        target = apply_rollback_to(st, "verification_intent")
        assert target is ReasoningPhase.COMPILING
        assert st.phase is ReasoningPhase.COMPILING
        assert st.lifecycle is TaskLifecycleState.PLANNING  # 门序同步回退
        assert semantic_consistent(st.lifecycle, st.phase)


# ═══════════════════════════════════════════════════════════════
# 4. 非法拒绝流
# ═══════════════════════════════════════════════════════════════


class TestIllegalRejectionFlow:
    def test_illegal_state_pair_rejected(self) -> None:
        """非法状态组合（奇偶不一致）即拒绝。"""
        # 找到一对非法组合
        pair = next(
            (lc, ph)
            for lc in TaskLifecycleState
            for ph in ReasoningPhase
            if not is_valid(lc, ph)
        )
        with pytest.raises(StateConstraintError):
            assert_valid(*pair)

    def test_illegal_phase_transition_rejected(self) -> None:
        """非法阶段迁移即拒绝（ACT→IDLE 非正常推进）。"""
        st = TaskState(task_id="e2e-4")
        st.phase = ReasoningPhase.ACT
        with pytest.raises(ValueError):
            st.transition(ReasoningPhase.IDLE)

    def test_gate_guard_blocks_incomplete_prior(self) -> None:
        """READY 门：生成前未检索先验即拦截。"""
        with pytest.raises(GuardViolation):
            assert_gate(Gate.READY, {"prior_searched": False})


# ═══════════════════════════════════════════════════════════════
# 5. 路由流
# ═══════════════════════════════════════════════════════════════


class TestRoutingFlow:
    def test_risk_decision_routes_full(self) -> None:
        """RiskGate 四决策 → 生命周期节点映射全覆盖。"""
        assert RiskGateDecision("skip", None, None).next_node == "run_loop"
        assert RiskGateDecision("run", None, None).next_node == "run_loop"
        assert RiskGateDecision("confirm", None, None).next_node == "finalize"
        assert RiskGateDecision("abort", None, None).next_node == "error"


# ═══════════════════════════════════════════════════════════════
# 6. Agent API 流
# ═══════════════════════════════════════════════════════════════


class TestAgentApiFlow:
    def test_agent_lifecycle_api_works(self) -> None:
        """bare-init Agent：生命周期图挂载后 describe/supports 按映射工作。"""
        from openkitsune.agent.core import Agent as V2Agent

        agent = V2Agent.__new__(V2Agent)  # 规避重型 __init__
        agent._lifecycle_graph = build_agent_lifecycle_graph()

        snapshot = agent.describe_lifecycle()
        assert snapshot["entry_point"] == "init"
        assert "reflect" in snapshot["nodes"]
        assert agent.supports_lifecycle_node("run_loop") is True
        assert agent.supports_lifecycle_node("nonexistent") is False
