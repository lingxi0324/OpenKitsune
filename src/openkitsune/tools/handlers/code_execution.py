"""Execute Code 工具处理器（OpenKitsune 适配移植自 Hermes code_execution_tool）

- 持久会话内核：一个子进程常驻，变量/import 跨调用存活（reset=true 重置）
- 脚本内编程式工具调用：默认只读安全白名单（自动从 handler_registry 的
  ApprovalClass 推导 + 保守基础集合），执行类/破坏类工具一律排除
- 超时 / 中断熔断：杀掉内核进程树并丢弃状态，下个调用重新拉起
- stdout 超出内联上限：head/tail 截断 + 全文落盘返回路径

# ApprovalClass checklist (新增 / 修改工具时必读)
# 1. TOOLS 列表加工具名
# 2. TOOL_CLASSES 加 ApprovalClass 显式声明
# 3. 行为依赖参数 → policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
# 详见 docs/policy_v2_research.md §4.21
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from typing import TYPE_CHECKING, Any, Callable

from ...config import settings
from ...core.policy_v2 import ApprovalClass

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)

# 保守的基础脚本内工具白名单（registry 未显式分类时仍放行；执行类显式
# 分类的工具无论是否在此集合都会被强制排除）。
_SAFE_BASE_TOOLS = frozenset(
    {
        "read_file",
        "list_directory",
        "grep",
        "search_memory",
        "web_search",
        "web_fetch",
        "knowledge_list",
        "knowledge_search",
        "get_skill_info",
        "tool_search",
        "get_tool_info",
    }
)

_SAFE_CLASSES = frozenset(
    {
        ApprovalClass.READONLY_SCOPED,
        ApprovalClass.READONLY_GLOBAL,
        ApprovalClass.READONLY_SEARCH,
    }
)

_BLOCKED_CLASSES = frozenset(
    {
        ApprovalClass.EXEC_LOW_RISK,
        ApprovalClass.EXEC_CAPABLE,
        ApprovalClass.DESTRUCTIVE,
        ApprovalClass.MUTATING_SCOPED,
        ApprovalClass.MUTATING_GLOBAL,
        ApprovalClass.CONTROL_PLANE,
        ApprovalClass.INTERACTIVE,
        ApprovalClass.NETWORK_OUT,
        ApprovalClass.UNKNOWN,
    }
)


def _compute_sandbox_tools(agent: "Agent", extra: list[str] | None) -> frozenset[str]:
    """推导脚本内工具白名单：基础安全集合 + registry 显式 READONLY 类工具。

    任何被 registry 显式标为执行/破坏/修改类的工具一律排除；未显式分类的
    基础集合工具放行（保守只读）。``extra`` 来自参数/配置，同样受类别钳制。
    """
    candidates = set(_SAFE_BASE_TOOLS)
    if extra:
        candidates.update(str(t) for t in extra if t)
    allowed: set[str] = set()
    registry = getattr(agent, "handler_registry", None)
    if registry is not None and hasattr(registry, "get_tool_class"):
        for name in candidates:
            klass = registry.get_tool_class(name)
            if klass is None:
                allowed.add(name)
            elif isinstance(klass, tuple) and klass[0] in _SAFE_CLASSES:
                allowed.add(name)
        # registry 里显式 READONLY 的工具自动加入（无论是否在基础集合）
        if hasattr(registry, "list_tools"):
            for name in registry.list_tools():
                klass = registry.get_tool_class(name)
                if klass is not None and isinstance(klass, tuple) and klass[0] in _SAFE_CLASSES:
                    allowed.add(name)
    else:
        allowed = set(candidates)
    return frozenset(allowed)


def _format_result(raw_json: str) -> str:
    """把内核返回的 JSON 结果组装成 LLM 友好文本。"""
    try:
        r = json.loads(raw_json)
    except Exception:
        return raw_json
    if not isinstance(r, dict):
        return raw_json
    kernel = r.get("kernel") or {}
    status = r.get("status", "ok")
    header = (
        f"[execute_code] status={status} "
        f"duration={r.get('duration_seconds', '?')}s "
        f"kernel={'reused' if kernel.get('reused') else 'new'}"
        f"{' (state reset)' if kernel.get('state_reset') else ''} "
        f"exec_count={kernel.get('execution_count')} "
        f"tool_calls={r.get('tool_calls_made', 0)}"
    )
    parts = [header]
    out = r.get("output")
    if out:
        parts.append(str(out))
    err = r.get("error")
    if err:
        parts.append(f"--- error ---\n{err}")
    hint = r.get("hint")
    if hint:
        parts.append(f"hint: {hint}")
    warning = r.get("warning")
    if warning:
        parts.append(f"warning: {warning}")
    spill = r.get("stdout_spill_path")
    if spill:
        parts.append(f"full stdout saved to: {spill}")
    tool_errors = r.get("tool_errors")
    if tool_errors:
        summary = ", ".join(
            f"{e.get('tool')}: {str(e.get('error'))[:100]}" for e in tool_errors
        )
        parts.append(f"script tool errors: {summary}")
    return "\n".join(parts)


class CodeExecutionHandler:
    """Execute Code 工具处理器"""

    TOOLS = ["execute_code"]
    TOOL_CLASSES = {"execute_code": ApprovalClass.EXEC_CAPABLE}

    def __init__(self, agent: "Agent"):
        self.agent = agent

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name == "execute_code":
            return await self._execute_code(params)
        return f"Unknown code_execution tool: {tool_name}"

    async def _execute_code(self, params: dict[str, Any]) -> str:
        code = params.get("code", "")
        if not isinstance(code, str) or not code.strip():
            return "execute_code requires a non-empty 'code' parameter."
        reset = bool(params.get("reset", False))

        try:
            timeout = int(params.get("timeout", settings.code_execution_default_timeout_seconds))
        except (TypeError, ValueError):
            timeout = int(settings.code_execution_default_timeout_seconds)
        timeout = max(0, timeout)
        max_timeout = int(getattr(settings, "code_execution_max_timeout_seconds", 900) or 0)
        if max_timeout > 0 and timeout > 0:
            timeout = min(timeout, max_timeout)

        max_tool_calls = int(getattr(settings, "code_execution_max_tool_calls", 50) or 0)

        child_python = getattr(settings, "code_execution_python", None) or sys.executable
        child_cwd = str(getattr(self.agent, "default_cwd", None) or settings.project_root)

        extra_tools = list(getattr(settings, "code_execution_sandbox_tools", None) or [])
        sandbox_tools = _compute_sandbox_tools(self.agent, extra_tools)

        loop = asyncio.get_running_loop()
        cancel_event = threading.Event()
        current_task = asyncio.current_task()

        def _on_cancel(_task: asyncio.Task) -> None:
            if _task.cancelled():
                cancel_event.set()

        if current_task is not None:
            current_task.add_done_callback(_on_cancel)

        from ..code_kernel import execute_in_session_kernel

        def _run() -> str:
            return execute_in_session_kernel(
                code,
                owner=str(getattr(self.agent, "session_id", "") or "default"),
                child_python=child_python,
                child_cwd=child_cwd,
                sandbox_tools=sandbox_tools,
                timeout=timeout,
                max_tool_calls=max_tool_calls,
                reset=reset,
                is_interrupted=lambda: cancel_event.is_set(),
                dispatch=self._make_dispatch(loop),
            )

        try:
            raw = await asyncio.to_thread(_run)
        finally:
            if current_task is not None:
                try:
                    current_task.remove_done_callback(_on_cancel)
                except Exception:
                    pass
        return _format_result(raw)

    def _make_dispatch(self, loop: asyncio.AbstractEventLoop):
        """脚本内工具调用：把内核 RPC 线程的请求桥接到主事件循环执行 handler。"""
        registry = getattr(self.agent, "handler_registry", None)
        if registry is None or not hasattr(registry, "execute_by_tool"):
            return None

        from ..code_kernel import tool_error

        def dispatch(tool_name: str, tool_args: dict) -> str:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_execute(registry, tool_name, tool_args), loop
                )
                result = future.result(timeout=300)
            except asyncio.TimeoutError:
                return tool_error(f"Tool '{tool_name}' timed out inside execute_code")
            except Exception as exc:
                return tool_error(str(exc))
            return result if isinstance(result, str) else str(result)

        return dispatch

    @staticmethod
    async def _async_execute(registry, tool_name: str, tool_args: dict) -> str:
        try:
            result = await registry.execute_by_tool(tool_name, tool_args)
        except Exception as exc:
            from ..code_kernel import tool_error
            return tool_error(str(exc))
        return result if isinstance(result, str) else str(result)


def create_handler(agent: "Agent"):
    handler = CodeExecutionHandler(agent)
    return handler.handle
