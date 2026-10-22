"""
R1 轻量 Todo 常态化，Plan 模式风险触发（整改版 v2.0 §1）

- 轻量 todo：任何步骤数 ≥2 且非纯问答的任务，建议建 2–8 条单行 todo。
- Plan 模式：命中任一风险信号时触发，而非按步骤数。
- 行为模式：``suggest``（软引导，返回建议文本）/ ``enforce``（硬门槛，
  返回拒绝文本）。默认 suggest——沿用历史教训：todo 不应成为工具执行
  的硬门槛，避免模型反复收到"请先创建 Todo"长提示阻碍任务。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine

logger = logging.getLogger(__name__)

# 高风险工具名 → 风险信号映射（用于 Plan 风险触发检测）
_RISK_TOOL_SIGNALS: dict[str, str] = {
    # 不可逆/破坏性
    "delete_file": "irreversible",
    "delete_files": "irreversible",
    "remove_file": "irreversible",
    "rm": "irreversible",
    "delete_directory": "irreversible",
    "move_file": "irreversible",
    "overwrite_file": "irreversible",
    "write_file": "irreversible",        # 覆盖既有文件由策略层判定，这里标记候选
    # 外部副作用
    "send_message": "external",
    "send_email": "external",
    "send_mail": "external",
    "publish": "external",
    "broadcast": "external",
    "org_broadcast": "external",
    "payment": "external",
    "transfer": "external",
    # 权限敏感
    "create_agent": "permission",
    "spawn_agent": "permission",
    "delegate_to_agent": "permission",
    "delegate_parallel": "permission",
    "approve": "permission",
}

# 高频普通工具（不该触发 Plan）
_BENIGN_TOOLS = frozenset(
    {
        "read_file",
        "list_files",
        "search_files",
        "web_fetch",
        "get_time",
        "browser_navigate",
        "browser_open",
        "browser_get_content",
        "browser_screenshot",
        "run_shell",      # 只读命令由权限层把关；此处不预判风险
        "run_powershell",
    }
)

# 步骤计数启发式：用户请求中出现"然后/接着/之后/依次/先…再…/1. 2. 3."
_STEP_HINTS = re.compile(
    r"(然后|接着|接下来|之后|依次|逐个|分别|先.{0,8}再|同时|并且|1[\.\、\)]|2[\.\、\)]|3[\.\、\)]|4[\.\、\)]|5[\.\、\)]|6[\.\、\)]|7[\.\、\)]|8[\.\、\)])"
)


def estimate_step_count(user_request: str, tool_names: list[str] | None = None) -> int:
    """估算任务步骤数：工具调用数 + 请求中的步骤提示词。"""
    count = 0
    if tool_names:
        count += len([t for t in tool_names if t])
    text = user_request or ""
    count += len(_STEP_HINTS.findall(text))
    # "、"/"，"分隔的并列动作也计数
    count += len(re.findall(r"[、,，；;]", text)) // 2
    return max(count, 1)


def detect_risk_signal(
    tool_name: str,
    tool_input: dict | None = None,
    user_request: str = "",
    *,
    user_requested_plan: bool = False,
    first_time: bool = False,
) -> str | None:
    """检测 Plan 模式风险信号，命中返回信号名，否则 None。

    信号（任一命中即进 Plan）：
      irreversible / external / permission / user_requested / first_time
    """
    tool_input = tool_input or {}
    signal = _RISK_TOOL_SIGNALS.get(tool_name, "")
    if signal:
        return signal

    # 参数级检测：path 指向既有文件 + write/delete 类 → irreversible
    if tool_name in ("write_file", "edit_file", "patch_file"):
        path = str(tool_input.get("path", "") or tool_input.get("file_path", ""))
        if path:
            return "irreversible"

    # 用户明确要求先出计划
    text = (user_request or "").strip()
    if not user_requested_plan and re.search(r"(先出.{0,6}计划|先给.{0,6}方案|计划一下|出个方案|plan first|先规划)", text, re.I):
        return "user_requested"
    if user_requested_plan:
        return "user_requested"

    if first_time:
        return "first_time"

    return None


def todo_policy_check(
    *,
    session_id: str | None = None,
    tool_name: str = "",
    tool_input: dict | None = None,
    user_request: str = "",
    existing_todo_steps: int = 0,
    tool_call_count: int = 0,
    mode: str = "suggest",
) -> str | None:
    """R1 主入口。

    Returns:
        - None：无需 todo（放行）或规则未启用。
        - str：suggest 模式下返回轻量建议文本（不阻断）；
                enforce 模式下返回拒绝文本（阻断）。
    """
    engine = get_rule_engine()
    if not engine.is_enabled("todo_policy"):
        return None

    cfg = get_process_rules_config()
    steps = existing_todo_steps or estimate_step_count(user_request, [tool_name] if tool_name else [])
    # first_time 仅对"描述较长（≥20 字）且本会话尚无工具调用"的请求触发，
    # 避免把"现在几点了"这类单步查询误判为陌生长流程。
    risk = detect_risk_signal(
        tool_name, tool_input, user_request,
        first_time=tool_call_count == 0 and len((user_request or "").strip()) >= 20,
    )

    needs_todo = steps >= cfg.todo_min_steps
    needs_plan = risk is not None

    if not needs_todo and not needs_plan:
        return None

    if needs_plan and mode == "enforce":
        audit_record(
            "todo_policy", "block", "blocked",
            detail=f"Plan 风险信号 '{risk}' 触发强制 Plan 前置",
            tool_name=tool_name,
        )
        return (
            f"⚠️ 该操作命中 Plan 风险信号（{risk}）：{_SIGNAL_TEXT.get(risk, risk)}。"
            "请先创建 Plan（create_plan_file + exit_plan_mode）获得用户批准后再执行。"
        )

    if needs_todo and mode == "enforce":
        audit_record(
            "todo_policy", "block", "blocked",
            detail=f"多步任务（估算 {steps} 步）未建 todo",
            tool_name=tool_name,
        )
        return (
            f"⚠️ 该任务估算需 {steps} 步（≥{cfg.todo_min_steps}），请先调用 "
            "create_todo 创建 2–8 条步骤计划并逐条 update_todo_step。"
        )

    # suggest 模式：只给提示，不阻断
    if needs_plan:
        audit_record(
            "todo_policy", "suggest", "applied",
            detail=f"建议 Plan：风险信号 '{risk}'",
            tool_name=tool_name,
        )
        return f"💡 提示：此操作涉及风险信号（{risk}），建议先走 Plan 模式（create_plan_file）。"

    audit_record(
        "todo_policy", "suggest", "applied",
        detail=f"建议 todo：估算 {steps} 步",
        tool_name=tool_name,
    )
    if existing_todo_steps and existing_todo_steps > cfg.todo_max_steps:
        return (
            f"💡 提示：当前 todo 共 {existing_todo_steps} 步，超过上限 "
            f"{cfg.todo_max_steps}，建议合并或分层（禁止碎片化）。"
        )
    return (
        f"💡 提示：此任务估算需 {steps} 步，建议先 create_todo 建计划并逐条跟踪。"
    )


_SIGNAL_TEXT = {
    "irreversible": "删除/覆盖/移动等不可逆操作",
    "external": "对外发送消息/发布/资金等外部副作用",
    "permission": "需授权/凭证/跨账号写入",
    "user_requested": "用户要求先出计划",
    "first_time": "首次执行的陌长生流程",
}


def deterministic_todo_decision(
    *,
    tool_name: str = "",
    tool_input: dict | None = None,
    user_request: str = "",
    existing_todo_steps: int = 0,
    tool_call_count: int = 0,
) -> dict[str, Any]:
    """R1 确定性判定 + 置信度（供自主决策层 L0 使用）。

    Returns:
        {decision, confidence, reason}
    """
    cfg = get_process_rules_config()
    steps = existing_todo_steps or estimate_step_count(
        user_request, [tool_name] if tool_name else []
    )
    risk = detect_risk_signal(
        tool_name,
        tool_input,
        user_request,
        first_time=tool_call_count == 0 and len((user_request or "").strip()) >= 20,
    )

    # 高风险工具名命中 → 高置信（确定性足够，不必问 LLM）
    if risk in ("irreversible", "external", "permission"):
        return {
            "decision": "plan",
            "confidence": 0.95,
            "reason": f"确定性风险信号 '{risk}'",
        }
    if risk == "user_requested":
        return {
            "decision": "plan",
            "confidence": 0.9,
            "reason": "用户明确要求先出计划",
        }

    # 步骤数远高于阈值 → 高置信 todo；恰在阈值边界 → 低置信（问 LLM）
    if steps >= cfg.todo_max_steps:
        return {
            "decision": "todo",
            "confidence": 0.95,
            "reason": f"估算 {steps} 步，超过上限 {cfg.todo_max_steps}",
        }
    if steps >= cfg.todo_min_steps:
        # 边界情况（步骤数刚过阈值）→ 中置信，交给 AI 自主判断
        conf = 0.9 if steps >= cfg.todo_min_steps + 2 else 0.5
        return {
            "decision": "todo",
            "confidence": conf,
            "reason": f"估算 {steps} 步（阈值 {cfg.todo_min_steps}）",
        }

    # 单步任务：确定性明确不需要 todo
    return {
        "decision": "none",
        "confidence": 0.9,
        "reason": f"估算 {steps} 步，低于阈值 {cfg.todo_min_steps}",
    }
