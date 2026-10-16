"""工具结果校验：结果进入上下文前，校验是否有效、是否满足调用意图。

现有机制只覆盖"显式失败"（is_error / 错误标记）→ 失败计数与回滚，缺少三层校验：

1. **空/无信息结果**：工具返回"成功"标志但无实际数据（如 run_shell 探针静默失败、
   命令 exit 0 却无输出）——模型看到"成功"却没有数据，会反复执行同一调用；
2. **结果与调用意图不匹配**：如 get_tool_info 返回 "Status : DEFERRED"（schema 未加载）
   这类状态占位而非实际数据——模型误读为"工具不可用/未激活"，反复查询状态；
3. **校验反馈缺失**：发现问题后没有向模型注入"原因 + 建议"，模型无从收敛。

本模块以纯规则校验（零 LLM 延迟），返回 ``(issue_key, message)`` 列表：
主循环对每个 issue_key 只注入一次反馈，避免消息轰炸。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["validate_tool_results"]

# 显式失败标记（与 _reasoning_runtime / tool_result 的错误口径一致）
_ERROR_PREFIXES = (
    "❌",
    "⚠️ 工具执行错误",
    "错误类型:",
    "ToolError",
    "⚠️ 策略拒绝:",
)

# 仅返回成功标志、无实质数据的文本
_EMPTY_RESULTS = frozenset(
    {
        "ok",
        "ok.",
        "done",
        "done.",
        "success",
        "成功",
        "已执行",
        "已执行。",
        "执行成功",
        "执行成功。",
        "无输出",
        "",
    }
)

# run_shell 类"执行成功但无输出"的静默模式：如 "命令执行成功 (exit code: 0):" 后无实质内容
_SILENT_SHELL_RE = re.compile(
    r"命令执行成功.*exit code:\s*0\)?[：:]?\s*$|exit code:\s*0[）)]?\s*$"
)

# DEFERRED 占位（延迟加载工具状态，非实际数据）
_DEFERRED_RE = re.compile(r"DEFERRED.{0,60}(?:not yet loaded|schema|尚未加载)", re.IGNORECASE)


def _first_sentence(text: str, cap: int = 100) -> str:
    cut = re.split(r"[。\n；;]", text, maxsplit=1)[0].strip()
    if len(cut) <= cap:
        return cut
    return cut[:cap].rstrip(",，;； ") + "…"


def _content_of(result: Any) -> tuple[str, bool]:
    if isinstance(result, dict):
        content = str(result.get("content", ""))
        is_error = bool(result.get("is_error", False))
        return content, is_error
    return str(result or ""), False


def validate_tool_results(
    tool_calls: list[dict] | None,
    tool_results: list[Any] | None,
) -> list[tuple[str, str]]:
    """批量校验本轮工具结果，返回 ``[(issue_key, feedback), ...]``。

    issue_key 形如 ``"{tool_name}:{problem_type}"``，主循环据此对同一问题
    只注入一次反馈。

    Args:
        tool_calls: 本轮 decision.tool_calls（与 tool_results 索引对齐）。
        tool_results: 本轮 tool_results_for_msg（budget 截断后）。
    """
    calls = tool_calls or []
    results = tool_results or []
    issues: list[tuple[str, str]] = []

    for i, tc in enumerate(calls):
        name = str(tc.get("name", "unknown"))
        if i >= len(results):
            continue
        content, is_error = _content_of(results[i])

        # 1) 显式错误（已有机制，补一条明确反馈）
        stripped = content.lstrip()
        if is_error or stripped.startswith(_ERROR_PREFIXES):
            issues.append(
                (
                    f"{name}:error",
                    f"工具 {name} 执行失败：{_first_sentence(content, 100)}"
                    "。请更换工具或调整参数，不要用相同方式重试。",
                )
            )
            continue

        # 2) DEFERRED / schema 未加载占位：结果与调用意图不匹配
        if _DEFERRED_RE.search(content):
            issues.append(
                (
                    f"{name}:deferred",
                    f"工具 {name} 返回 DEFERRED（schema 未加载）而非实际数据。"
                    "请改用 tool_search 搜索该工具名激活后直接调用，"
                    "不要重复调用 get_tool_info 查询状态。",
                )
            )
            continue

        # 3a) 空结果：没有任何内容
        cleaned = content.strip()
        if not cleaned:
            issues.append(
                (
                    f"{name}:empty",
                    f"工具 {name} 返回空结果，未产生任何可用信息。"
                    "请更换工具或调整参数，不要重复调用同一工具。",
                )
            )
            continue

        # 3b) 无信息结果：仅成功标志 / 静默 shell
        if cleaned.lower() in _EMPTY_RESULTS or _SILENT_SHELL_RE.search(cleaned):
            issues.append(
                (
                    f"{name}:noop",
                    f"工具 {name} 仅返回成功标志，未返回实际数据"
                    "（可能为静默失败）。请检查命令/参数后更换实现方式，"
                    "不要重复执行同一调用。",
                )
            )
            continue

    return issues
