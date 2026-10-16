"""摘要注入安全、tool_calls 计费、microcompact 无损去重测试。"""

import json

from openkitsune.core._context_runtime import ContextManager
from openkitsune.core.microcompact import microcompact


# ----------------------------------------------------------------------
# 摘要注入（P1-5）
# ----------------------------------------------------------------------


def test_inject_merges_into_existing_user_message() -> None:
    """recent 首条已是 user → 合并摘要前缀，避免连续两条 user。"""
    recent = [{"role": "user", "content": "继续刚才的任务"}]
    result = ContextManager._inject_summary_into_recent("摘要正文", recent)
    assert len(result) == 1
    assert result[0]["_compaction_summary"] is True
    assert "摘要正文" in result[0]["content"]
    assert "继续刚才的任务" in result[0]["content"]
    # 结束标记存在
    assert "[摘要结束]" in result[0]["content"]


def test_inject_inserts_summary_when_first_is_not_user() -> None:
    recent = [{"role": "assistant", "content": "上次回答"}]
    result = ContextManager._inject_summary_into_recent("摘要正文", recent)
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[0]["_compaction_summary"] is True
    assert "[摘要结束]" in result[0]["content"]


def test_inject_merges_into_list_content() -> None:
    recent = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "追问细节"}, {"type": "image", "source": {"url": "x"}}],
        }
    ]
    result = ContextManager._inject_summary_into_recent("摘要正文", recent)
    assert len(result) == 1
    content = result[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "摘要正文" in content[0]["text"]


def test_inject_empty_summary_passthrough() -> None:
    recent = [{"role": "user", "content": "x"}]
    assert ContextManager._inject_summary_into_recent("", recent) == recent


# ----------------------------------------------------------------------
# tool_calls 计费（P1-2）
# ----------------------------------------------------------------------


def _estimate_cm() -> ContextManager:
    cm = ContextManager.__new__(ContextManager)
    cm._token_cache = {}
    return cm


def test_estimate_charges_top_level_tool_calls() -> None:
    cm = _estimate_cm()
    with_tools = {
        "role": "assistant",
        "content": "调用中",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": json.dumps({"cmd": "cat " + "A" * 800})}}
        ],
    }
    without = {"role": "assistant", "content": "调用中"}
    tokens_with = cm._estimate_single_message_tokens(with_tools)
    tokens_without = cm._estimate_single_message_tokens(without)
    assert tokens_with > tokens_without
    assert tokens_with - tokens_without > 50  # 参数 800 字符必然显著增加


def test_estimate_tool_calls_malformed_no_crash() -> None:
    cm = _estimate_cm()
    msg = {"role": "assistant", "content": "x", "tool_calls": [object()]}  # 不可序列化
    tokens = cm._estimate_single_message_tokens(msg)
    assert tokens > 0


# ----------------------------------------------------------------------
# microcompact 无损去重（P1-7）
# ----------------------------------------------------------------------


def _tool_result_msg(call_id: str, text: str, *, cold_ref: str | None = None) -> dict:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": text}
    if cold_ref:
        block["_cold_output_ref"] = cold_ref
    return {"role": "user", "content": [block]}


def _tool_call_msg(call_id: str, name: str = "bash", inp: dict | None = None) -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": call_id, "name": name, "input": inp or {}}],
    }


def _dedup_messages(text: str) -> list[dict]:
    """4 对 call/result：c1/c2 旧（可去重），c3/c4 属最后 3 条（保留）。"""
    messages = []
    for cid in ("c1", "c2", "c3", "c4"):
        messages.append(_tool_call_msg(cid))
        messages.append(_tool_result_msg(cid, text))
    return messages


def test_microcompact_dedup_without_cold_ref() -> None:
    """无冷存引用时，字节相同的旧结果也被回读引用替换（无损：原文仍在前）。"""
    text = "结果" * 100
    cleaned = microcompact(_dedup_messages(text))
    # 第二条结果（c2, index 3）被替换为引用
    block = cleaned[3]["content"][0]
    assert "identical tool result" in block["content"]
    assert "see tool_use_id=c1" in block["content"]


def test_microcompact_keeps_first_full_copy() -> None:
    text = "结果" * 50
    cleaned = microcompact(_dedup_messages(text))
    first_block = cleaned[1]["content"][0]
    assert first_block["content"] == text  # 原文完整保留


def test_microcompact_keeps_recent_results_intact() -> None:
    """最后 3 条消息不参与去重（保留近期上下文）。"""
    text = "结果" * 50
    cleaned = microcompact(_dedup_messages(text))
    # c3/c4（index 5、7）属于最后 3 条 → 不替换
    assert cleaned[5]["content"][0]["content"] == text
    assert cleaned[7]["content"][0]["content"] == text
