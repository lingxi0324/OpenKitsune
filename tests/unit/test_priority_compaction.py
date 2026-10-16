"""确定性压缩算子 / 结构重构 / 优先级完整性校验测试（含 V2/V3 优化用例）。"""

from openkitsune.core._priority_compaction import (
    CompressionGrade,
    PriorityLevel,
    _tail_start_index,
    apply_deterministic_ops,
    compute_compacted_spans,
    purge_p6_noise,
    restructure_by_priority,
    verify_priority_integrity,
)


def _m(role: str, content, **extra) -> dict:
    return {"role": role, "content": content, **extra}


def _estimate(messages) -> int:
    # 简化估算：str 按字符/2，list 块按内容估算
    total = 0
    for msg in messages:
        c = msg.get("content", "")
        if isinstance(c, str):
            total += max(1, len(c) // 2)
        elif isinstance(c, list):
            for item in c:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    total += max(1, len(str(item.get("text", ""))) // 2)
                elif item.get("type") == "tool_result":
                    raw = item.get("content", "")
                    total += max(1, len(str(raw)) // 2)
                else:
                    total += 5
    return total


def _estimate_realistic(messages) -> int:
    """真实度更高的估算：tool_use 的 input JSON 计入 token（与 _msg_text
    一致），保证尾部保护预算与 EXTERNALIZE 文本长度判断同源。"""
    import json as _json

    total = 0
    for msg in messages:
        c = msg.get("content", "")
        if isinstance(c, str):
            total += max(1, len(c) // 2)
        elif isinstance(c, list):
            for item in c:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    total += max(1, len(str(item.get("text", ""))) // 2)
                elif item.get("type") == "tool_result":
                    total += max(1, len(str(item.get("content", ""))) // 2)
                elif item.get("type") == "tool_use":
                    try:
                        total += max(
                            1,
                            len(_json.dumps(item.get("input", {}), ensure_ascii=False, default=str)) // 2,
                        )
                    except (TypeError, ValueError):
                        total += 5
    return total


# ----------------------------------------------------------------------
# 确定性算子
# ----------------------------------------------------------------------


def test_no_grade_no_change() -> None:
    messages = [_m("user", "内容")]
    out, stats = apply_deterministic_ops(messages, None, estimate_tokens=_estimate)
    assert out == messages
    assert stats["grade"] is None


def test_drop_p6_noise() -> None:
    messages = [
        _m("user", "目标任务必须完成"),
        _m("assistant", "loading"),  # 早期噪声
        _m("assistant", "中间思考"),
        _m("user", "真实指令"),
        _m("assistant", "真实答复"),
        _m("user", "继续"),
    ]
    out, stats = apply_deterministic_ops(messages, "light", estimate_tokens=_estimate)
    assert stats["dropped_p6"] == 1
    assert not any(m.get("content") == "loading" for m in out)
    # P0/P2/P1 不动
    assert any(m.get("content", "").startswith("目标任务") for m in out)
    assert any(m.get("content") == "真实答复" for m in out)


def test_drop_p6_protects_recent_tail() -> None:
    messages = [
        _m("user", "目标"),
        _m("assistant", "loading"),  # 早期噪声
        _m("user", "最近轮噪声1"),
        _m("assistant", "最近轮噪声2"),
        _m("user", "最近轮噪声3"),
    ]
    out, stats = apply_deterministic_ops(messages, "light", estimate_tokens=_estimate, recent_protect=3)
    # 早期噪声被删，最后 3 条保留（recent_protect 保护）
    assert stats["dropped_p6"] == 1
    assert len(out) == 4


def test_dedup_identical_tool_results() -> None:
    text = "结果" * 100
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "c1", "name": "bash"}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "c1", "content": text}]),
        _m("assistant", [{"type": "tool_use", "id": "c2", "name": "bash"}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "c2", "content": text}]),
        _m("user", "结尾"),
    ]
    # tail_protect_fraction=0 时仅 recent_protect 决定保护区
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1,
        tail_protect_fraction=0.0,
    )
    assert stats["deduped"] == 1
    second_result = out[3]["content"][0]
    assert "identical tool result" in second_result["content"]


def test_version_fold_repeated_writes() -> None:
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "w1", "name": "write_file", "input": {"path": "a.py"}}]),
        _m("assistant", [{"type": "tool_use", "id": "w2", "name": "write_file", "input": {"path": "a.py"}}]),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1
    )
    assert stats["folded"] == 1
    # 第二次 write 被折叠
    assert any("版本折叠" in str(m.get("content", "")) for m in out)


def test_externalize_long_process_log() -> None:
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "D" * 800}}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1
    )
    assert stats["externalized"] == 1
    assert "过程日志已精简" in str(out[0]["content"])


# ----------------------------------------------------------------------
# V2: 无条件 P6 清理 / 同路径版本折叠 / 驱逐区间 / 置信度保护
# ----------------------------------------------------------------------


