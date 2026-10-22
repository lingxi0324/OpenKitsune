"""
R7 记忆保存：事件触发 + 轮末筛选（整改版 v2.0 §7）

事件触发（即时保存）：
  preference   稳定偏好浮现（跨任务可复用特征）
  correction   用户纠正 / 明确"记住"
  decision     关键决策完成（长期约束/口径）
  conflict     与已存偏好矛盾 → update 替换，不新增矛盾条目

轮末筛选（捕获遗漏）：
  每轮结束时扫描本对话，捕获未保存的稳定特征 → 补存。

过滤规则：一次性指令不存；临时上下文不存；未确认推测不存。
单条记忆 ≤50 字；与旧偏好冲突 → update/deactivate，禁止直接新增矛盾条目。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine

logger = logging.getLogger(__name__)

# 一次性指令/临时上下文特征（过滤规则）
_TRANSIENT_PATTERNS = re.compile(
    r"(帮我写|帮我把|发我|给我|现在|今天|本次|这轮|这个文件|这份|这个链接|明天|下周|这个任务)",
)

# 稳定偏好/纠正信号
_PREFERENCE_PATTERNS = re.compile(
    r"(以后|始终|每次|都|习惯|偏好|更喜欢|不喜欢|不要|禁止|别|请记住|记住|一直|长期)",
)
_CORRECTION_PATTERNS = re.compile(r"(不是|不对|错了|别用|不要用|改成|改为|换成|我说的是|重新)")

_MAX_CHARS = 50


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def classify_memory_candidate(text: str) -> str | None:
    """判断对话内容是否值得保存，返回事件类型或 None。

    - 命中纠正信号 → correction
    - 命中偏好信号且非瞬态 → preference
    - 否则 None（不保存）
    """
    text = (text or "").strip()
    if not text:
        return None

    # 瞬态内容直接过滤（一次性指令/临时上下文）
    if _TRANSIENT_PATTERNS.search(text) and not _PREFERENCE_PATTERNS.search(text):
        return None

    if _CORRECTION_PATTERNS.search(text):
        return "correction"

    if _PREFERENCE_PATTERNS.search(text):
        return "preference"

    return None


def memory_event(
    *,
    event_type: str,
    content: str,
    session_id: str | None = None,
    agent_id: str = "",
    mode: str = "observe",
) -> dict[str, Any] | None:
    """R7 主入口：事件触发保存。

    Returns:
        - None：规则未启用 / 事件类型未启用 / 内容为空。
        - dict：{event_type, content(截断), action: "save" | "update" | "skip"}。
          上层（记忆管理器）据此落库；conflict 类型标记 update。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("memory_events"):
        return None
    cfg = get_process_rules_config()
    if not cfg.memory_events_enabled:
        return None

    if event_type not in cfg.memory_event_types:
        return None

    content = (content or "").strip()
    if not content:
        return None

    truncated = _truncate(content, cfg.memory_max_chars)
    action = "update" if event_type == "conflict" else "save"

    audit_record(
        "memory_events", f"event:{event_type}", "applied",
        detail=f"action={action} content={truncated}",
    )
    return {
        "event_type": event_type,
        "content": truncated,
        "action": action,
        "session_id": session_id,
        "agent_id": agent_id,
    }


def end_of_turn_scan(
    *,
    turn_messages: list[str],
    session_id: str | None = None,
    agent_id: str = "",
    mode: str = "observe",
) -> list[dict[str, Any]]:
    """轮末筛选：扫描本轮对话，捕获遗漏的稳定特征。

    Returns:
        list[dict]：建议保存的记忆候选（可空）。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("memory_events"):
        return []
    cfg = get_process_rules_config()
    if not cfg.memory_events_enabled:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for msg in turn_messages:
        if not isinstance(msg, str) or not msg.strip():
            continue
        event_type = classify_memory_candidate(msg)
        if event_type is None:
            continue
        truncated = _truncate(msg, cfg.memory_max_chars)
        if truncated in seen:
            continue
        seen.add(truncated)
        candidates.append(
            {
                "event_type": event_type,
                "content": truncated,
                "action": "save",
                "session_id": session_id,
                "agent_id": agent_id,
            }
        )
        audit_record(
            "memory_events", "end_of_turn_scan", "applied",
            detail=f"捕获遗漏候选 {event_type}: {truncated}",
        )
    return candidates


def deterministic_memory_decision(content: str) -> dict[str, Any]:
    """R7 确定性判定 + 置信度（供自主决策层 L0 使用）。

    Returns:
        {decision: "save"/"update"/"skip", confidence, reason}
    """
    text = (content or "").strip()
    if not text:
        return {"decision": "skip", "confidence": 0.95, "reason": "空内容"}

    # 强纠正信号 → 高置信 correction
    if _CORRECTION_PATTERNS.search(text) and not _TRANSIENT_PATTERNS.search(text):
        return {"decision": "update", "confidence": 0.85, "reason": "纠正信号明确"}

    # 强偏好且非瞬态 → 中高置信
    if _PREFERENCE_PATTERNS.search(text) and not _TRANSIENT_PATTERNS.search(text):
        return {"decision": "save", "confidence": 0.8, "reason": "偏好信号明确"}

    # 瞬态词 + 偏好词并存（矛盾）→ 低置信（交 AI）
    if _TRANSIENT_PATTERNS.search(text) and _PREFERENCE_PATTERNS.search(text):
        return {
            "decision": "skip",
            "confidence": 0.4,
            "reason": "瞬态与偏好信号并存，交 AI 判断",
        }

    # 纯瞬态 → 高置信 skip
    if _TRANSIENT_PATTERNS.search(text):
        return {"decision": "skip", "confidence": 0.85, "reason": "一次性指令/临时上下文"}

    # 无明确信号 → 中低置信
    return {"decision": "skip", "confidence": 0.5, "reason": "信号不明，交 AI 判断"}
