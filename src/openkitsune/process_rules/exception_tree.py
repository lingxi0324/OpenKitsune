"""
R5 异常处理决策树（整改版 v2.0 §5，最高优先）

五类分支 + 换通道/共性成因/降级：
  A 瞬时错误（超时/限流/503/连接重置）→ 指数退避重试（1s→3s），同类上限 2 次
  B 参数/语法错误 → 按错误信息修正参数，重试 1 次
  C 权限/认证错误 → 不绕过；检查授权状态；需用户介入时请求用户操作
  D 前置条件不满足 → 补前置（依赖/服务/文件）后重试 1 次
  E 结果与预期不符 → 换验证通道回读（不同工具/直读文件/复算）

换通道界限：同一动作失败 2 次 → 换命令/目录/依赖/库/实现路径
共性成因：同类错误累计 ≥3 次 → 停止重试，查共同成因
降级规则：确实做不到 → 明确说明未完成项、原因、影响；不悄悄降级
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine

logger = logging.getLogger(__name__)


# 错误类别（与 tools/errors.ErrorType 对齐 + 补充 E 类）
class ErrorClass:
    TRANSIENT = "A_transient"
    PARAM = "B_param"
    PERMISSION = "C_permission"
    PREREQ = "D_prereq"
    RESULT_MISMATCH = "E_result_mismatch"


_ERROR_CLASS_HINTS = {
    ErrorClass.TRANSIENT: "暂时性错误（超时/限流/连接重置），指数退避重试 1s→3s，同类上限 2 次",
    ErrorClass.PARAM: "参数/语法错误，按错误信息修正参数后重试 1 次",
    ErrorClass.PERMISSION: "权限/认证错误，不绕过；检查授权或请求用户介入",
    ErrorClass.PREREQ: "前置条件不满足，补齐依赖/服务/文件后重试 1 次",
    ErrorClass.RESULT_MISMATCH: "结果与预期不符，换验证通道回读/复算",
}


@dataclass
class ToolFailure:
    """单次工具失败记录（用于阈值统计）。"""

    tool_name: str
    error_class: str
    message: str = ""
    ts: float = field(default_factory=time.time)


class FailureTracker:
    """会话级失败统计：同类错误计数、失败次数。"""

    def __init__(self) -> None:
        self._class_counts: dict[tuple[str, str], int] = {}   # (tool, class) → count
        self._total_fails: dict[str, int] = {}                # tool → fail count

    def record(self, failure: ToolFailure) -> None:
        key = (failure.tool_name, failure.error_class)
        self._class_counts[key] = self._class_counts.get(key, 0) + 1
        self._total_fails[failure.tool_name] = self._total_fails.get(failure.tool_name, 0) + 1

    def same_class_count(self, tool_name: str, error_class: str) -> int:
        return self._class_counts.get((tool_name, error_class), 0)

    def total_fails(self, tool_name: str) -> int:
        return self._total_fails.get(tool_name, 0)


_TRACKERS: dict[str, FailureTracker] = {}


def get_tracker(session_id: str | None) -> FailureTracker:
    key = session_id or "default"
    if key not in _TRACKERS:
        _TRACKERS[key] = FailureTracker()
    return _TRACKERS[key]


def classify_error_class(
    *,
    error: Exception | None = None,
    error_type: str = "",
    message: str = "",
    permission_blocked: bool | None = None,
) -> str:
    """将异常分类到决策树五类。

    优先复用 tools/errors.ErrorType（如 error_type 已由 classify_error 给出）。
    """
    if permission_blocked is True:
        return ErrorClass.PERMISSION

    et = (error_type or "").lower()
    msg = (message or str(error) or "").lower()

    # C 权限
    if et in ("permission",) or "permission" in et:
        return ErrorClass.PERMISSION
    if any(kw in msg for kw in ("403", "forbidden", "unauthorized", "access denied", "无权限", "没有权限")):
        return ErrorClass.PERMISSION

    # A 瞬时
    if et in ("transient", "timeout", "rate_limit"):
        return ErrorClass.TRANSIENT
    if any(kw in msg for kw in ("timeout", "timed out", "connection reset", "connection refused",
                                "too many requests", "429", "503", "502", "rate limit", "网络", "超时")):
        return ErrorClass.TRANSIENT

    # D 前置
    if et in ("dependency",):
        return ErrorClass.PREREQ
    if any(kw in msg for kw in ("command not found", "not recognized", "no such file", "does not exist",
                                "not found", "未安装", "找不到", "不存在", "服务未启动", "模块缺失")):
        # 资源不存在 → 前置类（文件/命令/服务缺失）
        return ErrorClass.PREREQ

    # B 参数
    if et in ("validation",):
        return ErrorClass.PARAM
    if any(kw in msg for kw in ("invalid", "illegal", "schema", "argument", "参数", "格式", "必填", "required field")):
        return ErrorClass.PARAM

    # 默认：无法归类的异常按 B 参数修正一次，再按换通道处理
    return ErrorClass.PARAM


def decide_retry(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    error_class: str = "",
    failure_count: int = 0,
) -> dict[str, Any]:
    """按决策树决定重试策略。

    Returns:
        dict: {
            retry: bool,
            backoff_seconds: float | None,
            action: "retry" | "switch_channel" | "check_common_cause" | "ask_user" | "stop",
            hint: str,
        }
    """
    engine = get_rule_engine()
    cfg = get_process_rules_config()
    if not engine.is_enabled("exception_tree") or not cfg.exception_tree_enabled:
        return {
            "retry": False, "backoff_seconds": None,
            "action": "stop", "hint": "规则未启用，按原路径处理",
        }

    tracker = get_tracker(session_id)
    # decide_retry 读取 tracker 中已记录的失败（handle_failure 在调用前已 record 本次），
    # 因此这里不再 +1，避免退避序列错位：第 1 次失败 → 1s，第 2 次 → 3s，第 3 次 → 查共性。
    same_class = tracker.same_class_count(tool_name, error_class)
    total_fails = tracker.total_fails(tool_name)

    # 共性成因：同类 ≥3 次 → 停止重试（最优先，任何类别都先查共性）
    if same_class >= cfg.common_cause_threshold:
        audit_record(
            "exception_tree", "common_cause", "applied",
            detail=f"{tool_name} 同类错误 {same_class} 次 ≥{cfg.common_cause_threshold}，停止重试查共同成因",
            tool_name=tool_name,
        )
        return {
            "retry": False, "backoff_seconds": None,
            "action": "check_common_cause",
            "hint": f"同类错误已累计 {same_class} 次，停止重试，排查共同成因（warning 即使伴随成功也必须处理）",
        }

    # 分类动作（类别重试上限内 → 重试；耗尽 → 换通道；权限 → 请求用户）
    if error_class == ErrorClass.TRANSIENT:
        backoffs = cfg.retry_backoff_seconds
        step = min(same_class - 1, len(backoffs) - 1)
        delay = backoffs[step] if backoffs else 1.0
        retry = same_class <= cfg.retry_max_transient
        audit_record(
            "exception_tree", "retry_transient", "applied" if retry else "blocked",
            detail=f"{tool_name} 瞬时错误第 {same_class} 次，退避 {delay}s",
            tool_name=tool_name,
        )
        if retry:
            return {
                "retry": True, "backoff_seconds": delay,
                "action": "retry",
                "hint": _ERROR_CLASS_HINTS[error_class] + f"（本次退避 {delay}s）",
            }
        return {
            "retry": False, "backoff_seconds": None,
            "action": "switch_channel",
            "hint": _ERROR_CLASS_HINTS[error_class] + "（重试上限已到，换通道）",
        }

    if error_class == ErrorClass.PERMISSION:
        return {
            "retry": False, "backoff_seconds": None,
            "action": "ask_user",
            "hint": _ERROR_CLASS_HINTS[error_class] + "（需用户介入，禁止绕过）",
        }

    if error_class == ErrorClass.PREREQ:
        retry = same_class <= cfg.retry_max_preflight
        return {
            "retry": retry, "backoff_seconds": 0.0 if retry else None,
            "action": "retry" if retry else "switch_channel",
            "hint": _ERROR_CLASS_HINTS[error_class] + ("（补齐后重试）" if retry else "（重试上限已到，换通道）"),
        }

    # B 参数
    retry = same_class <= cfg.retry_max_param
    return {
        "retry": retry, "backoff_seconds": 0.0 if retry else None,
        "action": "retry" if retry else "switch_channel",
        "hint": _ERROR_CLASS_HINTS[error_class] + ("（修正后重试）" if retry else "（重试上限已到，换通道）"),
    }


def handle_failure(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    error: Exception | None = None,
    error_type: str = "",
    message: str = "",
    failure_count: int = 0,
    permission_blocked: bool | None = None,
) -> dict[str, Any]:
    """R5 主入口：记录失败 → 分类 → 决策。

    Returns: 见 decide_retry；同时已把本次失败写入 tracker。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("exception_tree"):
        return {
            "retry": False, "backoff_seconds": None,
            "action": "stop", "hint": "规则未启用",
        }

    error_class = classify_error_class(
        error=error, error_type=error_type, message=message,
        permission_blocked=permission_blocked,
    )
    tracker = get_tracker(session_id)
    tracker.record(ToolFailure(tool_name=tool_name, error_class=error_class, message=message or str(error)))

    decision = decide_retry(
        session_id=session_id,
        tool_name=tool_name,
        error_class=error_class,
        failure_count=failure_count or tracker.total_fails(tool_name),
    )
    decision["error_class"] = error_class
    return decision


