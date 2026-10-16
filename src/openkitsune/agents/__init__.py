"""Public exports, loaded only when requested to keep API startup lightweight."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .factory import AgentFactory, AgentInstancePool
    from .fallback import FallbackResolver
    from .lock_manager import LockManager
    from .orchestrator import AgentOrchestrator
    from .profile import AgentProfile, AgentType, ProfileStore, SkillsMode
    from .task_queue import Priority, QueuedTask, TaskQueue

__all__ = [
    "AgentFactory",
    "AgentInstancePool",
    "AgentOrchestrator",
    "AgentProfile",
    "AgentType",
    "FallbackResolver",
    "LockManager",
    "Priority",
    "ProfileStore",
    "QueuedTask",
    "SkillsMode",
    "TaskQueue",
]

_EXPORTS = {
    "AgentFactory": (".factory", "AgentFactory"),
    "AgentInstancePool": (".factory", "AgentInstancePool"),
    "AgentOrchestrator": (".orchestrator", "AgentOrchestrator"),
    "AgentProfile": (".profile", "AgentProfile"),
    "AgentType": (".profile", "AgentType"),
    "FallbackResolver": (".fallback", "FallbackResolver"),
    "LockManager": (".lock_manager", "LockManager"),
    "Priority": (".task_queue", "Priority"),
    "ProfileStore": (".profile", "ProfileStore"),
    "QueuedTask": (".task_queue", "QueuedTask"),
    "SkillsMode": (".profile", "SkillsMode"),
    "TaskQueue": (".task_queue", "TaskQueue"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, symbol = target
    value = getattr(import_module(module, __name__), symbol)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
