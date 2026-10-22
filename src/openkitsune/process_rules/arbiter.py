"""
R4 多 Agent 冲突裁决（整改版 v2.0 §4）

裁决排序键（按优先级）：
  1. evidence       证据：可溯源、可复核的事实与数据（实测 > 推断 > 声称）
  2. goal_alignment 目标一致性：与用户本次目标对齐程度（偏离目标的结论降权）
  3. confidence     置信度：Agent 自报置信（仅在前两键持平时代替排序）

规则：
  - 共识只作参考，不自动采纳：多数 Agent 一致 ≠ 结论正确，仍须按排序键核验。
  - 冲突出现时 → 触发检查点（R2 agent_conflict）。
  - 冲突未解决前，不进入交付阶段。
  - 分歧点 ≤1 且可裁决 → 直接裁决并标注理由；分歧 ≥2 或涉核心结论 → 走完整流程。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine
from .checkpoints import trigger_checkpoint

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """单个子 Agent 返回。"""

    agent_id: str
    text: str
    evidence: float = 0.0          # 0..1 证据强度（实测=1.0, 推断=0.5, 声称=0.2）
    goal_alignment: float = 0.5    # 0..1 目标一致性
    confidence: float = 0.5        # 0..1 自报置信度
    sources: list[str] = field(default_factory=list)   # 可溯源来源
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """加权分：证据 0.5 / 目标一致性 0.3 / 置信度 0.2。"""
        return 0.5 * self.evidence + 0.3 * self.goal_alignment + 0.2 * self.confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "text": self.text[:300],
            "evidence": self.evidence,
            "goal_alignment": self.goal_alignment,
            "confidence": self.confidence,
            "sources": self.sources[:5],
            "score": round(self.score, 3),
        }


def _normalize(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def _dispute_count(results: list[AgentResult]) -> int:
    """启发式：文本结论不同的对数量（去重后差异度）。"""
    texts = [r.text.strip()[:100] for r in results if r.text.strip()]
    if not texts:
        return 0
    unique = set(texts)
    if len(unique) <= 1:
        return 0
    return len(unique) - 1


def arbitrate(
    results: list[AgentResult],
    *,
    session_id: str | None = None,
    core_conclusion: bool = False,
    mode: str = "observe",
) -> dict[str, Any]:
    """R4 主入口。

    Returns:
        dict: {
            winner: AgentResult | None,
            ranking: list[AgentResult],      # 按 score 降序
            disputes: int,
            consensus: bool,                 # 是否多数一致（仅供参考）
            action: "arbitrated" | "blocked" | "skipped",
            checkpoint: list[str] | None,    # 冲突触发的检查点三问
        }
    """
    engine = get_rule_engine()
    if not engine.is_enabled("arbiter"):
        return {
            "winner": results[0] if results else None,
            "ranking": list(results),
            "disputes": 0,
            "consensus": True,
            "action": "skipped",
            "checkpoint": None,
        }
    cfg = get_process_rules_config()
    if not cfg.arbiter_enabled or not results:
        return {
            "winner": results[0] if results else None,
            "ranking": list(results),
            "disputes": 0,
            "consensus": True,
            "action": "skipped",
            "checkpoint": None,
        }

    # 规范化分值
    for r in results:
        r.evidence = _normalize(r.evidence, 0.5)
        r.goal_alignment = _normalize(r.goal_alignment, 0.5)
        r.confidence = _normalize(r.confidence, 0.5)

    ranking = sorted(results, key=lambda r: r.score, reverse=True)
    disputes = _dispute_count(results)
    consensus = len(results) > 1 and disputes == 0

    # 冲突 → 触发检查点（R2 agent_conflict）
    checkpoint = None
    if disputes > 0:
        checkpoint = trigger_checkpoint(
            session_id=session_id,
            kind="agent_conflict",
            reason=f"多 Agent 结果分歧 {disputes} 处",
        )

    # 裁决阈值：分歧 ≥2 或涉核心结论 → 完整流程（不静默取平均）
    if disputes >= cfg.arbiter_dispute_threshold or core_conclusion:
        audit_record(
            "arbiter", "arbitrate", "applied",
            detail=f"disputes={disputes} core={core_conclusion} winner={ranking[0].agent_id if ranking else '-'}",
        )
        return {
            "winner": ranking[0] if ranking else None,
            "ranking": ranking,
            "disputes": disputes,
            "consensus": consensus,
            "action": "arbitrated",
            "checkpoint": checkpoint,
        }

    if disputes == 1:
        # 单点分歧且可裁决 → 直接裁决，标注理由
        audit_record(
            "arbiter", "arbitrate", "applied",
            detail=f"disputes=1 直接裁决 winner={ranking[0].agent_id if ranking else '-'}",
        )
        return {
            "winner": ranking[0] if ranking else None,
            "ranking": ranking,
            "disputes": disputes,
            "consensus": consensus,
            "action": "arbitrated",
            "checkpoint": checkpoint,
        }

    # 无分歧 → 共识（仅供参考，不自动采纳）
    audit_record("arbiter", "consensus", "applied", detail="结果一致，共识仅作参考")
    return {
        "winner": ranking[0] if ranking else None,
        "ranking": ranking,
        "disputes": 0,
        "consensus": True,
        "action": "consensus",
        "checkpoint": None,
    }


def deterministic_arbiter_decision(
    results: list[AgentResult],
    *,
    session_id: str | None = None,
    core_conclusion: bool = False,
) -> dict[str, Any]:
    """R4 确定性判定 + 置信度（供自主决策层 L0 使用）。

    证据分差大 → 高置信裁决；分差接近 / 核心结论 → 中低置信（交 AI 判断）。
    """
    if not results:
        return {"decision": "human", "confidence": 0.5, "reason": "无结果"}
    if len(results) == 1:
        return {"decision": "winner", "confidence": 0.95, "reason": "单结果直接采纳"}

    for r in results:
        r.evidence = _normalize(r.evidence, 0.5)
        r.goal_alignment = _normalize(r.goal_alignment, 0.5)
        r.confidence = _normalize(r.confidence, 0.5)

    ranking = sorted(results, key=lambda r: r.score, reverse=True)
    top, second = ranking[0], ranking[1]
    gap = top.score - second.score

    disputes = _dispute_count(results)
    if disputes == 0:
        return {"decision": "consensus", "confidence": 0.9, "reason": "结果一致"}

    if gap >= 0.25 and not core_conclusion:
        return {
            "decision": "winner",
            "confidence": 0.9,
            "reason": f"证据分差 {gap:.2f}，确定性采纳 {top.agent_id}",
            "winner": top.agent_id,
        }
    # 分差小或核心结论 → 中低置信（交 AI）
    return {
        "decision": "winner" if gap >= 0.15 else "human",
        "confidence": 0.5 if not core_conclusion else 0.3,
        "reason": f"分差 {gap:.2f} 较小" + ("，涉及核心结论" if core_conclusion else ""),
        "winner": top.agent_id,
    }
