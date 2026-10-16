"""
Session Todo 状态管理 + 生命周期函数

从 plan.py 拆分而来，负责：
- 模块级字典管理（_session_active_todos / _session_todo_required / _session_handlers）
- 注册、注销、查询、清理函数
- auto_close_todo / cancel_todo / force_close_plan 等生命周期函数

ADR: Persistence Architecture (TD3)
------------------------------------
Single-worker deployment:
  - Module-level dicts (_session_active_todos, _session_todo_required,
    _session_handlers) are the PRIMARY source of truth for in-flight state.
  - TodoStore (todo_store.json) is a durable backup; on restart the store
    is loaded back into module-level dicts to recover active plans.

Multi-worker deployment (future):
  - Module-level dicts will be REPLACED by a shared backend (Redis or
    equivalent) so that all workers share the same in-flight state.
  - TodoStore can remain as a file-based audit log / cold backup.
  - Migration path: introduce a TodoStateBackend interface, make the
    module-level dict the default implementation, add Redis impl later.
"""

import logging
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .todo_handler import PlanHandler

logger = logging.getLogger(__name__)

__all__ = [
    # Public API
    "require_todo_for_session",
    "is_todo_required",
    "has_active_todo",
    "get_active_plan_id",
    "register_active_todo",
    "unregister_active_todo",
    "clear_session_todo_state",
    "cleanup_session",
    "auto_close_todo",
    "complete_todo_after_final_answer",
    "cancel_todo",
    "force_close_plan",
    "register_plan_handler",
    "get_todo_handler_for_session",
    "get_active_todo_prompt",
    "hydrate_todo_from_messages",
    "get_active_todo_sessions",
    "iter_active_todo_sessions",
    # Private but depended on externally (transition period)
    "_session_active_todos",
    "_session_todo_required",
    "_session_handlers",
    "_emit_todo_lifecycle_event",
    # Backward-compatible aliases
    "has_active_plan",
    "get_active_plan_prompt",
    "require_plan_for_session",
    "is_plan_required",
    "register_active_plan",
    "unregister_active_plan",
    "clear_session_plan_state",
    "auto_close_plan",
    "cancel_plan",
    "get_plan_handler_for_session",
]

# ============================================
# Session Todo 状态管理（模块级别）
# ============================================

_MAX_SESSIONS = 100

# 记录哪些 session 被标记为需要 Todo（compound 任务）
_session_todo_required: dict[str, bool] = {}

# 记录 session 的活跃 Todo（session_id -> plan_id）
_session_active_todos: dict[str, str] = {}

# 存储 session -> PlanHandler 实例的映射（用于任务完成判断时查询 Plan 状态）
_session_handlers: dict[str, "PlanHandler"] = {}


def _prune_oldest_sessions() -> None:
    """当任一模块级字典超过 _MAX_SESSIONS 时，淘汰最早注册的条目。"""
    all_ids = set(_session_todo_required) | set(_session_active_todos) | set(_session_handlers)
    if len(all_ids) <= _MAX_SESSIONS:
        return
    excess = len(all_ids) - _MAX_SESSIONS
    stale = set(_session_todo_required) - set(_session_active_todos)
    victims = list(stale)[:excess]
    if len(victims) < excess:
        remaining = [sid for sid in all_ids if sid not in set(victims)]
        victims.extend(remaining[: excess - len(victims)])
    for sid in victims:
        cleanup_session(sid)
    if victims:
        logger.debug(f"[Todo] Pruned {len(victims)} stale sessions (max={_MAX_SESSIONS})")


def cleanup_session(session_id: str) -> None:
    """Remove all entries for the given session_id from all module-level dicts."""
    _session_todo_required.pop(session_id, None)
    _session_active_todos.pop(session_id, None)
    _session_handlers.pop(session_id, None)


def require_todo_for_session(session_id: str, required: bool) -> None:
    """标记 session 是否需要 Todo（由 Prompt Compiler 调用）"""
    _prune_oldest_sessions()
    _session_todo_required[session_id] = required
    logger.info(f"[Plan] Session {session_id} todo_required={required}")


def is_todo_required(session_id: str) -> bool:
    """检查 session 是否被标记为需要 Todo"""
    return _session_todo_required.get(session_id, False)


def has_active_todo(session_id: str) -> bool:
    """检查 session 是否有活跃的 Todo"""
    return session_id in _session_active_todos


def get_active_plan_id(session_id: str) -> str | None:
    """获取 session 当前活跃 Todo 的 plan_id（供 SSE 事件同步用）"""
    return _session_active_todos.get(session_id)


def register_active_todo(session_id: str, plan_id: str) -> None:
    """注册活跃的 Todo"""
    _prune_oldest_sessions()
    _session_active_todos[session_id] = plan_id
    logger.info(f"[Plan] Registered active todo {plan_id} for session {session_id}")