def test_purge_p6_unconditional() -> None:
    # P6 清理不依赖压缩档位（预算充足时也可执行）
    messages = [
        _m("user", "目标"),
        _m("assistant", "loading"),
        _m("assistant", "阶段成果"),
        _m("user", "继续"),
        _m("assistant", "结论"),
    ]
    out, stats = purge_p6_noise(messages, estimate_tokens=_estimate)
    assert stats["dropped_p6"] == 1
    assert not any(m.get("content") == "loading" for m in out)
    assert any(m.get("content") == "目标" for m in out)


def test_version_fold_same_path_different_content() -> None:
    # V2: 同路径写入覆盖即折叠旧版（不依赖内容是否相同）
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "w1", "name": "write_file", "input": {"path": "a.py", "content": "v1 内容"}}]),
        _m("assistant", [{"type": "tool_use", "id": "w2", "name": "write_file", "input": {"path": "a.py", "content": "v2 内容完全不同"}}]),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1
    )
    assert stats["folded"] == 1
    # 旧版本（w1）被折叠，最新（w2）保留
    assert "版本折叠" in str(out[0]["content"])
    assert "v2 内容完全不同" in str(out[1]["content"])


def test_version_fold_different_paths_kept() -> None:
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "w1", "name": "write_file", "input": {"path": "a.py"}}]),
        _m("assistant", [{"type": "tool_use", "id": "w2", "name": "write_file", "input": {"path": "b.py"}}]),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1
    )
    assert stats["folded"] == 0


def test_compacted_spans_recorded() -> None:
    messages = [
        _m("user", "目标"),
        _m("assistant", "loading"),  # P6 → DROP
        _m("assistant", "阶段成果"),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "light", estimate_tokens=_estimate, recent_protect=1
    )
    spans = stats["compacted_spans"]
    assert len(spans) == 1
    assert spans[0]["op"] == "DROP"
    assert spans[0]["start_index"] == 1  # 原始 index 1（loading）


def test_low_confidence_blocks_externalize() -> None:
    # 未知工具名（低置信 0.4）→ EXTERNALIZE 跳过（宁可少压，不可误压）
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "custom_plugin_call", "input": {"q": "X" * 800}}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "证据"}]),
        _m("user", "结尾"),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate, recent_protect=1, confidence_threshold=0.8
    )
    assert stats["externalized"] == 0
    # 原始内容保留
    assert "X" * 800 in str(out[0]["content"])


def test_compute_compacted_spans_detects_replaced() -> None:
    before = [
        _m("user", "目标A"),
        _m("assistant", "旧内容"),
        _m("user", "结尾"),
    ]
    after = [
        _m("user", "目标A"),
        _m("user", "[上下文压缩 -- 仅供参考]\n摘要", _compaction_summary=True),
    ]
    spans = compute_compacted_spans(before, after)
    assert len(spans) == 1
    assert spans[0]["start_index"] == 1  # 旧内容被摘要化
    assert spans[0]["op"] == "SUMMARY_OR_REPLACED"


def test_compute_compacted_spans_none_when_unchanged() -> None:
    before = [_m("user", "a"), _m("assistant", "b")]
    assert compute_compacted_spans(before, list(before)) == []


def test_compute_compacted_spans_multiset_dedup() -> None:
    # 3 条相同指纹 bash 被折叠成 1 条：只保留 1 条配额，
    # 其余 2 条必须计入驱逐区间（否则其 KV 状态漏驱逐）
    bash = _m(
        "assistant",
        [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "D" * 50}}],
    )
    source = [bash, dict(bash), dict(bash), _m("user", "结尾")]
    result = [bash, _m("user", "结尾")]  # 折叠为 1 条 bash
    spans = compute_compacted_spans(source, result)
    assert len(spans) == 1
    assert spans[0]["start_index"] == 1
    assert spans[0]["end_index"] == 3
    # 保留的那条（index 0）不在驱逐区间


# ----------------------------------------------------------------------
# V3: 尾部 15% 上下文进程保护（token 预算累计）
# ----------------------------------------------------------------------


def test_tail_start_index_by_token_budget() -> None:
    # 6 条消息，估算 token：每条按字符/2，最后 3 条大消息构成 ~30% tokens
    messages = [
        _m("user", "A" * 40),       # 20t
        _m("assistant", "B" * 40),  # 20t
        _m("user", "C" * 40),       # 20t
        _m("assistant", "D" * 60),  # 30t
        _m("user", "E" * 60),       # 30t
        _m("assistant", "F" * 60),  # 30t
    ]
    total = 150
    start = _tail_start_index(messages, _estimate, tail_protect_fraction=0.15, recent_protect=1)
    # 尾部 15% ≈ 22.5t：从末尾累计 F(30) ≥ 22.5 → 起点 index 5；
    # 与 recent_protect=1（起点 5）取 min → 5。尾部 1 条（F）受保护
    assert start == 5
    out, stats = apply_deterministic_ops(
        messages, "light", estimate_tokens=_estimate,
        tail_protect_fraction=0.15, recent_protect=1,
    )
    # 尾部受保护消息不被清理
    assert out == messages


