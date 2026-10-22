"""
R2 检查点条件触发（整改版 v2.0 §2）

四类触发点，命中任一即触发一次自检（≤30s 三问：方向/路径/遗漏）：
  1. stage_boundary   每个 todo 完成时、每个交付物产出前
  2. deviation        工具返回与预期不符（类型/数值/空结果/异常码）
  3. high_risk        删除/覆盖/发布/外部消息/资金/权限变更之前
  4. agent_conflict   delegate 结果不一致或互相矛盾

成本约束：单次自检 ≤30s；连续 N 个 todo 顺利 → 合并一次快速核对；
失败后才做完整 postmortem，成功路径不做复盘仪式。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine

logger = logging.getLogger(__name__)


@dataclass
class CheckpointTrigger:
    kind: str                        # stage_boundary / deviation / high_risk / agent_conflict
    reason: str = ""
    ts: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return _KIND_NAMES.get(self.kind, self.kind)


_KIND_NAMES = {
    "stage_boundary": "阶段边界",
    "deviation": "预期偏差",
    "high_risk": "高风险操作",
    "agent_conflict": "多Agent冲突",
}


class CheckpointTracker:
    """会话级检查点状态：记录最近触发、todo 连续顺利计数、自检耗时。"""

    def __init__(self) -> None:
        self.last_trigger: CheckpointTrigger | None = None
        self.consecutive_ok: int = 0        # 连续顺利的 todo 数
        self.selfcheck_count: int = 0
        self.selfcheck_total_ms: float = 0.0

    def note_todo_ok(self) -> None:
        self.consecutive_ok += 1

    def note_todo_mixed(self) -> None:
        self.consecutive_ok = 0


_TRACKERS: dict[str, CheckpointTracker] = {}


def get_tracker(session_id: str | None) -> CheckpointTracker:
    """按会话取跟踪器。"""
    key = session_id or "default"
    if key not in _TRACKERS:
        _TRACKERS[key] = CheckpointTracker()
    return _TRACKERS[key]


def _should_skip(tracker: CheckpointTracker, cfg: Any) -> bool:
    """阶段边界合并：连续 N 个 todo 顺利 → 跳过本轮单独核对。"""
    return tracker.consecutive_ok >= cfg.checkpoint_merge_after


def trigger_checkpoint(
    *,
    session_id: str | None = None,
    kind: str,
    reason: str = "",
    tool_name: str = "",
    context: dict[str, Any] | None = None,
    mode: str = "observe",   # observe: 记录+返回三问；enforce: 额外返回阻断提示
) -> list[str] | None:
    """R2 主入口。

    Returns:
        - None：规则未启用或阶段边界被合并跳过。
        - list[str]：三问自检问题（观察模式，供上层注入提示）。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("checkpoints"):
        return None
    cfg = get_process_rules_config()
    if not cfg.checkpoint_enabled:
        return None

    tracker = get_tracker(session_id)
    # 高风险与冲突永远触发；阶段边界按合并规则
    if kind == "stage_boundary" and _should_skip(tracker, cfg):
        tracker.note_todo_mixed()  # 合并跳过一次，重置计数避免永远跳过
        return None

    questions = [
        "方向：当前结果是否仍指向用户原始目标？",
        "路径：是否存在更优路径 / 是否需要修正计划？",
        "遗漏：是否存在未覆盖的步骤或未声明的假设？",
    ]
    trigger = CheckpointTrigger(
        kind=kind,
        reason=reason,
        context={"tool_name": tool_name, **(context or {})},
    )
    tracker.last_trigger = trigger
    tracker.selfcheck_count += 1

    audit_record(
        "checkpoints", f"selfcheck:{kind}", "applied",
        detail=reason or _KIND_NAMES.get(kind, kind),
        tool_name=tool_name,
    )
    return questions


def note_todo_completed(session_id: str | None, *, ok: bool) -> None:
    """阶段边界计数：todo 完成时由上层调用。"""
    tracker = get_tracker(session_id)
    if ok:
        tracker.note_todo_ok()
    else:
        tracker.note_todo_mixed()


def detect_deviation(expected: Any, actual: Any, *, tool_name: str = "") -> str | None:
    """预期偏差检测（轻量启发式，供 R2 deviation 触发判断）。

    - 预期有内容、实际为空 → 偏差
    - 类型不匹配 → 偏差
    - 实际含异常码/错误标志 → 偏差
    """
    if expected is None or actual is None:
        return None
    if hasattr(expected, "type") and hasattr(actual, "type") and expected.type != actual.type:
        return f"返回类型不符：期望 {expected.type}，实际 {actual.type}"

    exp_str = str(expected).strip()
    act_str = str(actual).strip()
    if not act_str:
        return "返回空结果"
    if exp_str and exp_str not in act_str and len(exp_str) > 0:
        # 期望内容未出现在结果中且结果很短 → 可疑
        if len(act_str) < 120:
            return f"结果与预期不符：期望含 '{exp_str[:50]}'"
    return None


def deterministic_checkpoint_decision(
    *,
    kind: str = "",
    tool_name: str = "",
    consecutive_ok: int = 0,
    deviation: str | None = None,
) -> dict[str, Any]:
    """R2 确定性判定 + 置信度（供自主决策层 L0 使用）。

    Returns:
        {decision: bool, confidence, reason}
    """
    cfg = get_process_rules_config()
    # 高风险操作与多 Agent 冲突 → 高置信必须触发
    if kind in ("high_risk", "agent_conflict"):
        return {
            "decision": True,
            "confidence": 0.95,
            "reason": f"检查点类别 '{kind}' 强制触发",
        }
    # 明确偏差 → 高置信触发
    if deviation:
        return {
            "decision": True,
            "confidence": 0.9,
            "reason": f"预期偏差：{deviation[:80]}",
        }
    # 阶段边界：连续顺利 ≥ 合并阈值 → 高置信跳过；否则中置信
    if kind == "stage_boundary":
        if consecutive_ok >= cfg.checkpoint_merge_after:
            return {
                "decision": False,
                "confidence": 0.9,
                "reason": f"连续 {consecutive_ok} 步顺利，合并跳过",
            }
        return {
            "decision": True,
            "confidence": 0.6,
            "reason": "阶段边界检查点（中置信，可交 AI 判断）",
        }
    # 未知类别 → 低置信（问 LLM）
    return {
        "decision": False,
        "confidence": 0.4,
        "reason": f"未知检查点类别 '{kind}'",
    }
