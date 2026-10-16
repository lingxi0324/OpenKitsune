"""P0—P6 分层识别与动态评分测试。"""

import pytest

from openkitsune.core._priority_compaction import (
    PriorityLevel,
    classify_message,
    grade_pressure,
    score_block,
    segment_turns,
)


def _m(role: str, content, **extra) -> dict:
    return {"role": role, "content": content, **extra}


# ----------------------------------------------------------------------
# 分类
# ----------------------------------------------------------------------


def test_system_is_p0() -> None:
    assert classify_message(_m("system", "你是助手"), msg_index=0, total=5) == PriorityLevel.P0


def test_first_user_text_is_p0() -> None:
    # 首条非工具 user 文本（first_user_text_index）→ P0（用户原始目标）
    assert (
        classify_message(
            _m("user", "完成核心任务"), msg_index=1, total=5, first_user_text_index=1
        )
        == PriorityLevel.P0
    )


def test_other_user_text_is_p2() -> None:
    assert classify_message(_m("user", "继续追问"), msg_index=3, total=5) == PriorityLevel.P2


def test_user_tool_result_is_p3() -> None:
    msg = _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "证据"}])
    assert classify_message(msg, msg_index=2, total=5) == PriorityLevel.P3


def test_last_assistant_text_is_p1() -> None:
    assert classify_message(_m("assistant", "最终结论"), msg_index=4, total=5) == PriorityLevel.P1


def test_middle_assistant_text_is_p2() -> None:
    assert classify_message(_m("assistant", "中间答复"), msg_index=2, total=5) == PriorityLevel.P2


def test_tool_use_write_is_p4() -> None:
    msg = _m("assistant", [{"type": "tool_use", "id": "t1", "name": "write_file", "input": {}}])
    assert classify_message(msg, msg_index=2, total=5) == PriorityLevel.P4


def test_tool_use_process_is_p5() -> None:
    msg = _m("assistant", [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}])
    assert classify_message(msg, msg_index=2, total=5) == PriorityLevel.P5


def test_noise_is_p6() -> None:
    assert classify_message(_m("user", "loading"), msg_index=3, total=5) == PriorityLevel.P6
    assert classify_message(_m("assistant", ""), msg_index=3, total=5) == PriorityLevel.P6


def test_summary_marker_is_p2() -> None:
    msg = _m("user", "摘要正文", _compaction_summary=True)
    assert classify_message(msg, msg_index=0, total=3) == PriorityLevel.P2


# ----------------------------------------------------------------------
# 分级触发
# ----------------------------------------------------------------------


def test_grade_thresholds() -> None:
    # V3: >75% 即触发压缩（light 只做零风险清理）；85/93/97 逐级加重
    assert grade_pressure(0.50) is None
    assert grade_pressure(0.74) is None
    assert grade_pressure(0.75) == "light"
    assert grade_pressure(0.85) == "moderate"
    assert grade_pressure(0.93) == "heavy"
    assert grade_pressure(0.97) == "extreme"
    assert grade_pressure(0.99) == "extreme"


def test_grade_custom_thresholds() -> None:
    assert grade_pressure(0.85, thresholds=(("light", 0.85),)) == "light"
    assert grade_pressure(0.84, thresholds=(("light", 0.85),)) is None


# ----------------------------------------------------------------------
# 动态评分
# ----------------------------------------------------------------------


def test_p0_scores_higher_than_p6() -> None:
    s0 = score_block(_m("user", "完成核心任务"), PriorityLevel.P0, tokens=10, msg_index=0, total=4)
    s6 = score_block(_m("user", "loading"), PriorityLevel.P6, tokens=10, msg_index=3, total=4)
    assert s0 > s6


def test_redundancy_penalty() -> None:
    base = score_block(_m("user", "内容"), PriorityLevel.P3, tokens=100, msg_index=2, total=4)
    dup = score_block(_m("user", "内容"), PriorityLevel.P3, tokens=100, msg_index=2, total=4, redundant=True)
    assert dup < base


def test_token_cost_penalty() -> None:
    small = score_block(_m("user", "x"), PriorityLevel.P5, tokens=10, msg_index=2, total=4)
    large = score_block(_m("user", "x"), PriorityLevel.P5, tokens=5000, msg_index=2, total=4)
    assert large < small


def test_goal_keyword_raises_relevance() -> None:
    goal = score_block(_m("user", "必须完成"), PriorityLevel.P2, tokens=10, msg_index=2, total=4)
    plain = score_block(_m("user", "随便聊聊"), PriorityLevel.P2, tokens=10, msg_index=2, total=4)
    assert goal > plain


# ----------------------------------------------------------------------
# 轮次切分
# ----------------------------------------------------------------------


def test_segment_turns_keeps_tool_pairs_together() -> None:
    messages = [
        _m("system", "sys"),
        _m("user", "目标"),
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "bash"}]),
        _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]),
        _m("assistant", "结论"),
        _m("user", "新任务"),
        _m("assistant", "回答"),
    ]
    turns = segment_turns(messages)
    # 轮 = 从 user 输入（或 system）到下一个 user 输入之前：sys / 目标回合
    # （含 tool_use+tool_result+结论） / 新任务回合（含回答） → 3 轮
    assert len(turns) == 3
    tool_turn = [t for t in turns if any(
        isinstance(b, dict) and b.get("type") == "tool_use" for m in t.msgs for b in (m.get("content", []) if isinstance(m.get("content"), list) else [])
    )]
    assert len(tool_turn) == 1
    assert len(tool_turn[0].msgs) == 4  # 目标 + tool_use + tool_result + 结论 同轮


def test_segment_turns_empty() -> None:
    assert segment_turns([]) == []


# ----------------------------------------------------------------------
# V2 置信度机制（宁可少压，不可误压）
# ----------------------------------------------------------------------


def test_confidence_structural_signals_are_high() -> None:
    from openkitsune.core._priority_compaction import classify_with_confidence

    assert classify_with_confidence(_m("system", "s"), msg_index=0, total=3) == (PriorityLevel.P0, 1.0)
    first_user = classify_with_confidence(
        _m("user", "目标"), msg_index=1, total=3, first_user_text_index=1
    )
    assert first_user == (PriorityLevel.P0, 1.0)
    tool_res = classify_with_confidence(
        _m("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]),
        msg_index=1,
        total=3,
    )
    assert tool_res == (PriorityLevel.P3, 1.0)
    last_asm = classify_with_confidence(_m("assistant", "结论"), msg_index=2, total=3)
    assert last_asm == (PriorityLevel.P1, 1.0)


def test_confidence_whitelist_and_text() -> None:
    from openkitsune.core._priority_compaction import classify_with_confidence

    w = classify_with_confidence(
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "write_file", "input": {}}]),
        msg_index=1,
        total=3,
    )
    assert w == (PriorityLevel.P4, 0.85)
    text = classify_with_confidence(_m("user", "普通追问"), msg_index=2, total=3)
    assert text == (PriorityLevel.P2, 0.6)


def test_confidence_unknown_tool_is_low() -> None:
    from openkitsune.core._priority_compaction import classify_with_confidence

    unknown = classify_with_confidence(
        _m("assistant", [{"type": "tool_use", "id": "t1", "name": "custom_plugin_call", "input": {}}]),
        msg_index=1,
        total=3,
    )
    # 未知工具名 → 低置信 0.4：压缩算子不得激进处理（避免 P3 证据被误清）
    assert unknown[1] == 0.4
    assert unknown[0] in (PriorityLevel.P4, PriorityLevel.P5)
