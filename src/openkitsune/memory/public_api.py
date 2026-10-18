"""OpenKitsune 记忆系统公共接口（Public Memory API）。

本模块是记忆子系统唯一的稳定对外入口，供三类调用方使用：

1. **项目内部模块** —— 通过 :class:`MemorySystemAPI` 读写记忆，无需直接依赖
   ``MemoryManager`` 的内部缓存、scope 规则和 contextvars 细节。
2. **外部 API / 插件** —— 实现 :class:`MemoryProvider` 协议后注册到
   :class:`MemoryProviderRegistry`，即可把外部记忆服务的数据接入检索，
   或将本系统产生的记忆镜像到外部服务。
3. **LLM / 自动化流程** —— :data:`MEMORY_TOOL_SCHEMAS` 提供与
   function-calling 兼容的工具描述，:func:`dispatch_memory_tool` 负责把
   一次工具调用分发到统一接口。

快速开始::

    from openkitsune.memory import MemoryRecord, create_memory_api

    api = create_memory_api(agent.memory_manager)
    memory_id = await api.add(MemoryRecord(content="用户偏好暗色主题"))
    hits = await api.search("主题", limit=5)
    context = await api.get_injection_context("主题偏好")

接入外部记忆服务::

    class MyMemoryAPI:
        name = "my-memory-api"

        async def add(self, memory):
            return await external_client.create(memory.to_dict())

        async def search(self, query, limit=10):
            return await external_client.search(query, limit=limit)

    api.register_provider(MyMemoryAPI(), mode="augment")

只有 ``name`` 和 ``search`` 是外部接入的最小要求；``add`` / ``get`` /
``delete`` / ``stats`` / ``get_injection_context`` 缺失时会自动跳过。
Provider 方法可以是同步函数，返回值是 awaitable 时会自动 await。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .types import MemoryPriority, MemoryType, SemanticMemory, normalize_tags

if TYPE_CHECKING:
    from .manager import MemoryManager

logger = logging.getLogger(__name__)

_PROVIDER_MODES = frozenset({"augment", "replace"})

# 语义记忆中可通过 metadata 透传的字符串字段
_SEMANTIC_EXTRA_FIELDS = (
    "layer",
    "status",
    "trust_tier",
    "content_origin",
    "kind",
    "entity",
)


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


def _coerce_memory_type(value: str | None) -> MemoryType:
    """把任意字符串类型收敛为合法 ``MemoryType``，未知值回退到 FACT。"""
    if not value:
        return MemoryType.FACT
    try:
        return MemoryType(str(value))
    except ValueError:
        return MemoryType.FACT


def _coerce_memory_priority(value: str | None) -> MemoryPriority:
    """把任意字符串优先级收敛为合法 ``MemoryPriority``，未知值回退到 SHORT_TERM。"""
    if not value:
        return MemoryPriority.SHORT_TERM
    try:
        return MemoryPriority(str(value))
    except ValueError:
        return MemoryPriority.SHORT_TERM


def _parse_datetime(value: Any) -> datetime | None:
    """解析 ISO 时间字符串；无法解析时返回 None。"""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


@dataclass
class MemoryRecord:
    """记忆数据的稳定交换格式。

    内部记忆对象（``SemanticMemory``）与外部 API 的 JSON 数据都先转换成本
    结构，再进入公共接口。外部系统只需产出 ``content``，其余字段均可选。
    """

    id: str = ""
    content: str = ""
    type: str = "fact"
    priority: str = ""
    importance: float = 0.5

    subject: str = ""
    predicate: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""

    scope: str = ""
    scope_owner: str = ""
    user_id: str = ""
    workspace_id: str = ""

    created_at: str = ""
    updated_at: str = ""

    # 多来源合并时的附加信息
    score: float = 0.0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 可序列化的字典。"""
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type,
            "priority": self.priority,
            "importance": self.importance,
            "subject": self.subject,
            "predicate": self.predicate,
            "tags": list(self.tags),
            "source": self.source,
            "scope": self.scope,
            "scope_owner": self.scope_owner,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "score": self.score,
            "provider": self.provider,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryRecord:
        """从外部 API 的字典构造，容忍常见字段别名。"""
        if not isinstance(data, dict):
            return cls(content=str(data or ""))
        content = data.get("content")
        if content is None:
            content = data.get("text") or data.get("memory") or ""
        importance = data.get("importance", data.get("importance_score", 0.5))
        memory_type = data.get("type", data.get("memory_type", "fact"))
        return cls(
            id=str(data.get("id", "") or ""),
            content=str(content),
            type=str(memory_type or "fact"),
            priority=str(data.get("priority", "") or ""),
            importance=float(importance if importance is not None else 0.5),
            subject=str(data.get("subject", "") or ""),
            predicate=str(data.get("predicate", "") or ""),
            tags=normalize_tags(data.get("tags")),
            source=str(data.get("source", "") or ""),
            scope=str(data.get("scope", "") or ""),
            scope_owner=str(data.get("scope_owner", "") or ""),
            user_id=str(data.get("user_id", "") or ""),
            workspace_id=str(data.get("workspace_id", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
            score=float(data.get("score", data.get("relevance", 0.0)) or 0.0),
            provider=str(data.get("provider", "") or ""),
            metadata=dict(data.get("metadata", {}) or {}),
        )

    @classmethod
    def from_memory(
        cls,
        memory: Any,
        *,
        score: float = 0.0,
        provider: str = "builtin",
    ) -> MemoryRecord:
        """从内部 ``SemanticMemory``（或其兼容对象）构造。"""
        created_at = getattr(memory, "created_at", None)
        updated_at = getattr(memory, "updated_at", None)
        memory_type = getattr(memory, "type", MemoryType.FACT)
        priority = getattr(memory, "priority", MemoryPriority.SHORT_TERM)
        return cls(
            id=str(getattr(memory, "id", "") or ""),
            content=str(getattr(memory, "content", "") or ""),
            type=memory_type.value if hasattr(memory_type, "value") else str(memory_type),
            priority=priority.value if hasattr(priority, "value") else str(priority),
            importance=float(getattr(memory, "importance_score", 0.5) or 0.5),
            subject=str(getattr(memory, "subject", "") or ""),
            predicate=str(getattr(memory, "predicate", "") or ""),
            tags=normalize_tags(getattr(memory, "tags", [])),
            source=str(getattr(memory, "source", "") or ""),
            scope=str(getattr(memory, "scope", "") or ""),
            scope_owner=str(getattr(memory, "scope_owner", "") or ""),
            user_id=str(getattr(memory, "user_id", "") or ""),
            workspace_id=str(getattr(memory, "workspace_id", "") or ""),
            created_at=created_at.isoformat() if isinstance(created_at, datetime) else "",
            updated_at=updated_at.isoformat() if isinstance(updated_at, datetime) else "",
            score=float(score or 0.0),
            provider=provider,
            metadata={
                "confidence": getattr(memory, "confidence", 0.5),
                "revision": getattr(memory, "revision", 1),
                "core_priority": getattr(memory, "core_priority", 0),
                **{
                    key: getattr(memory, key)
                    for key in _SEMANTIC_EXTRA_FIELDS
                    if getattr(memory, key, "")
                },
            },
        )

    def to_semantic_memory(self) -> SemanticMemory:
        """转换为内部 ``SemanticMemory``（写入内置存储时使用）。"""
        kwargs: dict[str, Any] = {
            "type": _coerce_memory_type(self.type),
            "priority": _coerce_memory_priority(self.priority),
            "content": self.content,
            "source": self.source,
            "subject": self.subject,
            "predicate": self.predicate,
            "tags": list(self.tags),
            "importance_score": self.importance,
        }
        if self.id:
            kwargs["id"] = self.id
        created_at = _parse_datetime(self.created_at)
        if created_at is not None:
            kwargs["created_at"] = created_at
        updated_at = _parse_datetime(self.updated_at)
        if updated_at is not None:
            kwargs["updated_at"] = updated_at

        for key in _SEMANTIC_EXTRA_FIELDS:
            if self.metadata.get(key):
                kwargs[key] = str(self.metadata[key])
        with contextlib.suppress(TypeError, ValueError):
            if "confidence" in self.metadata:
                kwargs["confidence"] = float(self.metadata["confidence"])
            if "core_priority" in self.metadata:
                kwargs["core_priority"] = int(self.metadata["core_priority"])

        return SemanticMemory(**kwargs)


# ---------------------------------------------------------------------------
# 外部 Provider 协议
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryProvider(Protocol):
    """外部记忆服务的接入协议。

    最小实现：``name`` 属性 + ``search`` 方法。
    其余方法按能力实现，未实现的方法在调用时会被安全跳过。
    """

    name: str

    async def add(self, memory: MemoryRecord) -> str: ...

    async def search(self, query: str, limit: int = 10) -> list[MemoryRecord | dict]: ...

    async def get(self, memory_id: str) -> MemoryRecord | dict | None: ...

    async def delete(self, memory_id: str) -> bool: ...

    async def stats(self) -> dict: ...

    async def get_injection_context(self, query: str, max_tokens: int = 700) -> str: ...


@dataclass
class RegisteredProvider:
    """注册表中的一条外部 Provider 记录。"""

    provider: MemoryProvider
    mode: str = "augment"
    priority: int = 100


def _coerce_record(item: Any, provider: str) -> MemoryRecord | None:
    """把 Provider 返回的任意条目收敛为 ``MemoryRecord``。"""
    if isinstance(item, MemoryRecord):
        record = item
    elif isinstance(item, dict):
        record = MemoryRecord.from_dict(item)
    elif isinstance(item, str):
        record = MemoryRecord(content=item)
    else:
        return None
    if not record.provider:
        record.provider = provider
    return record


async def _maybe_await(value: Any) -> Any:
    """兼容同步/异步 Provider 实现。"""
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# 内置适配器
# ---------------------------------------------------------------------------


class BuiltinMemoryProvider:
    """把 ``MemoryManager`` 包装成统一的 Provider 接口。"""

    name = "builtin"

    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager

    @property
    def manager(self) -> MemoryManager:
        return self._manager

    async def add(self, memory: MemoryRecord) -> str:
        return await asyncio.to_thread(self._add_sync, memory)

    def _add_sync(self, memory: MemoryRecord) -> str:
        semantic = memory.to_semantic_memory()
        return self._manager.add_memory(
            semantic,
            scope=memory.scope or "user",
            scope_owner=memory.scope_owner,
            user_id=memory.user_id or None,
            workspace_id=memory.workspace_id or None,
        )

    async def search(
        self,
        query: str = "",
        limit: int = 10,
        *,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        scope: str = "",
        scope_owner: str = "",
        user_id: str = "",
        workspace_id: str = "",
    ) -> list[MemoryRecord]:
        return await asyncio.to_thread(
            self._search_sync,
            query,
            limit,
            memory_type,
            tags,
            scope,
            scope_owner,
            user_id,
            workspace_id,
        )

    def _search_sync(
        self,
        query: str,
        limit: int,
        memory_type: str | None,
        tags: list[str] | None,
        scope: str,
        scope_owner: str,
        user_id: str,
        workspace_id: str,
    ) -> list[MemoryRecord]:
        kwargs: dict[str, Any] = {"limit": limit}
        if query:
            kwargs["query"] = query
        if memory_type:
            kwargs["memory_type"] = _coerce_memory_type(memory_type)
        if tags:
            kwargs["tags"] = tags
        if scope:
            kwargs["scope"] = scope
        if scope_owner:
            kwargs["scope_owner"] = scope_owner
        if user_id:
            kwargs["user_id"] = user_id
        if workspace_id:
            kwargs["workspace_id"] = workspace_id
        memories = self._manager.search_memories(**kwargs)
        return [MemoryRecord.from_memory(memory) for memory in memories]

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get_sync, memory_id)

    def _get_sync(self, memory_id: str) -> MemoryRecord | None:
        memory = None
        store = getattr(self._manager, "store", None)
        getter = getattr(store, "get_semantic", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                memory = getter(memory_id)
        if memory is None:
            memory = self._manager.get_memory(memory_id)
        return MemoryRecord.from_memory(memory) if memory is not None else None

    async def delete(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._manager.delete_memory, memory_id)

    async def stats(self) -> dict:
        return await asyncio.to_thread(self._manager.get_stats)

    async def get_injection_context(self, query: str = "", max_tokens: int = 700) -> str:
        text = await self._manager.get_injection_context_async(query)
        return (text or "")[: max(200, max_tokens * 4)]


# ---------------------------------------------------------------------------
# Provider 注册表
# ---------------------------------------------------------------------------


class MemoryProviderRegistry:
    """管理内置 Provider 与外部 Provider 的注册表。"""

    def __init__(self, builtin: MemoryProvider | None = None) -> None:
        self._builtin = builtin
        self._providers: dict[str, RegisteredProvider] = {}
        self._lock = threading.RLock()

    @property
    def builtin(self) -> MemoryProvider | None:
        return self._builtin

    def register(
        self,
        provider: MemoryProvider,
        *,
        mode: str = "augment",
        priority: int = 100,
    ) -> str:
        """注册外部 Provider。

        Args:
            provider: 实现了 :class:`MemoryProvider` 协议的对象。
            mode: ``augment`` = 与内置记忆并存；``replace`` = 读取时优先使用
                该 Provider，其结果非空时不再返回内置结果。
            priority: 数值越小越先调用，仅影响同模式下的顺序。
        """
        name = str(getattr(provider, "name", "") or "").strip()
        if not name:
            raise ValueError("MemoryProvider must declare a non-empty 'name'")
        mode = mode or "augment"
        if mode not in _PROVIDER_MODES:
            raise ValueError(f"Unsupported memory provider mode: {mode!r}")
        if self._builtin is not None and name == self._builtin.name:
            raise ValueError(f"Provider name {name!r} is reserved by the built-in provider")
        with self._lock:
            self._providers[name] = RegisteredProvider(
                provider=provider,
                mode=mode,
                priority=int(priority),
            )
        return name

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._providers.pop(str(name), None) is not None

    def get(self, name: str) -> RegisteredProvider | None:
        with self._lock:
            return self._providers.get(str(name))

    def list(self) -> list[RegisteredProvider]:
        with self._lock:
            entries = list(self._providers.values())
        return sorted(entries, key=lambda entry: entry.priority)

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)


# ---------------------------------------------------------------------------
# 统一门面
# ---------------------------------------------------------------------------


class MemorySystemAPI:
    """记忆系统的统一公共门面（async-first）。

    所有方法都不会因外部 Provider 失败而中断：异常会被记录并退化为跳过，
    内置记忆始终可用（除非 ``manager`` 为空）。
    """

    def __init__(self, manager: MemoryManager | None = None) -> None:
        builtin = BuiltinMemoryProvider(manager) if manager is not None else None
        self.registry = MemoryProviderRegistry(builtin)

    @property
    def manager(self) -> MemoryManager | None:
        builtin = self.registry.builtin
        return builtin.manager if isinstance(builtin, BuiltinMemoryProvider) else None

    # ---- Provider 管理 ----

    def register_provider(
        self,
        provider: MemoryProvider,
        *,
        mode: str = "augment",
        priority: int = 100,
    ) -> str:
        return self.registry.register(provider, mode=mode, priority=priority)

    def unregister_provider(self, name: str) -> bool:
        return self.registry.unregister(name)

    # ---- 数据操作 ----

    async def add(self, memory: MemoryRecord | dict[str, Any]) -> str:
        """写入一条记忆。

        有内置存储时返回其分配的 ID（重复内容可能为空串）；否则返回首个外部
        Provider 返回的 ID。
        """
        record = memory if isinstance(memory, MemoryRecord) else MemoryRecord.from_dict(memory)
        memory_id = record.id
        has_builtin = False

        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            has_builtin = True
            memory_id = await builtin.add(record)

        external_id = ""
        for entry in self.registry.list():
            result = await self._call_provider(entry.provider, "add", record, default="")
            if not external_id and result:
                external_id = str(result)

        if has_builtin:
            return str(memory_id or "")
        return str(memory_id or external_id or "")

    async def search(
        self,
        query: str = "",
        *,
        limit: int = 10,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        scope: str = "",
        scope_owner: str = "",
        user_id: str = "",
        workspace_id: str = "",
    ) -> list[MemoryRecord]:
        """跨 Provider 检索记忆。

        排序规则：``replace`` 模式 Provider 优先；其结果非空时直接返回。
        否则返回内置结果 + ``augment`` Provider 结果，按 Provider 优先级拼接，
        相同 ``id`` / 内容去重。
        """
        entries = self.registry.list()

        replace_entries = [entry for entry in entries if entry.mode == "replace"]
        replace_results = await asyncio.gather(
            *[
                self._call_provider(entry.provider, "search", query, limit, default=[])
                for entry in replace_entries
            ]
        )
        replaced = self._merge_records(
            replace_results,
            limit,
            provider_names=[str(getattr(entry.provider, "name", "")) for entry in replace_entries],
        )
        if replaced:
            return replaced

        batches: list[Any] = []
        provider_names: list[str] = []
        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            batches.append(
                await builtin.search(
                    query,
                    limit,
                    memory_type=memory_type,
                    tags=tags,
                    scope=scope,
                    scope_owner=scope_owner,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
            )
            provider_names.append("builtin")

        augment_entries = [entry for entry in entries if entry.mode == "augment"]
        augment_results = await asyncio.gather(
            *[
                self._call_provider(entry.provider, "search", query, limit, default=[])
                for entry in augment_entries
            ]
        )
        batches.extend(augment_results)
        provider_names.extend(str(getattr(entry.provider, "name", "")) for entry in augment_entries)
        return self._merge_records(batches, limit, provider_names=provider_names)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        """按 ID 读取记忆，依次尝试内置存储与其他 Provider。"""
        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            record = await builtin.get(memory_id)
            if record is not None:
                return record

        for entry in self.registry.list():
            result = await self._call_provider(entry.provider, "get", memory_id, default=None)
            record = _coerce_record(result, str(getattr(entry.provider, "name", "")))
            if record is not None:
                return record
        return None

    async def delete(self, memory_id: str) -> bool:
        """删除记忆；任一 Provider 成功即视为成功。"""
        deleted = False
        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            deleted = bool(await builtin.delete(memory_id))

        for entry in self.registry.list():
            result = await self._call_provider(entry.provider, "delete", memory_id, default=False)
            deleted = bool(result) or deleted
        return deleted

    async def stats(self) -> dict[str, Any]:
        """返回内置统计与各 Provider 统计。"""
        result: dict[str, Any] = {"builtin": {}, "providers": {}}
        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            result["builtin"] = await builtin.stats()

        for entry in self.registry.list():
            name = str(getattr(entry.provider, "name", ""))
            result["providers"][name] = await self._call_provider(
                entry.provider, "stats", default={}
            )
        return result

    async def get_injection_context(self, query: str = "", max_tokens: int = 700) -> str:
        """获取用于提示词注入的记忆上下文。"""
        max_chars = max(200, int(max_tokens) * 4)
        entries = self.registry.list()

        for entry in entries:
            if entry.mode != "replace":
                continue
            context = await self._call_provider(
                entry.provider, "get_injection_context", query, max_tokens, default=""
            )
            if str(context or "").strip():
                return str(context)[:max_chars]

        parts: list[str] = []
        builtin = self.registry.builtin
        if isinstance(builtin, BuiltinMemoryProvider):
            builtin_context = await builtin.get_injection_context(query, max_tokens)
            if builtin_context.strip():
                parts.append(builtin_context)

        for entry in entries:
            if entry.mode != "augment":
                continue
            context = await self._call_provider(
                entry.provider, "get_injection_context", query, max_tokens, default=""
            )
            if str(context or "").strip():
                name = str(getattr(entry.provider, "name", "external"))
                parts.append(f"[{name}]\n{context}")

        return "\n\n".join(parts)[:max_chars]

    # ---- 内部工具 ----

    async def _call_provider(
        self,
        provider: MemoryProvider,
        method: str,
        *args: Any,
        default: Any = None,
    ) -> Any:
        fn = getattr(provider, method, None)
        if not callable(fn):
            return default
        try:
            return await _maybe_await(fn(*args))
        except Exception as exc:  # 外部服务不可用不能影响内置记忆
            logger.warning(
                "[MemoryAPI] provider %s.%s failed: %s",
                getattr(provider, "name", "?"),
                method,
                exc,
            )
            return default

    @staticmethod
    def _merge_records(
        batches: list[Any],
        limit: int,
        *,
        provider_names: list[str],
    ) -> list[MemoryRecord]:
        merged: list[MemoryRecord] = []
        seen: set[str] = set()
        for index, batch in enumerate(batches):
            if isinstance(batch, (dict, str, MemoryRecord)):
                batch = [batch]
            if not isinstance(batch, list):
                continue
            provider_name = provider_names[index] if index < len(provider_names) else ""
            for item in batch:
                record = _coerce_record(item, provider_name)
                if record is None or not record.content:
                    continue
                key = record.id or record.content.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(record)
                if len(merged) >= limit:
                    return merged
        return merged


# ---------------------------------------------------------------------------
# 工具描述与分发（与 function-calling 兼容）
# ---------------------------------------------------------------------------

MEMORY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "memory_add",
        "category": "Memory",
        "description": (
            "Persist one durable memory (fact/preference/skill/rule/error/experience) "
            "through the unified memory interface."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"},
                "type": {
                    "type": "string",
                    "enum": ["fact", "preference", "skill", "error", "rule", "experience"],
                    "default": "fact",
                },
                "importance": {
                    "type": "number",
                    "description": "重要性（0-1）",
                    "default": 0.5,
                },
                "subject": {"type": "string", "description": "主体（可选）"},
                "predicate": {"type": "string", "description": "谓词（可选）"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签（可选）",
                },
                "scope": {
                    "type": "string",
                    "enum": ["auto", "global", "user", "session"],
                    "description": "作用范围（可选，默认跟随当前上下文）",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_search",
        "category": "Memory",
        "description": (
            "Search the unified memory interface across the built-in store and "
            "registered external memory providers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "default": 10},
                "type": {
                    "type": "string",
                    "enum": ["fact", "preference", "skill", "error", "rule", "experience"],
                    "description": "记忆类型过滤（可选）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签过滤（可选）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_get",
        "category": "Memory",
        "description": "Read one memory by id from the unified memory interface.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "记忆 ID"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_delete",
        "category": "Memory",
        "description": "Delete one memory by id across the built-in store and providers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "记忆 ID"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_stats",
        "category": "Memory",
        "description": "Get memory statistics for the built-in store and each provider.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_context",
        "category": "Memory",
        "description": "Build prompt-ready memory context for a query via the unified interface.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "当前任务或问题"},
                "max_tokens": {"type": "integer", "default": 700},
            },
        },
    },
]

MEMORY_TOOL_NAMES: tuple[str, ...] = tuple(schema["name"] for schema in MEMORY_TOOL_SCHEMAS)


async def dispatch_memory_tool(
    api: MemorySystemAPI,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一次 function-calling 工具调用分发到 :class:`MemorySystemAPI`。

    返回值始终是 JSON 可序列化的字典，便于直接作为 HTTP API 响应或工具结果。
    """
    name = str(tool_name or "").strip()
    args = dict(arguments or {})

    if name == "memory_add":
        importance = args.get("importance", 0.5)
        record = MemoryRecord(
            content=str(args.get("content", "") or ""),
            type=str(args.get("type", "fact") or "fact"),
            importance=float(0.5 if importance is None else importance),
            subject=str(args.get("subject", "") or ""),
            predicate=str(args.get("predicate", "") or ""),
            tags=normalize_tags(args.get("tags")),
            scope=str(args.get("scope", "") or ""),
        )
        if record.scope == "auto":
            record.scope = ""
        memory_id = await api.add(record)
        return {"ok": bool(memory_id), "id": memory_id}

    if name == "memory_search":
        records = await api.search(
            str(args.get("query", "") or ""),
            limit=int(args.get("limit", 10) or 10),
            memory_type=str(args.get("type", "") or "") or None,
            tags=normalize_tags(args.get("tags")) or None,
        )
        return {
            "ok": True,
            "count": len(records),
            "items": [record.to_dict() for record in records],
        }

    if name == "memory_get":
        record = await api.get(str(args.get("memory_id", "") or ""))
        return {
            "ok": record is not None,
            "memory": record.to_dict() if record is not None else None,
        }

    if name == "memory_delete":
        deleted = await api.delete(str(args.get("memory_id", "") or ""))
        return {"ok": deleted}

    if name == "memory_stats":
        return {"ok": True, "stats": await api.stats()}

    if name == "memory_context":
        context = await api.get_injection_context(
            str(args.get("query", "") or ""),
            max_tokens=int(args.get("max_tokens", 700) or 700),
        )
        return {"ok": bool(context), "context": context}

    raise ValueError(f"Unknown memory tool: {name!r}")


def create_memory_api(manager: MemoryManager | None = None) -> MemorySystemAPI:
    """创建统一记忆接口。

    Args:
        manager: 项目内的 ``MemoryManager`` 实例；为 None 时只使用外部 Provider。
    """
    return MemorySystemAPI(manager)
