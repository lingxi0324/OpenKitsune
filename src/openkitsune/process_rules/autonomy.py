"""
autonomy —— AI 自主决策层（整改版 v2.0 增强）

设计目标：规则不再由确定性代码"一刀切"，而是**分层决策**：

    L0 确定性快判（毫秒级，零成本）→ 给出置信度
    L1 灰色地带 → 调用 LLM 让 AI 基于完整上下文自主判断
    L2 兜底 → LLM 失败/超时/预算用尽 → 回退确定性结果（fail-open）

决策项（每条规则一个 decision key）：
    r1_todo      是否需要轻量 todo
    r1_plan      是否命中 Plan 风险信号（进 Plan 模式）
    r2_checkpoint 是否触发检查点（四类）
    r3_preflight 快检 or 详检
    r4_arbiter   多 Agent 冲突如何裁决（winner / 共识 / 需人工）
    r5_retry     异常如何处置（retry / switch_channel / ask_user / stop）
    r7_memory    记忆是否保存（save / update / skip）

成本约束（v2.0 文档 §0-§9）：
- LLM 决策每会话每规则有预算上限（autonomy_budget_per_rule，默认 3 次）。
- 单次决策 max_tokens 小（autonomy_max_tokens，默认 120），temperature 低。
- 命中预算 → 后续直接回退确定性结果，不再调 LLM。
- LLM 调用本身也受 guarded 保护：任何异常 → 回退。

配置（settings.process_rules_*）：
    autonomy_enabled: bool       默认 True
    autonomy_mode: str           默认 "auto"（L0 低置信才问 LLM；"always" 总是问；"never" 禁用 LLM）
    autonomy_confidence_threshold: float  默认 0.75（确定性置信 < 阈值 → 问 LLM）
    autonomy_max_tokens: int     默认 120
    autonomy_budget_per_rule: int 默认 3
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

from .config import get_process_rules_config
from .engine import audit_record, get_rule_engine

logger = logging.getLogger(__name__)

# 决策提示模板（system）
_AUTONOMY_SYSTEM = """你是流程规则决策器。根据给定的任务上下文，对每条规则做出"是否需要触发"的判断。
只输出 JSON，不要多余文字。输出格式：
{"r1_todo": true/false, "r1_plan": false, "r2_checkpoint": true/false,
 "r3_preflight": "fast"/"detail", "r4_arbiter": "winner"/"consensus"/"human",
 "r5_retry": "retry"/"switch_channel"/"ask_user"/"stop", "r7_memory": "save"/"update"/"skip",
 "reason": "一句话理由"}
