"""Agent 流程/推理逻辑整改（门序/角色/策略/相克补全）回归测试。

补全模块覆盖规范 L2–L4 在既有六性质约束层上缺失的映射：
1. 门序维度 —— 12 门全序、推进门 ↔ 推理阶段映射、门谓词（先验/溯源）；
2. 完备口径 —— 任务级生命周期 × 门 10×12 → 60 合法态（不残缺不重复）；
3. 角色与拓扑 —— 9 角色、星型拓扑（仅编排角色可调度）、4 组对角制衡；
4. 策略注入 —— 5 类策略 × 阶段/角色决策表，无漏路由；
5. 相克触发 —— 5 条规则、3 条强制回退（触发前提校验）、2 条门谓词；
6. 完整性自检 —— 生命周期图构建期 fail-fast。
"""

from __future__ import annotations

import pytest

from openkitsune.agent.core import build_agent_lifecycle_graph
from openkitsune.agent.lifecycle_constraints import (
    ALL_ROLES,
    BALANCE_ROLLBACK,
    BALANCE_RULES,
    COUNTERBALANCE,
    GATE_KIND,
    GATE_ORDER,
    GATE_TO_PHASE,
    PHASE_TO_GATE,
    STRATEGY_ROLES,
    STRATEGY_STAGES,
    AgentRole,
    Gate,
    GateCode,
    GuardViolation,
    StateConstraintError,
    StrategyTag,
    TopologyViolation,
    advance_guarded,
    apply_rollback_to,
    assert_complete_mapping,
    assert_gate,
    assert_star_topology,
    derive_lifecycle_for,
    gate_sequence_ok,
    gate_valid_codes,
    rollback_for,
    semantic_consistent,
    strategy_for,
)
from openkitsune.agent.state import ReasoningPhase, TaskState
from openkitsune.runtime.models import TaskLifecycleState


# ═══════════════════════════════════════════════════════════════
# 1. 门序维度
# ═══════════════════════════════════════════════════════════════


class TestGateSequence:
    def test_gate_order_full(self) -> None:
        """恰 12 门且保持定义序（G0..G11 全序）。"""
        assert len(GATE_ORDER) == 12
        assert gate_sequence_ok() is True
        assert [g.value for g in GATE_ORDER] == [
            "why",
            "ready",
            "start",
            "flow",
            "aggregate",
            "refine",
            "evidence",
            "gap",
            "trim",
            "finalize",
            "archive",
            "close",
        ]

    def test_gate_kinds_covered(self) -> None:
        """12 门职能分类完整：入口/推进/内部/回退/闭环五类齐备。"""
        kinds = set(GATE_KIND.values())
        assert kinds == {"entry", "transition", "internal", "rollback", "closure"}
        assert sum(k == "transition" for k in GATE_KIND.values()) == 6  # 6 道推进门
        assert sum(k == "internal" for k in GATE_KIND.values()) == 3  # refine/trim/archive

    def test_phase_to_gate_mapping(self) -> None:
        """6 个推进门 ↔ 6 个推进阶段一一对应、无悬空。"""
        assert len(PHASE_TO_GATE) == 6
        for phase, gate in PHASE_TO_GATE.items():
            assert gate in GATE_ORDER
            assert GATE_TO_PHASE[gate] is phase
        assert PHASE_TO_GATE[ReasoningPhase.COMPILING] is Gate.READY
        assert PHASE_TO_GATE[ReasoningPhase.THINK] is Gate.START
        assert PHASE_TO_GATE[ReasoningPhase.ACT] is Gate.FLOW
        assert PHASE_TO_GATE[ReasoningPhase.OBSERVE] is Gate.AGGREGATE
        assert PHASE_TO_GATE[ReasoningPhase.VERIFY] is Gate.EVIDENCE
        assert PHASE_TO_GATE[ReasoningPhase.DONE] is Gate.FINALIZE

    def test_lifecycle_to_gate_full(self) -> None:
        """全部 10 个任务级生命周期均有主门归属。"""
        assert len(PHASE_TO_GATE) + len(
            set(GATE_ORDER) - set(PHASE_TO_GATE.values())
        ) == len(GATE_ORDER)
        # 10 生命周期 → 10 门（WHY/GAP/CLOSE 等辅助门也在进程性归属内）
        from openkitsune.agent.lifecycle_constraints import LIFECYCLE_TO_GATE

        assert len(LIFECYCLE_TO_GATE) == 10
        for lc in TaskLifecycleState:
            assert LIFECYCLE_TO_GATE[lc] in GATE_ORDER


# ═══════════════════════════════════════════════════════════════
# 2. 完备口径：60 合法态
# ═══════════════════════════════════════════════════════════════


