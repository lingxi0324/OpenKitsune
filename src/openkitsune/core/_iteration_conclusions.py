"""迭代结论锚点：每轮工具调用后提炼一行中文结论，作为上下文锚点保留。

设计目标（对标 Hermes：每轮保留结论、驱逐工具过程细节）：

- 主循环每一轮迭代结束后，把本轮工具调用产出提炼为**一行中文结论**；
- 结论链以单条 ``_model_source="iteration_conclusions"`` 消息持续保留在
  上下文中（压缩时前置保护、不驱逐），模型在任意时刻都能看到任务进展；
- 工具调用的原始输入/输出、长结果等过程细节可以被压缩、摘要或驱逐，
  不影响任务推进——解决"要么没有记忆、要么上下文太复杂"的两难。

提炼采用纯规则（零 LLM 延迟）：锚点只需要"这步做了什么、结果如何"的
粗粒度信号，不需要完整语义；失败时降级为结果首句截断。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["extract_conclusion_line", "render_conclusions"]

# 结论行长度上限：一行中文结论（超出截断，锚点不需要细节）
_MAX_LINE_CHARS = 220
# 单条工具结果提取的最大字符数
_MAX_RESULT_CHARS = 100
# 错误标记（与 _reasoning_runtime / tool_result 的错误口径一致）
_ERROR_MARKERS = ("❌", "⚠️ 工具执行错误", "错误类型:", "⚠️ 策略拒绝:", "Tool not found", "未找到该工具")

# 明显无信息量的结果（提炼时跳过，避免结论行被"成功"刷屏）
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

# 从结果中剥离的噪音（markdown 围栏、前导符号、多余空白）
_NOISE_RE = re.compile(r"```[a-zA-Z0-9_-]*|`{1,3}|#+\s*|\*\*|__")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """清洗工具结果文本：去代码块围栏、markdown 符号、折叠空白、裁剪。"""
    text = (text or "").strip()
    text = _NOISE_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text[: _MAX_RESULT_CHARS]


def _is_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _ERROR_MARKERS)


def _first_sentence(text: str, cap: int = 80) -> str:
    """取结果第一句（按句号/换行/分号切分），截断到 cap 字符。"""
    cut = re.split(r"[。\n；;]", text, maxsplit=1)[0].strip()
    if len(cut) <= cap:
        return cut
    return cut[:cap].rstrip(",，;； ") + "…"


def _summarize_result(tool_name: str, content: str) -> str:
    """把一条工具结果压成一句短语（成功/失败/无信息三态）。"""
    cleaned = _clean(content)
    if _is_error(cleaned):
        return f"{tool_name}失败：{_first_sentence(cleaned, 60)}"
    if not cleaned or cleaned.lower() in _EMPTY_RESULTS:
        return f"{tool_name}：已执行（无额外输出）"
    return f"{tool_name}：{_first_sentence(cleaned, 80)}"


def extract_conclusion_line(
    iteration: int,
    tool_calls: list[dict] | None,
    tool_results: list[Any] | None,
) -> str:
    """从一轮工具调用及结果提炼一行中文结论。

    Args:
        iteration: 从 1 开始的迭代序号（用于结论行锚点）。
        tool_calls: 本轮 decision.tool_calls（可能为空）。
        tool_results: 本轮 tool_results_for_msg（与 tool_calls 索引对齐）。

    Returns:
        一行中文结论；无工具调用时返回"未调用工具"行。
    """
    calls = tool_calls or []
    results = tool_results or []
    if not calls:
        return f"迭代{iteration}：本轮未调用工具，继续基于已有信息推进。"

    parts: list[str] = []
    for i, tc in enumerate(calls):
        name = str(tc.get("name", "unknown"))
        raw = results[i] if i < len(results) else None
        content = str(raw.get("content", "")) if isinstance(raw, dict) else str(raw or "")
        parts.append(_summarize_result(name, content))

    line = f"迭代{iteration}：" + "；".join(parts)
    if len(line) > _MAX_LINE_CHARS:
        line = line[:_MAX_LINE_CHARS].rstrip("，,；; ") + "…"
    return line


def render_conclusions(conclusions: list[str]) -> str:
    """把结论链渲染为一条上下文消息的 content（带前缀标记，压缩保护依赖它）。"""
    if not conclusions:
        return ""
    return "[迭代结论]\n" + "\n".join(conclusions)