- r1_todo: 任务是否多步（≥2 步）且值得跟踪。
- r1_plan: 是否命中风险信号（不可逆/外部副作用/权限敏感/用户要求先规划/首次陌生流程）。
- r2_checkpoint: 当前是否处于阶段边界、结果偏差、高风险操作前或多Agent冲突。
- r3_preflight: 该工具调用是否需要详检（新工具/高风险/失败过/参数不确定）。
- r4_arbiter: 多Agent结果冲突时如何裁决（winner=按证据采纳某方；consensus=结果一致；human=需用户裁决）。
- r5_retry: 异常处置建议。
- r7_memory: 是否值得保存为长期记忆。
判断要保守：不确定时倾向 false / "skip"，不制造额外开销。
【必填】reason 键必须给出 20 字以内的判断依据，禁止省略或留空。"""

# 决策键 → 合法值
_VALID = {
    "r1_todo": (True, False),
    "r1_plan": (True, False),
    "r2_checkpoint": (True, False),
    "r3_preflight": ("fast", "detail"),
    "r4_arbiter": ("winner", "consensus", "human"),
    "r5_retry": ("retry", "switch_channel", "ask_user", "stop"),
    "r7_memory": ("save", "update", "skip"),
}

_JSON_RE = re.compile(r"\{.*\}", re.S)


class AutonomyTracker:
    """会话级 LLM 决策预算与历史。"""

    def __init__(self) -> None:
        self._used: dict[str, int] = {}
        self._cache: dict[str, dict[str, Any]] = {}   # (rule, signature) → decision

    def budget_left(self, rule: str, budget: int) -> bool:
        return self._used.get(rule, 0) < budget

    def consume(self, rule: str) -> None:
        self._used[rule] = self._used.get(rule, 0) + 1

    def cached(self, rule: str, signature: str) -> dict[str, Any] | None:
        return self._cache.get((rule, signature))

    def remember(self, rule: str, signature: str, decision: dict[str, Any]) -> None:
        self._cache[(rule, signature)] = decision


_TRACKERS: dict[str, AutonomyTracker] = {}


def get_tracker(session_id: str | None) -> AutonomyTracker:
    key = session_id or "default"
    if key not in _TRACKERS:
        _TRACKERS[key] = AutonomyTracker()
    return _TRACKERS[key]


def _signature(decision_key: str, context: dict[str, Any]) -> str:
    """生成决策签名：相同上下文复用缓存，避免重复 LLM 调用。"""
    parts = []
    for k in ("tool_name", "user_request", "error_type", "message"):
        v = context.get(k)
        if v is not None:
            parts.append(f"{k}={str(v)[:120]}")
    return f"{decision_key}|{'|'.join(parts)}"


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """从 LLM 输出中提取 JSON（容忍围栏/多余文字）。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _sanitize(decision: dict[str, Any]) -> dict[str, Any]:
    """只保留合法键值，未知键丢弃；reason 文案保留但截断防注入。"""
    cleaned: dict[str, Any] = {}
    for key, valid_values in _VALID.items():
        val = decision.get(key)
        if val in valid_values:
            cleaned[key] = val
    reason = decision.get("reason")
    if isinstance(reason, str) and reason.strip():
        cleaned["reason"] = reason.strip()[:200]
    return cleaned


async def _call_llm(context: dict[str, Any], decision_keys: list[str], max_tokens: int) -> dict[str, Any] | None:
    """调用系统 LLM 做自主决策。失败返回 None（上层回退确定性）。"""
    try:
        from openkitsune.llm.client import chat
        from openkitsune.llm.types import Message

        # 构造上下文摘要（截断，控制 token 成本）
        tool = context.get("tool_name", "")
        user_req = str(context.get("user_request", ""))[:300]
        error_type = context.get("error_type", "")
        message = str(context.get("message", ""))[:200]
        agents = context.get("agent_results", "")
        if isinstance(agents, (list, tuple)):
            agents = "；".join(f"{a.agent_id}:{a.text[:80]}" for a in agents[:3])

        prompt = (
            f"工具: {tool or '无'}\n"
            f"用户请求: {user_req or '无'}\n"
            f"错误类型: {error_type or '无'} 错误信息: {message or '无'}\n"
            f"子Agent结果: {str(agents)[:200] or '无'}\n"
            f"请判断: {', '.join(decision_keys)}"
        )
        resp = await chat(
            messages=[Message(role="user", content=prompt)],
            system=_AUTONOMY_SYSTEM,
            max_tokens=max_tokens,
            temperature=0.2,
        )
        text = resp.text if hasattr(resp, "text") else str(resp)
        parsed = _parse_llm_json(text)
        if parsed is None:
            logger.debug("[Autonomy] LLM output not JSON: %.120s", text)
            return None
        return _sanitize(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Autonomy] LLM call failed, fallback deterministic: %s", exc)
        return None


