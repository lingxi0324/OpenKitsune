"""Cooperative reasoning planner: routing, invariants and A/B comparison.

The A/B comparison here is intentionally offline and deterministic: it scores
structured coverage (primary hit, peer presence, pre-output check on risky or
conflicting questions, synthesis closure, method budget) instead of asking an
LLM to judge answer quality. That keeps the comparison reproducible in CI; it
does not replace a live answer-quality evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from openkitsune.agent import reasoning_coop
from openkitsune.agent.reasoning_coop import (
    COUNTERWEIGHT,
    EXPANSION,
    FAMILY_METHODS,
    METHODS,
    build_plan,
    method_budget,
    render_plan_prompt,
)

BANNED_TERMS = ("五行", "相生", "相克", "河图", "洛书", "中宫", "飞宫", "八卦")


@dataclass(frozen=True)
class Case:
    message: str
    primary: str
    tier: str

    @property
    def needs_check(self) -> bool:
        return self.tier == "verified"


CASES: tuple[Case, ...] = (
    Case("为什么线上服务会突然大量超时？", "abductive", "verified"),
    Case("这次促销导致销量上涨，后面还会带来什么后果？", "causal_chain", "lightweight"),
    Case("从这三个案例能总结出什么规律？", "inductive", "lightweight"),
    Case("站在用户和商家的角度，分别怎么看这个改版？", "perspective", "expanded"),
    Case("这个架构类似什么？能类比到生物系统吗？", "analogical", "expanded"),
    Case("这个业务系统的反馈回路在哪里，如何形成闭环？", "systems_feedback", "lightweight"),
    Case("从第一性原理看，这件事的本质是什么？", "first_principles", "lightweight"),
    Case("这个行业过去十年是如何演变的？", "timeline", "lightweight"),
    Case("如何评价这个方案？利弊分别是什么？", "dialectic", "expanded"),
    Case("如果前提成立，能否必然推出这个结论？", "deductive", "lightweight"),
    Case("帮我把这个需求拆成开发任务", "deductive", "lightweight"),
    Case("我们要在生产环境删除旧数据，有什么风险？", "deductive", "verified"),
    Case("为什么这个方案既有效率问题又有公平问题，怎么权衡？", "abductive", "verified"),
    Case(
        "我们准备重构支付系统，需要先分析根本原因、总结历史规律，并评估未来风险",
        "inductive",
        "verified",
    ),
    Case("从多个用户的反馈里总结规律，再看各方视角的差异", "inductive", "expanded"),
)


def _legacy_first_match(message: str) -> str:
    """The pre-existing routing: first keyword table that matches wins."""
    msg = message.lower()
    table = (
        ("abductive", r"为什么|原因|怎么回事|为啥|何故"),
        ("causal_chain", r"导致|引起|影响|后果|会怎样|会怎么样"),
        ("inductive", r"规律|总结|共同点|特点|特征|归纳"),
        ("first_principles", r"根本|本质|最基础|从原理|第一性|底层逻辑"),
        ("analogical", r"像|类似|类比|对比|和.*相似"),
        ("dialectic", r"怎么看|如何评价|好不好|利弊|优点缺点|正反"),
        ("systems_feedback", r"系统|反馈|循环|回路|生态"),
        ("timeline", r"历史|发展|演变|过去|现在|未来|历程"),
        ("perspective", r"从.*角度|站在.*立场|谁的视角|换位思考"),
    )
    for method_id, pattern in table:
        if re.search(pattern, msg):
            return method_id
    return "deductive"


def _count(flags: list[bool]) -> int:
    return sum(1 for flag in flags if flag)


def test_cooperative_beats_single_method_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    """Offline A/B: cooperative coverage vs the single-method baseline."""
    coop = [build_plan(case.message) for case in CASES]
    single = [build_plan(case.message, cooperative=False) for case in CASES]
    check_cases = [case for case in CASES if case.needs_check]

    coop_primary = _count(
        [plan.primary == case.primary for plan, case in zip(coop, CASES, strict=False)]
    )
    single_primary = _count(
        [plan.primary == case.primary for plan, case in zip(single, CASES, strict=False)]
    )
    coop_peer = _count([bool(plan.partner) for plan in coop])
    single_peer = _count([bool(plan.partner) for plan in single])
    coop_check = _count(
        [
            plan.tier == "verified" and bool(plan.counterweight)
            for plan, case in zip(coop, CASES, strict=False)
            if case.needs_check
        ]
    )
    single_check = _count(
        [
            plan.tier == "verified" and bool(plan.counterweight)
            for plan, case in zip(single, CASES, strict=False)
            if case.needs_check
        ]
    )
    coop_synthesis = _count([bool(plan.synthesis) for plan in coop])
    single_synthesis = _count([bool(plan.synthesis) for plan in single])
    coop_chars = sum(len(render_plan_prompt(plan)) for plan in coop) / len(coop)
    single_chars = sum(len(render_plan_prompt(plan)) for plan in single) / len(single)

    rows = [
        f"primary hit    coop={coop_primary}/{len(CASES)}  single={single_primary}/{len(CASES)}",
        f"peer method    coop={coop_peer}/{len(CASES)}  single={single_peer}/{len(CASES)}",
        f"pre-output check  coop={coop_check}/{len(check_cases)}  single={single_check}/{len(check_cases)}",
        f"synthesis step coop={coop_synthesis}/{len(CASES)}  single={single_synthesis}/{len(CASES)}",
        f"prompt chars   coop={coop_chars:.0f}  single={single_chars:.0f}",
    ]
    with capsys.disabled():
        print(f"\n[reasoning A/B] cooperative vs single method (n={len(CASES)})")
        print("\n".join(rows))

    # Both modes share the same detection, so primary accuracy is equal here;
    # the legacy first-match comparison lives in its own test below.
    assert coop_primary >= single_primary
    assert coop_peer == len(CASES) and single_peer == 0
    assert coop_check == len(check_cases) and single_check == 0
    assert coop_synthesis == len(CASES) and single_synthesis == 0
    assert coop_chars <= 160


def test_every_method_is_reachable() -> None:
    expected = {
        "abductive": "为什么会发生这件事？",
        "causal_chain": "这个改动会带来什么后果？",
        "inductive": "这些案例有什么共同点？",
        "perspective": "从运维的角度看这个问题",
        "analogical": "这个机制好比什么？",
        "systems_feedback": "这个系统有哪些反馈回路？",
        "first_principles": "拆到本质，哪些是不可再分的基本要素？",
        "timeline": "这件事的演变历程是怎样的？",
        "dialectic": "这个方案有什么利弊？",
        "deductive": "由这个前提可以推导出什么？",
    }
    assert set(expected) == {spec.id for spec in METHODS}
    for method_id, message in expected.items():
        assert build_plan(message).primary == method_id


def test_tier_routing_matches_question_risk() -> None:
    for case in CASES:
        plan = build_plan(case.message)
        assert plan.tier == case.tier, case.message
        assert plan.primary == case.primary, case.message
        assert len(plan.method_ids()) <= method_budget(plan.tier)
        assert abs(sum(plan.weights.values()) - 1.0) < 1e-9


def test_relations_are_closed_cycles() -> None:
    families = set(FAMILY_METHODS)
    assert set(EXPANSION) == families
    assert set(COUNTERWEIGHT) == families
    assert set(EXPANSION.values()) == families
    assert set(COUNTERWEIGHT.values()) == families
    assert all(source != target for source, target in EXPANSION.items())
    assert all(source != target for source, target in COUNTERWEIGHT.items())
    assert len(families) == 5
    for members in FAMILY_METHODS.values():
        assert len(members) == 2
        assert len(set(members)) == 2
    all_methods = [method_id for members in FAMILY_METHODS.values() for method_id in members]
    assert sorted(all_methods) == sorted(spec.id for spec in METHODS)


def test_plan_methods_are_unique_and_weighted() -> None:
    for case in CASES:
        plan = build_plan(case.message)
        methods = plan.method_ids()
        assert len(methods) == len(set(methods))
        assert plan.primary in methods
        if plan.tier == "lightweight":
            assert plan.expansion is None and plan.counterweight is None
        if plan.tier == "expanded":
            assert plan.expansion and plan.counterweight is None
        if plan.tier == "verified":
            assert plan.counterweight and plan.expansion is None
        assert set(plan.weights) <= {"primary", "partner", "expansion", "counterweight"}


def test_prompt_is_compact_and_free_of_metaphysics() -> None:
    for case in CASES:
        prompt = render_plan_prompt(build_plan(case.message))
        assert len(prompt) <= 200, (case.message, len(prompt))
        assert "收束" in prompt
        assert "自检" in prompt
        # The skeleton is rendered as tags, not as sentences the model has to
        # read and obey; a regression back to prose shows up as newlines/padding.
        assert "  " not in prompt and "\n\n" not in prompt
        for term in BANNED_TERMS:
            assert term not in prompt

    source = Path(reasoning_coop.__file__)
    text = source.read_text(encoding="utf-8")
    for term in BANNED_TERMS:
        assert term not in text


def test_primary_accuracy_not_worse_than_legacy_first_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    coop_hits = sum(1 for case in CASES if build_plan(case.message).primary == case.primary)
    legacy_hits = sum(1 for case in CASES if _legacy_first_match(case.message) == case.primary)
    with capsys.disabled():
        print(
            f"[reasoning A/B] primary hit: coop={coop_hits}/{len(CASES)} "
            f"legacy first-match={legacy_hits}/{len(CASES)}"
        )
    assert coop_hits >= legacy_hits
    assert coop_hits == len(CASES)


def test_chat_injection_uses_the_plan() -> None:
    from openkitsune.api.routes.chat import _build_reasoning_injection

    prompt = _build_reasoning_injection("为什么这个方案既有效率问题又有公平问题，怎么权衡？")
    assert "推理编排" in prompt
    assert "反证" in prompt
    assert "勿复述" in prompt
    for term in BANNED_TERMS:
        assert term not in prompt


def test_chat_injection_is_skipped_without_method_signal() -> None:
    from openkitsune.api.routes.chat import _build_reasoning_injection

    assert _build_reasoning_injection("把这段文字改得更正式一点") == ""
    assert _build_reasoning_injection("") == ""
