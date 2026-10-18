"""Canonical ReasoningEngine driven by ``runtime.state_graph.StateGraph``.

The public class uses the complete private runtime loop and wires a
:class:`StateGraph` on top to make Decision-to-node routing explicit. It also
composes the extracted guards and tool filters into engine methods.
"""

from __future__ import annotations

import logging
from typing import Any

from openkitsune.agent.lifecycle_constraints import (
    assert_routing_coverage,
    assert_routing_functional,
)
from openkitsune.agent.route_derivation import (
    assert_derivation_equivalent,
    derive_decision_to_label,
)
from openkitsune.core._reasoning_runtime import (
    Checkpoint,
    Decision,
    DecisionType,
    _execute_riskgate_tool_confirmation,
    _open_riskgate_tool_confirmation,
)
from openkitsune.core._reasoning_runtime import (
    ReasoningEngine as _RuntimeReasoningBase,
)
from openkitsune.runtime.state_graph import END, START, StateGraph
from openkitsune.runtime.state_graph.guards.conversation_state import (
    has_recoverable_tool_issue,
    looks_like_waiting_for_user_response,
)
from openkitsune.runtime.state_graph.guards.tool_failure_ack import (
    check_tool_failure_acknowledgement,
)
from openkitsune.runtime.state_graph.guards.tool_filters import (
    filter_tools_by_mode,
    get_mode_ruleset,
    is_shell_write_command,
    should_block_tool,
)
from openkitsune.tools.tool_result import successful_tool_effect_actions

__all__ = [
    "Checkpoint",
    "Decision",
    "DecisionType",
    "GuardVerdict",
    "ReasoningEngine",
    "_execute_riskgate_tool_confirmation",
    "_open_riskgate_tool_confirmation",
    "build_reasoning_graph",
    "get_mode_ruleset",
    "is_shell_write_command",
]

logger = logging.getLogger(__name__)

# Reasoning node ids (ReAct phases plus task verification + finalize).
NODE_REASON = "reason"
NODE_ACT = "act"
NODE_OBSERVE = "observe"
NODE_VERIFY = "verify"
NODE_FINALIZE = "finalize"

# Routing label map derived from decision-intent signatures (route_derivation).
# 逐条手写路由已替换为『意图签名 + 处置规则』推导；构建期断言严格等价，
# 行为与原字面表零变化。新决策词汇只需在 route_derivation._DECISION_INTENT
# 声明意图，路由自动归位（不重复设计）。
_DECISION_TO_LABEL: dict[str, str] = derive_decision_to_label()

# 构建期自检：推导表与既有行为等价 + 完备（全词可达）+ 函数性（无悬空节点）
assert_derivation_equivalent()