def deterministic_retry_decision(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    error_type: str = "",
    message: str = "",
    error: Exception | None = None,
) -> dict[str, Any]:
    """R5 确定性判定 + 置信度（供自主决策层 L0 使用）。

    对分类明确的错误给高置信；对模糊/未知错误给低置信（交 AI 判断）。
    """
    error_class = classify_error_class(
        error=error, error_type=error_type, message=message
    )
    decision = handle_failure(
        session_id=session_id,
        tool_name=tool_name,
        error_type=error_type,
        message=message,
    )

    # 权限 → 高置信 ask_user（确定性足够）
    if error_class == ErrorClass.PERMISSION:
        decision["confidence"] = 0.95
        decision["reason"] = "权限错误确定性 ask_user"
        return decision

    # 分类是否明确：消息含强特征词 → 高置信
    msg = (message or str(error) or "").lower()
    strong_signals = (
        "timeout", "timed out", "connection", "too many requests", "429", "503",
        "403", "forbidden", "unauthorized",
        "command not found", "not recognized", "invalid", "illegal", "schema",
        "validation",
    )
    has_strong = any(s in msg for s in strong_signals) or bool(error_type)
    if has_strong:
        decision["confidence"] = 0.85
        decision["reason"] = f"错误分类 '{error_class}' 特征明确"
    else:
        # 无强特征 → 低置信，交 AI 判断是否重试/换通道
        decision["confidence"] = 0.4
        decision["reason"] = f"错误分类 '{error_class}' 特征模糊，交 AI 判断"

    if "reason" not in decision:
        decision["reason"] = decision.get("hint", "")
    return decision
