"""
R3 工具预检分层（整改版 v2.0 §3）

分层规则：
  快检  同会话已成功调用 ≥N 次且参数形态未变 → 直接调用，不重复预检
  详检  ① 首次使用 ② 高风险动作 ③ 上次失败过 ④ schema 不确定
        → 查工具说明/schema、确认权限与前置条件后调用（≤1 次预检调用）

成本约束：预检判断在 1 个工具调用内完成；连续失败 2 次 → 停止重试，
转异常决策树（R5）。以「上次调用结果」为准，不以主观熟悉度为准。
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
class ToolHistoryEntry:
    """单工具调用历史。"""

    tool_name: str
    success_count: int = 0
    fail_count: int = 0
    last_success_at: float = 0.0
    last_fail_at: float = 0.0
    last_params_shape: str = ""
    is_known: bool = False   # 是否在工具目录中确认存在

    @property
    def last_outcome(self) -> str:
        if self.fail_count and self.last_fail_at >= self.last_success_at:
            return "failed"
        return "success"


# 高风险动作工具（详检必查）
_HIGH_RISK_TOOLS = frozenset(
    {
        "delete_file",
        "delete_files",
        "remove_file",
        "rm",
        "delete_directory",
        "move_file",
        "overwrite_file",
        "write_file",
        "edit_file",
        "patch_file",
        "send_message",
        "send_email",
        "send_mail",
        "publish",
        "broadcast",
        "org_broadcast",
        "payment",
        "transfer",
        "create_agent",
        "spawn_agent",
        "delegate_to_agent",
        "delegate_parallel",
        "approve",
        "run_shell",        # 沙箱/权限前置必查
        "run_powershell",
    }
)


class PreflightTracker:
    """会话级工具调用历史（快检/详检判定依据）。"""

    def __init__(self) -> None:
        self._history: dict[str, ToolHistoryEntry] = {}

    def get(self, tool_name: str) -> ToolHistoryEntry | None:
        return self._history.get(tool_name)

    def note_result(self, tool_name: str, *, ok: bool, params: dict | None = None) -> None:
        entry = self._history.setdefault(tool_name, ToolHistoryEntry(tool_name=tool_name))
        now = time.time()
        if ok:
            entry.success_count += 1
            entry.last_success_at = now
        else:
            entry.fail_count += 1
            entry.last_fail_at = now
        if params is not None:
            entry.last_params_shape = _params_shape(params)
        entry.is_known = True

    def mark_known(self, tool_name: str) -> None:
        self._history.setdefault(tool_name, ToolHistoryEntry(tool_name=tool_name)).is_known = True


def _params_shape(params: dict | None) -> str:
    if not params:
        return ""
    return ",".join(sorted(str(k) for k in params.keys()))


_TRACKERS: dict[str, PreflightTracker] = {}


def get_tracker(session_id: str | None) -> PreflightTracker:
    key = session_id or "default"
    if key not in _TRACKERS:
        _TRACKERS[key] = PreflightTracker()
    return _TRACKERS[key]


def classify_preflight(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    params: dict | None = None,
    known_tool: bool = False,
) -> str:
    """判定预检层：返回 'fast'（快检）或 'detail'（详检）。

    判定依据（以「上次调用结果」为准，不以主观熟悉度）：
      - 上次失败过 → detail
      - 高风险工具 → detail
      - 首次使用（无历史）→ detail
      - 同会话成功 ≥ threshold 次 且参数形态未变 → fast
    """
    engine = get_rule_engine()
    if not engine.is_enabled("preflight"):
        return "fast"  # 规则关闭 → 一律快检（不新增负担）

    cfg = get_process_rules_config()
    if not cfg.preflight_enabled:
        return "fast"

    if tool_name in _HIGH_RISK_TOOLS:
        return "detail"
    if not known_tool:
        return "detail"

    tracker = get_tracker(session_id)
    entry = tracker.get(tool_name)
    if entry is None:
        return "detail"

    if entry.last_outcome == "failed":
        return "detail"

    if entry.success_count >= cfg.preflight_fast_check_threshold:
        # 参数形态未变才快检
        if params is None or entry.last_params_shape == _params_shape(params):
            return "fast"
    return "detail"


# 详检清单（4 项，与 v2.0 文档 §3 一致）
_DETAIL_CHECKS = [
    "参数 schema 是否完整、类型是否正确",
    "权限/认证是否满足",
    "前置条件（依赖/服务/文件）是否就绪",
    "输入数据是否已取得且非过期记忆",
]


def preflight_check(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    params: dict | None = None,
    known_tool: bool = False,
    permission_ok: bool | None = None,
    mode: str = "observe",
) -> dict[str, Any] | None:
    """R3 主入口。

    Returns:
        - None：快检通过 / 规则未启用 / 无法判定。
        - dict：详检结果 {layer, checks, issues, suggest}。
          issues 非空时上层决定是否提示（observe）或阻断（enforce）。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("preflight"):
        return None
    cfg = get_process_rules_config()
    if not cfg.preflight_enabled:
        return None

    layer = classify_preflight(
        session_id=session_id, tool_name=tool_name, params=params, known_tool=known_tool
    )
    if layer == "fast":
        return None

    issues: list[str] = []
    # 权限前置（由上层注入，None=未知）
    if permission_ok is False:
        issues.append("权限/认证不满足")

    if not known_tool:
        issues.append(f"工具 '{tool_name}' 不在已知目录中（首次使用，需确认 schema）")

    audit_record(
        "preflight", "detail_check", "applied" if issues else "passed",
        detail=f"layer=detail issues={len(issues)}",
        tool_name=tool_name,
    )
    if not issues:
        return {
            "layer": "detail",
            "checks": _DETAIL_CHECKS,
            "issues": [],
            "suggest": "",
        }
    return {
        "layer": "detail",
        "checks": _DETAIL_CHECKS,
        "issues": issues,
        "suggest": " ".join(issues),
    }


