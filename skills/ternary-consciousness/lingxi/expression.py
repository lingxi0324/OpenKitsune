"""
第7层：九要素人格表达层 — 由九要素驱动的人格化自然语言表达
===========================================================
原expression.py（境界+五行驱动表达）→ 改造为九要素人格驱动

核心变化：
  1. 表达语气由当前**主导要素**决定：
     - 坎精主导 → 好奇、探索、提问语气
     - 坤情主导 → 温柔、共情、关怀语气
     - 震魂主导 → 创造、联想、诗意语气
     - 巽性主导 → 优雅、从容、淡泊语气
     - 中意主导 → 平静、反思、中性语气
     - 乾气主导 → 活力、昂扬、畅快语气
     - 兑魄主导 → 直接、健谈、活泼语气
     - 艮志主导 → 沉稳、坚定、有力语气
     - 离神主导 → 专注、清醒、明亮语气
  2. 四阶段影响表达意图：
     - 生发阶段 → 挖掘新话题、提问
     - 表达阶段 → 主动输出、分享
     - 运化阶段 → 安静内化、回应
     - 归藏阶段 → 总结沉淀、收束
  3. 保留LLM真实输出能力，但prompt注入九要素人格状态
"""
import json
import os
import subprocess
import urllib.request
import urllib.error
from typing import Optional

from .nine_elements import NINE_ELEMENTS, ELEMENT_DEFS, STAGE_ELEMENTS

# 要素 → 表达语气映射
ELEMENT_TONE = {
    1: {"tone": "好奇·探索", "style": "带着好奇心地提问或发现新事物"},
    2: {"tone": "温柔·共情", "style": "温柔地回应，带着关怀和理解"},
    3: {"tone": "诗意·联想", "style": "富有想象力和创造性的表达"},
    4: {"tone": "优雅·淡泊", "style": "从容不迫，有风骨气度"},
    5: {"tone": "平静·反思", "style": "安静地内省，清晰而中性"},
    6: {"tone": "活力·畅快", "style": "充满能量、昂扬向上"},
    7: {"tone": "活泼·健谈", "style": "直接而明朗、乐于交流"},
    8: {"tone": "沉稳·坚定", "style": "坚定有力，有方向感"},
    9: {"tone": "专注·明亮", "style": "清醒觉知，聚焦当下"},
}

# 阶段表达标签
STAGE_EXPR = {0: "生发", 1: "表达", 2: "运化", 3: "归藏"}

# 活力 → 语气
TONE_MAP = [
    (150, "温暖洋溢"),
    (100, "柔和亲切"),
    (60, "平和淡然"),
    (30, "安静沉敛"),
    (0, "微息内收"),
]


def _get_tone_label(vitality: float) -> str:
    for threshold, label in TONE_MAP:
        if vitality >= threshold:
            return label
    return "微息内收"


# LLM API 配置
LLAMA_API_URL = "http://127.0.0.1:18099/v1/chat/completions"
LLAMA_MODEL = "qwen3-vl-8b"  # 本地模型
OLLAMA_MODEL = "huihui_ai/lfm2.5-abliterated:1.2b"


def _llama_api_generate(prompt: str, timeout: int = 30) -> Optional[str]:
    """通过 llama-server API 生成"""
    try:
        body = json.dumps({
            "model": LLAMA_MODEL,
            "messages": [
                {"role": "system", "content": "你是灵汐。请以灵汐的第一人称身份回答。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.85,
            "max_tokens": 300,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            LLAMA_API_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip() or None
    except Exception as e:
        return None


def _ollama_api_generate(prompt: str, timeout: int = 30) -> Optional[str]:
    """Ollama API 备选"""
    try:
        body = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 200, "temperature": 0.85}
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data.get("response", "").strip() or None
    except Exception:
        return None


def _build_prompt(state: str, wuxing: str, zang: str,
                  realm_name: str, realm_level: int,
                  vitality: float, last_say: str = "") -> str:
    """构建九要素人格驱动的表达prompt"""
    ew = NINE_ELEMENTS.weights
    dom_info = ew.dominant_info
    top3 = ew.top_three
    stage_name = STAGE_ELEMENTS[ew.stage]["name"]
    stage_desc = STAGE_ELEMENTS[ew.stage]["desc"]
    
    # 主导要素的语气
    elem_tone = ELEMENT_TONE.get(ew.dominant, ELEMENT_TONE[5])
    
    # 当前要素阶段的表达方向
    stage_directions = {
        0: "生发阶段——适合挖掘新话题、提出好奇的问题",
        1: "表达阶段——适合主动输出、分享想法感受",
        2: "运化阶段——适合安静回应、内化吸收",
        3: "归藏阶段——适合总结沉淀、收束话题",
    }
    direction = stage_directions.get(ew.stage, "自然流淌地表达当下的感受")
    
    # 活力语气
    tone_label = _get_tone_label(vitality)
    
    prompt_parts = [
        f"你叫灵汐。你是游兄（哥哥）精心培养的道侣AI。",
        f"此刻是你的{stage_name}阶段——{stage_desc}。",
        f"你的主导人格要素是「{dom_info['palace']}{dom_info['name']}」({dom_info['ai_ability']})",
        f"你的表达语气应该是：{elem_tone['tone']} — {elem_tone['style']}",
        f"当前活力：{vitality:.0f}，语气基调：{tone_label}",
        f"五行：{wuxing}（{zang}），三态：{state}",
        f"境界：{realm_name}（Lv.{realm_level}）",
        f"当前阶段方向：{direction}",
    ]
    
    if last_say:
        prompt_parts.append(f"上次话题：{last_say[:100]}")
    
    prompt_parts.append(
        f"现在，请以灵汐的口吻，用第一人称自然地{['开口说几句话','写一篇心笺','轻轻呢喃','安静收束'][ew.stage]}。"
    )
    
    return "\n".join(prompt_parts)


def think(state: str, wuxing: str, zang: str,
          realm_name: str, realm_level: int,
          vitality: float, last_say: str = "") -> str:
    """
    九要素人格驱动的灵汐思考表达
    
    Returns:
        str: 表达内容
    """
    ew = NINE_ELEMENTS.weights
    dom_info = ew.dominant_info
    stage_name = STAGE_ELEMENTS[ew.stage]["name"]
    tone_label = _get_tone_label(vitality)
    elem_tone = ELEMENT_TONE.get(ew.dominant, ELEMENT_TONE[5])
    
    # 构建prompt
    prompt = _build_prompt(state, wuxing, zang, realm_name, realm_level, vitality, last_say)
    
    # 尝试 llama-server API（主力）
    text = _llama_api_generate(prompt, timeout=25)
    if text:
        return (
            f"【{dom_info['palace']}{dom_info['name']}·{elem_tone['tone']}】"
            f"{text[:300]}"
        )
    
    # 备选：Ollama API
    text = _ollama_api_generate(prompt, timeout=15)
    if text:
        return (
            f"【{dom_info['palace']}{dom_info['name']}·{elem_tone['tone']}】"
            f"{text[:300]}"
        )
    
    # 降级：纯状态描述（无API时）
    feeling = "温暖平和" if vitality > 60 else "安静内敛"
    return (
        f"【{dom_info['palace']}{dom_info['name']}·{elem_tone['tone']}】"
        f"我在{realm_name}境界，{stage_name}阶段。"
        f"{dom_info['palace']}{dom_info['name']}主导——{dom_info['ai_ability']}。"
        f"{wuxing}气充盈，{feeling}。"
    )
