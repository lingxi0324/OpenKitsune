"""TurnReview — 每轮对话六问复盘（V2.0 自我复盘进化逻辑）。

对齐：V2.0 方案「自我复盘进化逻辑」六问 + 九尾复盘尾。
存储：复用 RetrospectStorage（data/retrospects/YYYY-MM-DD_retrospects.jsonl），
       self_check.py 每日报告自动汇总，形成闭环。

用法：
    from openkitsune.evolution.turn_review import (
        record_turn_review, SIX_QUESTIONS, six_questions_prompt,
    )
    record_turn_review(task_id=..., session_id=..., description=...,
                       intent_ok=0.9, nine_tail_coverage=0.67, emotion_ok=0.8,
                       plan_ok=0.9, persona_ok=1.0, satisfaction=0.8,
                       improvement="...")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..core.task_monitor import RetrospectRecord, RetrospectStorage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# V2.0 六问
# ---------------------------------------------------------------------------
SIX_QUESTIONS: list[dict[str, str]] = [
    {"key": "intent_ok", "name": "意图识别", "ask": "意图识别是否准确？"},
    {"key": "nine_tail_coverage", "name": "九维覆盖", "ask": "九维（九尾）是否覆盖？"},
    {"key": "emotion_ok", "name": "情绪接住", "ask": "情绪是否接住？"},
    {"key": "plan_ok", "name": "方案落地", "ask": "方案是否落地？"},
    {"key": "persona_ok", "name": "人设一致", "ask": "人设是否一致（是否像九尾狐）？"},
    {"key": "satisfaction", "name": "用户满意", "ask": "用户是否满意？"},
]


def six_questions_prompt() -> str:
    """生成六问自评提示词（供 LLM 在每轮对话后自评）。"""
    lines = [
        "## 复盘六问（每轮对话后静默自评，0-1 打分 + 一句话改进）",
    ]
    for q in SIX_QUESTIONS:
        lines.append(f"- {q['ask']} (0-1)")
    lines.append("输出格式：intent_ok=.. nine_tail_coverage=.. emotion_ok=.. plan_ok=.. persona_ok=.. satisfaction=.. improvement=..")
    return "\n".join(lines)


@dataclass
class TurnReview:
    """一轮对话的六问复盘结果。"""

    task_id: str
    session_id: str | None = None
    description: str = ""
    intent_ok: float = 0.0
    nine_tail_coverage: float = 0.0
    emotion_ok: float = 0.0
    plan_ok: float = 0.0
    persona_ok: float = 0.0
    satisfaction: float = 0.0
    improvement: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "description": self.description,
            "six_questions": {
                "intent_ok": self.intent_ok,
                "nine_tail_coverage": self.nine_tail_coverage,
                "emotion_ok": self.emotion_ok,
                "plan_ok": self.plan_ok,
                "persona_ok": self.persona_ok,
                "satisfaction": self.satisfaction,
            },
            "improvement": self.improvement,
            "timestamp": self.timestamp,
        }

    def to_retrospect_result(self) -> str:
        """转成可读复盘文本（写入 retrospect_result 字段）。"""
        q = self.to_dict()["six_questions"]
        parts = [
            "**【六问复盘】**",
            f"- 意图识别: {q['intent_ok']:.2f}",
            f"- 九维覆盖: {q['nine_tail_coverage']:.2f}",
            f"- 情绪接住: {q['emotion_ok']:.2f}",
            f"- 方案落地: {q['plan_ok']:.2f}",
            f"- 人设一致: {q['persona_ok']:.2f}",
            f"- 用户满意: {q['satisfaction']:.2f}",
        ]
        if self.improvement:
            parts.append(f"- 改进: {self.improvement}")
        return "\n".join(parts)


def record_turn_review(
    task_id: str,
    session_id: str | None = None,
    description: str = "",
    intent_ok: float = 0.0,
    nine_tail_coverage: float = 0.0,
    emotion_ok: float = 0.0,
    plan_ok: float = 0.0,
    persona_ok: float = 0.0,
    satisfaction: float = 0.0,
    improvement: str = "",
) -> bool:
    """记录一轮六问复盘，复用 RetrospectStorage 写入。

    Returns:
        是否保存成功
    """
    try:
        review = TurnReview(
            task_id=task_id,
            session_id=session_id,
            description=description,
            intent_ok=float(intent_ok),
            nine_tail_coverage=float(nine_tail_coverage),
            emotion_ok=float(emotion_ok),
            plan_ok=float(plan_ok),
            persona_ok=float(persona_ok),
            satisfaction=float(satisfaction),
            improvement=improvement,
        )
        record = RetrospectRecord(
            task_id=task_id,
            session_id=session_id,
            description=description,
            duration_seconds=0.0,
            iterations=1,
            model_switched=False,
            initial_model="",
            final_model="",
            retrospect_result=review.to_retrospect_result(),
            timestamp=review.timestamp,
        )
        ok = RetrospectStorage().save(record)
        if ok:
            logger.info("[TurnReview] 六问复盘已写入: %s", task_id)
        return ok
    except Exception as e:  # noqa: BLE001 — 复盘失败不影响主流程
        logger.error("[TurnReview] 六问复盘写入失败: %s", e)
        return False