async def decide(
    decision_key: str,
    *,
    session_id: str | None = None,
    deterministic: Callable[[], dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """自主决策主入口（async）。

    Args:
        decision_key: 决策项（r1_todo / r1_plan / r2_checkpoint / r3_preflight /
                      r4_arbiter / r5_retry / r7_memory）
        deterministic: 确定性判定函数，返回 {decision, confidence, reason} 等。
        context: 决策上下文（tool_name/user_request/error_type/message/...）。

    Returns:
        dict: {
            key, decision, confidence, decided_by ("deterministic"/"llm"/"fallback"),
            reason, llm_raw (可选)
        }
    """
    engine = get_rule_engine()
    cfg = get_process_rules_config()
    if not engine.is_enabled("autonomy") or not cfg.autonomy_enabled:
        # 自主决策关闭 → 纯确定性
        det = deterministic() if deterministic else {"decision": None, "confidence": 1.0}
        det.setdefault("decided_by", "deterministic")
        det.setdefault("key", decision_key)
        return det

    # L0 确定性快判
    det = deterministic() if deterministic else {"decision": None, "confidence": 0.5}
    conf = float(det.get("confidence", 0.0))
    decision = det.get("decision")
    mode = cfg.autonomy_mode
    context = context or {}

    # 缓存命中 → 直接用（相同上下文不重复问 LLM；返回拷贝避免污染原对象）
    tracker = get_tracker(session_id)
    sig = _signature(decision_key, context)
    cached = tracker.cached(decision_key, sig)
    if cached is not None:
        hit = dict(cached)
        hit["decided_by"] = "llm_cached"
        return hit

    need_llm = False
    if mode == "always":
        need_llm = True
    elif mode == "auto":
        need_llm = conf < cfg.autonomy_confidence_threshold
    # mode == "never" → 不调 LLM

    if not need_llm or not tracker.budget_left(decision_key, cfg.autonomy_budget_per_rule):
        det.setdefault("decided_by", "deterministic")
        det.setdefault("key", decision_key)
        return det

    tracker.consume(decision_key)
    try:
        llm_dec = await _call_llm(context, [decision_key], cfg.autonomy_max_tokens)
    except Exception as exc:  # noqa: BLE001
        # fail-open：LLM 调用本身异常也不外泄
        logger.debug("[Autonomy] LLM call raised, fallback deterministic: %s", exc)
        llm_dec = None

    if not llm_dec:
        # L2 兜底：LLM 失败 → 确定性结果
        audit_record(
            "autonomy", "llm_fallback", "degraded",
            detail=f"{decision_key} LLM 失败，回退确定性",
        )
        det.setdefault("decided_by", "fallback")
        det.setdefault("key", decision_key)
        return det

    llm_val = llm_dec.get(decision_key)
    if llm_val is None:
        det.setdefault("decided_by", "fallback")
        det.setdefault("key", decision_key)
        return det

    decision = llm_val
    result = {
        "key": decision_key,
        "decision": decision,
        "confidence": 1.0,  # LLM 判定视为高置信（预算内）
        "decided_by": "llm",
        "reason": llm_dec.get("reason", ""),
        "llm_raw": llm_dec,
    }
    tracker.remember(decision_key, sig, result)
    audit_record(
        "autonomy", f"llm_decision:{decision_key}", "applied",
        detail=f"decision={decision} reason={llm_dec.get('reason','')[:120]}",
    )
    return result


def decide_async_or_sync(decision_key: str, **kw: Any) -> dict[str, Any]:
    """兼容同步调用：内部若有运行 loop 则走确定性，否则 asyncio.run 完整执行。

    供非 async 上下文调用（如同步 tool handler 内）。无运行 loop 时用
    asyncio.run 跑完整自主决策（含 LLM）；已有 loop（被 async 上下文误调）
    时避免嵌套 loop，直接回退确定性。
    """
    try:
        asyncio.get_running_loop()
        # 已有运行 loop：不能安全嵌套 asyncio.run → 纯确定性
        det = kw.get("deterministic")
        result = det() if det else {"decision": None, "confidence": 1.0}
        result.setdefault("decided_by", "deterministic")
        result.setdefault("key", decision_key)
        return result
    except RuntimeError:
        # 无运行 loop：同步上下文，完整执行（含 LLM）
        return asyncio.run(decide(decision_key, **kw))
