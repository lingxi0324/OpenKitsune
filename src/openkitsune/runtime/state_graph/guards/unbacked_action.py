"""Unbacked-action-claim guard.

Ported from OpenAkita ``runtime/state_graph/guards/unbacked_action.py``
(P-RC-5 P5.6 extraction), reduced to the detection core used by the
reasoning engine's final-answer path:

1. **"I already did X" with no tool ran at all.** The LLM uses an
   action-claim phrase (``已保存`` / ``成功发送`` / ...) but no tool
   was called this turn -> the reasoning loop forces a bounded retry
   and, on budget exhaustion, returns a non-deceptive failure instead
   of accepting the hallucinated claim as the final answer.

The negation / recap filters (``_is_negated_action_mention``,
``RECAP_NEAR_RE`` windows) prevent false positives for legitimate
summaries of past tool runs and negated statements ("请不要删除").
"""

from __future__ import annotations

import re

from ._text_patterns import action_done_re
from .recap_context import RECAP_NEAR_RE

__all__ = [
    "action_claim_re",
    "looks_like_no_tool_completion_claim",
]


def action_claim_re() -> re.Pattern[str]:
    """Compiled regex that detects Chinese action-claim phrases.

    Matches patterns like "已帮你保存", "已完成", "成功发送", "已经删除" — these
    indicate the LLM is *claiming* it performed an operation rather than merely
    analysing or describing content.  Used by the implicit-REPLY heuristic to
    avoid accepting hallucinated action descriptions.
    """
    pat = getattr(action_claim_re, "_cached", None)
    if pat is not None:
        return pat
    verbs = (
        "保存|发送|创建|删除|修改|更新|上传|下载|执行|生成|导出|复制|移动|"
        "写入|添加|设置|配置|安装|部署|打包|编译|构建|启动|重启|停止|关闭|"
        "记住|记录|存入|保存到记忆|调用|读取"
    )
    pat = re.compile(
        rf"(?:"
        rf"(?:已[经]?|成功|顺利|我已经|我已)(?:帮你?|为你|给你)?(?:{verbs})"
        rf"|已通过.{{0,30}}(?:验证|读取|检查)"
        rf"|工具已.{{0,10}}(?:调用|执行)"
        rf"|(?:write_file|edit_file|read_file|run_shell|run_powershell)"
        rf".{{0,30}}(?:已调用|已执行|已验证|验证完成)"
        rf")"
    )
    action_claim_re._cached = pat  # type: ignore[attr-defined]
    return pat


_NEGATION_RE = re.compile(
    r"(?:并?不(?:是|代表|应|该|要|允许|能)?|不能|不应|不要|"
    r"没有|未|并非|而非|非(?:声称|表示)?|避免(?:说|写|使用)?)"
    r"[`\"'“”‘’\s：:，,。；;、-]{0,8}$"
)


def _is_negated_action_mention(text: str, start: int) -> bool:
    """Check if action mention is negated by preceding context."""
    before = text[max(0, start - 18) : start]
    return bool(_NEGATION_RE.search(before))


def _is_negated_mention(text: str, match: re.Match[str]) -> bool:
    """Regex-wrapper negation check matching the legacy engine helper."""
    return _is_negated_action_mention(text, match.start())


def _is_recap_match(text: str, match: re.Match[str]) -> bool:
    """Check whether the claim sits inside a historical-recap window."""
    half = 48
    start = max(0, match.start() - half)
    end = min(len(text), match.end() + half)
    return bool(RECAP_NEAR_RE.search(text[start:end]))


def looks_like_no_tool_completion_claim(
    text: str,
    action_claim_re: re.Pattern[str],
) -> bool:
    """Detect final-answer text that claims an external action already ran.

    Ported byte-for-byte from OpenAkita's ``_looks_like_no_tool_completion_claim``:
    a match from any of (action-claim phrases, "already X" done phrases,
    textual tool-execution traces) counts only when it is neither a recap
    of past work nor a negated mention.
    """
    if not text:
        return False
    patterns = (
        action_claim_re,
        action_done_re(),
        _TEXTUAL_TOOL_EXECUTION_CLAIM_RE,
    )
    return any(
        not _is_recap_match(text, match) and not _is_negated_mention(text, match)
        for pattern in patterns
        for match in pattern.finditer(text)
    )


# 文本化工具执行轨迹：``调用 xxx(...) ... 完成/成功/已完成`` 字样。
_TEXTUAL_TOOL_EXECUTION_CLAIM_RE = re.compile(
    r"(?:调用|执行)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]{0,600}\)"
    r"\s*(?:\.{3}|…|，|,|\s)*(?:完成|成功|已完成)",
    re.IGNORECASE,
)
