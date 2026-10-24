"""Cooperative reasoning planner.

Ten reasoning methods are grouped into five families. The family layout
encodes three relations:

* peer: the other method in the same family. It deepens the primary reading
  and checks it for consistency.
* expansion: the next family in the generative chain. It widens the
  hypothesis space by exactly one step.
* counterweight: the family that is positioned to challenge the primary
  reading. It only runs as a pre-output check, and only when the question is
  risky or the detected signals conflict.

Every plan closes with a synthesis step that merges the weighted drafts into
a single answer, so the methods never produce a pile of parallel conclusions.

Tiers keep the guidance proportional to the question:

* lightweight: primary + peer
* expanded: primary + peer + expansion
* verified: primary + peer + counterweight
* single: primary only (baseline used for A/B evaluation, not for answering)

The weights below are provisional; they are meant to be tuned by evaluation
rather than treated as fixed truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MethodSpec:
    """Static description of one reasoning method."""

    id: str
    name: str
    description: str
    family: str
    keywords: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()


METHODS: tuple[MethodSpec, ...] = (
    MethodSpec(
        "abductive",
        "溯因推理",
        "从结果找最可能的原因",
        "causal",
        ("为什么", "为何", "为啥", "何故", "原因", "怎么回事", "根因", "root cause"),
    ),
    MethodSpec(
        "causal_chain",
        "因果链分析",
        "梳理完整因果链条",
        "causal",
        ("导致", "引起", "影响", "后果", "连锁", "波及", "传导", "会怎样", "会怎么样"),
    ),
    MethodSpec(
        "inductive",
        "归纳总结",
        "从多个案例中总结出规律",
        "pattern",
        ("规律", "归纳", "总结", "共同点", "共性", "特征", "模式", "普遍性"),
    ),
    MethodSpec(
        "perspective",
        "视角代入",
        "多视角代入分析",
        "pattern",
        ("视角", "角度", "立场", "换位", "各方"),
        (r"从.{0,6}角度", r"站在.{0,8}(立场|角度|一边)"),
    ),
    MethodSpec(
        "analogical",
        "类比映射",
        "跨领域类比分析",
        "structural",
        ("类比", "类似", "好比", "相似", "打个比方", "像什么"),
        (r"和.{0,10}相似",),
    ),
    MethodSpec(
        "systems_feedback",
        "系统论反馈回路",
        "分析系统的反馈回路",
        "structural",
        ("系统", "反馈", "回路", "闭环", "循环", "生态", "机制"),
    ),
    MethodSpec(
        "first_principles",
        "第一性原理分解",
        "拆解到最基本的要素",
        "foundational",
        ("第一性", "本质", "根本", "底层逻辑", "最基础", "从原理", "基本要素"),
    ),
    MethodSpec(
        "timeline",
        "时间线推演",
        "梳理演化时间线",
        "foundational",
        ("历史", "演变", "发展", "时间线", "历程", "阶段", "未来"),
    ),
    MethodSpec(
        "dialectic",
        "辩证综合",
        "正反合辩证分析",
        "integrative",
        ("怎么看", "如何评价", "利弊", "优缺点", "正反", "取舍", "权衡", "值不值", "该不该"),
    ),
    MethodSpec(
        "deductive",
        "演绎推理",
        "从一般原理推导出具体结论",
        "integrative",
        ("推导", "推出", "必然", "逻辑上", "前提", "蕴含"),
        (r"如果.{0,20}那么",),
    ),
)

METHOD_BY_ID: dict[str, MethodSpec] = {spec.id: spec for spec in METHODS}

FAMILY_METHODS: dict[str, tuple[str, ...]] = {
    "causal": ("abductive", "causal_chain"),
    "structural": ("analogical", "systems_feedback"),
    "pattern": ("inductive", "perspective"),
    "integrative": ("dialectic", "deductive"),
    "foundational": ("first_principles", "timeline"),
}

# Generative chain: each family hands off to the next one.
EXPANSION: dict[str, str] = {
    "causal": "structural",
    "structural": "pattern",
    "pattern": "integrative",
    "integrative": "foundational",
    "foundational": "causal",
}

# Challenge relation: the family positioned to question the primary reading.
COUNTERWEIGHT: dict[str, str] = {
    "causal": "pattern",
    "pattern": "foundational",
    "foundational": "structural",
    "structural": "integrative",
    "integrative": "causal",
}

ROLE_WEIGHTS: dict[str, float] = {
    "primary": 0.50,
    "partner": 0.20,
    "expansion": 0.20,
    "counterweight": 0.10,
}

# Short role tags replace the verbose per-role sentences: the tag is enough for
# the model to infer the behaviour ("补漏校验" reads as "fill the gap, don't
# start a second conclusion") while costing four characters instead of thirty.
ROLE_TAGS: dict[str, str] = {
    "primary": "主",
    "partner": "补漏校验",
    "expansion": "延伸",
    "counterweight": "反证",
}

# One guardrail token per family. The long-form guidance lives in the module
# docstring / tests, not in every turn's prompt.
FAMILY_CHECKS: dict[str, str] = {
    "causal": "区分相关与因果",
    "pattern": "标明样本边界",
    "structural": "标出反馈与延迟",
    "foundational": "拆到最小要素",
    "integrative": "先检验前提",
}

TIER_LABELS: dict[str, str] = {
    "single": "单法",
    "lightweight": "轻量档",
    "expanded": "扩展档",
    "verified": "校验档",
}

OUTPUT_CONTRACTS: dict[str, str] = {
    "lightweight": "回答结构：结论 → 关键依据。",
    "expanded": "回答结构：结论 → 关键依据 → 一个延伸视角（不同立场或后续影响）。",
    "verified": "回答结构：结论 → 关键依据 → 风险与边界（至少一条可能推翻结论的情形）。",
}

_TIER_BUDGET: dict[str, int] = {"single": 1, "lightweight": 2, "expanded": 3, "verified": 3}

_COMPLEXITY_RE = re.compile(r"并且|以及|同时|权衡|方案|规划|对比|评估|设计|策略|路线|如何|怎么")
_HIGH_RISK_RE = re.compile(
    r"生产|线上|事故|故障|安全|合规|法律|医疗|诊断|用药|投资|财务|税务|隐私|"
    r"不可逆|删除|迁移|风险|宕机|泄露"
)

_ORDER: dict[str, int] = {spec.id: index for index, spec in enumerate(METHODS)}


@dataclass(frozen=True)
class ReasoningPlan:
    """A resolved set of methods plus their fusion weights."""

    tier: str
    primary: str
    partner: str | None = None
    expansion: str | None = None
    counterweight: str | None = None
    synthesis: tuple[str, ...] = ("dialectic", "deductive")
    weights: dict[str, float] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier)

    def method_ids(self) -> list[str]:
        ordered = (self.primary, self.partner, self.expansion, self.counterweight)
        return [method_id for method_id in ordered if method_id]


def _matched_terms(text: str, spec: MethodSpec) -> list[str]:
    matched = [keyword for keyword in spec.keywords if keyword in text]
    matched.extend(pattern for pattern in spec.patterns if re.search(pattern, text))
    return matched


def score_methods(message: str) -> dict[str, int]:
    """Keyword-score every method; unlike first-match routing, no method shadows another."""
    text = (message or "").lower()
    if not text.strip():
        return {}
    scores: dict[str, int] = {}
    for spec in METHODS:
        hits = len(_matched_terms(text, spec))
        if hits:
            scores[spec.id] = hits
    return scores


def _rank(scores: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(scores.items(), key=lambda item: (-item[1], _ORDER[item[0]]))


def _pick(family: str, scores: dict[str, int], used: set[str]) -> str | None:
    members = FAMILY_METHODS[family]
    ranked = sorted(
        members,
        key=lambda method_id: (-scores.get(method_id, 0), members.index(method_id)),
    )
    for method_id in ranked:
        if method_id not in used:
            used.add(method_id)
            return method_id
    return None


def _collect_signals(
    text: str,
    scores: dict[str, int],
    ranked: list[tuple[str, int]],
    primary: str,
) -> dict[str, Any]:
    top = ranked[0][1] if ranked else 0
    second = ranked[1][1] if len(ranked) > 1 else 0
    primary_family = METHOD_BY_ID[primary].family
    rival = next(
        (
            method_id
            for method_id, _ in ranked[1:]
            if METHOD_BY_ID[method_id].family != primary_family
        ),
        None,
    )
    rival_score = scores.get(rival, 0) if rival else 0
    families = {METHOD_BY_ID[method_id].family for method_id in scores}
    complexity_markers = len(_COMPLEXITY_RE.findall(text))
    return {
        "matched": _matched_terms(text, METHOD_BY_ID[primary]),
        "confidence": round(top / (top + second), 2) if top and (top + second) else 0.0,
        "rival": rival,
        "conflict": bool(rival) and rival_score >= top,
        "high_risk": bool(_HIGH_RISK_RE.search(text)),
        "complexity": len(text) >= 60 or complexity_markers >= 2 or text.count("？") >= 2,
        "families": sorted(families),
    }


def _resolve_tier(signals: dict[str, Any], scores: dict[str, int]) -> str:
    if signals["high_risk"] or signals["conflict"]:
        return "verified"
    if signals["complexity"] or len(signals["families"]) >= 2:
        return "expanded"
    if not scores:
        return "lightweight"
    return "lightweight"


def build_plan(
    message: str,
    *,
    cooperative: bool = True,
    tier: str | None = None,
) -> ReasoningPlan:
    """Resolve the method combination for ``message``.

    ``cooperative=False`` yields the single-method baseline used for A/B
    evaluation. ``tier`` forces a specific tier; by default it is derived from
    the detected signals.
    """
    text = (message or "").strip()
    scores = score_methods(text)
    ranked = _rank(scores)
    primary = ranked[0][0] if ranked else "deductive"
    signals = _collect_signals(text, scores, ranked, primary)

    if not cooperative:
        return ReasoningPlan(
            tier="single",
            primary=primary,
            synthesis=(),
            weights={"primary": 1.0},
            signals=signals,
        )

    resolved_tier = tier or _resolve_tier(signals, scores)
    if resolved_tier not in {"lightweight", "expanded", "verified"}:
        raise ValueError(f"unknown tier: {resolved_tier}")

    primary_family = METHOD_BY_ID[primary].family
    used: set[str] = {primary}
    partner = _pick(primary_family, scores, used)
    expansion = None
    counterweight = None

    if resolved_tier == "expanded":
        expansion = _pick(EXPANSION[primary_family], scores, used)
    elif resolved_tier == "verified":
        rival = signals["rival"]
        challenge_family = METHOD_BY_ID[rival].family if rival else COUNTERWEIGHT[primary_family]
        counterweight = _pick(challenge_family, scores, used)
        if counterweight is None:
            counterweight = _pick(COUNTERWEIGHT[primary_family], scores, used)

    slots = {
        "primary": primary,
        "partner": partner,
        "expansion": expansion,
        "counterweight": counterweight,
    }
    folded = 0.0
    weights: dict[str, float] = {}
    for role in ("partner", "expansion", "counterweight"):
        if slots[role]:
            weights[role] = ROLE_WEIGHTS[role]
        else:
            folded += ROLE_WEIGHTS[role]
    weights["primary"] = round(ROLE_WEIGHTS["primary"] + folded, 2)

    return ReasoningPlan(
        tier=resolved_tier,
        primary=primary,
        partner=partner,
        expansion=expansion,
        counterweight=counterweight,
        weights=weights,
        signals=signals,
    )


def render_plan_prompt(plan: ReasoningPlan) -> str:
    """Render the plan as a compact system-prompt section.

    Routing, slot selection, ordering and weights are decided in code by
    :func:`build_plan`; the prompt only carries the resulting skeleton. Every
    sentence the model can infer from the structure itself is omitted, because
    this block is paid on every turn.
    """
    spec = METHOD_BY_ID[plan.primary]
    if plan.tier == "single":
        return (
            f"【推理方法】{spec.name}：{spec.description}\n"
            f"要求：围绕该方法独立完成推演，再给出结论。"
        )

    steps: list[str] = []
    used: set[str] = set()
    for role in ("primary", "partner", "expansion", "counterweight"):
        method_id = getattr(plan, role)
        if method_id:
            used.add(method_id)
            steps.append(f"{ROLE_TAGS[role]} {METHOD_BY_ID[method_id].name}")
    # A method that already ran as a step is not repeated in the closing line.
    closing = [METHOD_BY_ID[item].name for item in plan.synthesis if item not in used] or ["合并"]
    steps.append("收束 " + "→".join(closing))

    checks = [FAMILY_CHECKS[spec.family]]
    if plan.counterweight:
        checks.append(FAMILY_CHECKS[METHOD_BY_ID[plan.counterweight].family])

    lines = [
        "【推理编排·内部，勿复述方法名与步骤】",
        " → ".join(steps),
        "自检：" + "；".join(dict.fromkeys(checks)),
    ]
    contract = OUTPUT_CONTRACTS.get(plan.tier)
    if contract:
        lines.append(contract)
    return "\n".join(lines)


def method_budget(tier: str) -> int:
    """Maximum number of methods a tier is allowed to schedule."""
    return _TIER_BUDGET.get(tier, 1)
