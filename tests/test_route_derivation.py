"""路由推导模块测试：等价锁定 + 完备/函数性 + 扩展性 + 运行时一致。"""

from __future__ import annotations

import pytest

from openkitsune.agent.reasoning import _DECISION_TO_LABEL, build_reasoning_graph
from openkitsune.agent.route_derivation import (
    ACT,
    FINALIZE,
    REASON,
    VERIFY,
    DecisionIntent,
    LEGACY_DECISION_TO_LABEL,
    assert_derivation_equivalent,
    derive_decision_to_label,
    derive_label_for_word,
)


class TestDerivationEquivalent:
    """推导表与既有字面表严格等价（行为零变化）。"""

    def test_table_equals_legacy(self) -> None:
        assert_derivation_equivalent()

    def test_every_word_maps_to_legacy_label(self) -> None:
        derived = derive_decision_to_label()
        for word, label in LEGACY_DECISION_TO_LABEL.items():
            assert derived[word] == label, word

    def test_no_extra_or_missing_keys(self) -> None:
        derived = derive_decision_to_label()
        assert set(derived) == set(LEGACY_DECISION_TO_LABEL)

    def test_matches_runtime_table(self) -> None:
        """reasoning.py 运行时事实源与推导表一致（替换真正生效）。"""
        assert _DECISION_TO_LABEL == derive_decision_to_label()


class TestClosureAndFunctionality:
    """完备性（全词有路由）+ 函数性（全节点可达，无悬空）。"""

    def test_all_words_have_target(self) -> None:
        derived = derive_decision_to_label()
        assert all(label in {ACT, VERIFY, FINALIZE, REASON} for label in derived.values())

    def test_all_nodes_reachable(self) -> None:
        reachable = set(derive_decision_to_label().values())
        assert reachable == {ACT, VERIFY, FINALIZE, REASON}

    def test_single_word_lookup(self) -> None:
        assert derive_label_for_word("tool_calls") == ACT
        assert derive_label_for_word("final_answer") == VERIFY
        assert derive_label_for_word("verify_incomplete") == REASON
        assert derive_label_for_word("unknown_word") is None


class TestExtensibility:
    """新增决策词汇只需声明意图，路由由规则推导（不重复设计）。"""

    def test_new_word_via_intent_declaration(self) -> None:
        intent_map = {
            "tool_calls": DecisionIntent.EXECUTE,
            "final_answer": DecisionIntent.PRODUCE_RESULT,
            "new_abort_word": DecisionIntent.ABORT,
        }
        derived = derive_decision_to_label(intent_map)
        assert derived["new_abort_word"] == FINALIZE
        assert derived["tool_calls"] == ACT
        assert derived["final_answer"] == VERIFY


class TestGraphIntegration:
    """推导表接入推理图后路由行为不变（闭环/完备的运行时侧验证）。"""

    @pytest.mark.asyncio
    async def test_graph_route_unchanged(self) -> None:
        graph = build_reasoning_graph()

        async def route(kind: str) -> str | None:
            return await graph.route(
                "reason", type("D", (), {"value": kind})()
            )

        assert await route("tool_calls") == "act"
        assert await route("final_answer") == "verify"
        assert await route("tool_use") == "act"
        assert await route("ask_user") == "finalize"
        assert await route("continue") == "reason"
        assert await route("error") == "finalize"
        assert await route("max_iterations") == "finalize"
        assert await route("verify_incomplete") == "reason"
