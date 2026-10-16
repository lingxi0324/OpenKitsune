"""
继续类指令检测与跨轮任务上下文恢复（R4 / R1 / R2 修复）。

问题现场（2026-10-12 实测）：用户在新会话里说"继续 / continue / 继续之前的
工作"，模型把该指令当作孤立请求，看不到跨轮任务定义（active_task_definition
未持久化或未注入），于是断言"这是一个新的会话"——表现为"失忆"。

本模块提供：
1. ``is_continuation_directive`` —— 规则识别继续类指令（中英文、严格/宽松）。
2. ``task_definition_is_hollow`` —— 判断当前轮 task_definition 是否"空洞"
   （只是指令本身、无实际任务内容）。带具体内容的继续指令（如"继续做
   Watermark 集成"）不算空洞，不会被历史任务定义覆盖。
3. ``restore_task_definition`` —— 按优先级恢复任务定义：
   ① session.metadata["active_task_definition"]（跨轮持久化，V1 已写入）
   ② 会话历史中的任务锚点消息（metadata.task_anchor 标记或首条长 user 消息）
   ③ memory store 最近 episode（与 list_recent_tasks 同源）
   恢复成功后回写 metadata（结构化），使后续轮次同样可见。
4. ``build_continuation_guidance`` —— 构造注入 prompt 的方向提示（成功恢复
   / 恢复失败引导检索，避免模型仅凭"这是新会话"下结论）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 任务锚点 metadata 标记 key（去重保护 / 恢复共用）
TASK_ANCHOR_META_KEY = "task_anchor"

# 任务锚点最小长度：比这更长的首条 user 消息视为任务定义
_ANCHOR_MIN_CHARS = 120

# 恢复定义的最大长度（与 TaskDefinition 注入量级一致）
_MAX_DEF_CHARS = 2000

# ── 严格匹配：整条消息就是继续指令（可带标点/语气词） ──
_CONTINUE_STRICT_RE = re.compile(
    r"^\s*(?:"
    r"continue|go\s*on|proceed|keep\s*(?:going|working|it\s*up)|resume|"
    r"继续|继续吧|接着|接着做|接着干|继续做|继续干|继续执行|继续推进|继续之前|继续上次|"
    r"之前的工作|之前的任务|上次的任务|上次做到哪|上次做到|上次我们|上次说到|"
    r"立即开始|马上开始|现在开始|开始吧|干起来|接着来"
    r")\s*[。.!！?？~～,，]*\s*$",
    re.IGNORECASE,
)

# ── 宽松匹配：包含继续语义词，且不含新任务内容词 ──
_CONTINUE_LOOSE_RE = re.compile(
    r"(?:继续|接着|接着做|继续做|继续执行|继续推进|continue|resume|"
    r"go\s*on|keep\s*going|上次|之前的工作|之前的任务|上一步)",
    re.IGNORECASE,
)

# 新任务内容词：命中则视为新指令而非"纯继续"
_NEW_TASK_VERBS = re.compile(
    r"(?:帮我写|帮我查|帮我创建|帮我分析|帮我生成|帮我做|帮我改|帮我修|"
    r"写一个|查一下|分析一下|生成一个|创建|新建|写代码|翻译一下|总结一下|"
    r"读一下|看一下|检查一下|排查一下|安装|下载|打开|搜索|找一下)",
)


def is_continuation_directive(message: str) -> bool:
    """判断用户消息是否为"继续类"指令（不含新任务内容）。"""
    stripped = (message or "").strip()
    if not stripped:
        return False
    if _CONTINUE_STRICT_RE.match(stripped):
        return True
    if _CONTINUE_LOOSE_RE.search(stripped) and not _NEW_TASK_VERBS.search(stripped):
        return True
    return False


def task_definition_is_hollow(task_def: str, message: str) -> bool:
    """判断当前轮 task_definition 是否"空洞"（无实际任务内容，可被覆盖）。

    规则：空定义 → 空洞；短定义（≤40 字符）→ 去掉消息中的继续语义词后，
    剩余内容为空（只有标点/语气词）→ 空洞（允许用历史任务定义覆盖）；
    剩余还有具体任务内容（如"Watermark 集成"）→ 不空洞，保留当前定义，
    避免历史任务覆盖用户明确指定的新内容。
    """
    stripped = (message or "").strip()
    if not task_def:
        return True
    if len(task_def) > 40:
        return False
    residue = _CONTINUE_LOOSE_RE.sub("", stripped)
    if residue and _CONTINUE_STRICT_RE.match(stripped):
        # 宽松词未覆盖的纯继续指令（如"立即开始/马上开始/开始吧"）→ 空洞
        residue = ""
    residue = residue.strip(" \t。.!！?？~～,，的了吧吗呢")
    return not residue


def _coerce_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts: list[str] = []
        for p in v:
            if isinstance(p, dict):
                parts.append(str(p.get("text", p.get("content", "")) or ""))
            else:
                parts.append(str(p))
        return "".join(parts)
    return str(v)


def _extract_anchor_from_messages(messages: list[dict]) -> tuple[str | None, dict | None]:
    """从会话消息中找任务锚点。

    优先 ``metadata.task_anchor`` 标记的消息；其次第一条长度 >= 阈值的
    user 消息（任务定义消息通常很长）。返回 (text, message)。
    """
    if not messages:
        return None, None
    for m in messages:
        meta = m.get("metadata") or {}
        if meta.get(TASK_ANCHOR_META_KEY):
            text = _coerce_text(m.get("content", "")).strip()
            if text:
                return text[:_MAX_DEF_CHARS], m
    for m in messages:
        if m.get("role") in ("user", "human"):
            text = _coerce_text(m.get("content", "")).strip()
            if len(text) >= _ANCHOR_MIN_CHARS:
                return text[:_MAX_DEF_CHARS], m
    return None, None


async def restore_task_definition(
    session: Any,
    memory_manager: Any,
    *,
    conversation_id: str = "",
) -> tuple[str, str] | None:
    """按优先级恢复任务定义，返回 (source, definition)；无法恢复返回 None。

    source ∈ {"session_metadata", "history_anchor", "recent_episode"}。
    从历史锚点恢复成功后回写 session metadata（结构化，供后续轮次复用）。
    """
    # ① 跨轮持久化（V1 已写入 active_task_definition）
    if session is not None:
        try:
            cached = session.get_metadata("active_task_definition")
            cached = str(cached or "").strip()
            if cached:
                return ("session_metadata", cached[:_MAX_DEF_CHARS])
        except Exception as exc:
            logger.debug("[TaskContinuation] metadata read failed: %s", exc)

    # ② 会话历史任务锚点
    anchor_text: str | None = None
    if session is not None:
        try:
            messages = list(getattr(session.context, "messages", []) or [])
        except Exception:
            messages = []
        anchor_text, _anchor_msg = _extract_anchor_from_messages(messages)
        if anchor_text:
            # 结构化回写：让后续轮次经 metadata 直接恢复
            try:
                if not session.get_metadata("active_task_definition"):
                    session.set_metadata("active_task_definition", anchor_text[:_MAX_DEF_CHARS])
            except Exception as exc:
                logger.debug("[TaskContinuation] metadata persist failed: %s", exc)
            return ("history_anchor", anchor_text)

    # ③ 最近 episode（与 list_recent_tasks 同源）
    try:
        store = getattr(memory_manager, "store", None)
        loader = getattr(store, "get_recent_episodes", None)
        if callable(loader):
            owner_user_id = getattr(memory_manager, "_current_user_id", None)
            owner_workspace_id = getattr(memory_manager, "_current_workspace_id", None)
            episodes = loader(
                days=3,
                limit=1,
                user_id=owner_user_id,
                workspace_id=owner_workspace_id,
            )
            for ep in episodes or []:
                goal = getattr(ep, "goal", "") or ""
                outcome = getattr(ep, "outcome", "") or "completed"
                if goal:
                    summary = getattr(ep, "summary", "") or ""
                    text = f"最近任务：{goal}"
                    if summary:
                        text += f"\n任务摘要：{str(summary)[:300]}"
                    text += f"\n结果：{outcome}"
                    return ("recent_episode", text[:_MAX_DEF_CHARS])
    except Exception as exc:
        logger.debug("[TaskContinuation] recent episodes failed: %s", exc)

    return None


def build_continuation_guidance(restored: tuple[str, str] | None) -> str | None:
    """构造注入 prompt 的方向提示（成功恢复 / 恢复失败引导检索）。

    恢复失败时注入引导，让模型用 list_recent_tasks / search_conversation_traces
    查找最近任务或询问用户，而不是仅凭"这是新会话"下结论。
    """
    if restored is not None:
        source, definition = restored
        return (
            "\n\n## Developer: TaskContinuation\n"
            f"用户要求继续之前的工作。已从 {source} 恢复任务上下文：\n{definition}\n"
            "请基于该任务定义继续推进；不要重复已完成步骤，不要泛化收尾。"
        )
    return (
        "\n\n## Developer: TaskContinuation\n"
        "用户要求继续之前的工作，但当前会话未能自动恢复任务定义。"
        "请先调用 list_recent_tasks 或 search_conversation_traces 查找最近任务，"
        "必要时询问用户要继续的具体任务；不要仅凭'这是新会话'下结论。"
    )
