"""
Microcompact — 请求前轻量上下文清理

零 LLM 调用成本的上下文瘦身策略，在发送 API 请求前执行:
1. 完整相同工具调用及结果引用去重
2. 保留输出回读引用，不按年龄删除证据
3. 旧 thinking 块移除

参考 Claude Code 的 microcompact 策略。
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

TOOL_RESULT_EXPIRY_SECONDS = 600  # 10 分钟
LARGE_RESULT_PREVIEW_CHARS = 500
LARGE_RESULT_THRESHOLD_CHARS = 8000


def microcompact(
    messages: list[dict],
    *,
    tool_result_expiry_s: float = TOOL_RESULT_EXPIRY_SECONDS,
    large_result_threshold: int = LARGE_RESULT_THRESHOLD_CHARS,
    preview_chars: int = LARGE_RESULT_PREVIEW_CHARS,
    current_time: float | None = None,
) -> list[dict]:
    """对消息列表执行轻量清理。

    注意：这是浅拷贝操作，会修改传入的消息列表。
    调用方应在需要时提前深拷贝。

    Args:
        messages: 消息列表
        tool_result_expiry_s: 工具结果过期秒数
        large_result_threshold: 大结果阈值字符数
        preview_chars: 预览保留字符数
        current_time: 当前时间（测试用）

    Returns:
        清理后的消息列表（原地修改）
    """
    cleaned = 0
    total_messages = len(messages)
    seen_tool_fingerprints: dict[str, str] = {}
    tool_calls = {
        b.get("id"): (b.get("name"), b.get("input"))
        for m in messages
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_use"
    }

    for i, msg in enumerate(messages):
        # Only process messages not in the last 3 (keep recent context intact)
        is_recent = i >= total_messages - 3

        content = msg.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type", "")

            if block_type == "tool_result" and not is_recent:
                result_content = block.get("content", "")
                # Only byte-identical results of identical calls may share a reference.
                # Existing overflow previews are already bounded and must keep their refs.
                identity = tool_calls.get(block.get("tool_use_id"))
                if identity and isinstance(result_content, str) and result_content:
                    fingerprint = hashlib.sha256(
                        json.dumps(
                            [identity, bool(block.get("is_error")), result_content],
                            ensure_ascii=False,
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()
                    previous = seen_tool_fingerprints.get(fingerprint)
                    if previous:
                        # P1-7 修复：无损去重不再要求冷存引用 —— 原文完整保留在
                        # 更早的消息中，替换为回读引用即可（对标 Hermes 的
                        # lossless back-reference）。有冷存时附 read_file 指引。
                        if block.get("_cold_output_ref"):
                            block["content"] = (
                                f"[identical tool result: see tool_use_id={previous}; "
                                f"sha256={fingerprint}; "
                                f"read_file(path=memory://tool-output/{block['_cold_output_ref']})]"
                            )
                        else:
                            block["content"] = (
                                f"[identical tool result: see tool_use_id={previous}; "
                                f"sha256={fingerprint}; 原文见前文]"
                            )
                        cleaned += 1
                    else:
                        seen_tool_fingerprints[fingerprint] = block.get("tool_use_id", "")
                # Do not expire or cut evidence without a durable, readable replacement.

            # 3. Remove old thinking blocks (except last 2 messages)
            if block_type in ("thinking", "redacted_thinking") and not is_recent:
                if len(block.get("thinking", "")) > 200:
                    block["thinking"] = "[thinking removed by microcompact]"
                    cleaned += 1

    if cleaned > 0:
        logger.debug("microcompact: cleaned %d blocks in %d messages", cleaned, total_messages)

    return messages


def snip_old_segments(
    messages: list[dict],
    *,
    max_groups: int = 50,
    snip_count: int = 5,
) -> tuple[list[dict], int]:
    """直接丢弃最早的 N 组对话段（History Snip）。

    零 LLM 调用成本，适用于超长对话的快速上下文释放。
    通过 user/assistant 消息对分组，移除最早的 N 组。

    Args:
        messages: 消息列表
        max_groups: 当组数超过此值时触发裁剪
        snip_count: 每次裁剪的组数

    Returns:
        (裁剪后的消息列表, 被移除的消息数量)
    """
    groups = _group_messages(messages)
    if len(groups) <= max_groups:
        return messages, 0

    to_snip = min(snip_count, len(groups) - 1)  # Keep at least 1 group
    snipped_msgs = 0
    for i in range(to_snip):
        snipped_msgs += len(groups[i])

    boundary_marker = {
        "role": "user",
        "content": f"[HISTORY_SNIP: removed {snipped_msgs} messages from {to_snip} conversation turns]",
        "_internal": False,
    }

    remaining = [boundary_marker]
    for group in groups[to_snip:]:
        remaining.extend(group)

    logger.info(
        "history_snip: removed %d messages (%d groups), %d remaining",
        snipped_msgs,
        to_snip,
        len(remaining),
    )
    return remaining, snipped_msgs


def _group_messages(messages: list[dict]) -> list[list[dict]]:
    """将消息按 user→assistant 对话轮次分组。

    每组以 user 消息开始，包含紧随的 assistant 消息和相关 tool_result。
    """
    from ._context_runtime import ContextManager

    return ContextManager.group_messages(messages)
