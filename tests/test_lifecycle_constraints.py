"""Agent 流程/推理逻辑整改（河洛内在约束层）回归测试。

覆盖六项内在性质：
1. 唯一 —— 双维度状态编码奇偶一致性（80 组合 → 40 合法，非法拒绝）；
2. 闭环 —— 生命周期图补 reflect 复盘节点后拓扑可达、无断头/孤立；
3. 完备 —— 推理路由表覆盖全部已知决策词汇、无悬空目标；
4. 递生 —— 前序工具产物完整回传（空产物拦截、失败结果放行）；
5. 制衡 —— 产出+验证不得同源自证；三角校验环相位/异源约束；
6. 回归 —— 既有迁移表与守卫行为不变、生命周期图描述含 reflect。
"""

from __future__ import annotations

import pytest

from openkitsune.agent.core import build_agent_lifecycle_graph
from openkitsune.agent.lifecycle_constraints import (
    GuardViolation,
    StateCode,
    StateConstraintError,
    TriadPhase,
    TriadValidator,
    assert_valid,
    is_valid,
    valid_codes,
)
from openkitsune.agent.reasoning import (
    _DECISION_TO_LABEL,
    _feedforward_complete,
    _no_self_verify,
    build_reasoning_graph,
)
from openkitsune.agent.state import ReasoningPhase, TaskState
from openkitsune.runtime.models import TaskLifecycleState


# ═══════════════════════════════════════════════════════════════
# 1. 唯一：双维度奇偶一致性
# ═══════════════════════════════════════════════════════════════


class TestStateUniqueness:
    def test_legal_state_count(self) -> None:
        """10×8=80 组合中恰有 40 个奇偶一致合法态（不残缺不重复）。"""
        codes = valid_codes()
        assert len(codes) == 40
        assert len({c.label for c in codes}) == 40  # 无重复

    def test_illegal_pair_rejected(self) -> None:
        """非法组合（奇偶不一致）即拒绝。"""
        for lc in TaskLifecycleState:
            for ph in ReasoningPhase:
                if is_valid(lc, ph):
                    continue
                with pytest.raises(StateConstraintError):
                    assert_valid(lc, ph)

    def test_state_code_parity(self) -> None:
        """StateCode.parity_consistent 与 is_valid 一致。"""
        for lc in TaskLifecycleState:
            for ph in ReasoningPhase:
                assert StateCode(lc, ph).parity_consistent == is_valid(lc, ph)

    def test_task_state_code_derived(self) -> None:
        """TaskState.state_code 为只读派生双维度编码。"""
        st = TaskState(task_id="t1")
        st.lifecycle = TaskLifecycleState.EXECUTING
        st.phase = ReasoningPhase.ACT
        assert st.state_code == "executing.act"


# ═══════════════════════════════════════════════════════════════
# 2. 闭环：生命周期拓扑
# ═══════════════════════════════════════════════════════════════


class TestLifecycleClosure:
    def test_graph_has_reflect(self) -> None:
        """整改后生命周期图含 reflect 复盘节点，finalize 必经复盘再收束。"""
        g = build_agent_lifecycle_graph()
        assert "reflect" in g.nodes
        assert g.successors("finalize") == ["reflect"]
        assert g.successors("reflect") == ["__end__"]

    def test_all_nodes_reachable(self) -> None:
        """闭环：从入口可达全部节点（无孤立/断头）。"""
        from openkitsune.agent.lifecycle_constraints import validate_closure

        g = build_agent_lifecycle_graph()
        unreachable, dead_ends = validate_closure(g)
        assert unreachable == set()
        assert dead_ends == set()

    def test_entry_to_end_path_visits_reflect(self) -> None:
        """唯一收敛路径须经 reflect：终而复始、复盘显式化。"""
        g = build_agent_lifecycle_graph()
        assert g.successors("run_loop") == ["finalize"]
        assert g.successors("finalize") == ["reflect"]
        assert g.successors("reflect") == ["__end__"]