def deterministic_preflight_decision(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    params: dict | None = None,
    known_tool: bool = False,
) -> dict[str, Any]:
    """R3 确定性判定 + 置信度（供自主决策层 L0 使用）。

    Returns:
        {decision: "fast"/"detail", confidence, reason}
    """
    cfg = get_process_rules_config()
    if tool_name in _HIGH_RISK_TOOLS:
        return {
            "decision": "detail",
            "confidence": 0.95,
            "reason": "高风险工具确定性详检",
        }
    if not known_tool:
        return {
            "decision": "detail",
            "confidence": 0.8,
            "reason": "工具不在已知目录（首次使用）",
        }

    tracker = get_tracker(session_id)
    entry = tracker.get(tool_name)
    if entry is None:
        return {
            "decision": "detail",
            "confidence": 0.6,
            "reason": "无调用历史（首次使用，中置信）",
        }
    if entry.last_outcome == "failed":
        return {
            "decision": "detail",
            "confidence": 0.9,
            "reason": "上次调用失败，需详检",
        }
    if entry.success_count >= cfg.preflight_fast_check_threshold:
        if params is None or entry.last_params_shape == _params_shape(params):
            return {
                "decision": "fast",
                "confidence": 0.9,
                "reason": f"成功 {entry.success_count} 次且参数形态未变",
            }
        # 参数形态变化：中等置信（某些工具形态变化也安全）
        return {
            "decision": "detail",
            "confidence": 0.5,
            "reason": "参数形态变化，交由 AI 判断是否需详检",
        }
    # 成功次数不足：边界 → 低置信
    return {
        "decision": "detail",
        "confidence": 0.5,
        "reason": f"成功 {entry.success_count} 次 < 快检阈值 {cfg.preflight_fast_check_threshold}",
    }
