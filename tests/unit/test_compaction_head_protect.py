"""head 保护测试：硬截断永不删除核心指令（system + 首条指令）。"""

import pytest

from openkitsune.core._context_runtime import ContextManager


def _msgs(*rows) -> list[dict]:
    return [dict(r) for r in rows]


def test_head_protect_covers_system_and_first_instructions() -> None:
    messages = _msgs(
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "核心任务：分析 Hermes 压缩机制"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "继续"},
        {"role": "assistant", "content": "结果 A"},
        {"role": "user", "content": "补充"},
    )
    head_end = ContextManager._head_protect_end(messages)
    assert head_end >= 3  # system + 首个 user + 首个 assistant 至少 3 条
    # 首个 user（核心指令）在保护范围内
    assert head_end > 1


def test_head_protect_min_floor_is_three() -> None:
    messages = _msgs(
        {"role": "user", "content": "只有一个问题"},
        {"role": "assistant", "content": "回答"},
    )
    assert ContextManager._head_protect_end(messages) == 2  # min(3, n)=2


def test_head_protect_empty() -> None:
    assert ContextManager._head_protect_end([]) == 0


def test_head_protect_handles_tool_first_appearance() -> None:
    """首个 tool 消息出现位置应被纳入 head（role 首次出现语义）。"""
    messages = _msgs(
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "跑一下"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    )
    head_end = ContextManager._head_protect_end(messages)
    # system(0) + user(1) + assistant(2) 首次出现 → max+1 = 3；至少 3
    assert head_end >= 3


def test_hard_truncate_keeps_head_when_budget_tight() -> None:
    """预算紧到 head 可容纳时：硬截断 drop 边界不越过 head。"""
    cm = ContextManager.__new__(ContextManager)
    cm._token_cache = {}
    messages = _msgs(
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "核心任务指令" + "X" * 300},
        {"role": "assistant", "content": "中间填充" + "Y" * 300},
        {"role": "user", "content": "更多上下文" + "Z" * 300},
        {"role": "assistant", "content": "最近结果" + "W" * 300},
    )
    head_end = ContextManager._head_protect_end(messages)
    assert head_end >= 3
    # head 自身的 token 数（含结尾 note 冗余）作为预算 → head 必须保留
    head_tokens = cm.estimate_messages_tokens(messages[:head_end])
    hard_limit = head_tokens + 60
    truncated = cm._hard_truncate_if_needed(messages, hard_limit)
    kept_roles = [m["role"] for m in truncated]
    assert "system" in kept_roles
    # 核心指令（第二条消息）未被删除
    assert any(m.get("content", "").startswith("核心任务指令") for m in truncated)


def test_hard_truncate_raises_rather_than_drop_head() -> None:
    """预算小到 head 都放不下：抛错（head 保护优先于预算满足，防残缺）。"""
    cm = ContextManager.__new__(ContextManager)
    cm._token_cache = {}
    messages = _msgs(
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "核心任务指令" + "X" * 300},
        {"role": "assistant", "content": "中间填充" + "Y" * 300},
    )
    from openkitsune.core.compression_contract import CompressionError

    with pytest.raises(CompressionError):
        cm._hard_truncate_if_needed(messages, hard_limit=30)
