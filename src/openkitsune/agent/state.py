"""Agent-level state for the v2 runtime.

The previous ``core/agent_state.py`` (431 lines) absorbed many concerns
that the v2 architecture now solves elsewhere:

* cancel mechanics moved to :class:`runtime.cancel_token.CancellationToken`;
* skip / user-insert routing moves to the messenger and stream bus;
* loop detection moves to the supervisor's stall detector and the
  progress ledger;
* per-turn iteration count is the supervisor's ``n_turns``.

What remains is a small, well-named record of the agent's *own*
context: which task it is currently servicing, which session and
conversation that belongs to, the sub-status within a single ReAct
turn, and a few counters that only the agent itself uses.

This module is the leaf of the agent layering described in ADR-0003.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any
from uuid import uuid4

from openkitsune.runtime.cancel_token import CancellationToken
from openkitsune.runtime.models import TaskLifecycleState

__all__ = [
    "ReasoningPhase",
    "TaskState",
    "AgentState",
    "derive_lifecycle_for_phase",
]


class ReasoningPhase(StrEnum):
    """Sub-status inside a single ReAct turn.

    Distinct from :class:`runtime.models.TaskLifecycleState`, which
    tracks the *task* (across many turns). ReasoningPhase tracks the
    *current turn* of an agent's thought / act / observe cycle. Both
    move together: a task can be ``EXECUTING`` while a single turn
    moves through ``THINK -> ACT -> OBSERVE -> THINK``.
    """

    IDLE = "idle"
    COMPILING = "compiling"
    THINK = "think"
    ACT = "act"
    OBSERVE = "observe"
    VERIFY = "verify"
    AWAITING_USER = "awaiting_user"
    DONE = "done"


class _PhaseRole(Enum):
    """推理阶段的内在职能签名（技术语义，非领域名词）。

    迁移合法性不再逐条手写，而是由『职能签名 + 递生链 + 收敛规则』推导：
    - ENTRY 启动位、COMPILE 汇编产物、DECIDE 消费并产出决策、
      ACT 消费决策产出动作、OBSERVE 消费动作产出观察、
      VERIFY 消费观察产出判定、INTERRUPT 中断等待、TERMINAL 终态复位。
    """

    ENTRY = "entry"
    COMPILE = "compile"
    DECIDE = "decide"
    ACT = "act"
    OBSERVE = "observe"
    VERIFY = "verify"
    INTERRUPT = "interrupt"
    TERMINAL = "terminal"


# 阶段 → 职能签名（唯一事实来源；迁移关系全部由规则推导）
_PHASE_ROLE: dict[ReasoningPhase, _PhaseRole] = {
    ReasoningPhase.IDLE: _PhaseRole.ENTRY,
    ReasoningPhase.COMPILING: _PhaseRole.COMPILE,
    ReasoningPhase.THINK: _PhaseRole.DECIDE,
    ReasoningPhase.ACT: _PhaseRole.ACT,
    ReasoningPhase.OBSERVE: _PhaseRole.OBSERVE,
    ReasoningPhase.VERIFY: _PhaseRole.VERIFY,
    ReasoningPhase.AWAITING_USER: _PhaseRole.INTERRUPT,
    ReasoningPhase.DONE: _PhaseRole.TERMINAL,
}

# 递生链：沿『汇编→决策→行动→观察→判定』的产物契约单向推进，
# 每个环节的产物恰好被下一环节消费（前序产物满足后序输入）。
_PRODUCE_CHAIN: tuple[_PhaseRole, ...] = (
    _PhaseRole.COMPILE,
    _PhaseRole.DECIDE,
    _PhaseRole.ACT,
    _PhaseRole.OBSERVE,
    _PhaseRole.VERIFY,
)


def _derive_phase_transitions() -> dict[ReasoningPhase, frozenset[ReasoningPhase]]:
    """由内在规则推导推理阶段迁移表（不逐条硬编码）。

    推导规则：
    1. 递生链：COMPILE 产物供 DECIDE 消费；DECIDE 可产出 ACT / VERIFY /
       中断 / 终态；ACT 产出 OBSERVE / 中断 / 终态；OBSERVE 回 DECIDE
       （再决策）或进 VERIFY / 终态；
    2. 判定收敛：VERIFY 通过进终态，未过回 DECIDE（唯一回退路径）；
    3. 中断归位：INTERRUPT 仅在收到用户输入后回 DECIDE 或进终态；
    4. 终态复位：TERMINAL 唯一出边回 ENTRY，完成一轮闭环。
    """
    table: dict[ReasoningPhase, set[ReasoningPhase]] = {}
    for phase, role in _PHASE_ROLE.items():
        targets: set[ReasoningPhase] = set()
        if role is _PhaseRole.ENTRY:
            targets |= {ReasoningPhase.COMPILING, ReasoningPhase.THINK, ReasoningPhase.DONE}
        elif role is _PhaseRole.COMPILE:
            targets |= {ReasoningPhase.THINK, ReasoningPhase.DONE}
        elif role is _PhaseRole.DECIDE:
            targets |= {ReasoningPhase.ACT, ReasoningPhase.VERIFY, ReasoningPhase.AWAITING_USER, ReasoningPhase.DONE}
        elif role is _PhaseRole.ACT:
            targets |= {ReasoningPhase.OBSERVE, ReasoningPhase.AWAITING_USER, ReasoningPhase.DONE}
        elif role is _PhaseRole.OBSERVE:
            targets |= {ReasoningPhase.THINK, ReasoningPhase.VERIFY, ReasoningPhase.DONE}
        elif role is _PhaseRole.VERIFY:
            targets |= {ReasoningPhase.DONE, ReasoningPhase.THINK}
        elif role is _PhaseRole.INTERRUPT:
            targets |= {ReasoningPhase.THINK, ReasoningPhase.DONE}
        elif role is _PhaseRole.TERMINAL:
            targets |= {ReasoningPhase.IDLE}
        table[phase] = frozenset(targets)
    return table


_VALID_PHASE_TRANSITIONS: dict[ReasoningPhase, frozenset[ReasoningPhase]] = (
    _derive_phase_transitions()
)


# ---------------------------------------------------------------------------
# 生命周期随门序同步（单一事实来源）
# ---------------------------------------------------------------------------

# 推进阶段 → 任务级生命周期应处阶段（门序同门归属）。
# 与约束层 lifecycle_constraints.PHASE_TO_GATE × LIFECYCLE_TO_GATE 语义同源：
#   COMPILING→READY→PLANNING   THINK→START→WAITING_DEPS
#   ACT→FLOW→EXECUTING         OBSERVE→AGGREGATE→STALLED
#   VERIFY→EVIDENCE→VERIFYING  DONE→FINALIZE→DONE
# 入口（IDLE）与中断（AWAITING_USER）阶段无推进门映射 → None：
# 调用方须保持生命周期现值，不得误打回初始态。
_LIFECYCLE_FOR_PHASE: dict[ReasoningPhase, TaskLifecycleState | None] = {
    ReasoningPhase.COMPILING: TaskLifecycleState.PLANNING,
    ReasoningPhase.THINK: TaskLifecycleState.WAITING_DEPS,
    ReasoningPhase.ACT: TaskLifecycleState.EXECUTING,
    ReasoningPhase.OBSERVE: TaskLifecycleState.STALLED,
    ReasoningPhase.VERIFY: TaskLifecycleState.VERIFYING,
    ReasoningPhase.DONE: TaskLifecycleState.DONE,
    ReasoningPhase.IDLE: None,
    ReasoningPhase.AWAITING_USER: None,
}


def derive_lifecycle_for_phase(phase: ReasoningPhase) -> TaskLifecycleState | None:
    """推进阶段 → 生命周期应处阶段（None = 无推进门，保持现值）。"""
    return _LIFECYCLE_FOR_PHASE.get(phase)


# 推理阶段 → 复合坐标 stage_idx（与 core/agent_state.STATUS_TO_STAGE 同口径）。
# 入口/中断阶段保持现值；S3_DRAFT / S7_OPTIMIZE / S9_RETROSPECT 没有独立
# phase（分别发生在 THINK 的流式输出、VERIFY 的收敛循环、DONE 后的收尾）。
_STAGE_FOR_PHASE: dict[ReasoningPhase, int | None] = {
    ReasoningPhase.COMPILING: 1,
    ReasoningPhase.THINK: 2,
    ReasoningPhase.ACT: 4,
    ReasoningPhase.OBSERVE: 5,
    ReasoningPhase.VERIFY: 6,
    ReasoningPhase.DONE: 8,
    ReasoningPhase.IDLE: None,
    ReasoningPhase.AWAITING_USER: None,
}


@dataclass
class TaskState:
    """Per-task state held inside a single agent.

    Mutates in place during a chat turn. The token field is the agent's
    handle to cooperative cancellation: stopping a task is
    ``state.cancel_token.cancel(reason)``, never raise-by-surprise.
    """

    task_id: str
    session_id: str = ""
    conversation_id: str = ""
    lifecycle: TaskLifecycleState = TaskLifecycleState.RECEIVED
    phase: ReasoningPhase = ReasoningPhase.IDLE
    cancel_token: CancellationToken = field(default_factory=CancellationToken)

    # Per-turn counters consumed by the agent's own self-checks. The
    # supervisor has its own counters; these are local hints.
    iteration: int = 0
    consecutive_tool_calls: int = 0
    tools_executed: list[str] = field(default_factory=list)
    last_tool_signature: str | None = None

    # Identifiers we need to surface to telemetry but the agent does not
    # mutate after task creation.
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def transition(self, target: ReasoningPhase) -> None:
        """Move to ``target``, validating the transition.

        Raises ``ValueError`` on illegal transitions. The previous code
        logged a warning and forced the move; v2 raises so bugs surface
        in tests rather than corrupting state silently.

        After a legal move, the task-level lifecycle follows the gate
        order automatically: progressing phases sync their lifecycle
        stage (COMPILING→PLANNING, … VERIFY→VERIFYING, DONE→DONE).
        Entry (IDLE) and interrupt (AWAITING_USER) phases keep the
        current lifecycle value (they are not gate-bound).
        """
        allowed = _VALID_PHASE_TRANSITIONS.get(self.phase, frozenset())
        if target not in allowed:
            raise ValueError(
                f"illegal ReasoningPhase transition: "
                f"{self.phase.value} -> {target.value} "
                f"(allowed: {sorted(s.value for s in allowed)})"
            )
        self.phase = target
        derived = derive_lifecycle_for_phase(target)
        if derived is not None:
            self.lifecycle = derived
        self._sync_composite_state()

    def _sync_composite_state(self) -> None:
        """按当前 phase 同步 (stage_idx, gate_idx)。

        入口（IDLE）与中断（AWAITING_USER）阶段不移动坐标。``gate_idx``
        取与 ``stage_idx`` 相同的值，保证 ``is_valid()`` 的奇偶校验恒成立。
        """
        stage = _STAGE_FOR_PHASE.get(self.phase)
        if stage is None:
            return
        self.stage_idx = stage
        self.gate_idx = stage

    # ------------------------------------------------------------------
    # Cooperative cancel adapter
    # ------------------------------------------------------------------

    def cancel(self, reason: str = "") -> bool:
        """Cancel the task cooperatively. Idempotent."""
        if self.cancel_token.cancel(reason):
            self.lifecycle = TaskLifecycleState.CANCELLED
            return True
        return False

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_token.is_cancelled()

    # ------------------------------------------------------------------
    # Tool history (used by the agent's local stall heuristic)
    # ------------------------------------------------------------------

    def record_tool_call(self, name: str, signature: str | None = None) -> None:
        self.tools_executed.append(name)
        self.consecutive_tool_calls += 1
        if signature is not None:
            self.last_tool_signature = signature

    def reset_tool_streak(self) -> None:
        self.consecutive_tool_calls = 0

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def mark_done(self, *, success: bool) -> None:
        self.lifecycle = TaskLifecycleState.DONE if success else TaskLifecycleState.FAILED
        self.phase = ReasoningPhase.DONE
        self.finished_at = datetime.now(UTC)

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    # ------------------------------------------------------------------
    # 双维度状态编码（任务级 × 回合级）
    # ------------------------------------------------------------------

    @property
    def state_code(self) -> str:
        """双维度状态编码 ``lifecycle.phase``。

        供奇偶一致性校验（openkitsune.agent.lifecycle_constraints）与
        诊断使用；只读派生字段，不改变任何既有运行路径。
        """
        return f"{self.lifecycle.value}.{self.phase.value}"

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 复合状态编码（任务级 × 回合级 × 校验门）—— 规范第 7 章
    # TaskState 新增 stage_idx + gate_idx 双维度，合法性由奇偶校验保证。
    # 与 lifecycle_constraints.Gate.parity_consistent 同义：
    #   is_valid() = (stage_idx % 2) == (gate_idx % 2)
    # 合法态共 60 个（10×12=120，同奇偶恰 60），另外 60 个失衡态被 is_valid 拦截。
    # ------------------------------------------------------------------

    stage_idx: int = 0
    gate_idx: int = 0

    def is_valid(self) -> bool:
        """复合状态合法性校验（规范第 7 章）。

        推进序号与校验序号同奇偶且在各自值域内（stage 0-9，gate 0-11）
        → 合法态；越界或异奇偶 → 失衡态，由 :meth:`advance` 拦截。
        """
        if not (0 <= self.stage_idx <= 9 and 0 <= self.gate_idx <= 11):
            return False
        return (self.stage_idx % 2) == (self.gate_idx % 2)

    def advance(self) -> tuple[int, int]:
        """规范 advance()：先过当前门再推进，保持同频。

        Returns:
            (new_stage_idx, new_gate_idx)

        Raises:
            ValueError: 推进越界（stage > 9 / gate > 11）或同奇偶校验失败。
        """
        new_stage = self.stage_idx + 1
        new_gate = self.gate_idx + 1
        if new_stage > 9 or new_gate > 11:
            raise ValueError(
                f"推进越界：stage={new_stage} (上限 9), gate={new_gate} (上限 11) – "
                f"已到流程终点，不能继续 advance()。"
            )
        if (new_stage % 2) != (new_gate % 2):
            raise ValueError(
                f"推进后失衡：stage={new_stage} (奇), gate={new_gate} (偶) – "
                f"同频推进必须同奇偶。这是失衡态之一。"
            )
        self.stage_idx = new_stage
        self.gate_idx = new_gate
        return (new_stage, new_gate)

    def rollback(self) -> tuple[int, int]:
        """规范 rollback()：同步回退 stage 和 gate。"""
        if self.stage_idx == 0 and self.gate_idx == 0:
            raise ValueError("rollback to initial state")
        new_stage = max(0, self.stage_idx - 1)
        new_gate = max(0, self.gate_idx - 1)
        self.stage_idx = new_stage
        self.gate_idx = new_gate
        return (new_stage, new_gate)

    # Serialisation
    # ------------------------------------------------------------------

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "lifecycle": self.lifecycle.value,
            "phase": self.phase.value,
            "iteration": self.iteration,
            "consecutive_tool_calls": self.consecutive_tool_calls,
            "tools_executed": list(self.tools_executed),
            "last_tool_signature": self.last_tool_signature,
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.finished_at.isoformat() if self.finished_at else None),
            "is_cancelled": self.is_cancelled,
        }


# ---------------------------------------------------------------------------
# AgentState — registry across sessions
# ---------------------------------------------------------------------------


def _new_task_id() -> str:
    return f"task_{uuid4().hex[:12]}"


class AgentState:
    """Per-agent state holding a registry of in-flight tasks by session.

    A single :class:`Agent` instance can serve many sessions
    concurrently; we key tasks by ``session_id``. The previous code added
    a ``current_task`` shim for back-compat; v2 drops the shim because
    callers always know which session they are in (the supervisor and
    messenger pass it through).
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._lock = threading.RLock()
        self._initialized: bool = False
        self._running: bool = False

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def begin_task(
        self,
        *,
        session_id: str = "",
        conversation_id: str = "",
        task_id: str | None = None,
    ) -> TaskState:
        """Register a new TaskState for ``session_id``.

        Replaces any pre-existing task for the same session (same
        semantic as the previous code, but explicit rather than
        background-cleared).
        """
        state = TaskState(
            task_id=task_id or _new_task_id(),
            session_id=session_id,
            conversation_id=conversation_id,
        )
        with self._lock:
            self._tasks[session_id or state.task_id] = state
        return state

    def get_task(self, session_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(session_id)

    def end_task(self, session_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.pop(session_id, None)

    def list_tasks(self) -> list[TaskState]:
        with self._lock:
            return list(self._tasks.values())

    def cancel_task(self, session_id: str, reason: str = "") -> bool:
        with self._lock:
            task = self._tasks.get(session_id)
        return task.cancel(reason) if task else False

    def cancel_all(self, reason: str = "agent shutdown") -> int:
        n = 0
        with self._lock:
            tasks = list(self._tasks.values())
        for t in tasks:
            if t.cancel(reason):
                n += 1
        return n

    # ------------------------------------------------------------------
    # Agent-level flags
    # ------------------------------------------------------------------

    @property
    def initialized(self) -> bool:
        return self._initialized

    @initialized.setter
    def initialized(self, value: bool) -> None:
        self._initialized = bool(value)

    @property
    def running(self) -> bool:
        return self._running

    @running.setter
    def running(self, value: bool) -> None:
        self._running = bool(value)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def to_jsonable(self) -> dict[str, Any]:
        with self._lock:
            tasks = [t.to_jsonable() for t in self._tasks.values()]
        return {
            "initialized": self._initialized,
            "running": self._running,
            "task_count": len(tasks),
            "tasks": tasks,
        }