class TestGateUniqueness:
    def test_gate_legal_state_count(self) -> None:
        """10×12=120 组合中恰 60 个奇偶一致合法态（不残缺不重复）。"""
        codes = gate_valid_codes()
        assert len(codes) == 60
        assert len({c.label for c in codes}) == 60

    def test_gate_code_parity(self) -> None:
        """GateCode.parity_consistent 与奇偶规则一致。"""
        for lc in TaskLifecycleState:
            for g in GATE_ORDER:
                expected = (list(TaskLifecycleState).index(lc) & 1) == (
                    GATE_ORDER.index(g) & 1
                )
                assert GateCode(lc, g).parity_consistent is expected

    def test_gate_codes_cover_all_members(self) -> None:
        """60 态覆盖全部 10 生命周期 × 12 门成员（无遗漏成员）。"""
        codes = gate_valid_codes()
        lifecycles = {c.lifecycle for c in codes}
        gates = {c.gate for c in codes}
        assert lifecycles == set(TaskLifecycleState)
        assert gates == set(GATE_ORDER)


# ═══════════════════════════════════════════════════════════════
# 3. 角色 / 拓扑 / 对角制衡
# ═══════════════════════════════════════════════════════════════


class TestRolesAndTopology:
    def test_nine_roles(self) -> None:
        """恰 9 个职责角色，无重复无缺失。"""
        assert len(ALL_ROLES) == 9
        assert set(ALL_ROLES) == {
            AgentRole.SECURITY,
            AgentRole.PERCEPTION,
            AgentRole.CONTEXT,
            AgentRole.EXECUTION,
            AgentRole.REASONING,
            AgentRole.VALIDATION,
            AgentRole.ORCHESTRATOR,
            AgentRole.DELIVERY,
            AgentRole.MEMORY,
        }

    def test_four_counterbalance_pairs(self) -> None:
        """4 组对角制衡：每组两端角色互异、均属 9 角色集。"""
        assert len(COUNTERBALANCE) == 4
        for left, right, desc in COUNTERBALANCE:
            assert left in ALL_ROLES and right in ALL_ROLES
            assert left is not right
            assert desc

    def test_star_topology_orchestrator_only(self) -> None:
        """仅 ORCHESTRATOR 可调度其他角色。"""
        assert_star_topology(AgentRole.ORCHESTRATOR, AgentRole.EXECUTION)
        with pytest.raises(TopologyViolation):
            assert_star_topology(AgentRole.EXECUTION, AgentRole.DELIVERY)
        with pytest.raises(TopologyViolation):
            assert_star_topology(AgentRole.REASONING, AgentRole.VALIDATION)

    def test_star_topology_self_call_allowed(self) -> None:
        """角色自调用不构成跨角色调度。"""
        assert_star_topology(AgentRole.MEMORY, AgentRole.MEMORY)


# ═══════════════════════════════════════════════════════════════
# 4. 策略注入
# ═══════════════════════════════════════════════════════════════


class TestStrategies:
    def test_five_tags_full(self) -> None:
        """5 类策略标签齐备，阶段表与角色表覆盖全部标签。"""
        assert set(StrategyTag) == {
            StrategyTag.GROWTH,
            StrategyTag.CLARITY,
            StrategyTag.STABILITY,
            StrategyTag.RIGOR,
            StrategyTag.LEARNING,
        }
        assert set(STRATEGY_STAGES) == set(StrategyTag)
        assert set(STRATEGY_ROLES) == set(StrategyTag)

    def test_strategy_lookup_returns_tag(self) -> None:
        """决策表查表返回合法策略标签（不悬空、不缺失）。"""
        for lc in TaskLifecycleState:
            for role in ALL_ROLES:
                tag = strategy_for(lc, role)
                assert tag in set(StrategyTag)

    def test_strategy_growth_mapping(self) -> None:
        """生长策略落在推进阶段与感知/执行角色。"""
        assert strategy_for(TaskLifecycleState.EXECUTING, AgentRole.EXECUTION) is (
            StrategyTag.GROWTH
        )
        assert strategy_for(TaskLifecycleState.DONE, AgentRole.MEMORY) is (
            StrategyTag.LEARNING
        )


# ═══════════════════════════════════════════════════════════════
# 5. 相克触发：三条回退 + 两条门谓词
# ═══════════════════════════════════════════════════════════════


