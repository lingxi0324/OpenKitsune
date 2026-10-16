"""上下文准备（Context Preparation）：KV 清理/停服前的任务快照与恢复注入。

对标豆包客户端的会话续传/防失忆逻辑 —— 清理前把当前任务的关键状态
固化为「任务快照」，恢复时作为「上下文准备块」注入，重建任务上下文，
避免 KV 清理（进程 stop 清掉注意力状态）或文本层压缩导致的"上下文失忆"。

关键认知（防止误伤）：
- KV Cache 只是注意力中间状态；token 层内容在 messages 里，重算即恢复。
- 真正的失忆源是**文本层压缩**（摘要化/删除）与**进程清理后无备份**。
- 本模块快照尾部 15% 上下文进程原文 + P0 目标 + 进行中状态，作为
  「以备不时之需」的恢复卡：停服/崩溃/切换模型后仍可重建任务上下文。

零 LLM：全部从消息与既有压缩统计确定性提取。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 注入块标记（识别"这是恢复卡而非用户输入"）
_RESTORE_MARKER = "[任务上下文恢复]"


def _msg_text(msg: dict) -> str:
    """提取消息可读文本（str content 或 list 块的 text/content/input）。"""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif item.get("type") == "tool_result":
                raw = item.get("content", "")
                if isinstance(raw, list):
                    raw = " ".join(
                        str(x.get("text", "")) for x in raw if isinstance(x, dict)
                    )
                parts.append(str(raw)[:200])
            elif item.get("type") == "tool_use":
                parts.append(
                    f"[工具:{item.get('name', '?')}] "
                    + json.dumps(item.get("input", {}), ensure_ascii=False, default=str)[:200]
                )
        return "\n".join(parts)
    return ""


def _tail_start_index(
    messages: list[dict],
    estimate_tokens: Callable[[list[dict]], int],
    *,
    tail_protect_fraction: float,
    recent_protect: int,
) -> int:
    """尾部进程起点：最近 tail_fraction% tokens（从末尾累计）与
    recent_protect 条取更保守者（与 _priority_compaction 同语义）。"""
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


@dataclass
class TaskContextSnapshot:
    """任务快照：KV 清理/停服前固化的任务恢复卡。"""

    task_goal: str
    progress_summary: str
    recent_process: list[dict] = field(default_factory=list)
    compacted_spans: list[dict] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    session_id: str = ""
    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "task_goal": self.task_goal,
            "progress_summary": self.progress_summary,
            "recent_process": self.recent_process,
            "compacted_spans": self.compacted_spans,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskContextSnapshot:
        return cls(
            task_goal=str(data.get("task_goal", "")),
            progress_summary=str(data.get("progress_summary", "")),
            recent_process=list(data.get("recent_process", []) or []),
            compacted_spans=list(data.get("compacted_spans", []) or []),
            tokens_before=int(data.get("tokens_before", 0) or 0),
            tokens_after=int(data.get("tokens_after", 0) or 0),
            created_at=str(data.get("created_at", "")),
            session_id=str(data.get("session_id", "")),
            snapshot_id=str(data.get("snapshot_id", uuid.uuid4().hex[:12])),
        )


def prepare_task_context(
    messages: list[dict],
    spans: list[dict],
    *,
    estimate_tokens: Callable[[list[dict]], int],
    tail_protect_fraction: float = 0.15,
    recent_protect: int = 3,
    max_goal_chars: int = 240,
    max_progress_chars: int = 700,
    session_id: str = "",
) -> TaskContextSnapshot:
    """从当前上下文生成任务快照（零 LLM，确定性提取）。

    - task_goal：首条 user 文本（P0 任务目标，截断）；
    - recent_process：尾部 15% 上下文进程原文备份（防失忆核心）；
    - progress_summary：尾部进程的可读文本摘要（角色 + 内容）；
    - compacted_spans：已压缩区间引用（恢复时可知哪些内容只剩摘要）。
    """
    goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            text = _msg_text(msg)
            if text and not text.startswith("[") or (text and "工具" not in text[:3]):
                goal = text.replace("\n", " ").strip()[:max_goal_chars]
                break
    start = _tail_start_index(
        messages, estimate_tokens,
        tail_protect_fraction=tail_protect_fraction, recent_protect=recent_protect,
    )
    tail = messages[start:] if start < len(messages) else list(messages)
    summary_parts: list[str] = []
    for msg in tail:
        text = _msg_text(msg).replace("\n", " ").strip()
        if text:
            role = msg.get("role", "?")
            if role == "user" and text.startswith("[工具结果"):
                summary_parts.append(f"工具结果: {text[:120]}")
            else:
                summary_parts.append(f"{role}: {text[:160]}")
    progress = "\n".join(summary_parts)[:max_progress_chars]
    total = estimate_tokens(messages)
    tail_tokens = estimate_tokens(tail)
    return TaskContextSnapshot(
        task_goal=goal,
        progress_summary=progress,
        recent_process=[dict(m) for m in tail],
        compacted_spans=list(spans or []),
        tokens_before=total,
        tokens_after=tail_tokens,
        session_id=session_id,
    )


def restore_task_context(snapshot: TaskContextSnapshot, *, max_recent_chars: int = 1200) -> dict:
    """把任务快照转成「上下文准备块」（注入消息）。

    恢复语义：目标 + 进行中 + 最近进程原文（尾部 15% 备份）作为恢复卡，
    使模型在 KV 已清空/进程已重启后仍能接续任务 —— 与豆包客户端
    「继续上次任务」等价，但快照来自清理前的确定性固化。
    """
    lines = [
        f"{_RESTORE_MARKER} 上次任务目标：{snapshot.task_goal or '（未识别）'}",
    ]
    if snapshot.progress_summary:
        lines.append(f"进行中/最近进程：\n{snapshot.progress_summary[:max_recent_chars]}")
    if snapshot.compacted_spans:
        n = sum(s.get("end_index", 0) - s.get("start_index", 0) for s in snapshot.compacted_spans)
        lines.append(f"（注：早期 {n} 条消息已被压缩为摘要，以下为恢复卡）")
    lines.append(f"（恢复卡时间：{snapshot.created_at}，ID：{snapshot.snapshot_id}）")
    return {
        "role": "system",
        "content": "\n".join(lines),
    }


def is_restore_block(msg: dict) -> bool:
    """判断消息是否为上下文准备块（防止恢复卡被误当用户输入压缩）。"""
    content = msg.get("content", "")
    return isinstance(content, str) and _RESTORE_MARKER in content
