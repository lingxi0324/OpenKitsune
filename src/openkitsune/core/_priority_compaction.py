"""任务价值优先的分层上下文压缩（P0—P6 优先级模型）。

落地自《上下文压缩机制设计》：
- 七层优先级 P0（系统/安全/用户原始目标）→ P6（噪声/心跳），数值越大压缩
  优先度越高；
- 动态评分：α×层级基权 + β×任务关联度 + γ×因果链贡献 + δ×不可恢复性 +
  ε×时效性 − η×冗余度 − θ×token 成本（权重可配置，不硬编码）；
- 分级压缩：占用率 80/90/95/98% → 轻/中/重/极限四档，先清低优先级再酌清
  高优先级，达标即停；
- 确定性压缩算子（零 LLM）：DROP / DEDUP / VERSION_FOLD / EXTERNALIZE；
- 结构重构：压缩后按任务读取优先级重排轮次（P0 最前），role 交替校验失败
  则回退原序（防 400）；
- 合规校验：P0/P1/P2 完整性（系统指令、用户目标、任务快照、最终结论）。

与现有机制的分工：
- ``CompactionGuard``（_compaction_guard.py）管"该不该压 / 熔断"；
- 本模块管"压什么、压多少、按什么顺序保留"。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 优先级层级
# ----------------------------------------------------------------------


class PriorityLevel(IntEnum):
    """P0 最高（绝对锁定），P6 最低（无条件清理）。数值即压缩优先度。"""

    P0 = 0  # 系统指令、安全合规、用户原始目标、授权边界、最终交付定义
    P1 = 1  # LLM 最终结论、正式成果、最终代码、方案定稿、最终答复
    P2 = 2  # 任务快照：目标、进度、待办、约束、依赖、阶段成果、摘要
    P3 = 3  # 工具执行结果、检索证据、关键数据、来源、置信度
    P4 = 4  # 有效代码/配置最终态、代码迭代草稿、废弃版本
    P5 = 5  # 工具调用过程、重试、参数草稿、调试日志、失败尝试
    P6 = 6  # 心跳日志、空行、重复提示、加载日志、无关闲聊


LEVEL_BASE_WEIGHT: dict[PriorityLevel, float] = {
    PriorityLevel.P0: 1.00,
    PriorityLevel.P1: 0.95,
    PriorityLevel.P2: 0.80,
    PriorityLevel.P3: 0.65,
    PriorityLevel.P4: 0.50,
    PriorityLevel.P5: 0.30,
    PriorityLevel.P6: 0.05,
}

# 写入/产出类工具 → P4（代码/产物）；过程/调试类 → P5
_WRITE_TOOLS = {
    "write_file", "create_file", "apply_patch", "edit_file", "patch", "write",
    "create", "save", "update_file", "modify_file", "file_write",
}
_PROCESS_TOOLS = {
    "bash", "terminal", "execute_code", "run", "search", "read_file", "web_search",
    "browser", "fetch", "grep", "glob", "list_dir", "ls", "cat", "npm", "pip",
}

# 用户目标/约束强词（首条 user 指令 + 强约束 → P0/P2 权重加成）
_GOAL_KEYWORDS = (
    "必须", "禁止", "不要", "授权", "目标", "要求", "记住", "最终", "完成",
    "交付", "约束", "边界", "不允许", "优先", "务必",
)

# 纯噪声（P6）特征
_NOISE_MARKERS = ("心跳", "loading", "Loading", "系统提示", "…", "...")


class CompressionGrade:
    """分级压缩档位（占用率阈值可配置）。"""

    LIGHT = "light"        # >= 80%: 全清 P6；P5 去重/外置；P0—P4 不动
    MODERATE = "moderate"  # >= 90%: P5 只留最新/关键失败；P4 折叠草稿；P3 初步摘要
    HEAVY = "heavy"        # >= 95%: P4 只留最终版本；P3 全部结构化摘要
    EXTREME = "extreme"    # >= 98%: 仅 P0+P1+最新 P2+关键 P3 引用；P4/P5/P6 全外置

    _LEVEL_ORDER = (LIGHT, MODERATE, HEAVY, EXTREME)


def grade_pressure(ratio: float, *, thresholds: Iterable[tuple[str, float]] | None = None) -> str | None:
    """按上下文占用率返回压缩档位；未达 light 阈值返回 None（不触发分级压缩）。

    默认阈值 0.75/0.85/0.93/0.97（>75% 即开始压缩：light 只做零风险清理 +
    轻量算子；85%+ 起 DEDUP/折叠，93%+ 起 EXTERNALIZE，97%+ 结构性全压）。
    可按 (grade, threshold) 传入覆盖。
    """
    if thresholds is None:
        thresholds = (
            (CompressionGrade.LIGHT, 0.75),
            (CompressionGrade.MODERATE, 0.85),
            (CompressionGrade.HEAVY, 0.93),
            (CompressionGrade.EXTREME, 0.97),
        )
    grade = None
    for name, threshold in thresholds:
        if ratio >= threshold:
            grade = name
    return grade


# ----------------------------------------------------------------------
# 消息分类（确定性，零 LLM）
# ----------------------------------------------------------------------


def _msg_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            block_type = item.get("type", "")
            if block_type == "text":
                parts.append(str(item.get("text", "")))
            elif block_type == "tool_use":
                try:
                    parts.append(
                        json.dumps(item.get("input", {}), ensure_ascii=False, default=str)
                    )
                except (TypeError, ValueError):
                    pass
            elif block_type == "tool_result":
                raw = item.get("content")
                if isinstance(raw, str):
                    parts.append(raw)
                elif isinstance(raw, list):
                    for seg in raw:
                        if isinstance(seg, dict) and seg.get("type") == "text":
                            parts.append(str(seg.get("text", "")))
        return "\n".join(parts)
    return ""


def _is_tool_result_message(msg: dict) -> bool:
    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in content
        if isinstance(item, dict)
    )


def _contains_tool_use(msg: dict) -> bool:
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(item, dict) and item.get("type") == "tool_use" for item in content)


def _tool_use_names(msg: dict) -> list[str]:
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    return [
        str(item.get("name", ""))
        for item in content
        if isinstance(item, dict) and item.get("type") == "tool_use"
    ]


def classify_message(
    msg: dict,
    *,
    msg_index: int,
    total: int,
    first_user_text_index: int = -1,
) -> PriorityLevel:
    """确定性分类：P0—P6。

    规则（保持可测、不依赖 LLM）：
    - system → P0；
    - 摘要/快照标记（_compaction_summary / compaction_summary / task_orientation
      / context_note / context_epoch_update）→ P2；
    - 首条非工具 user 文本（用户原始目标）→ P0；其余 user 文本 → P2；
    - user 含 tool_result → P3；role=tool → P5；
    - assistant 含 tool_use：写入/产出类工具 → P4，过程/调试类 → P5；
    - assistant 纯文本：最后一条 → P1（最终结论），其余 → P2（阶段成果）；
    - 空/噪声 → P6。
    """
    role = msg.get("role", "")
    content = msg.get("content", "")

    if role == "system":
        return PriorityLevel.P0

    # 快照/摘要标记
    source = msg.get("_model_source", "") or ""
    if (
        msg.get("_compaction_summary")
        or source == "compaction_summary"
        or source == "task_orientation"
    ):
        return PriorityLevel.P2

    text = _msg_text(msg)
    if isinstance(content, str) and (
        content.startswith("[context_note")
        or content.startswith("[context_epoch_update]")
        or content.startswith("[上下文边界]")
    ):
        return PriorityLevel.P2

    # 噪声 / 空内容
    if not text.strip():
        return PriorityLevel.P6
    if len(text.strip()) <= 2 and text.strip() in _NOISE_MARKERS:
        return PriorityLevel.P6
    if any(marker in text for marker in _NOISE_MARKERS) and len(text) < 40:
        return PriorityLevel.P6

    if role == "user":
        if _is_tool_result_message(msg):
            return PriorityLevel.P3
        if msg_index == first_user_text_index or msg_index == 0:
            return PriorityLevel.P0
        return PriorityLevel.P2

    if role == "tool":
        return PriorityLevel.P5

    if role == "assistant":
        if _contains_tool_use(msg):
            names = _tool_use_names(msg)
            if any(n in _WRITE_TOOLS for n in names):
                return PriorityLevel.P4
            if any(n in _PROCESS_TOOLS for n in names):
                return PriorityLevel.P5
            return PriorityLevel.P4 if names else PriorityLevel.P5
        # 纯文本
        if msg_index == total - 1:
            return PriorityLevel.P1  # 最终答复
        # 中间答复也含结论性内容时视为阶段成果
        return PriorityLevel.P2

    return PriorityLevel.P5


# ----------------------------------------------------------------------
# 分类置信度（V2：宁可少压，不可误压）
# ----------------------------------------------------------------------


def classify_with_confidence(
    msg: dict,
    *,
    msg_index: int,
    total: int,
    first_user_text_index: int = -1,
) -> tuple[PriorityLevel, float]:
    """确定性分类 + 置信度估计。

    置信度语义：规则命中的确定性强弱。
    - 1.0：结构级信号（system / 首条 user / tool_result / 末条 assistant /
      显式摘要标记）——无语义猜测，误判率趋近 0；
    - 0.85：白名单工具名（写入/过程类）——工具名已知，但输入语义未知；
    - 0.6：普通 user/assistant 文本——按 role+位置启发；
    - 0.4：未知工具名 fallback（猜测 P4/P5）——压缩算子应对此类块
      默认归入更高保护层级（跳过激进算子），避免 P3 证据误清。
    """
    role = msg.get("role", "")
    content = msg.get("content", "")

    if role == "system":
        return PriorityLevel.P0, 1.0

    source = msg.get("_model_source", "") or ""
    if (
        msg.get("_compaction_summary")
        or source == "compaction_summary"
        or source == "task_orientation"
    ):
        return PriorityLevel.P2, 1.0

    text = _msg_text(msg)
    if isinstance(content, str) and (
        content.startswith("[context_note")
        or content.startswith("[context_epoch_update]")
        or content.startswith("[上下文边界]")
    ):
        return PriorityLevel.P2, 1.0

    if not text.strip() or (
        any(marker in text for marker in _NOISE_MARKERS) and len(text) < 40
    ):
        return PriorityLevel.P6, 0.6

    if role == "user":
        if _is_tool_result_message(msg):
            return PriorityLevel.P3, 1.0
        if msg_index == first_user_text_index or msg_index == 0:
            return PriorityLevel.P0, 1.0
        return PriorityLevel.P2, 0.6

    if role == "tool":
        return PriorityLevel.P5, 0.6

    if role == "assistant":
        if _contains_tool_use(msg):
            names = _tool_use_names(msg)
            if any(n in _WRITE_TOOLS for n in names):
                return PriorityLevel.P4, 0.85
            if any(n in _PROCESS_TOOLS for n in names):
                return PriorityLevel.P5, 0.85
            # 未知工具名：低置信，默认保护（算子不得激进处理）
            return (PriorityLevel.P4 if names else PriorityLevel.P5), 0.4
        if msg_index == total - 1 and text.strip():
            return PriorityLevel.P1, 1.0
        return PriorityLevel.P2, 0.6

    return PriorityLevel.P5, 0.4


def _low_confidence(
    msg: dict,
    *,
    msg_index: int,
    total: int,
    first_user_text_index: int,
    threshold: float,
) -> bool:
    """置信度低于阈值 → 保守保护（跳过激进算子）。"""
    _, conf = classify_with_confidence(
        msg, msg_index=msg_index, total=total, first_user_text_index=first_user_text_index
    )
    return conf < threshold


# ----------------------------------------------------------------------
# 动态评分
# ----------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "alpha": 0.40,  # 层级基权
    "beta": 0.20,   # 任务关联度
    "gamma": 0.10,  # 因果链贡献
    "delta": 0.10,  # 不可恢复性
    "epsilon": 0.05,  # 时效性
    "eta": 0.10,    # 冗余度（惩罚）
    "theta": 0.05,  # token 成本（惩罚）
}


def score_block(
    msg: dict,
    level: PriorityLevel,
    *,
    tokens: int,
    msg_index: int,
    total: int,
    redundant: bool = False,
    weights: dict[str, float] | None = None,
) -> float:
    """综合优先级评分（分数越高越应保留）。

    Priority = α×层级基权 + β×任务关联度 + γ×因果链贡献 + δ×不可恢复性
               + ε×时效性 − η×冗余度 − θ×token 成本
    """
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)

    level_weight = LEVEL_BASE_WEIGHT[level]
    text = _msg_text(msg)
    relevance = 0.5
    if level in (PriorityLevel.P0, PriorityLevel.P1, PriorityLevel.P2):
        relevance = 0.9
    if any(kw in text for kw in _GOAL_KEYWORDS):
        relevance = max(relevance, 0.95)

    causal = 0.5
    if _contains_tool_use(msg):
        causal = 0.8
    elif _is_tool_result_message(msg):
        causal = 0.7

    irrecoverable = 0.4
    if msg.get("role") == "user" and not _is_tool_result_message(msg):
        irrecoverable = 0.9
    if msg.get("_cold_output_ref"):
        irrecoverable = 0.2

    recency = (msg_index / total) if total else 0.0
    redundancy_f = 0.8 if redundant else 0.1
    cost = min(1.0, max(0.0, tokens / 4000.0))

    return (
        w["alpha"] * level_weight
        + w["beta"] * relevance
        + w["gamma"] * causal
        + w["delta"] * irrecoverable
        + w["epsilon"] * recency
        - w["eta"] * redundancy_f
        - w["theta"] * cost
    )


def block_fingerprint(msg: dict) -> str:
    """工具结果去重指纹（字节相同判定）。"""
    text = _msg_text(msg)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ----------------------------------------------------------------------
# 轮次切分（结构重构的最小单元，轮内不拆保工具对）
# ----------------------------------------------------------------------


class Turn:
    __slots__ = ("msgs", "level", "index", "first_role")

    def __init__(self, msgs: list[dict], level: PriorityLevel, index: int) -> None:
        self.msgs = msgs
        self.level = level
        self.index = index
        self.first_role = msgs[0].get("role", "") if msgs else ""

    @property
    def tokens(self) -> int:
        # 由调用方注入估算函数，避免本模块与 ContextManager 循环依赖
        return getattr(self, "_tokens", 0)

    def with_tokens(self, tokens: int) -> Turn:
        self._tokens = tokens
        return self


def segment_turns(messages: list[dict]) -> list[Turn]:
    """按会话轮切分：轮 = 从一条 user 消息开始的连续序列（含其后 assistant /
    tool 对，直到下一条 user 之前）。system 消息各自独立成轮。

    轮内不拆 → tool_use / tool_result 配对天然完整。
    """
    turns: list[Turn] = []
    if not messages:
        return turns
    current: list[dict] = []
    current_start_role: str | None = None
    idx = 0
    for _i, msg in enumerate(messages):
        role = msg.get("role", "")
        if current_start_role is None:
            current = [msg]
            current_start_role = role
            continue
        if role == "system" or (role == "user" and not _is_tool_result_message(msg)):
            # 新轮开始：system 或新一轮用户输入（tool_result 属于当前轮）
            level = classify_message(
                current[0],
                msg_index=idx,
                total=len(messages),
            )
            turns.append(Turn(current, level, idx))
            current = [msg]
            current_start_role = role
            idx += 1
            continue
        current.append(msg)
    if current:
        level = classify_message(current[0], msg_index=idx, total=len(messages))
        turns.append(Turn(current, level, idx))
    return turns


# ----------------------------------------------------------------------
# 确定性压缩算子（零 LLM）
# ----------------------------------------------------------------------


def apply_deterministic_ops(
    messages: list[dict],
    grade: str | None,
    *,
    estimate_tokens: Callable[[list[dict]], int],
    recent_protect: int = 3,
    tail_protect_fraction: float = 0.15,
    confidence_threshold: float = 0.80,
) -> tuple[list[dict], dict]:
    """按压缩档位执行确定性算子：DROP P6 → DEDUP P3/P5 → VERSION_FOLD P4 →
    EXTERNALIZE P5。零 LLM 成本，先清低优先级，达标即停（由调用方判断）。

    尾部保护：最近 ``tail_protect_fraction``（默认 15%）的上下文进程（按
    token 预算从末尾累计）与最近 ``recent_protect`` 条消息均不触碰，取
    更保守者 —— 近期对话进程必须完整保留。

    返回 ``(new_messages, stats)``。stats 含各算子计数、token 变化与
    ``compacted_spans``（被清理/改写的原文区间，供 KV Cache 层协同驱逐）。
    """
    if grade is None:
        return list(messages), {"grade": None, "compacted_spans": []}

    tokens_before = estimate_tokens(messages)
    working = list(messages)
    n = len(working)
    orig_index = {id(m): i for i, m in enumerate(messages)}
    spans: list[dict] = []
    stats: dict = {
        "grade": grade, "dropped_p6": 0, "deduped": 0, "folded": 0,
        "externalized": 0, "tokens_before": tokens_before, "compacted_spans": [],
    }

    # ---------- DROP：清 P6（尾部保护：最近 15% token + 最近 N 条不动） ----------
    protected_tail = _tail_start_index(
        working, estimate_tokens,
        tail_protect_fraction=tail_protect_fraction, recent_protect=recent_protect,
    )
    first_ui = _first_user_text_index(working)
    kept: list[dict] = []
    for i, msg in enumerate(working):
        if i < protected_tail:
            level = classify_message(
                msg, msg_index=i, total=n, first_user_text_index=first_ui
            )
            if level == PriorityLevel.P6:
                stats["dropped_p6"] += 1
                spans.append({
                    "start_index": orig_index[id(msg)],
                    "end_index": orig_index[id(msg)] + 1,
                    "op": "DROP",
                    "reason": "P6 噪声（心跳/空行/重复提示）",
                })
                continue
        kept.append(msg)
    working = kept

    if grade in (CompressionGrade.MODERATE, CompressionGrade.HEAVY, CompressionGrade.EXTREME):
        # ---------- DEDUP：字节相同工具结果回读引用（早期区域） ----------
        tail_start = _tail_start_index(
            working, estimate_tokens,
            tail_protect_fraction=tail_protect_fraction, recent_protect=recent_protect,
        )
        seen: dict[str, str] = {}
        deduped_list: list[dict] = []
        for i, msg in enumerate(working):
            if i >= tail_start:
                deduped_list.append(msg)
                continue
            content = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(item, dict) and item.get("type") == "tool_result"
                for item in content
            ):
                fp = block_fingerprint(msg)
                prev_id = seen.get(fp)
                if prev_id and prev_id != msg.get("tool_use_id", ""):
                    new_content: list = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            ref = (
                                f"[identical tool result: see tool_use_id={prev_id}; "
                                f"sha256={fp[:12]}; 原文见前文]"
                            )
                            if item.get("_cold_output_ref"):
                                ref = (
                                    f"[identical tool result: see tool_use_id={prev_id}; "
                                    f"sha256={fp[:12]}; read_file(path=memory://tool-output/"
                                    f"{item['_cold_output_ref']})]"
                                )
                            item = {**item, "content": ref}
                        new_content.append(item)
                    stats["deduped"] += 1
                    spans.append({
                        "start_index": orig_index[id(msg)],
                        "end_index": orig_index[id(msg)] + 1,
                        "op": "DEDUP",
                        "reason": "字节相同工具结果回读引用",
                    })
                    deduped_list.append({**msg, "content": new_content})
                else:
                    seen[fp] = str(msg.get("tool_use_id", "") or next(
                        (str(b.get("tool_use_id", "")) for b in content if isinstance(b, dict) and b.get("type") == "tool_result"), ""
                    ))
                    deduped_list.append(msg)
            else:
                deduped_list.append(msg)
        working = deduped_list

        # ---------- VERSION_FOLD：P4 代码写入草稿折叠（同路径覆盖即折叠旧版，
        # 不依赖内容相同；显式 version/deprecated 字段亦触发） ----------
        tail_start = _tail_start_index(
            working, estimate_tokens,
            tail_protect_fraction=tail_protect_fraction, recent_protect=recent_protect,
        )
        write_seen: dict[str, tuple[str, int]] = {}  # key → (tool_use_id, folded_list idx)
        folded_list: list[dict] = []
        for i, msg in enumerate(working):
            if i >= tail_start:
                folded_list.append(msg)
                continue
            if _contains_tool_use(msg) and any(n in _WRITE_TOOLS for n in _tool_use_names(msg)):
                key = _write_fold_key(msg)
                new_id = str(msg.get("id", ""))
                if key in write_seen:
                    prev_id, prev_idx = write_seen[key]
                    # 折叠较早版本（保留最新一次写入）
                    if 0 <= prev_idx < len(folded_list):
                        prev_obj = folded_list[prev_idx]
                        folded_list[prev_idx] = {
                            **prev_obj,
                            "content": (
                                f"[版本折叠: 较早写入已被后续版本覆盖，最新见 "
                                f"tool_use_id={new_id or prev_id}]"
                            ),
                        }
                        stats["folded"] += 1
                        spans.append({
                            "start_index": orig_index[id(prev_obj)],
                            "end_index": orig_index[id(prev_obj)] + 1,
                            "op": "VERSION_FOLD",
                            "reason": "同路径/同目标写入被后续版本覆盖",
                        })
                    write_seen[key] = (new_id, len(folded_list))
                    folded_list.append(msg)
                else:
                    write_seen[key] = (new_id, len(folded_list))
                    folded_list.append(msg)
            else:
                folded_list.append(msg)
        working = folded_list

        # ---------- EXTERNALIZE：P5 过程/调试长文本精简（低置信块跳过，
        # 防止未知工具名的 P3 证据被误清 —— 宁可少压，不可误压） ----------
        tail_start = _tail_start_index(
            working, estimate_tokens,
            tail_protect_fraction=tail_protect_fraction, recent_protect=recent_protect,
        )
        first_ui = _first_user_text_index(working)
        externalized_list: list[dict] = []
        for i, msg in enumerate(working):
            if i >= tail_start:
                externalized_list.append(msg)
                continue
            text = _msg_text(msg)
            if (
                len(text) > 500
                and classify_message(
                    msg, msg_index=i, total=len(working), first_user_text_index=first_ui
                ) == PriorityLevel.P5
                and not _low_confidence(
                    msg, msg_index=i, total=len(working),
                    first_user_text_index=first_ui, threshold=confidence_threshold,
                )
            ):
                stats["externalized"] += 1
                spans.append({
                    "start_index": orig_index[id(msg)],
                    "end_index": orig_index[id(msg)] + 1,
                    "op": "EXTERNALIZE",
                    "reason": "P5 过程/调试日志精简",
                })
                externalized_list.append(
                    {
                        **msg,
                        "content": text[:200] + "\n…[过程日志已精简，原文可回溯]…",
                    }
                )
            else:
                externalized_list.append(msg)
        working = externalized_list

    stats["tokens_after"] = estimate_tokens(working)
    stats["tokens_saved"] = tokens_before - stats["tokens_after"]
    stats["compacted_spans"] = _merge_spans(spans)
    return working, stats


def _write_fold_key(msg: dict) -> str:
    """写入消息的折叠键：优先 (工具名, 显式目标路径/文件名)，无路径回退内容指纹。

    路径字段取 input 中的 path/file/filename/target —— 同目标多次写入视为
    版本迭代，保守折叠已被覆盖的旧版本（不猜测未来是否还会修改）。
    """
    content = msg.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = str(item.get("name", ""))
            input_data = item.get("input", {}) or {}
            if isinstance(input_data, dict):
                for k in ("path", "file", "filename", "target"):
                    val = input_data.get(k)
                    if val:
                        return f"{name}:{val}"
    return f"{msg.get('role', '')}:fp:{block_fingerprint(msg)[:12]}"


def _tail_start_index(
    messages: list[dict],
    estimate_tokens: Callable[[list[dict]], int],
    *,
    tail_protect_fraction: float,
    recent_protect: int,
) -> int:
    """尾部保护起点：最近 ``tail_protect_fraction``（默认 15%）的上下文进程
    （按 token 预算从末尾累计）与最近 ``recent_protect`` 条消息，取更保守
    （更靠前）者 —— 近期对话进程必须完整保留，任何压缩算子不得触碰。"""
    n = len(messages)
    if n <= 1:
        return 0
    total = estimate_tokens(messages)
    tail_budget = int(total * tail_protect_fraction)
    start = n
    acc = 0
    for i in range(n - 1, -1, -1):
        acc += estimate_tokens([messages[i]])
        if acc >= tail_budget:
            start = i
            break
    return min(start, n - recent_protect)


def purge_p6_noise(
    messages: list[dict],
    *,
    estimate_tokens: Callable[[list[dict]], int],
    recent_protect: int = 3,
    tail_protect_fraction: float = 0.15,
) -> tuple[list[dict], dict]:
    """无条件 P6 噪声清理（零风险操作，任何水位可执行，不依赖压缩档位）。

    对应改进建议第 3 条：预算充足时不做实质压缩，但 P6 清理可在任何水位
    无条件执行，避免"预算尚余 20% 却动了实质内容"。尾部保护同样生效：
    最近 15% 上下文进程不清理。
    """
    return apply_deterministic_ops(
        messages,
        CompressionGrade.LIGHT,
        estimate_tokens=estimate_tokens,
        recent_protect=recent_protect,
        tail_protect_fraction=tail_protect_fraction,
    )


def compute_compacted_spans(source: list[dict], result: list[dict]) -> list[dict]:
    """对比压缩前后消息，返回被删除/被改写/被摘要化的原文区间。

    对应改进建议第 5 条（KV Cache 协同）：文本层已清理/改写的 token，
    其 KV 状态应被驱逐，否则模型仍"记得"被压缩掉的内容 —— 可见层与
    注意力层不一致。压缩计算成功采纳后，调用方应立即将区间交给推理
    引擎驱逐（立即清理驱逐，确保压缩收益闭环）。

    多重集配额比较：按指纹计数比对 source/result。同指纹消息被折叠成
    较少条数时（如 DEDUP 把 12 条相同 bash 折叠成 1 条），只保留与
    result 数量相等的配额，超出配额的源消息记入驱逐区间 —— 否则那 11
    条折叠掉的 KV 状态会被"指纹仍在集合中"误判为保留而漏驱逐。
    """
    source_counts: dict[str, int] = {}
    for m in source:
        fp = block_fingerprint(m)
        source_counts[fp] = source_counts.get(fp, 0) + 1
    result_counts: dict[str, int] = {}
    for m in result:
        fp = block_fingerprint(m)
        result_counts[fp] = result_counts.get(fp, 0) + 1

    spans: list[dict] = []
    remaining = dict(result_counts)
    for i, msg in enumerate(source):
        fp = block_fingerprint(msg)
        if remaining.get(fp, 0) > 0:
            remaining[fp] -= 1  # 该实例在压缩结果中仍保留
        else:
            spans.append({
                "start_index": i,
                "end_index": i + 1,
                "op": "SUMMARY_OR_REPLACED",
                "reason": "消息未在压缩结果中保持原样（已摘要化/删除/改写/折叠）",
            })
    return _merge_spans(spans)


def _merge_spans(spans: list[dict]) -> list[dict]:
    """按 start_index 排序并合并相邻/重叠区间。"""
    if not spans:
        return []
    merged: list[dict] = []
    for span in sorted(spans, key=lambda s: s["start_index"]):
        if merged and span["start_index"] <= merged[-1]["end_index"]:
            merged[-1]["end_index"] = max(merged[-1]["end_index"], span["end_index"])
        else:
            merged.append(dict(span))
    return merged


def _first_user_text_index(messages: list[dict]) -> int:
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role == "user" and not _is_tool_result_message(msg):
            return i
    return -1


# ----------------------------------------------------------------------
# 结构重构（压缩后按任务读取优先级重排）
# ----------------------------------------------------------------------


def _is_tool_result_block(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == "tool_result"


def _alternation_ok(messages: list[dict]) -> bool:
    """role 交替校验：相邻非工具 user/assistant 文本消息 role 不得相同
    （Anthropic 交替规则；tool_result 跟随 tool_use 不受限）。"""
    prev: str | None = None
    for msg in messages:
        role = msg.get("role", "")
        if role in ("user", "assistant") and not _is_tool_result_message(msg):
            if role == prev:
                return False
            prev = role
    return True


def _pairs_intact(messages: list[dict]) -> bool:
    """工具配对校验：每个 tool_result 的 tool_use_id 在前一条消息的
    tool_use id 集合中存在（或没有 tool_result 块）。"""
    active_ids: set[str] = set()
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    active_ids.add(str(item.get("id", "")))
                elif item.get("type") == "tool_result":
                    tid = str(item.get("tool_use_id", ""))
                    if tid and tid not in active_ids:
                        return False
    return True


def restructure_by_priority(messages: list[dict], *, enabled: bool = True) -> list[dict]:
    """压缩后结构重构：按轮次优先级重排（P0 轮最前，同级别保持原序）。

    轮内不拆（保工具对）；重排结果必须通过 role 交替与工具配对校验，否则
    回退原序（防 provider 400）。system 轮恒在首位。
    """
    if not enabled or len(messages) <= 2:
        return list(messages)

    turns = segment_turns(messages)
    if len(turns) <= 2:
        return list(messages)

    ordered = sorted(turns, key=lambda t: (t.level, t.index))
    candidate = [m for t in ordered for m in t.msgs]

    if _alternation_ok(candidate) and _pairs_intact(candidate):
        return candidate
    logger.debug(
        "[PriorityRestructure] Reordered projection fails role/tool alternation; "
        "keeping original order"
    )
    return list(messages)


# ----------------------------------------------------------------------
# 合规校验（六重中的优先级部分）
# ----------------------------------------------------------------------


def verify_priority_integrity(before: list[dict], after: list[dict]) -> list[str]:
    """压缩前后优先级完整性校验，返回问题列表（空 = 通过）。

    覆盖设计文档六重校验中的：
    1. 安全合规：system 消息数量不减；
    2. 任务完整性（P0）：首条用户原始目标保留（或已由摘要/快照承接）；
    3. 优先级校验：P1 最终结论保留（末条 assistant 纯文本仍存在）；
    4. 任务快照（P2）：已有摘要/快照标记在压缩后仍有承接标记。

    预算/因果/摘要忠实度由 validate_projection、_sanitize_tool_pairs、
    validated_summary 分别承担（职责不重复）。
    """
    issues: list[str] = []

    # 1. system 保留
    before_sys = [m for m in before if m.get("role") == "system"]
    after_sys = [m for m in after if m.get("role") == "system"]
    if len(after_sys) < len(before_sys):
        issues.append(f"P0: system 消息被删除 ({len(before_sys)} -> {len(after_sys)})")

    # 2. 首条用户原始目标保留（或已由摘要/快照承接：压缩允许目标摘要化；
    #    承接标记包括边界摘要/上下文压缩 note/任务定向等快照类消息 ——
    #    摘要语义忠实度由 validated_summary 与 fallback 原文保留负责，此处
    #    只防"无任何承接的意外删除"）。
    first_user_text: dict | None = None
    for msg in before:
        if msg.get("role") == "user" and not _is_tool_result_message(msg):
            first_user_text = msg
            break
    if first_user_text is not None:
        target_text = _msg_text(first_user_text).strip()[:120]
        after_has_target = any(
            _msg_text(m).strip().startswith(target_text[:60])
            or target_text[:60] in _msg_text(m)
            for m in after
        )
        after_has_summary_carrier = any(
            m.get("_compaction_summary")
            or m.get("_model_source", "") in ("compaction_summary", "task_orientation", "runtime_context")
            or any(mk in _msg_text(m) for mk in ("[上下文压缩", "[上下文边界]", "[context_note", "[context_epoch_update]"))
            for m in after
        )
        if not after_has_target and not after_has_summary_carrier:
            issues.append("P0: 首条用户目标未保留（或未由摘要承接）")

    # 3. P1 最终结论保留
    before_last_assistant_text = None
    for msg in reversed(before):
        if msg.get("role") == "assistant" and not _contains_tool_use(msg) and _msg_text(msg).strip():
            before_last_assistant_text = msg
            break
    if before_last_assistant_text is not None:
        after_last_assistant_text = None
        for msg in reversed(after):
            if msg.get("role") == "assistant" and not _contains_tool_use(msg) and _msg_text(msg).strip():
                after_last_assistant_text = msg
                break
        if after_last_assistant_text is None:
            issues.append("P1: 最终结论（末条 assistant 文本）缺失")

    # 4. P2 快照/摘要承接
    before_has_summary_marker = any(
        m.get("_compaction_summary") or (m.get("_model_source", "") == "compaction_summary")
        for m in before
    )
    after_has_summary_marker = any(
        m.get("_compaction_summary") or (m.get("_model_source", "") == "compaction_summary")
        or _msg_text(m).startswith("[上下文压缩")
        for m in after
    )
    if before_has_summary_marker and not after_has_summary_marker:
        issues.append("P2: 压缩快照/摘要标记丢失（压缩上下文断裂）")

    return issues
