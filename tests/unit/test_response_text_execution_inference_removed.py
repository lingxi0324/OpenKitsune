"""Response wording must not be treated as evidence that a tool ran."""

from __future__ import annotations

import pytest

from openkitsune.agent.reasoning import ReasoningEngine
from openkitsune.tools.tool_result import mutation_effect


@pytest.mark.parametrize(
    "text",
    [
        "已发送结果到群里。",
        "write_file 已调用。",
        "已通过 read_file 工具验证。",
        "请确认邮件是否已发送。",
        "代码中的 status = '已发送' 表示成功。",
        "已通过网络查询确认 [来源:工具]。",
        "```tool_call\norg_accept_deliverable(task_chain_id='x')\n```",
    ],
)
def test_guard_evaluation_does_not_infer_execution_from_response_text(text: str) -> None:
    engine = ReasoningEngine.__new__(ReasoningEngine)

    verdicts = engine.evaluate_decision(text, tool_results=None)

    guard_names = [verdict.guard for verdict in verdicts]
    assert guard_names == [
        "tool_failure_ack",
        "waiting_for_user",
        "recoverable_tool_issue",
    ]
    assert "source_tag" not in guard_names
    assert "unbacked_action" not in guard_names


def test_runtime_tool_summary_uses_results_and_structured_effects() -> None:
    evidence = ReasoningEngine.summarize_tool_execution(
        [
            {
                "tool_name": "write_file",
                "is_error": False,
                "metadata": {"effects": [mutation_effect(action="write", target="file")]},
            },
            {"tool_name": "deliver_artifacts", "is_error": True},
        ]
    )

    assert evidence == {
        "total": 2,
        "succeeded": ["write_file"],
        "failed": ["deliver_artifacts"],
        "effect_actions": ["write"],
    }
