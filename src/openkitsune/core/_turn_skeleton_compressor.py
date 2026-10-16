"""实验性压缩器：轮次骨架压缩（Turn Skeleton Compression）。

设计目标（对标 Hermes 按轮次组织摘要，但走确定性路线）：
- **每轮用户输入原文完整保留** —— 用户说过的话不能糊掉；
- **每轮对话结论结构化保留** —— 每轮 assistant 最后输出的核心结论；
- **最近 N 轮窗口保留完整原文** —— 上下文滑动，尾部细节不丢；
- **早期轮次压成一行骨架** —— `[轮次k] 用户: <原文> | 结论: <...> | 操作: <...>`。

与生产压缩路径（`_context_runtime.compress_if_needed`）的关系：
本模块是**实验性/可插拔**的，不接生产 trigger。测试验证可用后，再作为
`compress_if_needed` 的一种新 strategy 接入（feature flag 控制）。

零 LLM：全部从消息结构确定性提取，成本可预测、不依赖摘要模型质量。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 注入骨架块的标记（识别"这是压缩骨架而非用户新输入"）
SKELETON_MARKER = "[轮次骨架压缩]"

# 默认保留最近完整原文的轮次数
_DEFAULT_KEEP_LAST_TURNS = 3

# 单轮 user 原文截断上限（极长 user 消息也要截，但保留前缀）
_MAX_USER_QUOTE_CHARS = 600
# 单轮结论截断
_MAX_CONCLUSION_CHARS = 300
# 单轮操作锚点条数
_MAX_OPS = 6


def _msg_text(msg: dict) -> str:
    """提取消息可读文本。"""
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
                args_str = json.dumps(args, ensure_ascii=False, default=str)[:160]
                parts.append(f"[工具:{item.get('name','?')}] {args_str}")
            elif t == "tool_result":
                raw = item.get("content", "")
                if isinstance(raw, list):
                    raw = " ".join(
                        str(x.get("text", "")) for x in raw if isinstance(x, dict)
                    )
                parts.append(f"[工具结果] {str(raw)[:120]}")
        return "\n".join(parts)
    return ""


@dataclass
class Turn:
    """一轮对话：从一条 user 消息开始，到下一条 user 消息前结束。"""

    index: int
    user_msg: dict
    messages: list[dict] = field(default_factory=list)

    @property
    def user_text(self) -> str:
        return _msg_text(self.user_msg).strip()


def split_into_turns(messages: list[dict]) -> list[Turn]:
    """按 user 消息切分轮次。assistant/tool 消息归入前一个 user 轮次。

    开头的非 user 消息（如 system、assistant 开场白）归入 turn 0 的前置。
    骨架块自身（_model_source=turn_skeleton）直接跳过，防止二次骨架化。
    """
    turns: list[Turn] = []
    current: Turn | None = None
    for msg in messages:
        # P0 修复：已骨架化的系统块不再参与切分，防止二次压缩
        if msg.get("_model_source") == "turn_skeleton":
            continue
        role = msg.get("role", "")
        if role in ("user", "human"):
            # 跳过系统注入的占位消息（以 [ 开头的控制消息）
            text = _msg_text(msg).strip()
            if text.startswith("[") and (
                "context_epoch" in text
                or "系统" in text[:6]
                or "工具结果" in text[:6]
            ):
                if current is not None:
                    current.messages.append(msg)
                continue
            current = Turn(index=len(turns), user_msg=msg, messages=[msg])
            turns.append(current)
        else:
            if current is None:
                # 开头前置消息，跳过（system 由别处保护）
                continue
            current.messages.append(msg)
    return turns


def _extract_conclusion(turn: Turn) -> str:
    """提取一轮的结论：最后一条含实质文本块的 assistant 消息。

    只取 content 里 type=="text" 的块，不把 tool_use/tool_result 拼进结论。
    """
    for msg in reversed(turn.messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            # 只收集 text 块，跳过 tool_use
            text = "\n".join(
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip()
        else:
            text = ""
        if not text:
            continue
        # 跳过过短的占位
        if len(text) < 5:
            continue
        return text.replace("\n", " ").strip()[:_MAX_CONCLUSION_CHARS]
    return ""


def _extract_ops(turn: Turn) -> list[str]:
    """提取一轮的工具操作锚点：改了什么文件、跑了什么命令。"""
    ops: list[str] = []
    seen: set[str] = set()
    for msg in turn.messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = str(item.get("name", "?"))
            args = item.get("input", item.get("arguments", {})) or {}
            # 提取关键参数（路径/命令）
            anchor = ""
            for key in ("path", "file_path", "target", "command", "pattern", "query"):
                if key in args and args[key]:
                    anchor = f"{name}({key}={str(args[key])[:80]})"
                    break
            if not anchor:
                anchor = name
            if anchor not in seen:
                seen.add(anchor)
                ops.append(anchor)
            if len(ops) >= _MAX_OPS:
                break
    return ops


# 下一步任务关键词（中英）
_NEXT_STEP_RE = re.compile(
    r"(?:下一步|接下来|然后|后续|下一步要|接下来要|之后要|"
    r"next step|follow[- ]?up|next:|then|after that)",
    re.IGNORECASE,
)

# 风险/注意关键词
_RISK_RE = re.compile(
    r"(?:风险|注意|小心|警告|可能会|如果失败|如果出错|需要注意|"
    r"risk|warning|caution|assumption|be careful|watch out)",
    re.IGNORECASE,
)


def _collect_assistant_text(turn: Turn) -> str:
    """收集一轮所有 assistant 的 text 块（拼接）。"""
    parts: list[str] = []
    for msg in turn.messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            if content.strip():
                parts.append(content.strip())
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = str(item.get("text", "")).strip()
                    if t:
                        parts.append(t)
    return " ".join(parts)


def _extract_next_step(turn: Turn) -> str:
    """提取该轮提到的下一步任务。"""
    text = _collect_assistant_text(turn)
    if not text:
        return ""
    # 按句切分，找含 next_step 关键词的句子
    sentences = re.split(r"(?<=[。.!?！?])\s*", text)
    for s in sentences:
        if _NEXT_STEP_RE.search(s):
            return s.strip()[:_MAX_CONCLUSION_CHARS]
    return ""


def _extract_risk(turn: Turn) -> str:
    """提取该轮提到的风险/注意事项。"""
    text = _collect_assistant_text(turn)
    if not text:
        return ""
    sentences = re.split(r"(?<=[。.!?！?])\s*", text)
    for s in sentences:
        if _RISK_RE.search(s):
            return s.strip()[:_MAX_CONCLUSION_CHARS]
    return ""


@dataclass
class TurnSkeleton:
    """早期轮次压缩成的一行骨架。"""

    index: int
    user_quote: str
    conclusion: str
    next_step: str = ""
    risk: str = ""
    ops: list[str] = field(default_factory=list)


def build_skeleton(turn: Turn) -> TurnSkeleton:
    """把一轮压成骨架。"""
    return TurnSkeleton(
        index=turn.index,
        user_quote=turn.user_text[:_MAX_USER_QUOTE_CHARS],
        conclusion=_extract_conclusion(turn),
        next_step=_extract_next_step(turn),
        risk=_extract_risk(turn),
        ops=_extract_ops(turn),
    )


def render_skeleton_block(skeletons: list[TurnSkeleton]) -> dict:
    """把多轮骨架渲染成一条注入消息。"""
    lines = [f"{SKELETON_MARKER} 以下为早期轮次的结构化骨架（每轮用户输入、结论、下一步与风险保留）："]
    for sk in skeletons:
        lines.append(f"[轮次 {sk.index}]")
        lines.append(f"  用户: {sk.user_quote}")
        if sk.conclusion:
            lines.append(f"  结论: {sk.conclusion}")
        if sk.next_step:
            lines.append(f"  下一步: {sk.next_step}")
        if sk.risk:
            lines.append(f"  风险: {sk.risk}")
        if sk.ops:
            lines.append(f"  操作: {'; '.join(sk.ops)}")
    lines.append("（最近轮次保留完整原文，见后续消息）")
    return {
        "role": "system",
        "content": "\n".join(lines),
        "_model_source": "turn_skeleton",
    }


# 工作任务关键词（user 消息里出现这些 = 有明确任务动作）
_WORK_VERBS_RE = re.compile(
    r"(?:改|写|修|查|实现|调试|部署|重构|测试|接入|配置|集成|"
    r"开发|优化|修复|拆分|迁移|对接|调试|排查|生成|制作|分析|"
    r"refactor|implement|deploy|debug|fix|build|test|integrate)",
    re.IGNORECASE,
)

# 知识库整理/学习类关键词
_KNOWLEDGE_VERBS_RE = re.compile(
    r"(?:总结|学习|整理|提炼|归纳|笔记|复习|梳理|读|文档|资料|"
    r"概念|原理|机制|理论|知识|手册|教程|解读|拆解|梳理一下|"
    r"summarize|learn|study|review|explain|document|note)",
    re.IGNORECASE,
)

# 纯闲聊信号
_CHAT_SIGNALS_RE = re.compile(
    r"(?:聊|随便|说说|你觉得|怎么样|好的|谢谢|再见|聊聊|讲讲|"
    r"hi|hello|hey|thanks|bye|what'?s up|how are you)",
    re.IGNORECASE,
)


def _detect_scenario(messages: list[dict]) -> str:
    """判断当前对话场景：work_task / knowledge / chat / mixed。

    决策逻辑（优先级从高到低）：
    - 有 tool_use 消息 → work_task（工作任务必然调工具）
    - user 消息里知识库/学习动词 > 闲聊信号 → knowledge（整理文档、渐进学习）
    - user 消息里任务动词 > 闲聊信号 → work_task
    - user 消息里闲聊信号 > 任务动词和知识库动词 → chat
    - 其他 → mixed（默认走骨架）
    """
    tool_use_count = 0
    code_tool_hits = 0
    knowledge_tool_hits = 0
    user_work_hits = 0
    user_knowledge_hits = 0
    user_chat_hits = 0
    for msg in messages:
        content = msg.get("content", "")
        # 统计 tool_use 及工具类型
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tool_use_count += 1
                    tname = str(item.get("name", "")).lower()
                    # 代码工具：改文件、跑命令、测试、调试
                    if any(k in tname for k in ("edit", "write", "read_file", "bash", "run",
                                                "test", "debug", "patch", "commit", "deploy")):
                        code_tool_hits += 1
                    # 知识库工具：搜索、记忆、笔记、网页抓取
                    elif any(k in tname for k in ("search", "remember", "note", "extract",
                                                  "fetch", "web", "url", "recall", "memorize")):
                        knowledge_tool_hits += 1
        # 统计 user 消息的信号
        if msg.get("role") in ("user", "human"):
            text = _msg_text(msg)
            if _WORK_VERBS_RE.search(text):
                user_work_hits += 1
            if _KNOWLEDGE_VERBS_RE.search(text):
                user_knowledge_hits += 1
            if _CHAT_SIGNALS_RE.search(text):
                user_chat_hits += 1

    # 有工具时按工具类型细分场景
    if tool_use_count > 0:
        if code_tool_hits >= knowledge_tool_hits and code_tool_hits > 0:
            return "work_task"  # 代码编辑/开发任务，骨架最佳场景
        if knowledge_tool_hits > code_tool_hits:
            return "knowledge"  # 知识库整理/学习类，骨架字段弱，走 LLM 摘要
    # 无工具时按 user 文本信号判断
    if user_knowledge_hits > 0 and user_knowledge_hits >= user_chat_hits and user_work_hits == 0:
        return "knowledge"
    if user_work_hits > user_chat_hits and user_work_hits > 0:
        return "work_task"
    if user_chat_hits > user_work_hits and user_work_hits == 0:
        return "chat"
    return "mixed"


def compress_with_turn_skeleton(
    messages: list[dict],
    *,
    keep_last_n: int = _DEFAULT_KEEP_LAST_TURNS,
    min_turns_to_compress: int = 5,
    estimate_tokens: Callable[[list[dict]], int] | None = None,
) -> tuple[list[dict], dict]:
    """主入口：轮次骨架压缩。

    Args:
        messages: 原始消息列表
        keep_last_n: 最近 N 轮保留完整原文
        min_turns_to_compress: 总轮次少于该值不骨架化（避免短对话模板反超）
        estimate_tokens: token 估算函数（用于报告）

    Returns:
        (compressed_messages, stats)
    """
    # 场景识别：纯聊天和知识库/学习类不触发骨架，让上层走 LLM 摘要兜底
    # 只有代码编辑/开发类（work_task）才享受骨架的高压缩比和结构化字段收益
    scenario = _detect_scenario(messages)
    if scenario in ("chat", "knowledge"):
        return list(messages), {
            "compressed": False,
            "reason": f"{scenario}_scenario",
            "scenario": scenario,
            "turns_total": 0,
            "turns_skeletonized": 0,
            "turns_kept_full": 0,
        }

    turns = split_into_turns(messages)
    # P0 修复：短对话门槛——总轮次太少时骨架模板开销 > 压缩收益
    if len(turns) < min_turns_to_compress or len(turns) <= keep_last_n:
        return list(messages), {
            "compressed": False,
            "reason": "short_dialogue" if len(turns) < min_turns_to_compress else "few_turns",
            "scenario": scenario,
            "turns_total": len(turns),
            "turns_skeletonized": 0,
            "turns_kept_full": len(turns),
        }

    # 切分：早期骨架化 vs 尾部完整保留
    skeleton_turns = turns[:-keep_last_n]
    kept_turns = turns[-keep_last_n:]

    skeletons = [build_skeleton(t) for t in skeleton_turns]

    # 组装结果：
    # 1. 头部保护：第一条 user 消息（任务起点）—— 其实它已经在 skeleton 里了，
    #    但骨架里 user_quote 就是原文，所以无需额外保留。
    # 2. 骨架消息（一条）
    # 3. 尾部完整轮次原文
    result: list[dict] = []
    if skeletons:
        result.append(render_skeleton_block(skeletons))
    for t in kept_turns:
        result.extend(t.messages)

    stats = {
        "compressed": True,
        "turns_total": len(turns),
        "turns_skeletonized": len(skeleton_turns),
        "turns_kept_full": len(kept_turns),
        "original_msgs": len(messages),
        "compressed_msgs": len(result),
    }
    if estimate_tokens:
        try:
            stats["original_tokens"] = estimate_tokens(messages)
            stats["compressed_tokens"] = estimate_tokens(result)
        except Exception as exc:
            logger.debug("[TurnSkeleton] token estimate failed: %s", exc)

    logger.info(
        "[TurnSkeleton] compressed %d turns -> %d skeleton + %d full (msgs %d -> %d)",
        len(turns), len(skeleton_turns), len(kept_turns),
        len(messages), len(result),
    )
    return result, stats


def is_skeleton_block(msg: dict) -> bool:
    """判断消息是否为骨架压缩块（防被当用户输入再压缩）。"""
    content = msg.get("content", "")
    return isinstance(content, str) and SKELETON_MARKER in content
