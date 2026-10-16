"""上一轮迭代审视：把"已完成的工作 + 自我审视"转成模拟用户反馈，作为下一轮锚点。

设计目标（对标用户视角的持续反馈回路）：

- 模型在长任务中会"忘记自己做过什么、做得怎么样"，导致重复调用、无效探索；
- 仅仅注入工具结果摘要（迭代结论）不够——模型不会主动审视"上一轮是否
  有重复/无效/停滞"，也不会把审视结果作为下一步的行为约束；
- 本模块把上一轮的工具调用结论与**规则化自我审视**（重复调用、结果无效、
  只读停滞）组合成一条 **role="user" 的"模拟用户反馈"消息**：模型天然更重视
  "用户"说的话，把它作为下一轮工具调用的锚点与约束。

消息示例：
```
[上一轮审视 · 请以此为锚点规划下一步]
已完成：迭代4：get_tool_info：Tool: get_memory_stats Status : DEFERRED...；list_directory：...
审视发现：
- 工具 get_tool_info(get_memory_stats) 已调用 4 次，结果均为 DEFERRED（无效）
- 已连续 4 轮只读探索，未取得实质推进
建议：
- 直接调用 get_memory_stats（已由 tool_search 激活），不要再查询状态
```

纯规则生成（零 LLM 延迟）；无问题时给出正向反馈，不制造噪音。
"""

from __future__ import annotations

__all__ = ["build_review_message"]

# 只读探索类工具（与 loop_budget.READONLY_EXPLORATION_TOOLS 保持一致）
_READONLY_TOOLS = frozenset(
    {
        "read_file",
        "list_directory",
        "grep",
        "glob",
        "web_fetch",
        "web_search",
        "news_search",
        "get_tool_info",
        "list_skills",
        "get_skill_info",
        "search_memory",
        "get_memory_stats",
        "get_session_context",
        "tool_search",
    }
)

# 与 _tool_result_validation 的问题类型标签一致
_ISSUE_LABELS = {
    "error": "执行失败",
    "deferred": "返回 DEFERRED 占位而非实际数据",
    "empty": "返回空结果",
    "noop": "仅返回成功标志无实际数据",
}


def _repeat_summary(
    tool_name_counts: dict[str, int], tool_argv_counts: dict[str, int]
) -> list[str]:
    """从任务内计数器中提炼"重复调用"问题。

    只对"同工具同参数"（精确重复）做低阈值提示；对"同名不同参"的只读
    探索（如 get_skill_info 查 3 个不同技能）属于合理探查，仅在累计次数
    很高（≥4）时提示"频繁调用"，避免误伤正常探索。
    """
    problems: list[str] = []
    # 同一只读工具累计调用 ≥4 次的探索性反复（换参数反复查）
    for name, cnt in sorted(tool_name_counts.items(), key=lambda x: -x[1]):
        if cnt >= 4 and name in _READONLY_TOOLS:
            problems.append(f"只读工具 {name} 已频繁调用 {cnt} 次（探索性调用，注意收敛）")
    # 同一工具同参数调用 ≥2 次（精确重复调用）
    for key, cnt in sorted(tool_argv_counts.items(), key=lambda x: -x[1]):
        if cnt >= 2:
            name = key.split(":", 1)[0] if ":" in key else key
            problems.append(f"工具 {name} 使用相同参数已调用 {cnt} 次")
    return problems[:3]


def _issues_summary(issues: list[tuple[str, str]]) -> list[str]:
    """从本轮校验问题中提炼"结果无效"问题。"""
    problems: list[str] = []
    for key, _msg in issues:
        tool_name = key.split(":", 1)[0] if ":" in key else key
        kind = key.split(":", 1)[1] if ":" in key else ""
        label = _ISSUE_LABELS.get(kind, "结果异常")
        problems.append(f"工具 {tool_name} {label}")
    return problems[:3]


def _suggestions(
    issues: list[tuple[str, str]], explore_rounds: int, repeat_lines: list[str]
) -> list[str]:
    """生成下一步建议（与问题一一对应，收敛导向）。"""
    suggestions: list[str] = []
    kinds = {k.split(":", 1)[1] if ":" in k else "" for k, _ in issues}
    if "deferred" in kinds:
        suggestions.append("用 tool_search 激活目标工具后直接调用，不要再查询状态")
    if "empty" in kinds or "noop" in kinds:
        suggestions.append("更换工具或调整参数，不要重复执行同一调用")
    if "error" in kinds:
        suggestions.append("检查参数/前置条件后换一种方式执行")
    if explore_rounds >= 2:
        suggestions.append("停止只读探索，直接调用目标工具完成任务或基于已有信息给出结论")
    if repeat_lines:
        suggestions.append("避免重复调用已确认无进展的工具")
    if not suggestions:
        suggestions.append("按当前计划继续推进")
    return suggestions[:3]


def build_review_message(
    conclusion_line: str,
    issues: list[tuple[str, str]],
    explore_rounds: int,
    tool_name_counts: dict[str, int],
    tool_argv_counts: dict[str, int],
) -> str:
    """构建"上一轮审视"模拟用户反馈消息。

    Args:
        conclusion_line: 上一轮迭代结论行（_iteration_conclusions 最新一条）。
        issues: 上一轮结果校验问题 [(issue_key, feedback), ...]。
        explore_rounds: 连续只读探索轮数。
        tool_name_counts: 任务内各工具累计调用次数（_tool_name_counter）。
        tool_argv_counts: 任务内同工具同参数调用次数（_tool_call_counter）。

    Returns:
        审视反馈文本（带明确前缀，role="user" 注入）。
    """
    review_lines: list[str] = []
    repeat_lines = _repeat_summary(tool_name_counts, tool_argv_counts)
    issue_lines = _issues_summary(issues)

    if not repeat_lines and not issue_lines and explore_rounds < 2:
        review_lines.append("未发现重复调用、无效结果或停滞问题。")

    for line in repeat_lines:
        review_lines.append(line + "（重复）")
    for line in issue_lines:
        review_lines.append(line + "（结果无效）")
    if explore_rounds >= 2:
        review_lines.append(f"已连续 {explore_rounds} 轮只读探索，未取得实质推进（停滞）")

    if review_lines:
        review_body = "\n".join(f"- {line}" for line in review_lines)
    else:
        review_body = "- 未发现问题，继续推进。"

    suggestions = _suggestions(issues, explore_rounds, repeat_lines)
    suggest_body = "\n".join(f"- {s}" for s in suggestions)

    return (
        "[上一轮审视 · 请以此为锚点规划下一步]\n"
        f"已完成：{conclusion_line}\n"
        f"审视发现：\n{review_body}\n"
        f"建议：\n{suggest_body}"
    )