# ═══════════════════════════════════════════════════════════════
# 3. 完备 / 归位可推导：推理路由表
# ═══════════════════════════════════════════════════════════════


class TestRoutingCompleteness:
    def test_graph_build_passes_coverage(self) -> None:
        """路由覆盖校验内嵌于图构建：全部已知决策词汇必有归宿。"""
        g = build_reasoning_graph()  # 覆盖/函数性校验在构建期 fail-fast
        assert g.entry_point == "reason"

    def test_routing_table_functional(self) -> None:
        """路由表无悬空目标、键均为非空字符串。"""
        for key, target in _DECISION_TO_LABEL.items():
            assert key and target


# ═══════════════════════════════════════════════════════════════
# 4. 递生：产物契约守卫
# ═══════════════════════════════════════════════════════════════


class TestFeedforward:
    def test_guard_passes_complete_product(self) -> None:
        assert _feedforward_complete(
            [{"tool_name": "read", "output": "data"}]
        ) is True

    def test_guard_rejects_empty_product(self) -> None:
        assert _feedforward_complete(
            [{"tool_name": "read", "output": None, "content": None, "result": None}]
        ) is False

    def test_guard_allows_failed_tool(self) -> None:
        """失败结果不算递生断裂（由故障守卫另行处理）。"""
        assert _feedforward_complete(
            [{"tool_name": "bash", "is_error": True}]
        ) is True

    def test_guard_allows_no_tools(self) -> None:
        assert _feedforward_complete([]) is True
        assert _feedforward_complete(None) is True


# ═══════════════════════════════════════════════════════════════
# 5. 制衡：禁止自证 + 三角校验环
# ═══════════════════════════════════════════════════════════════


class TestCheckAndBalance:
    def test_no_self_verify_blocks(self) -> None:
        """产出+验证同现 ⇒ 自证嫌疑拦截。"""
        assert _no_self_verify("我已经实现了该功能，并已测试通过") is False

    def test_no_self_verify_allows_separate(self) -> None:
        assert _no_self_verify("功能实现完成") is True
        assert _no_self_verify("验证通过，结果如下") is True

    def test_triad_cycle_normal(self) -> None:
        v = TriadValidator()
        v.submit(TriadPhase.PRODUCE, "agent_a")
        v.submit(TriadPhase.VERIFY, "agent_b")
        v.submit(TriadPhase.CHALLENGE, "agent_c")
        assert v.rounds == 1

    def test_triad_phase_duplicate_blocked(self) -> None:
        v = TriadValidator()
        v.submit(TriadPhase.PRODUCE, "a")
        with pytest.raises(GuardViolation):
            v.submit(TriadPhase.PRODUCE, "b")

    def test_triad_same_source_blocked(self) -> None:
        """产出/验证/质询三方必须异源。"""
        v = TriadValidator()
        v.submit(TriadPhase.PRODUCE, "a")
        v.submit(TriadPhase.VERIFY, "b")
        with pytest.raises(GuardViolation):
            v.submit(TriadPhase.CHALLENGE, "a")  # 与产出一源


# ═══════════════════════════════════════════════════════════════
# 6. 回归：既有行为不变
# ═══════════════════════════════════════════════════════════════


