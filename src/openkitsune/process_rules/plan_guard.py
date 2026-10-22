"""R8 Plan 合规门禁 —— 代码 Hook 层（非提示词约束）。

把此前只能靠 SKILL.md 软引导的四条诉求落到代码路径上：

1. ``validate_plan_structure``：计划必须先落成固定结构（goal / 每步
   description + expected + done_when），否则拒绝创建。
2. ``gate_tool_call``：执行工具前必须绑定到当前 ``in_progress`` 步骤；
   没有活动步骤、工具与步骤声明不符时按模式阻断。
3. ``validate_step_update``：步骤标记 completed/failed 必须携带证据
   （``actual=... | verdict=PASS|FAIL|DEVIATE``），把"隐式自检"变成
   "不写自检就无法推进状态机"。
4. ``build_progress_report``：轮末进度由代码从计划状态机生成，不依赖
   LLM 自述；同时检测"计划未完成却宣称完成"。

设计约束：
- 与 process_rules 其他规则一致，阈值/开关集中在 config.py。
- 默认 ``plan_guard_mode="enforce"``；对**非结构化历史计划**自动降级为
  ``observe``，避免旧计划被新门禁卡死（渐进式收紧）。
- 任何内部异常 fail-open：门禁自身故障绝不阻断主流程。
- 每条裁决写审计（rule=plan_guard）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record

logger = logging.getLogger(__name__)

# 计划自身的管理工具：永远放行，否则无法推进/修正计划
PLAN_TOOL_NAMES = frozenset(
    {
        "create_todo",
        "update_todo_step",
        "get_todo_status",
        "complete_todo",
        "create_plan_file",
        "exit_plan_mode",
    }
)

# 只读/无副作用工具：与当前步骤声明不符时只告警，不阻断
_READONLY_TOOL_NAMES = frozenset(
    {
        "read_file",
        "list_directory",
        "list_files",
        "glob",
        "grep",
        "web_search",
        "web_fetch",
        "get_time",
        "search_memory",
        "load_skill",
        "get_skill_info",
        "get_todo_status",
        "ask_user",
    }
)

_TERMINAL_STEP_STATES = frozenset({"completed", "failed", "skipped", "cancelled"})
_EVIDENCE_RE = re.compile(r"verdict\s*[:=]\s*(PASS|FAIL|DEVIATE)", re.I)
_ACTUAL_RE = re.compile(r"actual\s*[:=]", re.I)
_COMPLETION_CLAIM_RE = re.compile(
    r"(全部完成|已全部完成|已完成所有|任务已完成|已经完成|搞定|搞掂|all done|task complete|"
    r"completed successfully|everything is done)",
    re.I,
)

# (session_id, plan_id, step_id) -> 首次绑定的工具名
_TOOL_BINDINGS: dict[tuple[str, str, str], str] = {}
_MAX_BINDINGS = 512


@dataclass
class GuardDecision:
    """门禁裁决。``action`` ∈ allow / warn / block。"""

    action: str = "allow"
    code: str = ""
    message: str = ""

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def feedback(self) -> str:
        return self.message


def _allow() -> GuardDecision:
    return GuardDecision()


def _warn(code: str, message: str) -> GuardDecision:
    return GuardDecision(action="warn", code=code, message=message)


def _block(code: str, message: str) -> GuardDecision:
    return GuardDecision(action="block", code=code, message=message)


# ── 模式与结构判定 ──────────────────────────────────────────────


def _configured_mode() -> str:
    cfg = get_process_rules_config()
    if not cfg.plan_guard_enabled:
        return "off"
    mode = str(cfg.plan_guard_mode or "observe").lower()
    return mode if mode in ("off", "observe", "enforce") else "observe"


def effective_mode(plan: dict | None = None) -> str:
    """带历史计划降级的有效模式。

    非结构化旧计划（无 expected/done_when 且不是 plan_file）自动降级为
    observe：新门禁只审计+提示，不阻断，避免把存量任务卡死。
    """
    mode = _configured_mode()
    if mode == "enforce" and plan is not None and not is_structured(plan):
        return "observe"
    return mode


def is_structured(plan: dict | None) -> bool:
    if not isinstance(plan, dict):
        return False
    if str(plan.get("plan_type") or "") == "plan_file":
        return True
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("expected") or "").strip():
            return True
        if str(step.get("done_when") or "").strip():
            return True
    return False


def _audit(action: str, decision: GuardDecision, *, detail: str = "", tool_name: str = "") -> None:
    try:
        outcome = "blocked" if decision.blocked else "applied"
        audit_record(
            "plan_guard",
            action,
            outcome,
            detail=f"{decision.code}: {decision.message or detail}"[:500],
            tool_name=tool_name,
        )
    except Exception:  # noqa: BLE001
        pass


# ── 诉求 1：固定结构计划 ────────────────────────────────────────


def validate_plan_structure(
    plan: dict | None,
    *,
    require_expected: bool | None = None,
    mode: str | None = None,
) -> GuardDecision:
    """校验计划是否满足固定结构。

    ``require_expected`` 默认读配置；Plan 文件（create_plan_file）调用方
    显式传 False，因为详细内容在 Markdown body 里。
    """
    try:
        cfg = get_process_rules_config()
        if require_expected is None:
            require_expected = bool(cfg.plan_guard_require_expected)
        active_mode = mode or _configured_mode()
        if active_mode == "off":
            return _allow()

        if not isinstance(plan, dict):
            return _block("plan_missing", "计划对象缺失，拒绝进入执行态。")

        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            return _block("plan_empty", "计划至少需要 1 个步骤。")

        hard = active_mode == "enforce"
        problems: list[str] = []

        if len(steps) > cfg.todo_max_steps:
            problems.append(
                f"步骤数 {len(steps)} 超过上限 {cfg.todo_max_steps}，请合并/分层。"
            )

        seen: set[str] = set()
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                problems.append(f"第 {idx} 步不是对象。")
                continue
            sid = str(step.get("id") or "").strip()
            desc = str(step.get("description") or step.get("content") or "").strip()
            if not sid:
                problems.append(f"第 {idx} 步缺少 id。")
            elif sid in seen:
                problems.append(f"步骤 id 重复：{sid}。")
            seen.add(sid)
            if not desc:
                problems.append(f"第 {idx} 步（{sid or '?'}）缺少 description。")
            if require_expected:
                if not str(step.get("expected") or "").strip():
                    problems.append(f"第 {idx} 步（{sid or '?'}）缺少 expected（预期结果）。")
                if not str(step.get("done_when") or "").strip():
                    problems.append(f"第 {idx} 步（{sid or '?'}）缺少 done_when（完成判定标准）。")

        if problems:
            message = (
                "⚠️ 计划结构不合规，已拒绝创建：\n- "
                + "\n- ".join(problems[:8])
                + "\n请为每一步补齐 id / description / expected / done_when 后重试。"
            )
            decision = _block("plan_format_invalid", message) if hard else _warn(
                "plan_format_invalid", message
            )
            _audit("validate_plan", decision)
            return decision

        _audit("validate_plan", _allow())
        return _allow()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] validate_plan_structure degraded: %s", exc)
        return _allow()


# ── 计划解析辅助 ────────────────────────────────────────────────


def resolve_active_plan(session_id: str | None) -> dict | None:
    """从 todo_state 取当前会话的活跃计划；失败返回 None（fail-open）。"""
    if not session_id:
        return None
    try:
        from openkitsune.tools.handlers.todo_state import get_todo_handler_for_session

        handler = get_todo_handler_for_session(session_id)
        if handler is None:
            return None
        plan = handler.get_plan_for(session_id)
        if isinstance(plan, dict) and plan.get("status") == "in_progress":
            return plan
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] resolve_active_plan degraded: %s", exc)
        return None


def _active_step(plan: dict) -> dict | None:
    for step in plan.get("steps") or []:
        if isinstance(step, dict) and step.get("status") == "in_progress":
            return step
    return None


def _all_steps_terminal(plan: dict) -> bool:
    steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
    return bool(steps) and all(s.get("status") in _TERMINAL_STEP_STATES for s in steps)


def _is_plan_file_target(plan: dict, tool_name: str, tool_input: dict) -> bool:
    if tool_name not in ("read_file", "write_file", "edit_file"):
        return False
    target = str(
        tool_input.get("path")
        or tool_input.get("file_path")
        or tool_input.get("filename")
        or ""
    ).replace("\\", "/")
    if not target:
        return False
    plan_file = str(plan.get("plan_file") or "").replace("\\", "/")
    if plan_file and target.endswith(plan_file.split("/")[-1]):
        return True
    return "/plans/" in target or target.startswith("data/plans/")


def _binding_key(session_id: str | None, plan: dict, step: dict) -> tuple[str, str, str]:
    return (
        str(session_id or ""),
        str(plan.get("id") or ""),
        str(step.get("id") or ""),
    )


def _remember_binding(key: tuple[str, str, str], tool_name: str) -> None:
    if len(_TOOL_BINDINGS) >= _MAX_BINDINGS:
        _TOOL_BINDINGS.clear()
    _TOOL_BINDINGS[key] = tool_name


def _same_tool_family(a: str, b: str) -> bool:
    """同族工具视为同一步内的合理组合（navigate + screenshot 等）。"""
    families = ("browser_", "desktop_", "memory_", "skill_", "mcp_", "web_", "file_")
    return any(a.startswith(prefix) and b.startswith(prefix) for prefix in families)


# ── 诉求 2：工具调用必须绑定计划步骤 ────────────────────────────


def gate_tool_call(
    plan: dict | None,
    *,
    session_id: str | None = None,
    tool_name: str = "",
    tool_input: dict | None = None,
    mode: str | None = None,
) -> GuardDecision:
    """执行工具前的硬门禁。

    放行：计划工具 / 只读工具 / 计划已完成 / 无活跃计划。
    阻断：有活跃计划但没有任何 in_progress 步骤；当前步骤声明了其他
    工具且本次调用不是只读工具。
    """
    try:
        active_mode = mode or effective_mode(plan)
        if active_mode == "off" or not isinstance(plan, dict):
            return _allow()
        if plan.get("status") != "in_progress":
            return _allow()
        if tool_name in PLAN_TOOL_NAMES:
            return _allow()
        if _is_plan_file_target(plan, tool_name, tool_input or {}):
            return _allow()

        step = _active_step(plan)
        if step is None:
            if _all_steps_terminal(plan):
                return _allow()
            # 只读探查不阻断：没有活动步骤时仍允许读文件/搜索来补齐判断
            if tool_name in _READONLY_TOOL_NAMES:
                return _allow()
            message = (
                "⛔ 计划当前没有 in_progress 步骤，已拦截本次工具调用。\n"
                "请先 update_todo_step 将下一步置为 in_progress，并在该步写明预期结果，"
                "然后再执行工具。"
            )
            decision = _block("step_not_active", message) if active_mode == "enforce" else _warn(
                "step_not_active", message
            )
            _audit("gate_tool", decision, tool_name=tool_name)
            return decision

        step_id = str(step.get("id") or "")
        declared = str(step.get("tool") or "").strip()
        allow_tools = step.get("allow_tools") or []
        if not isinstance(allow_tools, list):
            allow_tools = []

        if declared and tool_name != declared and tool_name not in allow_tools:
            if _same_tool_family(declared, tool_name):
                return _allow()
            message = (
                f"⚠️ 当前步骤 {step_id} 声明的工具是 `{declared}`，"
                f"本次调用是 `{tool_name}`。\n"
                "若确需换工具，请先更新计划（update_todo_step 或重写计划），"
                "否则请改用声明工具。"
            )
            # 只读工具视为探查，不阻断；有副作用工具在 enforce 下阻断
            hard = active_mode == "enforce" and tool_name not in _READONLY_TOOL_NAMES
            decision = _block("tool_out_of_plan", message) if hard else _warn(
                "tool_out_of_plan", message
            )
            _audit("gate_tool", decision, tool_name=tool_name)
            return decision

        key = _binding_key(session_id, plan, step)
        bound = _TOOL_BINDINGS.get(key)
        if (
            bound
            and bound != tool_name
            and tool_name not in _READONLY_TOOL_NAMES
            and not _same_tool_family(bound, tool_name)
        ):
            message = (
                f"⚠️ 步骤 {step_id} 已绑定工具 `{bound}`，本次却调用 `{tool_name}`。"
                "同一执行单元内更换副作用工具属于计划偏离，请先修正计划。"
            )
            decision = _warn("tool_binding_drift", message)
            _audit("gate_tool", decision, tool_name=tool_name)
            return decision
        if not bound:
            _remember_binding(key, tool_name)

        return _allow()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] gate_tool_call degraded: %s", exc)
        return _allow()


# ── 诉求 3：步骤完成必须显式自检 ────────────────────────────────


def validate_step_update(
    plan: dict | None,
    *,
    step_id: str,
    status: str,
    result: str = "",
    mode: str | None = None,
) -> GuardDecision:
    """校验 update_todo_step 的完成证据。

    完成/失败必须提供 ``result``；结构化计划还必须在 result 中出现
    ``actual=`` 与 ``verdict=PASS|FAIL|DEVIATE``。判定与状态矛盾即拒绝。
    """
    try:
        if not isinstance(plan, dict):
            return _allow()
        active_mode = mode or effective_mode(plan)
        if active_mode == "off":
            return _allow()

        step = next(
            (s for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("id") == step_id),
            None,
        )
        if step is None:
            return _allow()  # 交给 handler 返回"未找到步骤"

        status = str(status or "").strip()
        evidence = str(result or "").strip()
        structured = is_structured(plan)
        hard = active_mode == "enforce"

        if status in ("completed", "failed") and not evidence:
            message = (
                f"⛔ 步骤 {step_id} 不能在没有证据时标记为 {status}。\n"
                "请在 result 中写明：actual=<结果/命令输出摘要> | verdict=PASS|FAIL|DEVIATE"
            )
            decision = _block("evidence_missing", message) if hard else _warn(
                "evidence_missing", message
            )
            _audit("step_update", decision, tool_name="update_todo_step")
            return decision

        if structured and status == "completed" and hard:
            if not _ACTUAL_RE.search(evidence) or not _EVIDENCE_RE.search(evidence):
                message = (
                    f"⛔ 步骤 {step_id} 缺少结构化自检证据，已拒绝标记完成。\n"
                    "result 必须形如：\n"
                    f'actual=<证据摘要≤120字> | verdict=PASS|FAIL|DEVIATE\n'
                    '示例：update_todo_step(step_id="'
                    + step_id
                    + '", status="completed", result="actual=nginx -t 返回 syntax is ok | verdict=PASS")'
                )
                decision = _block("selfcheck_format_missing", message)
                _audit("step_update", decision, tool_name="update_todo_step")
                return decision

        verdict_match = _EVIDENCE_RE.search(evidence)
        verdict = verdict_match.group(1).upper() if verdict_match else ""
        if status == "completed" and verdict in ("FAIL", "DEVIATE"):
            message = (
                f"⛔ 步骤 {step_id} 的自检判定是 {verdict}，与 status=completed 矛盾。"
                "请改用 failed，或修正证据后重试。"
            )
            decision = _block("verdict_conflict", message)
            _audit("step_update", decision, tool_name="update_todo_step")
            return decision
        if status == "failed" and verdict == "PASS":
            message = (
                f"⛔ 步骤 {step_id} 的自检判定是 PASS，与 status=failed 矛盾。"
                "请改用 completed，或修正证据后重试。"
            )
            decision = _block("verdict_conflict", message)
            _audit("step_update", decision, tool_name="update_todo_step")
            return decision

        # 历史非结构化计划：不阻断，但要求可见的自检口径（observe 提示）
        if not structured and status == "completed" and not verdict:
            message = (
                f"⚠️ 步骤 {step_id} 已完成，但缺少自检判定。"
                "建议在 result 中补一句：actual=<证据摘要> | verdict=PASS|FAIL|DEVIATE"
            )
            decision = _warn("selfcheck_format_missing", message)
            _audit("step_update", decision, tool_name="update_todo_step")
            return decision

        _audit("step_update", _allow(), tool_name="update_todo_step")
        return _allow()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] validate_step_update degraded: %s", exc)
        return _allow()


def build_selfcheck_prompt(
    plan: dict | None,
    *,
    tool_name: str = "",
    success: bool = True,
    result_text: str = "",
    max_excerpt: int = 160,
) -> str:
    """生成回注到工具结果的显式自检提示（诉求 3 的"提示面"）。"""
    try:
        if not isinstance(plan, dict) or plan.get("status") != "in_progress":
            return ""
        if effective_mode(plan) == "off":
            return ""
        step = _active_step(plan)
        if step is None:
            return ""
        excerpt = re.sub(r"\s+", " ", str(result_text or "")).strip()[:max_excerpt]
        expected = str(step.get("expected") or "").strip() or "（未声明，先在计划中补齐）"
        done_when = str(step.get("done_when") or "").strip() or "（未声明）"
        return (
            f"[PLAN-GUARD] step={step.get('id')} tool={tool_name} "
            f"result={'ok' if success else 'failed'}\n"
            f"预期：{expected}\n完成标准：{done_when}\n"
            f"证据摘录：{excerpt or '(空)'}\n"
            "推进状态前必须在回复或 update_todo_step 的 result 中写出：\n"
            f'STEP-CHECK {step.get("id")}: actual=<证据摘要≤120字> | '
            "verdict=PASS|FAIL|DEVIATE\n"
            "然后执行 update_todo_step(step_id=\""
            f"{step.get('id')}\", status=\"completed|failed\", result=\"<同上一行>\")\n"
            "禁止在没有 verdict 的情况下宣称该步骤完成。"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] build_selfcheck_prompt degraded: %s", exc)
        return ""


# ── 诉求 4：确定性进度汇报 + 假完成检测 ─────────────────────────


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:  # noqa: BLE001
        return None


def detect_stale_steps(plan: dict, *, now: datetime | None = None) -> list[str]:
    """找出长时间停留在 in_progress 的步骤（自动检测停滞）。"""
    try:
        cfg = get_process_rules_config()
        limit = max(int(cfg.plan_guard_stale_seconds), 1)
        now = now or datetime.now()
        stale: list[str] = []
        for step in plan.get("steps") or []:
            if not isinstance(step, dict) or step.get("status") != "in_progress":
                continue
            started = _parse_ts(step.get("started_at"))
            if started is None:
                continue
            if (now - started).total_seconds() >= limit:
                stale.append(str(step.get("id") or "?"))
        return stale
    except Exception:  # noqa: BLE001
        return []


def detect_premature_completion(plan: dict | None, response_text: str = "") -> str | None:
    """计划未完成却出现"完成"口径 → 返回告警文本。"""
    try:
        if not isinstance(plan, dict) or not _COMPLETION_CLAIM_RE.search(response_text or ""):
            return None
        unfinished = [
            s
            for s in plan.get("steps") or []
            if isinstance(s, dict) and s.get("status") not in _TERMINAL_STEP_STATES
        ]
        if not unfinished:
            return None
        ids = ", ".join(str(s.get("id") or "?") for s in unfinished[:5])
        return (
            f"⚠️ 回复中出现完成口径，但计划仍有 {len(unfinished)} 步未闭合（{ids}）。"
            "请改为如实汇报剩余步骤，或先更新计划状态。"
        )
    except Exception:  # noqa: BLE001
        return None


def build_progress_report(
    plan: dict | None,
    *,
    response_text: str = "",
    now: datetime | None = None,
) -> str:
    """从计划状态机生成确定性进度报告（轮末注入，不依赖 LLM 自述）。"""
    try:
        if not isinstance(plan, dict):
            return ""
        steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
        if not steps:
            return ""

        total = len(steps)
        counts = {
            key: sum(1 for s in steps if s.get("status") == key)
            for key in ("completed", "failed", "skipped", "cancelled", "pending", "in_progress")
        }
        done = counts["completed"] + counts["skipped"]
        percent = int(done * 100 / total) if total else 0
        icons = {
            "pending": "⬜",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️",
            "cancelled": "🚫",
        }

        lines = [
            f"📊 **计划进度**：{done}/{total}（{percent}%）",
            f"状态：✅{counts['completed']} ❌{counts['failed']} "
            f"🔄{counts['in_progress']} ⬜{counts['pending']} ⏭️{counts['skipped']}",
        ]
        for idx, step in enumerate(steps, start=1):
            status = str(step.get("status") or "pending")
            icon = icons.get(status, "❓")
            desc = str(step.get("description") or step.get("content") or step.get("id") or "")
            result = str(step.get("result") or "").strip()
            suffix = f" → {result[:80]}" if result else ""
            lines.append(f"{icon} {idx}. {desc[:80]}{suffix}")

        stale = detect_stale_steps(plan, now=now)
        if stale:
            minutes = max(int(get_process_rules_config().plan_guard_stale_seconds) // 60, 1)
            lines.append(f"⏰ 停滞提醒：{', '.join(stale)} 已在 in_progress 超过 {minutes} 分钟。")

        if counts["in_progress"] or counts["pending"]:
            lines.append("⚠️ 计划未闭合：仍有未完成步骤，结束回复前请如实说明剩余项。")

        premature = detect_premature_completion(plan, response_text)
        if premature:
            lines.append(premature)

        _audit("progress_report", _allow(), detail=f"{done}/{total}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] build_progress_report degraded: %s", exc)
        return ""


# ── Hook 适配器 ─────────────────────────────────────────────────


def _handle_hook(event: Any, context: dict) -> dict[str, str]:
    """把 HookEvent 映射到 Guard 裁决，返回 Hook 结果字典。

    保持同步：所有 Guard 逻辑均为纯函数/内存操作。
    """
    name = str(getattr(event, "value", event))
    if name == "plan_created":
        decision = validate_plan_structure(
            context.get("plan"),
            require_expected=bool(context.get("require_expected", True)),
        )
    elif name == "plan_step_tool":
        decision = gate_tool_call(
            context.get("plan"),
            session_id=context.get("session_id"),
            tool_name=str(context.get("tool_name") or ""),
            tool_input=context.get("tool_input") or {},
        )
    elif name == "plan_step_update":
        decision = validate_step_update(
            context.get("plan"),
            step_id=str(context.get("step_id") or ""),
            status=str(context.get("status") or ""),
            result=str(context.get("result") or ""),
        )
    elif name == "plan_turn_end":
        report = build_progress_report(
            context.get("plan"),
            response_text=str(context.get("response_text") or ""),
        )
        return {"decision": "allow", "output": report, "feedback": report}
    else:
        return {"decision": "allow"}

    return {
        "decision": decision.action,
        "output": decision.message,
        "feedback": decision.message,
    }


_HOOK_ID = "process_rules.plan_guard"


def install_plan_guard(executor: Any | None = None) -> Any:
    """把 plan_guard 注册到全局 HookExecutor（幂等）。

    返回实际使用的 executor，便于测试注入。
    """
    try:
        from openkitsune.agent.hooks import CallbackHook, HookEvent, get_hook_executor

        ex = executor if executor is not None else get_hook_executor()
        if ex.has_handler(_HOOK_ID):
            return ex
        ex.register(
            CallbackHook(
                _HOOK_ID,
                [
                    HookEvent.PLAN_CREATED,
                    HookEvent.PLAN_STEP_TOOL,
                    HookEvent.PLAN_STEP_UPDATE,
                    HookEvent.PLAN_TURN_END,
                ],
                _handle_hook,
            )
        )
        return ex
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] install degraded: %s", exc)
        return executor


async def run_plan_created_hook(plan: dict, *, require_expected: bool = True) -> str | None:
    """通过 Hook 层校验新计划结构；返回阻断提示文本或 None。"""
    try:
        install_plan_guard()
        from openkitsune.agent.hooks import HookEvent, get_hook_executor

        blocked = await get_hook_executor().execute_first_blocking(
            HookEvent.PLAN_CREATED,
            {"plan": plan, "require_expected": require_expected},
        )
        return blocked.feedback if blocked is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] created hook degraded: %s", exc)
        return None


async def run_tool_gate_hook(
    plan: dict | None,
    *,
    session_id: str | None,
    tool_name: str,
    tool_input: dict | None = None,
) -> str | None:
    """通过 Hook 层执行工具门禁；返回阻断提示文本或 None。"""
    try:
        if not isinstance(plan, dict):
            return None
        install_plan_guard()
        from openkitsune.agent.hooks import HookEvent, get_hook_executor

        blocked = await get_hook_executor().execute_first_blocking(
            HookEvent.PLAN_STEP_TOOL,
            {
                "plan": plan,
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_input": tool_input or {},
            },
        )
        return blocked.feedback if blocked is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] tool gate degraded: %s", exc)
        return None


async def run_step_update_hook(
    plan: dict | None,
    *,
    step_id: str,
    status: str,
    result: str = "",
) -> str | None:
    """通过 Hook 层校验步骤更新证据；返回阻断提示文本或 None。"""
    try:
        if not isinstance(plan, dict):
            return None
        install_plan_guard()
        from openkitsune.agent.hooks import HookEvent, get_hook_executor

        blocked = await get_hook_executor().execute_first_blocking(
            HookEvent.PLAN_STEP_UPDATE,
            {"plan": plan, "step_id": step_id, "status": status, "result": result},
        )
        return blocked.feedback if blocked is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] step update hook degraded: %s", exc)
        return None


async def run_turn_end_report(plan: dict | None, response_text: str = "") -> str:
    """通过 Hook 层生成轮末进度报告；Hook 失败时回退纯函数。"""
    try:
        if not isinstance(plan, dict):
            return ""
        install_plan_guard()
        from openkitsune.agent.hooks import HookEvent, get_hook_executor

        results = await get_hook_executor().execute(
            HookEvent.PLAN_TURN_END,
            {"plan": plan, "response_text": response_text},
        )
        for result in results:
            if result.success and result.feedback:
                return result.feedback
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PlanGuard] turn end hook degraded: %s", exc)
    return build_progress_report(plan, response_text=response_text)


def reset_guard_state() -> None:
    """测试用：清空工具绑定。"""
    _TOOL_BINDINGS.clear()
