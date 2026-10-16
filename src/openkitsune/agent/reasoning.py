"""Canonical ReasoningEngine driven by ``runtime.state_graph.StateGraph``.

The public class uses the complete private runtime loop and wires a
:class:`StateGraph` on top to make Decision-to-node routing explicit. It also
composes the extracted guards and tool filters into engine methods.
"""

from __future__ import annotations

import logging
from typing import Any

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

# Routing label map keyed off ``DecisionType.value`` strings.
_DECISION_TO_LABEL: dict[str, str] = {
    # Real DecisionType.value strings from the runtime enum.
    "tool_calls": "act",
    "final_answer": "verify",
    # Extended exit-reason tokens used by ``_last_exit_reason``.
    # Not DecisionType values, but the routing map accepts them so a
    # caller can pass either form.
    "tool_use": "act",
    "ask_user": "finalize",
    "continue": "reason",
    "error": "finalize",
    "max_iterations": "finalize",
    "verify_incomplete": "reason",
}


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
