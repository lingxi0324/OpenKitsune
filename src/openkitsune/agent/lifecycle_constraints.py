"""Agent 流程/推理逻辑的内在约束层（整改增强）。

为既有 Agent 生命周期图（openkitsune.agent.core）、ReAct 推理图
（openkitsune.agent.reasoning）与双维度状态枚举施加一组可校验的
工程性质。这组性质源自同一套「循环—完备—唯一—递生—制衡—归位」的
设计逻辑（与 agent-lifecycle-core 内核同源；此处为 OpenKitsune 域模型
的适配实现，不重复引入外部包）：

1. 闭环（CLOSURE）：生命周期拓扑须终而复始——从入口可达全部节点，
   复盘沉淀为显式节点，不允许孤立节点或断头；
2. 完备（COMPLETENESS）：路由/迁移表须覆盖全部已知决策词汇，无漏路由；
3. 唯一（UNIQUENESS）：任务级 × 回合级双维度状态编码奇偶一致，
   非法组合即拒绝，状态无二义；
4. 递生（FEEDFORWARD）：前序环节产物须满足后序输入契约；
5. 制衡（CHECK-AND-BALANCE）：产出 / 验证 / 质询三方异源，禁止自证；
6. 归位可推导（DERIVABLE PLACEMENT）：路由归属由声明式映射承载，
   函数性与覆盖性可机器校验，而非散落硬编码分支。

设计约束：本模块只做校验与增强，不改变既有运行路径；新增守卫在
正常上下文中一律放行（passed=True），仅在异常时拦截。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, StrEnum

from openkitsune.agent.state import (
    ReasoningPhase,
    TaskState,
    derive_lifecycle_for_phase,
)
from openkitsune.runtime.models import TaskLifecycleState

__all__ = [
    "StateConstraintError",
    "GuardViolation",
    "StateCode",
    "is_valid",
    "valid_codes",
    "validate_closure",
    "assert_routing_coverage",
    "feedforward_guard",
    "TriadPhase",
    "TriadValidator",
    "Gate",
    "GATE_ORDER",
    "GATE_KIND",
    "PHASE_TO_GATE",
    "GATE_TO_PHASE",
    "LIFECYCLE_TO_GATE",
    "GateCode",
    "gate_valid_codes",
    "gate_sequence_ok",
    "register_gate_guard",
    "assert_gate",
    "AgentRole",
    "ALL_ROLES",
    "ROLE_ALIASES",
    "COUNTERBALANCE",
    "TopologyViolation",
    "assert_star_topology",
    "StrategyTag",
    "STRATEGY_STAGES",
    "STRATEGY_ROLES",
    "strategy_for",
    "BALANCE_RULES",
    "BALANCE_ROLLBACK",
    "rollback_for",
    "assert_complete_mapping",
    "gate_index",
    "derive_lifecycle_for",
    "semantic_consistent",
    "assert_semantic_consistent",
    "apply_rollback_to",
    "advance_guarded",
]

# 枚举定义序（StrEnum 无 int 序数，取定义列表索引）
_LIFECYCLE_ORDER: list[TaskLifecycleState] = list(TaskLifecycleState)
_PHASE_ORDER: list[ReasoningPhase] = list(ReasoningPhase)
_LIFECYCLE_IDX: dict[TaskLifecycleState, int] = {
    m: i for i, m in enumerate(_LIFECYCLE_ORDER)
}
_PHASE_IDX: dict[ReasoningPhase, int] = {m: i for i, m in enumerate(_PHASE_ORDER)}


class StateConstraintError(ValueError):
    """状态/拓扑/路由不满足内在约束。"""


class GuardViolation(AssertionError):
    """守卫未通过：上下文不满足递生/制衡契约。"""


# ═══════════════════════════════════════════════════════════════
# 3. 唯一 —— 双维度奇偶一致性状态码
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True, order=True)
class StateCode:
    """任务级 × 回合级 双维度状态编码。"""

    lifecycle: TaskLifecycleState
    phase: ReasoningPhase

    @property
    def parity_consistent(self) -> bool:
        """状态合法性：两维度定义序奇偶一致（奇阳偶阴相配的等价表述）。"""
        return (_LIFECYCLE_IDX[self.lifecycle] & 1) == (_PHASE_IDX[self.phase] & 1)

    @property
    def label(self) -> str:
        return f"{self.lifecycle.value}.{self.phase.value}"


def is_valid(lifecycle: TaskLifecycleState, phase: ReasoningPhase) -> bool:
    """双维度奇偶一致性判定。"""
    return StateCode(lifecycle, phase).parity_consistent


def valid_codes() -> list[StateCode]:
    """合法态全集：10 × 8 = 80 组合中恰好 40 个合法，无重复。"""
    return [
        StateCode(st, p)
        for st in TaskLifecycleState
        for p in ReasoningPhase
        if StateCode(st, p).parity_consistent
    ]


def assert_valid(lifecycle: TaskLifecycleState, phase: ReasoningPhase) -> None:
    """非法组合即拒绝；系统永不进入未定义状态组合。"""
    if not is_valid(lifecycle, phase):
        raise StateConstraintError(
            f"非法状态组合: lifecycle[{lifecycle.value}] × phase[{phase.value}] "
            f"奇偶不一致"
        )


# ═══════════════════════════════════════════════════════════════
# 1. 闭环 —— 生命周期拓扑校验
# ═══════════════════════════════════════════════════════════════


def validate_closure(graph: object) -> tuple[set[str], set[str]]:
    """从入口做可达性遍历，返回 (不可达节点集, 无出口节点集)。

    两者皆为空即闭环成立：
    - 不可达节点：图上存在断头/孤立路径，任务会进入无法触达的环节；
    - 无出口节点：节点存在但无任何出边（无法收敛，潜在死锁）。
    本校验补足 StateGraph.validate 仅做结构检查、不查可达性的缺口。
    """
    entry = getattr(graph, "entry_point", None)
    if entry is None:
        raise StateConstraintError("图无入口，无法校验闭环")
    reachable: set[str] = set()
    queue = deque([entry])
    while queue:
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        for target in graph.successors(node):
            if target == "__end__":
                continue
            queue.append(target)

    nodes: set[str] = set(getattr(graph, "nodes", set()))
    unreachable = nodes - reachable
    dead_ends = {
        n
        for n in nodes
        if not graph.successors(n) and n not in getattr(graph, "static_edges", {})
    }
    return unreachable, dead_ends


def assert_closure(graph: object) -> None:
    """断言闭环成立：不可达节点与无出口节点必须为空。"""
    unreachable, dead_ends = validate_closure(graph)
    if unreachable or dead_ends:
        raise StateConstraintError(
            f"闭环校验失败：不可达节点={sorted(unreachable) or None}, "
            f"无出口节点={sorted(dead_ends) or None}"
        )


# ═══════════════════════════════════════════════════════════════
# 2. 完备 / 6. 归位可推导 —— 路由表校验
# ═══════════════════════════════════════════════════════════════


def assert_routing_coverage(mapping: dict[str, str], vocabulary: set[str]) -> None:
    """路由表须覆盖全部已知决策词汇（不残缺）；未知词不得静默落入默认分支。"""
    missing = vocabulary - set(mapping)
    if missing:
        raise StateConstraintError(f"路由表缺覆盖：{sorted(missing)}")


def assert_routing_functional(mapping: dict[str, str]) -> None:
    """路由表须为函数（归位唯一）：键有值、值非空、无悬空目标。"""
    dangling = [k for k, v in mapping.items() if not v]
    if dangling:
        raise StateConstraintError(f"路由表存在悬空目标：{dangling}")


# ═══════════════════════════════════════════════════════════════
# 4. 递生 —— 产物契约守卫
# ═══════════════════════════════════════════════════════════════


def feedforward_guard(produced: dict, required: list[str], *, stage: str) -> None:
    """前序环节产物须完整满足后序输入契约；缺项即递生断裂。"""
    missing = [k for k in required if k not in produced or produced[k] is None]
    if missing:
        raise GuardViolation(f"[{stage}] 递生断裂：缺后序所需字段 {missing}")


# ═══════════════════════════════════════════════════════════════
# 5. 制衡 —— 三角校验环（产出/验证/质询三方异源）
# ═══════════════════════════════════════════════════════════════


class TriadPhase(Enum):
    PRODUCE = "produce"       # 产出
    VERIFY = "verify"         # 验证
    CHALLENGE = "challenge"   # 质询


class TriadValidator:
    """三角校验环：任何『通过』结论须经历 产出→验证→质询 闭环。

    约束：
    - 相位不得重复（produce 后不得再 produce，直到经过 verify）；
    - 质询前置：必须先有产出与验证；
    - 三方异源：产出者 / 验证者 / 质询者必须互不相同。
    """

    def __init__(self) -> None:
        self._history: list[tuple[TriadPhase, str]] = []

    @property
    def rounds(self) -> int:
        return len([p for p, _ in self._history if p is TriadPhase.CHALLENGE])

    def submit(self, phase: TriadPhase, source: str) -> None:
        if self._history and self._history[-1][0] is phase:
            raise GuardViolation(f"相位重复：{phase.value} 不得连续出现")
        if phase is TriadPhase.CHALLENGE:
            producers = [s for p, s in self._history if p is TriadPhase.PRODUCE]
            verifiers = [s for p, s in self._history if p is TriadPhase.VERIFY]
            if not producers or not verifiers:
                raise GuardViolation("质询前置缺失：必须先有产出与验证")
            if len({producers[-1], verifiers[-1], source}) < 3:
                raise GuardViolation(
                    "三角同源：产出/验证/质询必须来自三个不同主体"
                )
        self._history.append((phase, source))


# ═══════════════════════════════════════════════════════════════
# 7. 门序维度（G0..G11）—— 规范 L2 补全
#    十二门：技术标识语义（与 agent-lifecycle-core 参考内核同源），
#    8 道推进门映射回合级推理阶段，4 道辅助门承载入口/回退/取舍/闭环。
# ═══════════════════════════════════════════════════════════════


class Gate(StrEnum):
    WHY = "why"              # G0 入口：意图动机确认
    READY = "ready"          # G1 素材就绪（transition → COMPILING）
    START = "start"          # G2 方案确立（transition → THINK）
    FLOW = "flow"            # G3 链路无阻（transition → ACT）
    AGGREGATE = "aggregate"  # G4 信息汇拢（transition → OBSERVE）
    REFINE = "refine"        # G5 结论提炼（internal）
    EVIDENCE = "evidence"    # G6 证据昭明（transition → VERIFY）
    GAP = "gap"              # G7 缺口补足（rollback 门）
    TRIM = "trim"            # G8 肃正取舍（internal）
    FINALIZE = "finalize"    # G9 产物定型（transition → DONE）
    ARCHIVE = "archive"      # G10 收束归档（internal）
    CLOSE = "close"          # G11 复盘闭环（closure）


GATE_ORDER: list[Gate] = list(Gate)
_GATE_IDX: dict[Gate, int] = {g: i for i, g in enumerate(GATE_ORDER)}

GATE_KIND: dict[Gate, str] = {
    Gate.WHY: "entry",
    Gate.READY: "transition",
    Gate.START: "transition",
    Gate.FLOW: "transition",
    Gate.AGGREGATE: "transition",
    Gate.REFINE: "internal",
    Gate.EVIDENCE: "transition",
    Gate.GAP: "rollback",
    Gate.TRIM: "internal",
    Gate.FINALIZE: "transition",
    Gate.ARCHIVE: "internal",
    Gate.CLOSE: "closure",
}

# 推进门 → 推理阶段（回合级进入该阶段前须先过对应门）
PHASE_TO_GATE: dict[ReasoningPhase, Gate] = {
    ReasoningPhase.COMPILING: Gate.READY,
    ReasoningPhase.THINK: Gate.START,
    ReasoningPhase.ACT: Gate.FLOW,
    ReasoningPhase.OBSERVE: Gate.AGGREGATE,
    ReasoningPhase.VERIFY: Gate.EVIDENCE,
    ReasoningPhase.DONE: Gate.FINALIZE,
}
GATE_TO_PHASE: dict[Gate, ReasoningPhase] = {v: k for k, v in PHASE_TO_GATE.items()}

# 任务级生命周期 → 主门（进程性阶段归属，用于完备口径编码）
# 终态语义：FAILED→TRIM（失败收束取舍）、CANCELLED→CLOSE（取消后复盘闭环收束）
LIFECYCLE_TO_GATE: dict[TaskLifecycleState, Gate] = {
    TaskLifecycleState.RECEIVED: Gate.WHY,
    TaskLifecycleState.PLANNING: Gate.READY,
    TaskLifecycleState.WAITING_DEPS: Gate.START,
    TaskLifecycleState.EXECUTING: Gate.FLOW,
    TaskLifecycleState.STALLED: Gate.AGGREGATE,
    TaskLifecycleState.REPLANNING: Gate.REFINE,
    TaskLifecycleState.VERIFYING: Gate.EVIDENCE,
    TaskLifecycleState.DONE: Gate.FINALIZE,
    TaskLifecycleState.FAILED: Gate.TRIM,
    TaskLifecycleState.CANCELLED: Gate.CLOSE,
}


@dataclass(frozen=True, order=True)
class GateCode:
    """任务级生命周期 × 门 双维度完备编码。

    规范口径：10 × 12 = 120 组合中恰 60 个奇偶一致合法态。
    与既有运行时口径（StateCode 10×8 → 40 合法）互补：
    40 态为回合推进的可达子集，60 态为含辅助门的完备状态空间。
    """

    lifecycle: TaskLifecycleState
    gate: Gate

    @property
    def parity_consistent(self) -> bool:
        return (_LIFECYCLE_IDX[self.lifecycle] & 1) == (_GATE_IDX[self.gate] & 1)

    @property
    def label(self) -> str:
        return f"{self.lifecycle.value}.{self.gate.value}"


def gate_valid_codes() -> list[GateCode]:
    """规范完备口径：10×12=120 组合中恰 60 个合法态，无重复。"""
    return [
        GateCode(st, g)
        for st in TaskLifecycleState
        for g in GATE_ORDER
        if GateCode(st, g).parity_consistent
    ]


def gate_sequence_ok() -> bool:
    """门序全序校验：恰 12 门且保持定义序。"""
    return list(Gate) == GATE_ORDER and len(GATE_ORDER) == 12


# ---- 门守卫谓词（可注册扩展；正常放行，异常拦截） ----
_GUARD_PREDICATES: dict[Gate, Callable[[dict], bool]] = {}


def register_gate_guard(gate: Gate, predicate: Callable[[dict], bool]) -> None:
    if gate not in GATE_ORDER:
        raise ValueError(f"未知门: {gate}")
    _GUARD_PREDICATES[gate] = predicate


def assert_gate(gate: Gate, ctx: dict | None = None) -> None:
    """门守卫：已注册谓词不通过即拦截；未注册门一律放行。"""
    pred = _GUARD_PREDICATES.get(gate)
    if pred is not None and not pred(ctx or {}):
        raise GuardViolation(f"门守卫拦截: {gate.value}")


# ═══════════════════════════════════════════════════════════════
# 8. 角色 / 星型拓扑 / 对角制衡 —— 规范 L3 补全
# ═══════════════════════════════════════════════════════════════


class AgentRole(StrEnum):
    SECURITY = "security"            # 安全闸门
    PERCEPTION = "perception"        # 输入感知 / 来源登记
    CONTEXT = "context"              # 上下文承载
    EXECUTION = "execution"          # 动作执行
    REASONING = "reasoning"          # 推理生成
    VALIDATION = "validation"        # 结果验证
    ORCHESTRATOR = "orchestrator"    # 编排 / 唯一状态源
    DELIVERY = "delivery"            # 呈现交付
    MEMORY = "memory"                # 长期记忆


ALL_ROLES: frozenset[AgentRole] = frozenset(AgentRole)

# 规范角色名 → 本域角色名（同义映射，不新增第二套角色）。
# 规范里的 COLLECTOR / CONTEXT_POOL / PRESENTER / MEMORY_STORE / GUARD /
# EXECUTOR 在本域分别由 PERCEPTION / CONTEXT / DELIVERY / MEMORY /
# SECURITY / EXECUTION 承载；保留映射是为了让规范术语可机器检索。
ROLE_ALIASES: dict[str, AgentRole] = {
    "ORCHESTRATOR": AgentRole.ORCHESTRATOR,
    "EXECUTOR": AgentRole.EXECUTION,
    "COLLECTOR": AgentRole.PERCEPTION,
    "CONTEXT_POOL": AgentRole.CONTEXT,
    "PRESENTER": AgentRole.DELIVERY,
    "MEMORY_STORE": AgentRole.MEMORY,
    "GUARD": AgentRole.SECURITY,
    "REASONER": AgentRole.REASONING,
    "VALIDATOR": AgentRole.VALIDATION,
}

# 四组对角对位制衡（互为张力、禁止同源）
COUNTERBALANCE: tuple[tuple[AgentRole, AgentRole, str], ...] = (
    (AgentRole.REASONING, AgentRole.VALIDATION, "生成-验证分离：推理产出不得自证"),
    (AgentRole.EXECUTION, AgentRole.DELIVERY, "执行-交付分离：执行不得自我宣称交付成功"),
    (AgentRole.PERCEPTION, AgentRole.CONTEXT, "采集-上下文契约：来源须登记，上下文须可溯"),
    (AgentRole.CONTEXT, AgentRole.MEMORY, "短长隔离：短期上下文与长期记忆读写分流"),
)


class TopologyViolation(ValueError):
    """星型拓扑违规：非编排角色直接调度其他角色。"""


def assert_star_topology(caller: AgentRole, callee: AgentRole) -> None:
    """星型拓扑：仅 ORCHESTRATOR 可调度其他角色，其余角色禁止直接调用。"""
    if caller is not AgentRole.ORCHESTRATOR and caller is not callee:
        raise TopologyViolation(
            f"{caller.value} 不得直接调度 {callee.value}（须经 orchestrator）"
        )


# ═══════════════════════════════════════════════════════════════
# 9. 五类策略注入 —— 规范 L4 补全
# ═══════════════════════════════════════════════════════════════


class StrategyTag(StrEnum):
    GROWTH = "growth"        # 意图导向主动推进
    CLARITY = "clarity"      # 明证可解释
    STABILITY = "stability"  # 完整落盘
    RIGOR = "rigor"          # 验证取舍去伪
    LEARNING = "learning"    # 反思沉淀


STRATEGY_STAGES: dict[StrategyTag, frozenset[TaskLifecycleState]] = {
    StrategyTag.GROWTH: frozenset(
        {
            TaskLifecycleState.RECEIVED,
            TaskLifecycleState.PLANNING,
            TaskLifecycleState.EXECUTING,
        }
    ),
    StrategyTag.CLARITY: frozenset({TaskLifecycleState.VERIFYING}),
    StrategyTag.STABILITY: frozenset(
        {TaskLifecycleState.WAITING_DEPS, TaskLifecycleState.STALLED}
    ),
    StrategyTag.RIGOR: frozenset(
        {TaskLifecycleState.VERIFYING, TaskLifecycleState.REPLANNING}
    ),
    StrategyTag.LEARNING: frozenset(
        {
            TaskLifecycleState.DONE,
            TaskLifecycleState.FAILED,
            TaskLifecycleState.CANCELLED,
        }
    ),
}

STRATEGY_ROLES: dict[StrategyTag, frozenset[AgentRole]] = {
    StrategyTag.GROWTH: frozenset({AgentRole.PERCEPTION, AgentRole.EXECUTION}),
    StrategyTag.CLARITY: frozenset({AgentRole.REASONING, AgentRole.VALIDATION}),
    StrategyTag.STABILITY: frozenset({AgentRole.CONTEXT, AgentRole.MEMORY}),
    StrategyTag.RIGOR: frozenset({AgentRole.VALIDATION, AgentRole.SECURITY}),
    StrategyTag.LEARNING: frozenset({AgentRole.MEMORY}),
}


def strategy_for(lifecycle: TaskLifecycleState, role: AgentRole) -> StrategyTag:
    """归位：命中最先匹配的策略标签（决策表覆盖，无漏路由）。"""
    for tag, stages in STRATEGY_STAGES.items():
        if lifecycle in stages and role in STRATEGY_ROLES[tag]:
            return tag
    return StrategyTag.STABILITY  # 兜底完整落盘


# ═══════════════════════════════════════════════════════════════
# 10. 五相克触发：三条制衡回退 + 两条门谓词
# ═══════════════════════════════════════════════════════════════

BALANCE_RULES: tuple[tuple[str, str], ...] = (
    ("generation_verification", "生成-验证分离：验证发现草稿缺陷 → 回退 THINK 重推"),
    ("verification_intent", "验证-意图边界：产物越界 → 回退 COMPILING 重解析"),
    ("execution_plan", "执行-规划纠偏：连续失败方案失效 → 回退 THINK 重规划"),
    ("generation_prior", "生成-先验约束：生成前须检索记忆先验（READY 门）"),
    ("retrospect_trace", "复盘-数据溯源：复盘仅消费完整审计日志（CLOSE 门）"),
)

BALANCE_ROLLBACK: dict[str, ReasoningPhase] = {
    "generation_verification": ReasoningPhase.THINK,
    "verification_intent": ReasoningPhase.COMPILING,
    "execution_plan": ReasoningPhase.THINK,
}


def rollback_for(task: TaskState, rule_id: str) -> ReasoningPhase:
    """按制衡规则强制回退推理阶段（可超出正常迁移表；先校验触发前提）。"""
    if rule_id not in BALANCE_ROLLBACK:
        raise ValueError(f"未知制衡规则: {rule_id}")
    if rule_id == "generation_verification" and task.phase not in (
        ReasoningPhase.VERIFY,
        ReasoningPhase.OBSERVE,
    ):
        raise GuardViolation("生成-验证分离须在 VERIFY/OBSERVE 触发")
    if rule_id == "verification_intent" and task.phase is not ReasoningPhase.VERIFY:
        raise GuardViolation("验证-意图边界须在 VERIFY 触发")
    if rule_id == "execution_plan" and task.phase not in (
        ReasoningPhase.ACT,
        ReasoningPhase.OBSERVE,
    ):
        raise GuardViolation("执行-规划纠偏须在 ACT/OBSERVE 触发")
    return BALANCE_ROLLBACK[rule_id]


def _prior_searched(ctx: dict) -> bool:
    return bool(ctx.get("prior_searched"))


def _audit_log_complete(ctx: dict) -> bool:
    return bool(ctx.get("audit_log_complete"))


register_gate_guard(Gate.READY, _prior_searched)
register_gate_guard(Gate.CLOSE, _audit_log_complete)


# ═══════════════════════════════════════════════════════════════
# 11. 完整性自检（映射补全的机器校验，构建期 fail-fast）
# ═══════════════════════════════════════════════════════════════


def assert_complete_mapping() -> None:
    """全部映射补全自检：门序/60 态/九角色/四制衡/五策略/五相克表闭合。"""
    if not gate_sequence_ok():
        raise StateConstraintError("门序残缺：须恰 12 门且保持定义序")
    codes = gate_valid_codes()
    if len(codes) != 60 or len({c.label for c in codes}) != 60:
        raise StateConstraintError(f"完备口径错误：应 60 合法态，实得 {len(codes)}")
    if len(ALL_ROLES) != 9:
        raise StateConstraintError("角色残缺：须 9 角色")
    if len(COUNTERBALANCE) != 4:
        raise StateConstraintError("对角制衡残缺：须 4 组")
    if set(STRATEGY_STAGES) != set(StrategyTag) or set(STRATEGY_ROLES) != set(StrategyTag):
        raise StateConstraintError("策略注入表残缺")
    rule_ids = {r for r, _ in BALANCE_RULES}
    if set(BALANCE_ROLLBACK) | {"generation_prior", "retrospect_trace"} != rule_ids:
        raise StateConstraintError("相克制衡表不闭合")
    for g in GATE_ORDER:
        pred = _GUARD_PREDICATES.get(g)
        if pred is not None and not callable(pred):
            raise StateConstraintError(f"门谓词不可调用: {g.value}")


# ═══════════════════════════════════════════════════════════════
# 12. 门序语义一致性 —— 生命周期×回合 推进合理性
#     以 12 门序为统一坐标系：生命周期阶段与回合阶段各自投影到
#     门序上，门距 ≤ window 即语义一致（同门或相邻推进门）。
#     补充代数奇偶校验（is_valid）无法覆盖的推进语义。
# ═══════════════════════════════════════════════════════════════


def gate_index(g: Gate) -> int:
    return _GATE_IDX[g]


def derive_lifecycle_for(phase: ReasoningPhase) -> TaskLifecycleState | None:
    """由回合推进门推导生命周期应处阶段（门序同门归属）。

    委托 agent.state.derive_lifecycle_for_phase —— 单一事实来源，
    避免映射双写漂移。仅推进阶段可推导；入口（IDLE）与中断
    （AWAITING_USER）阶段返回 None，调用方须保持生命周期现值。
    """
    return derive_lifecycle_for_phase(phase)


def semantic_consistent(
    lifecycle: TaskLifecycleState, phase: ReasoningPhase, window: int = 1
) -> bool:
    """生命周期主门与回合推进门的门距 ≤ window 即推进语义一致。

    入口（IDLE）与中断（AWAITING_USER）阶段无推进门，视为推进
    窗口内任意：只要任务未达终态（DONE/FAILED/CANCELLED），即与
    当前生命周期语义一致（中断不改变任务所处阶段）。
    """
    lgate = LIFECYCLE_TO_GATE.get(lifecycle)
    pgate = PHASE_TO_GATE.get(phase)
    if pgate is None:
        # 入口/中断阶段：与进行中生命周期一致，与终态冲突
        return lifecycle not in {
            TaskLifecycleState.DONE,
            TaskLifecycleState.FAILED,
            TaskLifecycleState.CANCELLED,
        }
    if lgate is None:
        return False
    return abs(gate_index(lgate) - gate_index(pgate)) <= window


def assert_semantic_consistent(
    lifecycle: TaskLifecycleState, phase: ReasoningPhase, *, stage: str = ""
) -> None:
    """语义一致性守卫：生命周期与回合推进脱节即拦截（正常放行，脱节拦截）。"""
    if not semantic_consistent(lifecycle, phase):
        prefix = f"[{stage}] " if stage else ""
        raise GuardViolation(
            f"{prefix}门序语义脱节：{lifecycle.value}(门 {LIFECYCLE_TO_GATE.get(lifecycle).value if LIFECYCLE_TO_GATE.get(lifecycle) else '?'}) "
            f"× {phase.value}(门 {PHASE_TO_GATE.get(phase).value if PHASE_TO_GATE.get(phase) else '?'})"
        )


def apply_rollback_to(task: TaskState, rule_id: str) -> ReasoningPhase:
    """制衡回退一体化入口：触发前提校验 → 强制回退阶段 → 生命周期门序同步。

    回退可能超出正常迁移表（制衡干预），直接设置 phase；随后按
    推进门推导同步生命周期（非推进门阶段保持现值）。
    """
    target = rollback_for(task, rule_id)
    task.phase = target
    derived = derive_lifecycle_for_phase(target)
    if derived is not None:
        task.lifecycle = derived
    return target


def advance_guarded(
    task: TaskState, target: ReasoningPhase, ctx: dict | None = None
) -> None:
    """守卫推进一体化入口：推进门守卫 → 合法迁移（含生命周期同步）→ 语义校验。

    供推理循环在真实推进点选用；ctx 仅携带门守卫所需上下文
    （如 READY 门需 prior_searched）。
    """
    gate = PHASE_TO_GATE.get(target)
    if gate is not None:
        assert_gate(gate, ctx or {})
    task.transition(target)
    assert_semantic_consistent(task.lifecycle, task.phase, stage="advance_guarded")