def unregister_active_todo(session_id: str) -> None:
    """注销活跃的 Todo（保留 handler 以支持后续新建 todo）"""
    if session_id in _session_active_todos:
        todo_id = _session_active_todos.pop(session_id)
        logger.info(f"[Todo] Unregistered todo {todo_id} for session {session_id}")
    if session_id in _session_todo_required:
        del _session_todo_required[session_id]


def clear_session_todo_state(session_id: str) -> None:
    """清除 session 的所有 Todo 状态（会话结束时调用）"""
    _session_todo_required.pop(session_id, None)
    _session_active_todos.pop(session_id, None)
    _session_handlers.pop(session_id, None)


def get_active_todo_sessions() -> dict[str, str]:
    """返回所有活跃 todo 的 {session_id: plan_id} 副本（只读）"""
    return dict(_session_active_todos)


# Backward-compatible alias
iter_active_todo_sessions = get_active_todo_sessions


def _emit_todo_lifecycle_event(session_id: str, event_type: str, plan: dict | None = None) -> None:
    """通过 WebSocket 广播 todo 生命周期事件（供非流式路径使用）"""
    try:
        from ...api.routes.websocket import broadcast_event
        from ...core.engine_bridge import fire_in_api

        data: dict = {"sessionId": session_id, "type": event_type}
        if plan:
            data["planId"] = plan.get("id", "")
            data["status"] = plan.get("status", "")
        fire_in_api(broadcast_event(f"todo:{event_type}", data))
    except Exception as e:
        logger.debug(f"[Todo] Failed to emit lifecycle event {event_type}: {e}")


def auto_close_todo(session_id: str) -> bool:
    """Close only plans whose steps were explicitly marked completed.

    Pending, running, failed, skipped and cancelled steps retain their status.
    A response ending is not independent verification of success.
    """
    if not has_active_todo(session_id):
        return False

    handler = get_todo_handler_for_session(session_id)
    plan = handler.get_plan_for(session_id) if handler else None
    if not handler or not plan:
        unregister_active_todo(session_id)
        return False

    if not handler.finalize_plan(plan, session_id, action="auto_close"):
        return False
    logger.info(f"[Todo] Auto-closed todo for session {session_id}")

    unregister_active_todo(session_id)
    _emit_todo_lifecycle_event(session_id, "todo_completed", plan)
    return True


def complete_todo_after_final_answer(session_id: str) -> bool:
    """Record response completion; close only an explicitly completed plan.

    Returns False when unfinished or unsuccessful steps remain. The active plan
    stays persisted for continuation, explicit closure or cancellation.
    """
    if not has_active_todo(session_id):
        return False

    handler = get_todo_handler_for_session(session_id)
    plan = handler.get_plan_for(session_id) if handler else None
    if not handler or not plan:
        unregister_active_todo(session_id)
        return False

    if not handler.finalize_plan(plan, session_id, action="final_answer"):
        return False
    logger.info(f"[Todo] Completed todo for session {session_id} after final answer")

    unregister_active_todo(session_id)
    _emit_todo_lifecycle_event(session_id, "todo_completed", plan)
    return True


def cancel_todo(session_id: str) -> bool:
    """
    用户主动取消时关闭活跃 Todo。

    与 auto_close_todo 不同，此函数将计划和未完成步骤标记为 cancelled。

    Returns:
        True 如果有 Todo 被取消，False 如果没有活跃 Todo
    """
    if not has_active_todo(session_id):
        return False

    handler = get_todo_handler_for_session(session_id)
    plan = handler.get_plan_for(session_id) if handler else None
    if not handler or not plan:
        unregister_active_todo(session_id)
        return True

    handler.finalize_plan(plan, session_id, action="cancel")
    logger.info(f"[Todo] Cancelled todo for session {session_id}")

    unregister_active_todo(session_id)
    _emit_todo_lifecycle_event(session_id, "todo_cancelled", plan)
    return True


def force_close_plan(session_id: str) -> bool:
    """
    强制关闭指定 session 的 Plan 状态（死锁恢复用）。

    无条件清除所有与该 session 关联的 Plan 模块级状态，
    无论 handler 实例或 plan 数据是否可达。
    用于打破 todo_required=True + has_active_todo=False 的死锁。

    Returns:
        True 如果清理了任何状态
    """
    had_state = False
    if session_id in _session_active_todos:
        plan_id = _session_active_todos.pop(session_id)
        logger.warning(f"[Plan] Force-closed active todo {plan_id} for {session_id}")
        had_state = True
    if session_id in _session_todo_required:
        del _session_todo_required[session_id]
        had_state = True
    handler = get_todo_handler_for_session(session_id)
    if handler:
        handler._todos_by_session.pop(session_id, None)
        if handler.current_todo and handler._get_conversation_id() == session_id:
            handler.current_todo = None
        try:
            handler._store.remove(session_id)
            handler._store.save()
        except Exception:
            pass
        had_state = True
    _session_handlers.pop(session_id, None)
    if had_state:
        logger.warning(f"[Plan] Force-closed all plan state for session {session_id}")
    return had_state