class TestBalanceRules:
    def test_five_rules_full(self) -> None:
        """5 条相克规则：3 条回退 + 2 条门谓词，规则表闭合。"""
        assert len(BALANCE_RULES) == 5
        assert set(BALANCE_ROLLBACK) == {
            "generation_verification",
            "verification_intent",
            "execution_plan",
        }
        rule_ids = {r for r, _ in BALANCE_RULES}
        assert set(BALANCE_ROLLBACK) | {"generation_prior", "retrospect_trace"} == rule_ids

    def test_rollback_generation_verification(self) -> None:
        """生成-验证分离：验证阶段触发，回退 THINK。"""
        task = TaskState(task_id="t")
        task.phase = ReasoningPhase.VERIFY
        assert rollback_for(task, "generation_verification") is ReasoningPhase.THINK

    def test_rollback_verification_intent(self) -> None:
        """验证-意图边界：验证阶段触发，回退 COMPILING。"""
        task = TaskState(task_id="t")
        task.phase = ReasoningPhase.VERIFY
        assert rollback_for(task, "verification_intent") is ReasoningPhase.COMPILING

    def test_rollback_execution_plan(self) -> None:
        """执行-规划纠偏：执行/观察阶段触发，回退 THINK。"""
        task = TaskState(task_id="t")
        task.phase = ReasoningPhase.ACT
        assert rollback_for(task, "execution_plan") is ReasoningPhase.THINK

    def test_rollback_trigger_precondition_enforced(self) -> None:
        """触发前提校验：阶段不符即拦截，防止误回退。"""
        task = TaskState(task_id="t")
        task.phase = ReasoningPhase.THINK
        with pytest.raises(GuardViolation):
            rollback_for(task, "generation_verification")  # THINK 非 VERIFY/OBSERVE
        with pytest.raises(GuardViolation):
            rollback_for(task, "execution_plan")  # THINK 非 ACT/OBSERVE

    def test_rollback_unknown_rule(self) -> None:
        task = TaskState(task_id="t")
        with pytest.raises(ValueError):
            rollback_for(task, "no_such_rule")

    def test_gate_guard_prior_searched(self) -> None:
        """生成-先验约束（READY 门）：未检索先验即拦截，检索后放行。"""
        with pytest.raises(GuardViolation):
            assert_gate(Gate.READY, {})
        assert_gate(Gate.READY, {"prior_searched": True})

    def test_gate_guard_audit_trace(self) -> None:
        """复盘-数据溯源（CLOSE 门）：审计日志不完整即拦截。"""
        with pytest.raises(GuardViolation):
            assert_gate(Gate.CLOSE, {"audit_log_complete": False})
        assert_gate(Gate.CLOSE, {"audit_log_complete": True})

    def test_gate_guard_unregistered_passes(self) -> None:
        """未注册谓词的门一律放行（放行优先）。"""
        assert_gate(Gate.START, {})
        assert_gate(Gate.GAP, {})


# ═══════════════════════════════════════════════════════════════
# 6. 完整性自检与接线
# ═══════════════════════════════════════════════════════════════


class TestCompleteMapping:
    def test_assert_complete_mapping_passes(self) -> None:
        """完整性自检通过：门序/60 态/九角色/四制衡/五策略/五相克闭合。"""
        assert_complete_mapping()

    def test_lifecycle_graph_build_includes_check(self) -> None:
        """生命周期图构建期触发完整性自检（fail-fast 接线）。"""
        g = build_agent_lifecycle_graph()
        assert g.entry_point == "init"
        assert "reflect" in g.nodes

    def test_register_gate_guard_roundtrip(self) -> None:
        """注册谓词后门守卫生效；恢复后不污染全局表。"""
        from openkitsune.agent import lifecycle_constraints as lc

        saved = lc._GUARD_PREDICATES.get(Gate.START)
        lc.register_gate_guard(Gate.START, lambda ctx: False)
        try:
            with pytest.raises(GuardViolation):
                assert_gate(Gate.START, {})
        finally:
            if saved is None:
                lc._GUARD_PREDICATES.pop(Gate.START, None)
            else:
                lc._GUARD_PREDICATES[Gate.START] = saved
        assert_gate(Gate.START, {})  # 恢复后放行


# ═══════════════════════════════════════════════════════════════
# 7. 门序语义边界（引入风险推演修复：入口/中断阶段）
# ═══════════════════════════════════════════════════════════════


