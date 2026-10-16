from datetime import datetime
from unittest.mock import MagicMock

import pytest


class _MockEnum:
    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other):
        if isinstance(other, _MockEnum):
            return self.value == other.value
        return NotImplemented

    def __hash__(self):
        return hash(self.value)


def _make_mock_memory(
    memory_id: str,
    content: str,
    memory_type: str = "fact",
    importance: float = 0.7,
):
    memory = MagicMock()
    memory.id = memory_id
    memory.content = content
    memory.type = _MockEnum(memory_type)
    memory.priority = _MockEnum("long_term")
    memory.importance_score = importance
    memory.tags = []
    memory.created_at = datetime.now()
    memory.updated_at = memory.created_at
    memory.access_count = 0
    return memory


def _make_manager(*, vector_enabled=False, memories=None):
    manager = MagicMock()
    manager.vector_store = MagicMock()
    manager.vector_store.enabled = vector_enabled
    manager.memory_md_path.exists.return_value = True
    manager.memory_md_path.read_text.return_value = "# Core Memory\n\nTest core memory"
    manager.retrieval_engine = None
    manager._recent_messages = None
    manager._memories = {memory.id: memory for memory in memories or []}

    def keyword_search(query, limit=5):
        keywords = [keyword for keyword in query.lower().split() if len(keyword) > 2]
        results = [
            memory
            for memory in manager._memories.values()
            if any(keyword in memory.content.lower() for keyword in keywords)
        ]
        results.sort(key=lambda memory: memory.importance_score, reverse=True)
        return results[:limit]

    manager._keyword_search = keyword_search
    manager._strip_common_prefix = lambda content: content
    return manager


def test_get_injection_context_delegates_to_the_retrieval_engine():
    from openkitsune.memory.manager import MemoryManager

    manager = _make_manager(memories=[_make_mock_memory("m1", "用户喜欢 Python 编程语言")])
    manager.retrieval_engine = MagicMock()
    manager.retrieval_engine.retrieve.return_value = "用户喜欢 Python 编程语言"

    result = MemoryManager.get_injection_context(manager, "Python")

    manager.retrieval_engine.retrieve.assert_called_once_with(
        query="Python", recent_messages=None, max_tokens=700
    )
    assert "Python 编程语言" in result


def test_get_injection_context_passes_the_task_description_as_query():
    from openkitsune.memory.manager import MemoryManager

    manager = _make_manager(vector_enabled=True)
    manager.retrieval_engine = MagicMock()
    manager.retrieval_engine.retrieve.return_value = "用户喜欢 Python 编程"

    MemoryManager.get_injection_context(manager, "编程语言")

    assert manager.retrieval_engine.retrieve.call_args.kwargs["query"] == "编程语言"


def test_get_injection_context_returns_the_engine_result_unchanged():
    from openkitsune.memory.manager import MemoryManager

    manager = _make_manager(vector_enabled=True)
    manager.retrieval_engine = MagicMock()
    manager.retrieval_engine.retrieve.return_value = "用户喜欢 Python 编程\n相关记忆摘要"

    assert (
        MemoryManager.get_injection_context(manager, "Python")
        == "用户喜欢 Python 编程\n相关记忆摘要"
    )


def test_get_injection_context_passes_recent_messages():
    from openkitsune.memory.manager import MemoryManager

    manager = _make_manager()
    manager._recent_messages = [{"role": "user", "content": "Python 怎么用"}]
    manager.retrieval_engine = MagicMock()
    manager.retrieval_engine.retrieve.return_value = "Python 使用指南"

    MemoryManager.get_injection_context(manager, "Python")

    assert manager.retrieval_engine.retrieve.call_args.kwargs["recent_messages"] == [
        {"role": "user", "content": "Python 怎么用"}
    ]


def test_related_memory_search_falls_back_to_keywords_without_vector_store():
    from openkitsune.prompt.retriever import _search_related_memories

    manager = _make_manager(memories=[_make_mock_memory("m1", "用户偏好深色主题界面")])

    result, used_vector = _search_related_memories("深色主题", manager, max_items=5)

    assert not used_vector
    assert "深色主题" in result


def test_related_memory_search_reports_a_successful_vector_lookup():
    from openkitsune.prompt.retriever import _search_related_memories

    manager = _make_manager(
        vector_enabled=True,
        memories=[_make_mock_memory("m1", "用户偏好深色主题界面")],
    )
    manager.vector_store.search.return_value = [("m1", 0.03)]

    result, used_vector = _search_related_memories("主题", manager, max_items=5)

    assert used_vector
    assert "深色主题" in result


@pytest.mark.asyncio
async def test_async_related_memory_search_falls_back_to_keywords():
    from openkitsune.prompt.retriever import async_search_related_memories

    manager = _make_manager(memories=[_make_mock_memory("m1", "系统使用 PostgreSQL 数据库")])

    result, used_vector = await async_search_related_memories("PostgreSQL", manager, max_items=5)

    assert not used_vector
    assert "PostgreSQL" in result
