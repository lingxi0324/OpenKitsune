from openkitsune.prompt.builder import _build_conversation_context_rules


def test_conversation_context_rules_require_derived_recalculation():
    rules = _build_conversation_context_rules()

    assert "基础事实" in rules
    assert "派生数据" in rules
    assert "重新计算" in rules
    assert "不直接复用旧计算结果" in rules
