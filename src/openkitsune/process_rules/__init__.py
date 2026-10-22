"""
process_rules —— 流程规则引擎（整改版 v2.0 代码落地 + 自主决策增强）

将《流程规则整改-v2》六条规则实现为**代码层强制机制**，并叠加 AI 自主决策层：

    R1 todo_policy      轻量 Todo 常态化 + Plan 模式风险触发
    R2 checkpoints      检查点条件触发（阶段边界/预期偏差/高风险/多Agent冲突）
    R3 preflight        工具预检分层（已知低风险快检 / 新·高风险·失败过详检）
    R4 arbiter          多 Agent 冲突裁决（证据 > 目标一致性 > 置信度，共识仅参考）
    R5 exception_tree   异常处理决策树（A瞬时/B参数/C权限/D前置/E结果不符 + 换通道）
    R7 memory_events    记忆保存（事件触发 + 轮末筛选）
    autonomy            分层自主决策：确定性快判兜底，灰色地带交 AI 自主判断

设计约束（v2.0 文档 §0-§9）：
- 所有规则带「触发条件 → 阈值 → 成本约束」三段式，阈值集中定义在 config.py。
- 引擎默认 fail-open：规则自身异常绝不阻断主流程，只记录审计日志。
- 每个规则触发均写入审计日志（logging + 可选 JSONL），可观测可回放。
- 自主决策层：L0 确定性置信 → L1 灰色地带问 LLM → L2 失败回退确定性；
  LLM 调用有预算上限与缓存，成本受控。
"""

from . import plan_guard
from .arbiter import AgentResult, arbitrate, deterministic_arbiter_decision
from .autonomy import decide, decide_async_or_sync, get_tracker as get_autonomy_tracker
from .checkpoints import (
    CheckpointTracker,
    detect_deviation,
    deterministic_checkpoint_decision,
    note_todo_completed,
    trigger_checkpoint,
)
from .config import ProcessRulesConfig, get_process_rules_config
from .engine import (
    RuleAudit,
    RuleEngine,
    audit_record,
    get_rule_engine,
    is_enabled,
)
from .exception_tree import (
    ErrorClass,
    classify_error_class,
    decide_retry,
    deterministic_retry_decision,
    handle_failure,
)
from .memory_events import (
    classify_memory_candidate,
    deterministic_memory_decision,
    end_of_turn_scan,
    memory_event,
)
from .plan_guard import (
    GuardDecision,
    build_progress_report,
    build_selfcheck_prompt,
    detect_premature_completion,
    detect_stale_steps,
    effective_mode,
    gate_tool_call,
    install_plan_guard,
    is_structured,
    resolve_active_plan,
    run_plan_created_hook,
    run_step_update_hook,
    run_tool_gate_hook,
    run_turn_end_report,
    validate_plan_structure,
    validate_step_update,
)
from .preflight import (
    PreflightTracker,
    classify_preflight,
    deterministic_preflight_decision,
    get_tracker as get_preflight_tracker,
    preflight_check,
)
from .todo_policy import (
    detect_risk_signal,
    deterministic_todo_decision,
    estimate_step_count,
    todo_policy_check,
)

__all__ = [
    # config
    "ProcessRulesConfig",
    "get_process_rules_config",
    # engine
    "RuleAudit",
    "RuleEngine",
    "audit_record",
    "get_rule_engine",
    "is_enabled",
    # R1
    "detect_risk_signal",
    "deterministic_todo_decision",
    "estimate_step_count",
    "todo_policy_check",
    # R2
    "CheckpointTracker",
    "detect_deviation",
    "deterministic_checkpoint_decision",
    "note_todo_completed",
    "trigger_checkpoint",
    # R3
    "PreflightTracker",
    "classify_preflight",
    "deterministic_preflight_decision",
    "get_preflight_tracker",
    "preflight_check",
    # R4
    "AgentResult",
    "arbitrate",
    "deterministic_arbiter_decision",
    # R5
    "ErrorClass",
    "classify_error_class",
    "decide_retry",
    "deterministic_retry_decision",
    "handle_failure",
    # R7
    "classify_memory_candidate",
    "deterministic_memory_decision",
    "end_of_turn_scan",
    "memory_event",
    # autonomy
    "decide",
    "decide_async_or_sync",
    "get_autonomy_tracker",
    # R8 plan guard
    "plan_guard",
    "GuardDecision",
    "build_progress_report",
    "build_selfcheck_prompt",
    "detect_premature_completion",
    "detect_stale_steps",
    "effective_mode",
    "gate_tool_call",
    "install_plan_guard",
    "is_structured",
    "resolve_active_plan",
    "run_plan_created_hook",
    "run_step_update_hook",
    "run_tool_gate_hook",
    "run_turn_end_report",
    "validate_plan_structure",
    "validate_step_update",
]
