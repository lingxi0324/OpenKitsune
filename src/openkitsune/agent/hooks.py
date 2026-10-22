"""Hook 扩展系统。

参考 Claude Code 的 28 种生命周期 Hook 事件设计。
支持:
- Shell 脚本 hooks
- Python callback hooks
- HTTP webhook hooks
- 配置文件声明 + 运行时动态注册
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HookEvent(StrEnum):
    """生命周期 Hook 事件"""

    # Tool lifecycle
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Agent lifecycle
    STOP = "stop"
    STOP_FAILURE = "stop_failure"
    SUB_AGENT_START = "sub_agent_start"
    SUB_AGENT_STOP = "sub_agent_stop"

    # Context management
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"

    # Permission
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_DENIED = "permission_denied"

    # Notification
    NOTIFICATION = "notification"
    USER_PROMPT_SUBMIT = "user_prompt_submit"

    # Task management
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"

    # Plan compliance (plan_guard hook layer)
    PLAN_CREATED = "plan_created"
    PLAN_STEP_TOOL = "plan_step_tool"
    PLAN_STEP_UPDATE = "plan_step_update"
    PLAN_TURN_END = "plan_turn_end"

    # Configuration
    CONFIG_CHANGE = "config_change"

    # File system
    FILE_CHANGED = "file_changed"
    CWD_CHANGED = "cwd_changed"

    # Worktree
    WORKTREE_CREATE = "worktree_create"
    WORKTREE_REMOVE = "worktree_remove"

    # Custom
    CUSTOM = "custom"


@dataclass
class HookResult:
    """Hook 执行结果。

    ``decision`` 为 Hook 的裁决（allow / warn / block），供
    :meth:`HookExecutor.execute_first_blocking` 聚合；``feedback`` 是
    需要回注给模型/调用方的提示文本。两者默认值保证旧 Hook 行为不变。
    """

    hook_id: str
    event: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0
    decision: str = "allow"
    feedback: str = ""


class HookHandler:
    """Hook 处理器基类"""

    def __init__(self, hook_id: str, events: list[HookEvent]) -> None:
        self.hook_id = hook_id
        self.events = events

    async def execute(self, event: HookEvent, context: dict) -> HookResult:
        raise NotImplementedError


class CallbackHook(HookHandler):
    """Python 回调 Hook"""

    def __init__(
        self,
        hook_id: str,
        events: list[HookEvent],
        callback: Callable[..., Any] | Callable[..., Coroutine],
    ) -> None:
        super().__init__(hook_id, events)
        self._callback = callback

    async def execute(self, event: HookEvent, context: dict) -> HookResult:
        import time

        start = time.monotonic()
        try:
            result = self._callback(event, context)
            if asyncio.iscoroutine(result):
                result = await result
            duration = (time.monotonic() - start) * 1000
            if isinstance(result, HookResult):
                result.duration_ms = result.duration_ms or duration
                return result
            if isinstance(result, dict):
                return HookResult(
                    hook_id=self.hook_id,
                    event=event.value,
                    success=True,
                    output=str(result.get("output", "")),
                    decision=str(result.get("decision", "allow")),
                    feedback=str(result.get("feedback", "")),
                    duration_ms=duration,
                )
            return HookResult(
                hook_id=self.hook_id,
                event=event.value,
                success=True,
                output=str(result) if result else "",
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return HookResult(
                hook_id=self.hook_id,
                event=event.value,
                success=False,
                error=str(e),
                duration_ms=duration,
            )


class ShellHook(HookHandler):
    """Shell 脚本 Hook"""

    def __init__(
        self,
        hook_id: str,
        events: list[HookEvent],
        command: str,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(hook_id, events)
        self._command = command
        self._timeout = timeout

    async def execute(self, event: HookEvent, context: dict) -> HookResult:
        import json
        import time

        start = time.monotonic()
        env_context = json.dumps(context, default=str, ensure_ascii=False)
        try:
            proc = await asyncio.create_subprocess_shell(
                self._command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"HOOK_EVENT": event.value, "HOOK_CONTEXT": env_context},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            duration = (time.monotonic() - start) * 1000
            return HookResult(
                hook_id=self.hook_id,
                event=event.value,
                success=proc.returncode == 0,
                output=stdout.decode(errors="replace") if stdout else "",
                error=stderr.decode(errors="replace") if stderr else "",
                duration_ms=duration,
            )
        except TimeoutError:
            duration = (time.monotonic() - start) * 1000
            return HookResult(
                hook_id=self.hook_id,
                event=event.value,
                success=False,
                error=f"Shell hook timed out after {self._timeout}s",
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return HookResult(
                hook_id=self.hook_id,
                event=event.value,
                success=False,
                error=str(e),
                duration_ms=duration,
            )


class HookExecutor:
    """Hook 执行器"""

    def __init__(self) -> None:
        self._handlers: list[HookHandler] = []

    def register(self, handler: HookHandler) -> None:
        """注册一个 Hook 处理器。"""
        self._handlers.append(handler)
        logger.debug(
            "Registered hook %s for events: %s",
            handler.hook_id,
            [e.value for e in handler.events],
        )

    def unregister(self, hook_id: str) -> None:
        """取消注册。"""
        self._handlers = [h for h in self._handlers if h.hook_id != hook_id]

    def has_handler(self, hook_id: str) -> bool:
        """是否已注册指定 hook_id（幂等注册用）。"""
        return any(h.hook_id == hook_id for h in self._handlers)

    def register_callback(
        self,
        hook_id: str,
        events: list[HookEvent],
        callback: Callable,
    ) -> None:
        """便捷方法：注册 Python 回调 Hook。"""
        self.register(CallbackHook(hook_id, events, callback))

    def register_shell(
        self,
        hook_id: str,
        events: list[HookEvent],
        command: str,
        timeout: float = 30.0,
    ) -> None:
        """便捷方法：注册 Shell 脚本 Hook。"""
        self.register(ShellHook(hook_id, events, command, timeout))

    async def execute(
        self,
        event: HookEvent,
        context: dict | None = None,
    ) -> list[HookResult]:
        """执行指定事件的所有匹配 Hooks。"""
        context = context or {}
        matching = [h for h in self._handlers if event in h.events]

        if not matching:
            return []

        results = []
        for handler in matching:
            try:
                result = await handler.execute(event, context)
                results.append(result)
                if not result.success:
                    logger.warning(
                        "Hook %s failed for %s: %s",
                        handler.hook_id,
                        event.value,
                        result.error,
                    )
            except Exception as e:
                logger.error(
                    "Hook %s crashed for %s: %s",
                    handler.hook_id,
                    event.value,
                    e,
                )
                results.append(
                    HookResult(
                        hook_id=handler.hook_id,
                        event=event.value,
                        success=False,
                        error=str(e),
                    )
                )

        return results

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

    async def execute_first_blocking(
        self,
        event: HookEvent,
        context: dict | None = None,
    ) -> HookResult | None:
        """执行事件的所有 Hooks，返回第一个 ``decision == "block"`` 的结果。

        语义：阻断优先。一旦某个 Hook 明确阻断，后续 Hook 仍会执行（审计
        完整性），但调用方只需要拿到第一份阻断理由。没有阻断时返回 None。
        所有异常都被吞掉——Hook 层永远不能因为自身故障阻断主流程。
        """
        results = await self.execute(event, context)
        for result in results:
            if result.success and result.decision == "block":
                return result
        return None

    async def execute_collect_feedback(
        self,
        event: HookEvent,
        context: dict | None = None,
    ) -> list[str]:
        """执行事件的所有 Hooks，收集 warn/block 的 feedback 文本。"""
        results = await self.execute(event, context)
        return [
            r.feedback
            for r in results
            if r.success and r.decision in ("warn", "block") and r.feedback
        ]


# Global hook executor instance
_global_executor: HookExecutor | None = None


def get_hook_executor() -> HookExecutor:
    """获取全局 Hook 执行器。"""
    global _global_executor
    if _global_executor is None:
        _global_executor = HookExecutor()
    return _global_executor


def set_hook_executor(executor: HookExecutor) -> None:
    """替换全局 Hook 执行器（用于测试）。"""
    global _global_executor
    _global_executor = executor
