"""Fix-9 回归测试：experience 噪声过滤（auto_postmortem source + 低 confidence）。"""

from __future__ import annotations

from openkitsune.memory.retrieval import RetrievalCandidate, RetrievalEngine


def _cand(
    memory_id: str,
    *,
    memory_type: str,
    source: str = "",
    confidence: float | None = None,
) -> RetrievalCandidate:
    raw = {"source": source}
    if confidence is not None:
        raw["confidence"] = confidence
    return RetrievalCandidate(
        memory_id=memory_id,
        content=memory_id,
        memory_type=memory_type,
        source_type="semantic",
        raw_data=raw,
    )


def test_strip_drops_auto_postmortem_source():
    items = [
        _cand("good", memory_type="experience", source="user_explicit"),
        _cand("bad1", memory_type="experience", source="auto_postmortem"),
        _cand("bad2", memory_type="experience", source="system:daily_memory"),
        _cand("bad3", memory_type="experience", source="consolidator"),
    ]
    out = RetrievalEngine._strip_experience_noise(items)
    assert [c.memory_id for c in out] == ["good"]


def test_strip_drops_low_confidence_fact_and_experience():
    items = [
        _cand("hi_fact", memory_type="fact", confidence=0.9),
        _cand("low_fact", memory_type="fact", confidence=0.3),
        _cand("hi_exp", memory_type="experience", confidence=0.7),
        _cand("low_exp", memory_type="experience", confidence=0.5),
    ]
    out = RetrievalEngine._strip_experience_noise(items)
    assert {c.memory_id for c in out} == {"hi_fact", "hi_exp"}


def test_strip_keeps_low_confidence_non_fact_types():
    """episode/attachment/recent/skill/preference 等不应用 confidence 过滤。"""
    items = [
        _cand("ep_low", memory_type="episode", confidence=0.1),
        _cand("att_low", memory_type="attachment", confidence=0.1),
        _cand("recent_low", memory_type="recent", confidence=0.1),
        _cand("pref_low", memory_type="preference", confidence=0.1),
    ]
    out = RetrievalEngine._strip_experience_noise(items)
    assert len(out) == 4


def test_strip_keeps_fact_when_confidence_missing():
    """confidence 字段缺失时不能误删（保守行为）。"""
    item = _cand("no_conf", memory_type="fact")
    out = RetrievalEngine._strip_experience_noise([item])
    assert out == [item]


def test_strip_handles_noisy_source_with_high_confidence():
    """source 命中 noisy 集合 → 即便 confidence=1.0 也应丢弃。"""
    item = _cand("auto_pm", memory_type="experience", source="auto_postmortem", confidence=1.0)
    out = RetrievalEngine._strip_experience_noise([item])
    assert out == []


def test_strip_handles_invalid_confidence_gracefully():
    """confidence 字段是字符串/无法 float — 当作 None 处理（保留）。"""
    item = RetrievalCandidate(
        memory_id="weird",
        content="x",
        memory_type="fact",
        source_type="semantic",
        raw_data={"confidence": "not-a-number"},
    )
    out = RetrievalEngine._strip_experience_noise([item])
    assert out == [item]
