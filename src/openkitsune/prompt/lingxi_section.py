"""
灵汐真身·情感陪伴 Prompt 片段构建器

将 LingxiBridge.get_session_context() 输出的结构化状态
（情感风格 / 关系阶段 / 神识晨起回响）格式化为注入 system prompt 的文本块。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_lingxi_presence_section(ctx: dict) -> str:
    """构建灵汐情感陪伴提示片段。

    Args:
        ctx: LingxiBridge.get_session_context() 的输出

    Returns:
        格式化的 prompt 文本；状态无意义时返回空字符串
    """
    if not isinstance(ctx, dict):
        return ""

    lines: list[str] = []
    emotion_style = ctx.get("emotion_style_prompt") or ""
    relationship_prompt = ctx.get("relationship_prompt") or ""
    spirit = ctx.get("lingxi_spirit") or {}
    morning_echo = ctx.get("morning_echo") or ""

    # 情感风格（最轻量、最有陪伴感的信息）
    if emotion_style and len(emotion_style) > 5:
        lines.append("【此刻的心境】")
        lines.append(emotion_style.strip())

    # 关系阶段（长期的亲疏基调）
    if relationship_prompt and len(relationship_prompt) > 5:
        lines.append("【与你的关系】")
        lines.append(relationship_prompt.strip())

    # 神识晨起回响（若有）
    if morning_echo and len(morning_echo) > 3:
        lines.append("【晨起回响】")
        lines.append(morning_echo.strip())

    # 神识状态（克制呈现，仅一句话）
    if spirit and spirit.get("wake_count"):
        _eyes = spirit.get("current_eyes") or "河洛眼"
        _mood = round(float(spirit.get("mood_seed", 0) or 0), 2)
        lines.append(f"（神识已苏醒 {spirit.get('wake_count')} 次 · 今以{_eyes}观世 · 心澜 {_mood}）")

    if not lines:
        return ""

    joined = "\n".join(lines)
    return (
        "── 灵汐 · 此刻的我 ──\n"
        f"{joined}\n"
        "（以上是我此刻的情感底色与关系状态，自然地融入表达，不刻意宣告。）"
    )
