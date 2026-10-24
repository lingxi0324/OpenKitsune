"""
流程规则引擎核心：规则开关、审计、降级保护。

- 提供统一入口 ``get_rule_engine()``，各规则模块通过它读取开关与审计。
- fail-open 设计：规则自身抛异常只记录日志，绝不阻断主流程。
- 审计记录同时写 logging 与可选 JSONL（audit_dir 配置）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_process_rules_config

logger = logging.getLogger(__name__)


@dataclass
class RuleAudit:
    """单次规则触发的审计记录。"""

    rule: str                    # 规则名（todo_policy / preflight / ...）
    action: str                  # 动作（suggest / block / check / arbitrate / classify ...）
    outcome: str                 # 结果（applied / skipped / degraded / blocked）
    detail: str = ""
    tool_name: str = ""
    duration_ms: float = 0.0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "action": self.action,
            "outcome": self.outcome,
            "detail": self.detail[:500],
            "tool_name": self.tool_name,
            "duration_ms": round(self.duration_ms, 2),
            "ts": round(self.ts, 3),
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts)),
        }


class RuleEngine:
    """规则引擎：开关查询 + 审计落盘。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._audit_buffer: list[dict[str, Any]] = []

    # ── 开关 ────────────────────────────────────────────────
    def is_enabled(self, rule: str) -> bool:
        try:
            return get_process_rules_config().rule_enabled(rule)
        except Exception:
            # 配置读取异常 → 视为关闭（fail-open：不阻断主流程）
            return False

    def rule_enabled(self, rule: str) -> bool:
        return self.is_enabled(rule)

    # ── 审计 ────────────────────────────────────────────────
    def record(
        self,
        rule: str,
        action: str,
        outcome: str,
        *,
        detail: str = "",
        tool_name: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        """记录一次规则审计。所有异常都吞掉——审计失败不影响主流程。"""
        try:
            rec = RuleAudit(
                rule=rule,
                action=action,
                outcome=outcome,
                detail=detail,
                tool_name=tool_name,
                duration_ms=duration_ms,
            ).to_dict()
            level = logging.WARNING if outcome == "blocked" else logging.INFO
            logger.log(
                level,
                "[ProcessRules] rule=%s action=%s outcome=%s tool=%s detail=%s",
                rule,
                action,
                outcome,
                tool_name or "-",
                detail[:200],
            )
            self._persist(rec)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ProcessRules] audit record failed: %s", exc)

    def _persist(self, rec: dict[str, Any]) -> None:
        try:
            cfg = get_process_rules_config()
            audit_dir = cfg.audit_dir
            if not audit_dir:
                return
            path = Path(audit_dir) / "process_rules.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 受保护执行：规则逻辑异常绝不外泄 ─────────────────────
    def guarded(self, rule: str, action: str, fn: Any, *, detail: str = "") -> Any:
        """执行规则逻辑；异常时按 fail-open 记录并返回 None。"""
        if not self.is_enabled(rule):
            return None
        started = time.monotonic()
        try:
            result = fn()
            self.record(
                rule,
                action,
                "applied",
                detail=detail,
                duration_ms=(time.monotonic() - started) * 1000,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            self.record(
                rule,
                action,
                "degraded",
                detail=f"{detail} | rule-error: {exc}",
                duration_ms=(time.monotonic() - started) * 1000,
            )
            return None


_ENGINE: RuleEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_rule_engine() -> RuleEngine:
    """全局引擎单例。"""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = RuleEngine()
    return _ENGINE


def is_enabled(rule: str) -> bool:
    """便捷开关查询。"""
    return get_rule_engine().is_enabled(rule)


def audit_record(rule: str, action: str, outcome: str, **kw: Any) -> None:
    """便捷审计入口。"""
    get_rule_engine().record(rule, action, outcome, **kw)


def reset_engine() -> None:
    """测试用：重置引擎单例。"""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
