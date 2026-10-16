"""确定性 fallback 摘要测试。

覆盖：用户原文保留、工具执行锚点、恢复提示、预算截断、空输入安全。
"""

from openkitsune.core._context_runtime import ContextManager


def _manager() -> ContextManager:
    """无需 brain 的轻量实例（_build_deterministic_fallback 不使用实例状态）。"""
    return ContextManager.__new__(ContextManager)


def _turn(role: str, content) -> dict:
    return {"role": role, "content": content}


def test_fallback_keeps_user_text_verbatim() -> None:
    cm = _manager()
    turns = [
        _turn("user", "把 src/ 下所有 .py 文件的行数统计出来并排序"),
        _turn("assistant", [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "wc -l src/*.py"}}]),
        _turn("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "42 行"}]),
        _turn("user", "再检查 main.py 是否通过 lint"),
    ]
    summary = cm._build_deterministic_fallback(turns, total_tokens=2000)
    assert "把 src/ 下所有 .py 文件的行数统计出来并排序" in summary
    assert "再检查 main.py 是否通过 lint" in summary
    # 工具锚点
    assert "bash" in summary
    assert "42 行" in summary
    # 恢复提示
    assert "恢复提示" in summary


def test_fallback_structure_is_complete() -> None:
    cm = _manager()
    turns = [
        _turn("user", "查找 todo 列表"),
        _turn("assistant", [{"type": "tool_use", "id": "t1", "name": "search_memory", "input": {"q": "todo"}}]),
        _turn("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "3 条待办"}]),
    ]
    summary = cm._build_deterministic_fallback(turns, total_tokens=500)
    assert "[上下文压缩 -- 摘要模型暂不可用" in summary
    assert "[用户原文]" in summary
    assert "[工具执行锚点]" in summary
    assert summary.endswith("…[确定性摘要已截断]") or "确定性摘要已截断" not in summary


def test_fallback_empty_turns_is_still_nonempty() -> None:
    cm = _manager()
    summary = cm._build_deterministic_fallback([], total_tokens=100)
    assert summary
    assert "恢复提示" in summary


def test_fallback_respects_budget() -> None:
    cm = _manager()
    long_text = "用户指令" * 2000
    turns = [_turn("user", long_text)]
    summary = cm._build_deterministic_fallback(turns, total_tokens=100)
    # 预算下限 600 字符（防残缺底线），上限不超过下限 + 截断尾部
    assert len(summary) <= 600 + 50


def test_fallback_truncation_prefers_user_text() -> None:
    """预算不足时用户原文必须保留（截断只能裁尾部锚点/footer）。"""
    cm = _manager()
    user_text = "核心任务：" + "A" * 3000
    turns = [
        _turn("user", user_text),
        _turn("assistant", [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]),
        _turn("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "结果"}]),
    ]
    summary = cm._build_deterministic_fallback(turns, total_tokens=1000)
    # 截断后用户原文的头部（最高优先级）仍在
    assert summary.startswith("[上下文压缩")
    assert "核心任务" in summary