class TestSemanticEdgeCases:
    def test_awaiting_user_keeps_progressing_lifecycle(self) -> None:
        """执行中等待用户：中断阶段与进行中生命周期语义一致（P2 修复）。"""
        assert semantic_consistent(TaskLifecycleState.EXECUTING, ReasoningPhase.AWAITING_USER)
        assert semantic_consistent(TaskLifecycleState.VERIFYING, ReasoningPhase.AWAITING_USER)
        assert semantic_consistent(TaskLifecycleState.STALLED, ReasoningPhase.AWAITING_USER)

    def test_idle_consistent_with_entry_only(self) -> None:
        """入口阶段：仅与未终态生命周期一致（初始/进行中）。"""
        assert semantic_consistent(TaskLifecycleState.RECEIVED, ReasoningPhase.IDLE)
        assert semantic_consistent(TaskLifecycleState.EXECUTING, ReasoningPhase.IDLE)
        # 终态冲突：任务已完成/失败/取消时不应处于 IDLE
        assert not semantic_consistent(TaskLifecycleState.DONE, ReasoningPhase.IDLE)
        assert not semantic_consistent(TaskLifecycleState.FAILED, ReasoningPhase.IDLE)
        assert not semantic_consistent(TaskLifecycleState.CANCELLED, ReasoningPhase.IDLE)

    def test_derive_lifecycle_none_for_non_progressing(self) -> None:
        """入口/中断阶段无推进门映射：返回 None，不得误打回 RECEIVED（P1 修复）。"""
        assert derive_lifecycle_for(ReasoningPhase.IDLE) is None
        assert derive_lifecycle_for(ReasoningPhase.AWAITING_USER) is None

    def test_derive_lifecycle_progressing_only(self) -> None:
        """仅推进阶段可推导生命周期（6 段全覆盖，无遗漏）。"""
        non_progressing = {ReasoningPhase.IDLE, ReasoningPhase.AWAITING_USER}
        progressing = [p for p in ReasoningPhase if p not in non_progressing]
        assert len(progressing) == 6
        mapped = [derive_lifecycle_for(p) for p in progressing]
        assert None not in mapped
        assert len({lc for lc in mapped}) == 6  # 6 段推得 6 个不同生命周期


# ═══════════════════════════════════════════════════════════════
# 8. 运行时接入：apply_rollback_to / advance_guarded
# ═══════════════════════════════════════════════════════════════


class TestRuntimeIntegration:
    def test_apply_rollback_to_syncs_phase_and_lifecycle(self) -> None:
        """一体化回退：阶段强制回退 + 生命周期门序同步。"""
        st = TaskState(task_id="t")
        st.transition(ReasoningPhase.COMPILING)
        st.transition(ReasoningPhase.THINK)
        st.transition(ReasoningPhase.ACT)
        st.transition(ReasoningPhase.OBSERVE)
        st.transition(ReasoningPhase.VERIFY)  # → VERIFYING
        assert st.lifecycle is TaskLifecycleState.VERIFYING

        target = apply_rollback_to(st, "generation_verification")
        assert target is ReasoningPhase.THINK
        assert st.phase is ReasoningPhase.THINK
        assert st.lifecycle is TaskLifecycleState.WAITING_DEPS  # 同步回退

    def test_apply_rollback_to_reparse(self) -> None:
        """一体化回退：产物越界 → COMPILING + PLANNING。"""
        st = TaskState(task_id="t")
        st.lifecycle = TaskLifecycleState.VERIFYING
        st.phase = ReasoningPhase.VERIFY
        target = apply_rollback_to(st, "verification_intent")
        assert target is ReasoningPhase.COMPILING
        assert st.phase is ReasoningPhase.COMPILING
        assert st.lifecycle is TaskLifecycleState.PLANNING

    def test_apply_rollback_to_keeps_lifecycle_on_unknown_rule(self) -> None:
        """未知规则拒绝（ValueError）。"""
        st = TaskState(task_id="t")
        with pytest.raises(ValueError):
            apply_rollback_to(st, "no_such_rule")

    def test_advance_guarded_ready_requires_prior(self) -> None:
        """守卫推进：READY 门要求先验检索，缺失即拦截（推进不落地）。"""
        st = TaskState(task_id="t")  # IDLE
        with pytest.raises(GuardViolation):
            advance_guarded(st, ReasoningPhase.COMPILING, {})  # 无 prior_searched
        assert st.phase is ReasoningPhase.IDLE  # 推进未落地（守卫先行）

    def test_advance_guarded_passes_with_prior(self) -> None:
        """守卫推进：先验检索后推进成功，生命周期同步。"""
        st = TaskState(task_id="t")
        advance_guarded(st, ReasoningPhase.COMPILING, {"prior_searched": True})
        assert st.phase is ReasoningPhase.COMPILING
        assert st.lifecycle is TaskLifecycleState.PLANNING

    def test_advance_guarded_illegal_move_rejected(self) -> None:
        """守卫推进：非法迁移（THINK→COMPILING）仍被迁移表拒绝。"""
        st = TaskState(task_id="t")
        st.transition(ReasoningPhase.THINK)  # 直接走真实推进（READY 门未注册之外的门放行）
        with pytest.raises(ValueError):
            advance_guarded(st, ReasoningPhase.COMPILING, {"prior_searched": True})
        assert st.phase is ReasoningPhase.THINK
