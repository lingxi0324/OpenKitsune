"""
九尾内核 · 狐心裁决 Prompt 片段构建器

将 KitsuneHeartBridge.get_session_context() 输出的结构化心判
（模式 / 情绪 / 潜台词 / 风险 / 伦理 / 记忆 / 目标 / 工具 / 创意）
格式化为注入 system prompt 的紧凑文本块。

与 lingxi_section.py 的关系：lingxi 负责「此刻的情感底色」，
本模块负责「九尾协调的裁决结果」，两者互补、可同时存在。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_SUBTEXT = 2
_MAX_NEEDS = 2
_MAX_MEMORY = 2
_MAX_GOALS = 2
_MAX_TOOLS = 4
_MAX_CREATIVE = 2


def build_kitsune_heart_section(ctx: dict) -> str:
    """构建狐心裁决提示片段。

    Args:
        ctx: KitsuneHeartBridge.get_session_context() 的输出

    Returns:
        格式化的 prompt 文本；心判无实质内容时返回空字符串
    """
    if not isinstance(ctx, dict):
        return ""
    verdict = ctx.get("verdict")
    if not isinstance(verdict, dict):
        return ""

    lines: list[str] = []
    mode = verdict.get("mode") or ""
    action = verdict.get("action") or "proceed"

    # ── 心判：模式 + 情绪 ─────────────────────────────────
    heart_bits: list[str] = []
    if mode:
        heart_bits.append(f"模式·{mode}")
    emotion = verdict.get("emotion") or {}
    if emotion.get("confidence", 0) > 0.3:
        _label = emotion.get("label") or emotion.get("dominant") or ""
        _int = emotion.get("intensity") or ""
        if _label:
            heart_bits.append(f"情绪·{_label}{f'（{_int}）' if _int and _int != 'none' else ''}")
    if heart_bits:
        lines.append("【心判】" + " ｜ ".join(heart_bits))

    # ── 潜台词与需求（心理尾） ────────────────────────────
    subtext = (verdict.get("subtext") or [])[:_MAX_SUBTEXT]
    needs = (verdict.get("needs") or [])[:_MAX_NEEDS]
    if subtext:
        lines.append("【潜台词】" + "；".join(subtext))
    if needs:
        lines.append("【隐性需求】" + "；".join(needs))

    # ── 风控标注（风控尾） ────────────────────────────────
    risk = verdict.get("risk") or {}
    risk_level = risk.get("level") or "low"
    if risk_level in ("high", "critical"):
        lines.append(f"【风控标注】{risk_level}级：{'；'.join(risk.get('flags') or ['高风险操作'])}，先确认再执行")
    elif risk_level == "medium":
        lines.append("【风控标注】medium：涉及敏感信息或越权行为，谨慎处理")

    # ── 伦理（伦理尾） ────────────────────────────────────
    ethics = verdict.get("ethics") or {}
    e_verdict = ethics.get("verdict") or "ok"
    if action == "refuse":
        lines.append("【底线】此请求触及安全底线，予以拒绝，不提供实现细节")
    elif e_verdict == "warn":
        lines.append("【底线】涉低俗/攻击/隐私风险，温和纠正，不迎合")
    guidance = (ethics.get("guidance") or "").strip()
    if guidance and action != "refuse":
        lines.append(f"【引导】{guidance}")

    # ── 记忆召回（记忆尾） ────────────────────────────────
    memory = (verdict.get("memory") or [])[:_MAX_MEMORY]
    if memory:
        lines.append("【想起】" + "；".join(memory))

    # ── 长期目标（战略尾） ────────────────────────────────
    goals = (verdict.get("goals") or [])[:_MAX_GOALS]
    if goals:
        _g = []
        for g in goals:
            _name = g.get("goal") or ""
            _kr = g.get("kr_done", 0)
            _kt = g.get("kr_total", 0)
            _g.append(f"{_name}" + (f"（{_kr}/{_kt} 关键结果）" if _kt else ""))
        lines.append("【在途目标】" + "；".join(_g))

    # ── 工具建议（工具尾） ────────────────────────────────
    tools = (verdict.get("tools") or [])[:_MAX_TOOLS]
    if tools:
        lines.append("【工具建议】" + "、".join(tools))

    # ── 创意候选（创意尾，仅创意/决策模式） ──────────────
    creative = (verdict.get("creative") or [])[:_MAX_CREATIVE]
    if creative:
        _c = []
        for opt in creative:
            _c.append(f"{opt.get('angle') or ''}：{opt.get('idea') or ''}")
        lines.append("【创意候选】" + " ｜ ".join(_c))

    if not lines:
        return ""

    joined = "\n".join(lines)
    return (
        "── 九尾心判 ──\n"
        f"{joined}\n"
        "（心判仅供内部协调参考：感知与约束自然融入表达，不逐条宣告；"
        "不改变安全底线、诚实原则与事实准确性。）"
    )
