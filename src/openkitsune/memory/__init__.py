"""
OpenKitsune 记忆系统 (v2)

架构:
- UnifiedStore: SQLite (主存储+FTS5) + SearchBackend (可插拔搜索)
- RetrievalEngine: 多路召回 + 重排序
- LifecycleManager: 归纳 + 衰减 + 去重
- MemoryExtractor: AI 提取 (v2: 工具感知/实体-属性)

记忆类型:
- SemanticMemory: 语义记忆 (实体-属性结构)
- Episode: 情节记忆 (完整交互故事)
- Scratchpad: 工作记忆草稿本 (跨 session 持久化)
"""

from .consolidator import MemoryConsolidator
from .extractor import MemoryExtractor
from .manager import MemoryManager
from .openkitsune_brain import (
    BRAIN_TOOL_NAMES,
    BRAIN_TOOL_SCHEMAS,
    OpenKitsuneBrainProvider,
    OpenKitsuneBrainRetrievalSource,
    create_openkitsune_brain_provider,
    dispatch_brain_tool,
)
from .public_api import (
    MEMORY_TOOL_NAMES,
    MEMORY_TOOL_SCHEMAS,
    BuiltinMemoryProvider,
    MemoryProvider,
    MemoryProviderRegistry,
    MemoryRecord,
    MemorySystemAPI,
    RegisteredProvider,
    create_memory_api,
    dispatch_memory_tool,
)
from .retrieval import RetrievalEngine
from .search_backends import (
    APIEmbeddingBackend,
    ChromaDBBackend,
    FTS5Backend,
    SearchBackend,
    create_search_backend,
)
from .types import (
    ActionNode,
    Attachment,
    AttachmentDirection,
    ConversationTurn,
    Episode,
    Memory,
    MemoryPriority,
    MemoryType,
    Scratchpad,
    SemanticMemory,
    SessionSummary,
)
from .unified_store import UnifiedStore

__all__ = [
    "MemoryManager",
    "MemoryExtractor",
    "MemoryConsolidator",
    "UnifiedStore",
    "RetrievalEngine",
    # Search backends
    "SearchBackend",
    "FTS5Backend",
    "ChromaDBBackend",
    "APIEmbeddingBackend",
    "create_search_backend",
    # Types
    "Memory",
    "SemanticMemory",
    "MemoryType",
    "MemoryPriority",
    "ConversationTurn",
    "SessionSummary",
    "Episode",
    "ActionNode",
    "Scratchpad",
    "Attachment",
    "AttachmentDirection",
    # Public API
    "MemorySystemAPI",
    "MemoryProvider",
    "MemoryProviderRegistry",
    "BuiltinMemoryProvider",
    "MemoryRecord",
    "RegisteredProvider",
    "create_memory_api",
    "dispatch_memory_tool",
    "MEMORY_TOOL_SCHEMAS",
    "MEMORY_TOOL_NAMES",
    # openkitsune-brain integration
    "OpenKitsuneBrainProvider",
    "OpenKitsuneBrainRetrievalSource",
    "create_openkitsune_brain_provider",
    "dispatch_brain_tool",
    "BRAIN_TOOL_SCHEMAS",
    "BRAIN_TOOL_NAMES",
]
