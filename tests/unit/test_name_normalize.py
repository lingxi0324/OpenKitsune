"""称呼归一化（memory/name_normalize）功能测试。

覆盖真实默认称呼路径（郎君 / 灵汐，配置驱动），与 tests/conftest.py 的
``_name_normalize_idempotent_terms`` 幂等隔离互补：
- 幂等 fixture 保证既有 memory 测试断言与个人称呼配置解耦；
- 本文件用 monkeypatch 显式设置真实称呼，验证替换行为本身。

同时覆盖检索侧对称归一化回归：保存侧把「用户」→ 称呼后，
查询侧「用户」仍能命中（manager 检索入口同步替换查询词）。
"""

from __future__ import annotations

import pytest

from openkitsune.memory.name_normalize import (
    normalize_memory,
    normalize_names,
    user_subject_query_values,
)
from openkitsune.memory.types import MemoryType, SemanticMemory


@pytest.fixture
def real_terms(monkeypatch):
    """把称呼设为产品默认（郎君 / 灵汐），测试后自动还原。"""
    from openkitsune.config import settings as _settings

    monkeypatch.setattr(_settings, "user_address_terms", ("郎君", "哥哥"))
    monkeypatch.setattr(_settings, "assistant_address_terms", ("灵汐", "汐儿"))
    monkeypatch.setattr(_settings, "name_normalize_enabled", True)


def test_user_content_replaced_with_default_terms(real_terms):
    assert normalize_names("用户住在上海") == "郎君住在上海"


def test_current_user_prefix_replaced(real_terms):
    assert normalize_names("当前用户的时区是 UTC+8") == "郎君的时区是 UTC+8"


def test_technical_user_context_protected(real_terms):
    # 多租户前缀与技术名词（界面/画像/配置）不替换
    assert normalize_names("多用户系统") == "多用户系统"
    assert normalize_names("用户界面") == "用户界面"


def test_assistant_terms_replaced(real_terms):
    assert normalize_names("助手说") == "灵汐说"
    assert normalize_names("AI 回答") == "灵汐 回答"  # 仅替换词本身，空格保留
    assert normalize_names("模型回答说") == "灵汐回答说"


def test_model_name_technical_context_protected(real_terms):
    assert normalize_names("模型 Qwen3.6 推理") == "模型 Qwen3.6 推理"
    assert normalize_names("模型名") == "模型名"


def test_normalize_memory_mutates_fields_in_place(real_terms):
    mem = SemanticMemory(
        type=MemoryType.FACT,
        content="用户住在上海",
        subject="用户",
        predicate="居住地",
    )
    changed = normalize_memory(mem)
    assert changed is True
    assert mem.content == "郎君住在上海"
    assert mem.subject == "郎君"
    assert mem.predicate == "居住地"


def test_disabled_returns_original(monkeypatch):
    from openkitsune.config import settings as _settings

    monkeypatch.setattr(_settings, "user_address_terms", ("郎君",))
    monkeypatch.setattr(_settings, "name_normalize_enabled", False)
    assert normalize_names("用户住在上海") == "用户住在上海"


def test_user_subject_query_values_includes_config_terms(real_terms):
    values = user_subject_query_values()
    assert "用户" in values
    assert "郎君" in values


def test_search_symmetric_normalization_hits_stored_term(real_terms, tmp_path):
    """检索侧对称归一化回归：存「郎君」后按「用户」查询仍命中。"""
    from openkitsune.memory.manager import MemoryManager

    manager = MemoryManager(
        data_dir=tmp_path / "memory",
        memory_md_path=tmp_path / "MEMORY.md",
        search_backend="fts5",
    )
    manager.start_session("session-a", user_id="user-a")
    manager.add_memory(
        SemanticMemory(
            type=MemoryType.FACT,
            content="用户住在上海",
            subject="用户",
            predicate="居住地",
        ),
        scope="global",
    )
    # 保存侧归一化：内容已存为「郎君住在上海」
    results = manager.search_memories("用户住在", scope="user")
    assert results, "query「用户住在」必须命中已归一化为「郎君住在上海」的记忆"
    assert "郎君住在上海" in results[0].content