def register_plan_handler(session_id: str, handler: "PlanHandler") -> None:
    """注册 PlanHandler 实例

    create_todo_handler 这类工厂返回的是绑定方法 ``handler.handle`` 而非实例；
    统一在此解包 ``__self__``，保证 _session_handlers 只存 PlanHandler 实例
    （2026-10-16 修复：hydrate 路径曾把绑定方法直接注册，导致
    get_active_todo_prompt 报 ``'function'/'method' object has no attribute
    'get_plan_prompt_section'``）。
    """
    _prune_oldest_sessions()
    if handler is not None:
        owner = getattr(handler, "__self__", None)
        if owner is not None:
            handler = owner
    _session_handlers[session_id] = handler
    logger.debug(f"[Plan] Registered handler for session {session_id}")


def get_todo_handler_for_session(session_id: str) -> Optional["PlanHandler"]:
    """获取 session 对应的 PlanHandler 实例

    防御性自愈：若历史/异常路径曾把绑定方法或函数注册进 _session_handlers，
    通过 __self__ 解包为实例并回写，避免调用方（get_active_todo_prompt 等）
    拿到非实例对象后崩溃。
    """
    handler = _session_handlers.get(session_id)
    if handler is None:
        return None
    if hasattr(handler, "get_plan_prompt_section"):
        return handler
    owner = getattr(handler, "__self__", None)
    if owner is not None and hasattr(owner, "get_plan_prompt_section"):
        _session_handlers[session_id] = owner  # 自愈：回写正确实例
        return owner
    return None


def get_active_todo_prompt(session_id: str) -> str:
    """
    获取 session 对应的活跃 Todo 状态段落（供持久事件采样）。

    返回紧凑格式的计划摘要，包含所有步骤及其当前状态。
    如果没有活跃 Todo 或 Todo 已完成，返回空字符串。
    """
    handler = get_todo_handler_for_session(session_id)
    if handler:
        return handler.get_plan_prompt_section(conversation_id=session_id)
    return ""


def hydrate_todo_from_messages(
    session_id: str,
    messages: list[dict],
    handler_factory: Optional[Callable] = None,
) -> bool:
    """对标 Hermes ``_hydrate_todo_store``：从消息历史水合 Todo。

    当 session 已注册 PlanHandler 但无活跃 Todo（内存/持久层均无），且消息
    历史中存在 ``create_todo`` 工具调用时，用 ``TodoStore.restore_from_messages``
    重建 plan 并注册为活跃 Todo —— 覆盖进程重启、store 清空、压缩后内存态
    丢失等场景，避免多轮任务"任务链断裂"（2026-10-11 V2 整改）。

    Args:
        session_id: 会话 ID
        messages: 消息历史（压缩前原文快照或当前 working_messages）
        handler_factory: 可选回调，session 尚无 PlanHandler 时用于创建并
            注册 handler（调用方传入 ``lambda: create_todo_handler(agent)``）。
            注意 create_todo_handler 返回的是绑定方法 ``handler.handle``，
            本函数会先解包 ``__self__`` 拿到 PlanHandler 实例再注册。

    Returns:
        是否成功水合出活跃 Todo
    """
    handler = get_todo_handler_for_session(session_id)
    if handler is None and handler_factory is not None:
        try:
            handler = handler_factory()
            if handler is not None:
                # create_todo_handler 返回绑定方法 handler.handle，先解包出
                # PlanHandler 实例再注册（与 _agent_runtime 恢复路径一致）；
                # register_plan_handler 内部也会兜底解包，这里显式处理以自文档化。
                owner = getattr(handler, "__self__", None)
                if owner is not None:
                    handler = owner
                register_plan_handler(session_id, handler)
        except Exception as exc:
            logger.warning("[Todo] handler factory failed: %s", exc)
    if handler is None or not messages:
        return False
    if get_active_todo_prompt(session_id):
        return False  # 已有活跃 Todo，无需水合
    store = getattr(handler, "_store", None)
    if store is None:
        return False
    try:
        plan = store.restore_from_messages(session_id, messages)
        if plan is None:
            return False
        store.upsert(session_id, plan)
        handler._todos_by_session[session_id] = plan
        register_active_todo(session_id, plan.get("id", ""))
        logger.info(
            "[Todo] Hydrated todo %s from message history (session=%s)",
            plan.get("id"),
            session_id,
        )
        return True
    except Exception as exc:
        logger.warning("[Todo] Hydration from messages failed: %s", exc)
        return False


# Backward-compatible aliases (deprecated — use the *_todo variants)
unregister_active_plan = unregister_active_todo
clear_session_plan_state = clear_session_todo_state
auto_close_plan = auto_close_todo
cancel_plan = cancel_todo
get_plan_handler_for_session = get_todo_handler_for_session
get_active_plan_prompt = get_active_todo_prompt
has_active_plan = has_active_todo
register_active_plan = register_active_todo
require_plan_for_session = require_todo_for_session
is_plan_required = is_todo_required