class GuardVerdict:
    """Lightweight result bag for :meth:`ReasoningEngine.evaluate_decision`."""

    __slots__ = ("guard", "passed", "message")

    def __init__(self, guard: str, passed: bool, message: str | None) -> None:
        self.guard = guard
        self.passed = passed
        self.message = message

    def __repr__(self) -> str:
        return (
            f"GuardVerdict(guard={self.guard!r}, passed={self.passed!r}, message={self.message!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GuardVerdict):
            return NotImplemented
        return (
            self.guard == other.guard
            and self.passed == other.passed
            and self.message == other.message
        )


def _decision_kind(result: Any) -> str:
    """Best-effort extraction of the decision's ``DecisionType.value``."""
    if result is None:
        return ""
    if hasattr(result, "type"):
        dt = result.type
        return getattr(dt, "value", str(dt))
    if hasattr(result, "value"):
        return result.value
    return str(result)


# 制衡/递生守卫：实现与词根常量下沉至 core/_reasoning_runtime.py（单一事实源），
# 运行时主循环在决策分发点强制调用；此处仅复用同一实现，避免重复设计。
# 语义约定（True = 通过）：_no_self_verify 禁止产出+验证同现（自证嫌疑）；
# _feedforward_complete 要求前序工具产物完整可消费（空产物拦截、失败放行）。
from openkitsune.core._reasoning_runtime import (
    _feedforward_complete,
    _no_self_verify,
)


def build_reasoning_graph() -> StateGraph:
    """Construct the canonical reasoning :class:`StateGraph`.

    Topology: ``START -> reason``; ``reason`` branches by Decision
    (``act``/``verify``/``finalize``/loop ``reason``); ``act -> observe
    -> reason`` (tool-result loopback); ``verify`` branches by
    verifier verdict (``finalize`` or ``reason``); ``finalize -> END``.
    Validated before return.
    """
    g = StateGraph()
    for node in (NODE_REASON, NODE_ACT, NODE_OBSERVE, NODE_VERIFY, NODE_FINALIZE):
        g.add_node(node)
    g.add_edge(START, NODE_REASON)

    def _route_from_reason(result: Any) -> str:
        return _DECISION_TO_LABEL.get(_decision_kind(result), NODE_REASON)

    g.add_conditional_edges(
        NODE_REASON,
        _route_from_reason,
        {
            "act": NODE_ACT,
            "verify": NODE_VERIFY,
            "finalize": NODE_FINALIZE,
            "reason": NODE_REASON,
        },
    )
    g.add_edge(NODE_ACT, NODE_OBSERVE)
    g.add_edge(NODE_OBSERVE, NODE_REASON)

    def _route_from_verify(result: Any) -> str:
        return "reason" if _decision_kind(result) == "verify_incomplete" else "finalize"

    g.add_conditional_edges(
        NODE_VERIFY,
        _route_from_verify,
        {"finalize": NODE_FINALIZE, "reason": NODE_REASON},
    )
    g.add_edge(NODE_FINALIZE, END)
    g.validate()
    # 完备/归位可推导：路由表须覆盖全部已知决策词汇且无悬空目标，
    # 未知决策不得静默落入默认分支（fail-fast 于构建期）。
    assert_routing_coverage(_DECISION_TO_LABEL, {dt.value for dt in DecisionType})
    assert_routing_functional(_DECISION_TO_LABEL)
    return g


class ReasoningEngine(_RuntimeReasoningBase):
    """Canonical ReAct engine with explicit :class:`StateGraph` routing.

    Inherits the canonical ``reason_stream`` loop, its non-streaming ``run``
    event consumer, and shared helpers such as ``release_large_buffers``
    from :class:`openkitsune.core._reasoning_runtime.ReasoningEngine`
    as its private implementation. The public additions are
    :attr:`decision_graph`, :meth:`route_decision`,
    :meth:`evaluate_decision`, :meth:`filter_tools`,
    :meth:`should_block`, and :meth:`describe_routing`.

    Honest scope: the event loop does not yet consume :attr:`decision_graph`.
    The graph remains an introspection and extension point for callers.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._decision_graph = build_reasoning_graph()

    # ----- StateGraph wiring -----------------------------------------

    @property
    def decision_graph(self) -> StateGraph:
        """Constructed reasoning :class:`StateGraph` for this engine."""
        return self._decision_graph

    async def route_decision(self, current_node: str, decision: Decision | None) -> str | None:
        """Look up the next node id given ``current_node`` and ``decision``."""
        return await self._decision_graph.route(current_node, decision)

    # ----- Tool trimming ---------------------------------------------

    def filter_tools(
        self,
        tools: list[dict],
        *,
        mode: str,
    ) -> list[dict]:
        """Apply mode permissions without a second intent-based schema trim."""
        return filter_tools_by_mode(tools, mode)

    def should_block(
        self,
        tool_name: str,
        tool_input: Any,
        allowed_tool_names: set[str] | None,
        mode: str,
    ) -> str | None:
        """Public wrapper around :func:`should_block_tool`."""
        return should_block_tool(tool_name, tool_input, allowed_tool_names, mode)

    # ----- Guard evaluation ------------------------------------------

    @staticmethod
    def summarize_tool_execution(tool_results: list[dict] | None) -> dict[str, Any]:
        """Return execution facts derived only from runtime tool results."""
        results = [result for result in (tool_results or []) if isinstance(result, dict)]
        succeeded = [
            result.get("tool_name") or result.get("name") or ""
            for result in results
            if not result.get("is_error")
        ]
        failed = [
            result.get("tool_name") or result.get("name") or ""
            for result in results
            if result.get("is_error")
        ]
        return {
            "total": len(results),
            "succeeded": [name for name in succeeded if name],
            "failed": [name for name in failed if name],
            "effect_actions": sorted(successful_tool_effect_actions(results)),
        }

    def evaluate_decision(
        self,
        text: str,
        *,
        last_user_text: str = "",
        tool_results: list[dict] | None = None,
        recent_messages: list[dict] | None = None,
    ) -> list[GuardVerdict]:
        """Evaluate guards without inferring tool execution from response wording.

        Returns a list of :class:`GuardVerdict`; a caller can
        short-circuit on the first ``passed=False`` to mirror the
        previous in-line behaviour.
        """
        verdicts: list[GuardVerdict] = []
        logger.debug("Runtime tool evidence: %s", self.summarize_tool_execution(tool_results))

        ack_msg = check_tool_failure_acknowledgement(text, tool_results)
        verdicts.append(GuardVerdict("tool_failure_ack", ack_msg is None, ack_msg))

        waiting = looks_like_waiting_for_user_response(text)
        verdicts.append(
            GuardVerdict(
                "waiting_for_user",
                not waiting,
                "waiting for user" if waiting else None,
            )
        )

        recoverable = has_recoverable_tool_issue(tool_results)
        verdicts.append(GuardVerdict("recoverable_tool_issue", True, f"recoverable={recoverable}"))

        return verdicts

    def evaluate_constraint_guards(
        self,
        text: str,
        tool_results: list[dict] | None = None,
    ) -> list[GuardVerdict]:
        """评估内在约束守卫（制衡 + 递生），独立于既有守卫契约。

        设计说明：``evaluate_decision`` 的守卫集是封闭契约
        （tests/unit/test_response_text_execution_inference_removed.py
        断言其守卫名列表精确为 3 条，且守卫不得从响应文本推断执行）。
        故内在约束守卫由本方法独立承载，调用方可按需组合：

        - ``no_self_verify``（制衡）：产出声明与验证声明同现 ⇒ 自证嫌疑；
        - ``feedforward_complete``（递生）：前序工具执行产物须完整可消费。
        """
        verdicts: list[GuardVerdict] = []

        self_verify_ok = _no_self_verify(text)
        verdicts.append(
            GuardVerdict(
                "no_self_verify",
                self_verify_ok,
                "self-verification suspected" if not self_verify_ok else None,
            )
        )

        feedforward_ok = _feedforward_complete(tool_results)
        verdicts.append(
            GuardVerdict(
                "feedforward_complete",
                feedforward_ok,
                "incomplete tool product" if not feedforward_ok else None,
            )
        )

        return verdicts

    # ----- Convenience helpers ---------------------------------------

    def classify_exit_reason(self, decision: Decision | None) -> str:
        """Map a ``Decision`` to the previous ``_last_exit_reason`` token.

        Mirrors the if/elif cascade the previous ``run()`` performs at
        loop termination so v2 callers can derive the same exit token
        without re-implementing the mapping.
        """
        kind = _decision_kind(decision)
        if kind == "ask_user":
            return "ask_user"
        if kind == "max_iterations":
            return "max_iterations"
        if kind == "verify_incomplete":
            return "verify_incomplete"
        if kind == "error":
            return "loop_terminated"
        return "normal"

    def is_terminal_decision(self, decision: Decision | None) -> bool:
        """True when the decision routes straight to ``finalize``."""
        return _DECISION_TO_LABEL.get(_decision_kind(decision), "") == "finalize"

    def supports_decision_kind(self, kind: str) -> bool:
        """True when ``kind`` is in the engine's routing table.

        Useful for the parity test which asserts the v1 and v2 engines
        accept the same Decision vocabulary.
        """
        return kind in _DECISION_TO_LABEL

    # ----- Debug / introspection -------------------------------------

    def describe_routing(self) -> dict[str, Any]:
        """Return a JSON-friendly snapshot of the reasoning graph topology."""
        return {
            "entry_point": self._decision_graph.entry_point,
            "nodes": sorted(self._decision_graph.nodes),
            "successors": {
                n: self._decision_graph.successors(n) for n in sorted(self._decision_graph.nodes)
            },
        }
