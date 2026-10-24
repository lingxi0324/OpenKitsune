# -*- coding: utf-8 -*-
"""
TCM 输入归一化层 — 让 AI / 病历口语直接喂给辨证引擎，无需写代码。

职责：
1. 把原始主诉文本（任意中英文标点分隔）切成症状词条；
2. 把口语 / 错别字 / 异名（"不士气"、"纳差"、"流鼻涕"、"睡不好"…）
   映射到引擎已收录的规范关键词（如"纳呆"、"流涕 鼻塞"、"失眠"）；
3. 脉象补全（"沉细" → "脉沉细 沉细"），让六经脉象模式与体用表都能命中；
4. 提供一键构造 DialecticInput 的便捷函数。

本模块只在输入端做无损归一，不修改引擎评分算法。
"""

import re
from typing import List, Optional, Tuple, Union

from .clinical_types import DialecticInput

# ── 整词精确映射（短词易误伤子串，只做整词替换）──────────────────────────
_EXACT_MAP = {
    "咳": "咳嗽",
    "吐": "呕吐",
    "不寐": "不寐",
}

# ── 子串映射（长键优先；命中即整个词条视为该变体，整体映射为规范关键词）──
_SUBSTRING_KEYS: List[Tuple[str, str]] = sorted(
    [
        ("食欲不振", "纳呆"),
        ("不想吃饭", "纳呆"),
        ("吃不下饭", "食不下"),
        ("不嗜食", "纳呆"),
        ("不思食", "纳呆"),
        ("不士气", "纳呆"),       # 主诉常见误写/口音
        ("不想吃", "纳呆"),
        ("吃不进", "食不下"),
        ("鼻流清涕", "流涕 鼻塞"),
        ("流清涕", "流涕 鼻塞"),
        ("清鼻涕", "流涕 鼻塞"),
        ("流鼻涕", "流涕 鼻塞"),
        ("打喷嚏", "鼻塞"),
        ("睡不着", "失眠"),
        ("睡不著", "失眠"),
        ("睡不好", "失眠"),
        ("入睡难", "失眠"),
        ("没力气", "乏力"),
        ("没精神", "乏力"),
        ("疲倦", "乏力"),
        ("疲劳", "乏力"),
        ("精神差", "乏力"),
        ("恶心想吐", "恶心 呕吐"),
        ("想吐", "恶心 呕吐"),
        ("干呕", "呕吐"),
        ("嗳气", "嗳气 打嗝"),
        ("呃逆", "呃逆 打嗝"),
        ("厌食", "纳呆"),
        ("纳差", "纳呆"),
        ("食少", "食少"),
    ],
    key=lambda kv: -len(kv[0]),
)


def split_complaint(text: str) -> List[str]:
    """按中英文标点 / 空白切分原始主诉，去空、去重（保序）。"""
    items = re.split(r"[，,、；;。．.／/\s]+", text or "")
    seen: set = set()
    out: List[str] = []
    for it in items:
        it = it.strip()
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _map_token(token: str) -> str:
    """单个词条归一：整词精确映射优先，其次长键子串整体映射。"""
    if token in _EXACT_MAP:
        return _EXACT_MAP[token]
    for src, dst in _SUBSTRING_KEYS:
        if src in token:
            return dst
    return token


def normalize_symptoms(raw: Union[str, List[str], None]) -> str:
    """把 symptoms（字符串 / 列表 / 原始主诉整段）归一为引擎可识别的规范串。

    - 字符串按标点自动切分；
    - 列表逐项处理；
    - 口语 / 错别字映射为规范关键词；
    - 去重保序，逗号连接。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        items = split_complaint(raw)
    elif isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        items = [str(raw).strip()] if str(raw).strip() else []

    out: List[str] = []
    seen: set = set()
    for token in items:
        mapped = _map_token(token)
        for piece in mapped.split(","):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.add(piece)
                out.append(piece)
    return ",".join(out)


_PULSE_CHARS = "沉浮迟数弦滑细弱微洪紧涩缓促结代"

def normalize_pulse(pulse: str) -> str:
    """脉象归一：'沉细' → '脉沉细 沉细'，保留裸形与脉前缀形供引擎命中。"""
    if not pulse:
        return ""
    p = str(pulse).strip()
    if "脉" in p:
        return p
    if p and all(c in _PULSE_CHARS for c in p):
        return f"脉{p} {p}"
    return p


def build_dialectic_input(
    symptoms: Union[str, List[str], None] = None,
    complaint: str = "",
    pulse: str = "",
    tongue: str = "",
    coat: str = "",
    physician: str = "",
    constitution: str = "",
    specialty: str = "内科",
    year: Optional[str] = None,
    collect_tide: bool = True,
) -> DialecticInput:
    """一键构造 DialecticInput：症状 / 主诉 / 脉象自动归一化。

    传参示例：
      build_dialectic_input(
          complaint="流鼻涕，咳嗽，呕吐，打嗝，不士气，纳差，纳呆，厌油，失眠",
          pulse="沉细")
    """
    raw = complaint if (complaint and not symptoms) else symptoms
    return DialecticInput(
        tongue=tongue or "",
        coat=coat or "",
        pulse=normalize_pulse(pulse),
        symptoms=normalize_symptoms(raw),
        physician=physician or "",
        constitution=constitution or "",
        specialty=specialty or "内科",
        year=str(year) if year else None,
        collect_tide=collect_tide,
    )
