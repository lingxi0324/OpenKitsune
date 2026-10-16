"""上下文水位交接快照（Handoff Snapshot）—— 90% 主动收尾 + 一次性短期交接。

设计动机（2026-10-16 对标 Hermes lineage 后整改）：
现有压缩链是「同会话 LLM 摘要续命」：85% 触发摘要压缩、98% 才硬停，中间
13% 区间反复摘要，信息逐层糊化，长任务后期模型对任务状态的感知持续退化；
跨会话恢复又只能靠用户主动说「继续」且只恢复任务定义文本。

本模块换一条路：**水位到 handoff_ratio（默认 0.90）时不再硬撑压缩，而是
主动结束本轮，把当前任务状态固化为一份结构化交接快照写入文件系统；新会话
启动时自动加载该快照注入 system prompt，并立即删除文件（一次性消费）。**

与既有机制的边界：
- 不进 memoryd / memory_manager.store / episode 库 —— 这是**短期交接令牌**，
  TTL（默认 7 天）后自动清理，不是长期记忆。
- 与 `_context_preparation.py`（KV 清理/停服前备份，保留最近 N 个、同会话内
  注入）不同：本模块是**跨会话一次性交接**，读一次即删。
- 与 `task_continuation.py`（用户主动说「继续」才恢复任务定义文本）不同：
  本模块在新会话启动时**自动检测并加载**，不需要用户显式指令。

文件布局：``<data_dir>/<context_handoff_dir>/handoff_<session>_<ts>.json``
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

# 注入块标记（system prompt 里识别这是交接恢复块而非用户输入）
HANDOFF_MARKER = "[任务交接恢复]"

# 默认 TTL：7 天（短期交接，不是长期记忆）
_DEFAULT_TTL_HOURS = 168.0

# 提取上限
_MAX_GOAL_CHARS = 400
_MAX_COMPLETED_CHARS = 1200
_MAX_NOTES_CHARS = 800
_MAX_TAIL_CHARS = 1500
_MAX_PATHS = 20


def _msg_text(msg: dict) -> str:
    """提取消息可读文本（str content 或 list 块）。"""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "text":
                parts.append(str(item.get("text", "")))
            elif t == "tool_use":
                args = item.get("input", item.get("arguments", {})) or {}
                parts.append(
                    f"[工具:{item.get('name', '?')}] "
                    + json.dumps(args, ensure_ascii=False, default=str)[:200]
                )
            elif t == "tool_result":
                raw = item.get("content", "")
                if isinstance(raw, list):
                    raw = " ".join(
                        str(x.get("text", "")) for x in raw if isinstance(x, dict)
                    )
                parts.append(f"[工具结果] {str(raw)[:160]}")
        return "\n".join(parts)
    return ""


def _extract_goal(messages: list[dict]) -> str:
    """从首条真实 user 消息提取任务目标。"""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = _msg_text(msg).strip()
        if not text:
            continue
        # 跳过系统注入的占位消息
        if text.startswith("[") and (
            "工具" in text[:6] or "context_epoch" in text or "系统" in text[:6]
        ):
            continue
        return text.replace("\n", " ").strip()[:_MAX_GOAL_CHARS]
    return ""


_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/])"
    r"(?:[^\s\"'，。；、）)>\]]+[\\/])+"
    r"[^\s\"'，。；、）)>\]]{1,200}"
)


def _extract_paths(messages: Iterable[dict], extra: list[str] | None = None) -> list[str]:
    """从消息文本里提取出现过的文件/目录绝对路径（关键路径锚点）。"""
    found: list[str] = []
    seen: set[str] = set()

    def _push(p: str) -> None:
        p = p.strip().rstrip(".,;，。；")
        if len(p) < 4 or p in seen:
            return
        # 过滤明显的噪音路径
        if p.endswith((".pyc", ".log", ".tmp")):
            return
        seen.add(p)
        found.append(p)

    for m in messages:
        text = _msg_text(m)
        for match in _PATH_RE.findall(text):
            _push(match)
    for e in extra or []:
        if e:
            _push(str(e))
    return found[:_MAX_PATHS]


def _extract_tail_summary(
    messages: list[dict],
    estimate_tokens: Callable[[list[dict]], int],
    *,
    tail_fraction: float = 0.15,
    min_msgs:  int = 4,
) -> str:
    """尾部进程摘要：最近 tail_fraction tokens 的可读轨迹。"""
    n = len(messages)
    if n == 0:
        return ""
    total = estimate_tokens(messages)
    tail_budget = max(1, int(total * tail_fraction))
    acc = 0
    start = n
    for i in range(n - 1, -1, -1):
        acc += estimate_tokens([messages[i]])
        if acc >= tail_budget:
            start = i
            break
    start = max(0, min(start, max(0, n - min_msgs)))
    lines: list[str] = []
    for msg in messages[start:]:
        text = _msg_text(msg).replace("\n", " ").strip()
        if not text:
            continue
        role = msg.get("role", "?")
        lines.append(f"{role}: {text[:180]}")
    return "\n".join(lines)[:_MAX_TAIL_CHARS]


@dataclass
class HandoffSnapshot:
    """一次性交接快照。"""

    task_goal: str
    completed_summary: str = ""
    next_steps: list[str] = field(default_factory=list)
    key_paths: list[str] = field(default_factory=list)
    short_notes: str = ""
    recent_tail: str = ""
    session_id: str = ""
    handoff_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    trigger_ratio: float = 0.0
    tokens_at_handoff: int = 0

    def to_dict(self) -> dict:
        return {
            "handoff_id": self.handoff_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "trigger_ratio": self.trigger_ratio,
            "tokens_at_handoff": self.tokens_at_handoff,
            "task_goal": self.task_goal,
            "completed_summary": self.completed_summary,
            "next_steps": list(self.next_steps),
            "key_paths": list(self.key_paths),
            "short_notes": self.short_notes,
            "recent_tail": self.recent_tail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HandoffSnapshot":
        return cls(
            task_goal=str(data.get("task_goal", "")),
            completed_summary=str(data.get("completed_summary", "")),
            next_steps=[str(x) for x in (data.get("next_steps") or [])],
            key_paths=[str(x) for x in (data.get("key_paths") or [])],
            short_notes=str(data.get("short_notes", "")),
            recent_tail=str(data.get("recent_tail", "")),
            session_id=str(data.get("session_id", "")),
            handoff_id=str(data.get("handoff_id", uuid.uuid4().hex[:12])),
            created_at=str(data.get("created_at", "")),
            trigger_ratio=float(data.get("trigger_ratio", 0.0) or 0.0),
            tokens_at_handoff=int(data.get("tokens_at_handoff", 0) or 0),
        )


def _handoff_dir(data_dir: str, handoff_dir: str) -> Path:
    base = Path(data_dir) / handoff_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


def prune_expired(
    data_dir: str,
    handoff_dir: str,
    *,
    ttl_hours: float = _DEFAULT_TTL_HOURS,
) -> int:
    """清理过期交接文件（启动/写入/消费时顺手调用）。返回删除数量。"""
    try:
        base = _handoff_dir(data_dir, handoff_dir)
    except Exception as exc:
        logger.debug("[Handoff] dir init failed: %s", exc)
        return 0
    cutoff = time.time() - ttl_hours * 3600.0
    removed = 0
    for f in base.glob("handoff_*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        except Exception as exc:
            logger.debug("[Handoff] prune %s failed: %s", f.name, exc)
    if removed:
        logger.info("[Handoff] pruned %d expired handoff file(s)", removed)
    return removed


def emit_handoff(
    messages: list[dict],
    *,
    data_dir: str,
    handoff_dir: str = "data/handoff",
    session_id: str = "",
    task_goal: str = "",
    completed_summary: str = "",
    next_steps: list[str] | None = None,
    short_notes: str = "",
    extra_paths: list[str] | None = None,
    trigger_ratio: float = 0.0,
    tokens_at_handoff: int = 0,
    estimate_tokens: Callable[[list[dict]], int] | None = None,
    ttl_hours: float = _DEFAULT_TTL_HOURS,
) -> HandoffSnapshot | None:
    """生成并写入一份交接快照。返回写入的快照；失败返回 None。

    纯确定性提取（零 LLM），与 `_context_preparation.prepare_task_context`
    同风格，但结构面向「跨会话一次性交接」。
    """
    # 顺手清理过期文件
    try:
        prune_expired(data_dir, handoff_dir, ttl_hours=ttl_hours)
    except Exception:
        pass

    if estimate_tokens is None:
        estimate_tokens = lambda msgs: sum(len(_msg_text(m)) // 2 for m in msgs)  # noqa: E731

    goal = (task_goal or "").strip() or _extract_goal(messages)
    tail = _extract_tail_summary(messages, estimate_tokens)
    paths = _extract_paths(messages, extra_paths)

    snap = HandoffSnapshot(
        task_goal=goal[:_MAX_GOAL_CHARS],
        completed_summary=completed_summary[:_MAX_COMPLETED_CHARS],
        next_steps=list(next_steps or []),
        key_paths=paths,
        short_notes=short_notes[:_MAX_NOTES_CHARS],
        recent_tail=tail,
        session_id=session_id,
        trigger_ratio=float(trigger_ratio),
        tokens_at_handoff=int(tokens_at_handoff),
    )

    try:
        base = _handoff_dir(data_dir, handoff_dir)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"handoff_{session_id or 'anon'}_{ts}_{snap.handoff_id}.json"
        path = base / fname
        path.write_text(
            json.dumps(snap.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "[Handoff] emitted handoff_id=%s session=%s goal_chars=%d paths=%d",
            snap.handoff_id, session_id, len(snap.task_goal), len(snap.key_paths),
        )
        return snap
    except Exception as exc:
        logger.warning("[Handoff] emit failed: %s", exc)
        return None


def consume_pending_handoff(
    data_dir: str,
    handoff_dir: str = "data/handoff",
    *,
    ttl_hours: float = _DEFAULT_TTL_HOURS,
) -> HandoffSnapshot | None:
    """新会话启动时调用：取最新一份待消费交接，读取后**立即删除文件**。

    一次性消费语义：不管注入是否成功，文件都已删除，避免下一轮重复加载。
    无待消费交接时返回 None。
    """
    try:
        base = _handoff_dir(data_dir, handoff_dir)
    except Exception as exc:
        logger.debug("[Handoff] dir init failed: %s", exc)
        return None

    # 顺手清理过期
    prune_expired(data_dir, handoff_dir, ttl_hours=ttl_hours)

    files = sorted(
        base.glob("handoff_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None

    path = files[0]
    snap: HandoffSnapshot | None = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        snap = HandoffSnapshot.from_dict(data)
    except Exception as exc:
        logger.warning("[Handoff] read %s failed: %s", path.name, exc)
    finally:
        # 一次性消费：无论读取成败都删除，避免脏文件反复被选中
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("[Handoff] unlink %s failed: %s", path.name, exc)

    if snap is None:
        return None
    logger.info(
        "[Handoff] consumed handoff_id=%s session=%s created=%s",
        snap.handoff_id, snap.session_id, snap.created_at,
    )
    return snap


def render_handoff_block(snap: HandoffSnapshot) -> str:
    """把交接快照渲染成注入 system prompt 的文本块。"""
    lines = [
        f"{HANDOFF_MARKER} 检测到上次任务在上下文水位过高时主动收尾，以下是交接快照：",
        f"- 任务目标：{snap.task_goal or '（未识别）'}",
    ]
    if snap.completed_summary:
        lines.append(f"- 已完成/进展：\n{snap.completed_summary}")
    if snap.next_steps:
        lines.append("- 下一步计划：")
        for i, step in enumerate(snap.next_steps, 1):
            lines.append(f"  {i}. {step}")
    if snap.key_paths:
        lines.append("- 关键文件/路径：")
        for p in snap.key_paths[:10]:
            lines.append(f"  · {p}")
    if snap.short_notes:
        lines.append(f"- 短期笔记：\n{snap.short_notes}")
    if snap.recent_tail:
        lines.append(f"- 最近对话轨迹：\n{snap.recent_tail}")
    lines.append(
        f"（交接 ID：{snap.handoff_id}，生成时间：{snap.created_at}，"
        f"触发水位：{snap.trigger_ratio:.0%}）"
    )
    lines.append(
        "用户若说「继续」，请基于以上交接内容无缝接续，不要重复已完成步骤，"
        "不要重新询问任务目标。"
    )
    return "\n".join(lines)