class TestRegression:
    def test_phase_transition_table_unchanged(self) -> None:
        """ReasoningPhase 合法迁移表保持原状。"""
        st = TaskState(task_id="t")
        st.phase = ReasoningPhase.THINK
        st.transition(ReasoningPhase.ACT)
        assert st.phase is ReasoningPhase.ACT
        with pytest.raises(ValueError):
            st.transition(ReasoningPhase.IDLE)  # ACT→IDLE 非法（原行为）

    def test_phase_transitions_derived_equivalent(self) -> None:
        """源代码替换：迁移表由内在规则推导生成，与既有字面表严格等价。"""
        from openkitsune.agent.state import (
            _VALID_PHASE_TRANSITIONS,
            _derive_phase_transitions,
        )

        # 原逐条字面表（行为基线）
        expected = {
            ReasoningPhase.IDLE: frozenset(
                {ReasoningPhase.COMPILING, ReasoningPhase.THINK, ReasoningPhase.DONE}
            ),
            ReasoningPhase.COMPILING: frozenset(
                {ReasoningPhase.THINK, ReasoningPhase.DONE}
            ),
            ReasoningPhase.THINK: frozenset(
                {
                    ReasoningPhase.ACT,
                    ReasoningPhase.VERIFY,
                    ReasoningPhase.AWAITING_USER,
                    ReasoningPhase.DONE,
                }
            ),
            ReasoningPhase.ACT: frozenset(
                {ReasoningPhase.OBSERVE, ReasoningPhase.AWAITING_USER, ReasoningPhase.DONE}
            ),
            ReasoningPhase.OBSERVE: frozenset(
                {ReasoningPhase.THINK, ReasoningPhase.VERIFY, ReasoningPhase.DONE}
            ),
            ReasoningPhase.VERIFY: frozenset(
                {ReasoningPhase.DONE, ReasoningPhase.THINK}
            ),
            ReasoningPhase.AWAITING_USER: frozenset(
                {ReasoningPhase.THINK, ReasoningPhase.DONE}
            ),
            ReasoningPhase.DONE: frozenset({ReasoningPhase.IDLE}),
        }
        assert _derive_phase_transitions() == expected
        assert _VALID_PHASE_TRANSITIONS == expected

    def test_derived_transition_table_closed(self) -> None:
        """推导表闭环：全部 8 态均有出边（无断头），DONE 唯一回 IDLE。"""
        from openkitsune.agent.state import _VALID_PHASE_TRANSITIONS

        for phase in ReasoningPhase:
            assert _VALID_PHASE_TRANSITIONS[phase], f"{phase} 无出边（断头）"
        assert _VALID_PHASE_TRANSITIONS[ReasoningPhase.DONE] == frozenset(
            {ReasoningPhase.IDLE}
        )

    def test_evaluate_decision_contract_unchanged(self) -> None:
        """evaluate_decision 守卫契约不变：正常上下文仍恰为 3 条既有守卫。"""
        from unittest import mock

        from openkitsune.agent.reasoning import ReasoningEngine

        with mock.patch.object(ReasoningEngine, "__init__", lambda self, *a, **k: None):
            engine = ReasoningEngine()
            verdicts = engine.evaluate_decision(
                "完成实现，结果见回复",
                tool_results=[{"tool_name": "read", "output": "ok"}],
            )
        assert [v.guard for v in verdicts] == [
            "tool_failure_ack",
            "waiting_for_user",
            "recoverable_tool_issue",
        ]

    def test_constraint_guards_catch_self_verify(self) -> None:
        """独立约束守卫：产出+验证同现 ⇒ no_self_verify 拦截。"""
        from unittest import mock

        from openkitsune.agent.reasoning import ReasoningEngine

        with mock.patch.object(ReasoningEngine, "__init__", lambda self, *a, **k: None):
            engine = ReasoningEngine()
            verdicts = engine.evaluate_constraint_guards("实现完成，并已测试通过")
        by_name = {v.guard: v for v in verdicts}
        assert by_name["no_self_verify"].passed is False
        assert by_name["feedforward_complete"].passed is True

    def test_constraint_guards_normal_pass(self) -> None:
        from unittest import mock

        from openkitsune.agent.reasoning import ReasoningEngine

        with mock.patch.object(ReasoningEngine, "__init__", lambda self, *a, **k: None):
            engine = ReasoningEngine()
            verdicts = engine.evaluate_constraint_guards(
                "分析完成，结论如下",
                tool_results=[{"tool_name": "read", "output": "data"}],
            )
        assert [v.guard for v in verdicts] == ["no_self_verify", "feedforward_complete"]
        assert all(v.passed for v in verdicts)