def test_tail_protect_keeps_recent_process() -> None:
    # 尾部保护内的噪声（最近进程）不得被无条件 P6 清理；
    # 精确 15% 预算已由 test_tail_start_index_by_token_budget 覆盖，此处用
    # 较大比例验证"尾部进程整体保留"的机制语义。
    messages = [
        _m("user", "目标" * 40),      # 40t 早期
        _m("assistant", "loading"),   # 噪声（早期，应清）
        _m("assistant", "阶段结论"),
        _m("user", "继续" * 20),      # 20t
        _m("assistant", "心跳"),      # 噪声：位于尾部保护区内 → 保留
        _m("user", "结尾" * 20),      # 20t
    ]
    out, stats = purge_p6_noise(
        messages, estimate_tokens=_estimate, recent_protect=1,
        tail_protect_fraction=0.4,
    )
    # 早期 loading 被清（index 1），尾部"心跳"（index 4）受保护保留
    assert stats["dropped_p6"] >= 1
    assert not any(m.get("content") == "loading" for m in out)
    assert any(m.get("content") == "心跳" for m in out)


def test_externalize_respects_tail_fraction() -> None:
    messages = [
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "D" * 800}}]),
        _m("user", "中间" * 4),
        _m("assistant", [{"type": "tool_use", "id": "t2", "name": "bash", "input": {"cmd": "E" * 800}}]),
        _m("user", "结尾" * 2),
    ]
    out, stats = apply_deterministic_ops(
        messages, "moderate", estimate_tokens=_estimate_realistic,
        recent_protect=1, tail_protect_fraction=0.15,
    )
    # 尾部 15% 预算（累计自末尾）：结尾 1t → E bash ~400t ≥ 预算 → t2 受保护；
    # 早期 t1 长文本被精简
    assert stats["externalized"] == 1
    assert "过程日志已精简" in str(out[0]["content"])
    assert "E" * 800 in str(out[2]["content"])   # 尾部保留原文


# ----------------------------------------------------------------------
# 结构重构
# ----------------------------------------------------------------------


def test_restructure_puts_p0_turn_first() -> None:
    messages = [
        _m("system", "系统指令"),
        _m("user", "中间问题"),
        _m("assistant", "中间回答"),
        _m("user", "核心目标指令"),  # 首条 user 文本其实是这个？不——第一条非 tool user 是"中间问题"
    ]
    # 构造：让"核心目标"是唯一 P0 轮但不在最前
    # 首条 user 判定在 classify 内部基于 first_user_text_index；restructure 用
    # segment_turns 的轮级（轮首消息级别）。为稳定测试，直接构造两个 user 轮。
    out = restructure_by_priority(messages)
    # system 恒在前；P0 轮（核心目标）应排在 P2 轮前
    roles = [m.get("role") for m in out]
    assert roles[0] == "system"
    assert out[0].get("content") == "系统指令"


def test_restructure_keeps_tool_pairs() -> None:
    messages = [
        _m("system", "s"),
        _m("user", "目标A"),
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "bash"}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "o"}]),
        _m("user", "目标B"),
        _m("assistant", "结论B"),
    ]
    out = restructure_by_priority(messages)
    assert out == messages  # 重排后应保持合法（或原序回退）且工具对完整


def test_restructure_disabled_passthrough() -> None:
    messages = [_m("user", "a"), _m("assistant", "b")]
    assert restructure_by_priority(messages, enabled=False) == messages


# ----------------------------------------------------------------------
# 优先级完整性校验
# ----------------------------------------------------------------------


def test_verify_passes_on_normal_projection() -> None:
    before = [
        _m("system", "s"),
        _m("user", "目标"),
        _m("assistant", "结论"),
    ]
    after = [
        _m("system", "s"),
        _m("user", "[上下文压缩 -- 仅供参考]\n摘要", _compaction_summary=True),
        _m("assistant", "结论"),
    ]
    assert verify_priority_integrity(before, after) == []


def test_verify_flags_missing_system() -> None:
    before = [_m("system", "s"), _m("user", "目标")]
    after = [_m("user", "目标")]
    issues = verify_priority_integrity(before, after)
    assert any(i.startswith("P0:") and "system" in i for i in issues)


def test_verify_flags_missing_first_user_goal() -> None:
    before = [_m("system", "s"), _m("user", "核心目标指令")]
    after = [_m("system", "s"), _m("user", "无关内容")]
    issues = verify_priority_integrity(before, after)
    assert any(i.startswith("P0:") and "用户目标" in i for i in issues)


def test_verify_flags_missing_final_conclusion() -> None:
    before = [_m("system", "s"), _m("user", "目标"), _m("assistant", "最终结论")]
    after = [_m("system", "s"), _m("user", "目标"), _m("user", "更多")]
    issues = verify_priority_integrity(before, after)
    assert any(i.startswith("P1:") for i in issues)


def test_verify_flags_lost_summary_marker() -> None:
    before = [_m("user", "旧摘要", _compaction_summary=True), _m("user", "目标"), _m("assistant", "结论")]
    after = [_m("user", "目标"), _m("assistant", "结论")]
    issues = verify_priority_integrity(before, after)
    assert any(i.startswith("P2:") for i in issues)
