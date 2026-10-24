# -*- coding: utf-8 -*-
"""处方层：主方组成 → 自动加减 → 药证映射 → 配伍校验。

输入主方名与归一化症状，输出可直接交付的处方结构：
  - 组成（药物 + 剂量）
  - 加味 / 减味（含依据）
  - 药证映射（每味药对应哪条四诊证据）
  - 配伍校验（十八反 / 十九畏 / 妊娠禁忌）
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .wuwei import FORMULAS, HERB_WUWEI, analyze_formula

# 剂量单位：默认 g，丸散类或果实类改用枚
_UNIT = {"大枣": "枚", "鸡子黄": "枚"}

# 症状 → 加味（药物, 剂量, 君臣佐使位, 功效）
ADDITION_RULES: List[dict] = [
    {"trigger": ("咳嗽", "咳痰", "干咳"), "add": [("杏仁", 9, "佐", "降肺气止咳")]},
    {"trigger": ("痰多", "痰白", "痰稀"), "add": [("陈皮", 6, "佐", "燥湿化痰"), ("茯苓", 9, "佐", "健脾渗湿")]},
    {"trigger": ("痰黄", "黄稠"), "add": [("川贝母", 6, "佐", "清热化痰")]},
    {"trigger": ("咽痛", "咽干"), "add": [("桔梗", 6, "佐", "宣肺利咽")]},
    {"trigger": ("鼻塞", "流涕", "喷嚏"), "add": [("白芷", 6, "佐", "宣通鼻窍")]},
    {"trigger": ("头痛", "头项强痛"), "add": [("川芎", 6, "佐", "行气活血止痛")]},
    {"trigger": ("眩晕", "头晕", "目眩"), "add": [("天麻", 6, "佐", "平肝息风")]},
    {"trigger": ("失眠", "不寐", "入睡难"), "add": [("酸枣仁", 9, "佐", "养心安神")]},
    {"trigger": ("心悸", "心慌"), "add": [("远志", 6, "佐", "安神定志")]},
    {"trigger": ("纳差", "纳呆", "不思食", "食欲不振", "食不下"), "add": [("神曲", 9, "佐", "消食和胃"), ("麦芽", 9, "佐", "行气消食")]},
    {"trigger": ("腹胀", "腹满", "痞满"), "add": [("厚朴", 6, "佐", "行气除满")]},
    {"trigger": ("便溏", "腹泻", "大便粘滞", "大便黏"), "add": [("苍术", 6, "佐", "燥湿健脾")]},
    {"trigger": ("便秘", "便干", "大便干"), "add": [("火麻仁", 9, "佐", "润肠通便")]},
    {"trigger": ("口干", "口渴", "津亏"), "add": [("麦冬", 9, "佐", "养阴生津")]},
    {"trigger": ("畏寒", "手足冷", "四肢冷", "肢冷"), "add": [("干姜", 6, "佐", "温中散寒")]},
    {"trigger": ("水肿", "小便不利", "身重"), "add": [("泽泻", 9, "佐", "利水渗湿")]},
    {"trigger": ("腰酸", "腰痛", "膝软"), "add": [("牛膝", 9, "佐", "补肝肾强腰膝")]},
    {"trigger": ("胁痛", "胸胁满", "胸胁苦满"), "add": [("香附", 9, "佐", "疏肝理气")]},
    {"trigger": ("心烦", "烦躁", "焦虑"), "add": [("栀子", 6, "佐", "清心除烦")]},
    {"trigger": ("恶心", "呕吐", "喜呕"), "add": [("竹茹", 9, "佐", "和胃止呕")]},
    {"trigger": ("自汗", "汗多"), "add": [("黄芪", 12, "佐", "益气固表")]},
    {"trigger": ("乏力", "气短", "倦怠"), "add": [("黄芪", 12, "佐", "益气升阳")]},
    {"trigger": ("盗汗", "潮热"), "add": [("知母", 6, "佐", "滋阴清虚热")]},
    {"trigger": ("目赤", "目涩", "目干"), "add": [("菊花", 6, "佐", "清肝明目")]},
    {"trigger": ("痛经", "月经色暗", "月经量少"), "add": [("当归", 9, "佐", "养血活血")]},
]

# 症状 → 减味（从主方组成中移除，并记录依据）
REDUCTION_RULES: List[dict] = [
    {
        "trigger": ("出血", "吐衄", "发斑", "崩漏"),
        "remove": ("麻黄", "桂枝", "川芎", "红花", "桃仁", "吴茱萸"),
        "reason": "出血倾向，减辛温动血之品",
    },
    {
        "trigger": ("孕妇", "妊娠", "怀孕"),
        "remove": ("桃仁", "红花", "大黄", "芒硝", "牛膝", "附子", "半夏"),
        "reason": "妊娠禁忌，减破血峻下及有毒之品",
    },
    {
        "trigger": ("舌红", "少苔", "无苔", "剥苔", "盗汗"),
        "remove": ("附子", "干姜", "肉桂", "吴茱萸"),
        "reason": "阴虚津亏，减大辛大热之品",
    },
    {
        "trigger": ("便溏", "腹泻", "久泻"),
        "remove": ("大黄", "芒硝", "火麻仁"),
        "reason": "脾虚便溏，减峻下润肠之品",
    },
]

# 十八反 / 十九畏（仅收录本库涉及的药对）
INCOMPATIBLE_PAIRS: List[Tuple[str, str, str]] = [
    ("甘草", "甘遂", "十八反：藻戟遂芫俱战草"),
    ("甘草", "大戟", "十八反：藻戟遂芫俱战草"),
    ("甘草", "海藻", "十八反：藻戟遂芫俱战草"),
    ("甘草", "芫花", "十八反：藻戟遂芫俱战草"),
    ("附子", "半夏", "十八反：半蒌贝蔹及攻乌"),
    ("附子", "瓜蒌", "十八反：半蒌贝蔹及攻乌"),
    ("附子", "川贝母", "十八反：半蒌贝蔹及攻乌"),
    ("细辛", "藜芦", "十八反：诸参辛芍叛藜芦"),
    ("人参", "藜芦", "十八反：诸参辛芍叛藜芦"),
    ("丹参", "藜芦", "十八反：诸参辛芍叛藜芦"),
    ("肉桂", "赤石脂", "十九畏：官桂善能调冷气，若逢石脂便相欺"),
]


def _fmt(herb: str, dose: int) -> str:
    return f"{herb} {dose}{_UNIT.get(herb, 'g')}"


def _hit(text: str, triggers: Tuple[str, ...]) -> List[str]:
    return [t for t in triggers if t in text]


def _position(herb: str, fx) -> str:
    if not (fx.君 or fx.臣 or fx.佐 or fx.使):
        return "—"
    for name, key in (("君", fx.君), ("臣", fx.臣), ("佐", fx.佐), ("使", fx.使)):
        if herb in key:
            return name
    return "佐"


def build_prescription(formula_name: str, symptoms: str) -> Dict:
    """基于主方与归一化症状生成处方。

    :param formula_name: 主方名（须在 wuwei.FORMULAS 中）
    :param symptoms: 归一化后的症状串（逗号或空格分隔）
    """
    text = symptoms or ""
    analysis = analyze_formula(formula_name)
    if "错误" in analysis:
        return {
            "主方": formula_name,
            "错误": analysis["错误"],
            "组成": [],
            "加味": [],
            "减味": [],
            "药证映射": [],
            "配伍校验": {"通过": False, "冲突": ["主方未收录，无法生成组成"]},
        }

    base_name = analysis["名称"]
    fx = FORMULAS[base_name]
    base_herbs = [(h, d) for (h, d) in fx.组成]
    base_names = [h for (h, _) in base_herbs]
    text_map = {
        h: fx.组成文本[i]
        for i, (h, _) in enumerate(base_herbs)
        if i < len(fx.组成文本)
    }

    # ── 减味 ──
    removed: List[dict] = []
    removed_names: set = set()
    for rule in REDUCTION_RULES:
        hits = _hit(text, rule["trigger"])
        if not hits:
            continue
        for herb in rule["remove"]:
            if herb in base_names and herb not in removed_names:
                removed_names.add(herb)
                removed.append({
                    "药物": herb,
                    "依据": f"{'、'.join(hits)} → {rule['reason']}",
                })

    # ── 加味 ──
    added: List[dict] = []
    added_names: set = set()
    for rule in ADDITION_RULES:
        hits = _hit(text, rule["trigger"])
        if not hits:
            continue
        for herb, dose, pos, effect in rule["add"]:
            if herb in base_names or herb in added_names:
                continue
            added_names.add(herb)
            added.append({
                "药物": herb,
                "剂量": dose,
                "剂量文本": _fmt(herb, dose),
                "君臣佐使": pos,
                "功效": effect,
                "依据": "、".join(hits),
            })

    # ── 组成（加味插在使药之前）──
    kept = [(h, d) for (h, d) in base_herbs if h not in removed_names]
    body = [(h, d) for (h, d) in kept if _position(h, fx) != "使"]
    tail = [(h, d) for (h, d) in kept if _position(h, fx) == "使"]
    composition = (
        [text_map.get(h) or _fmt(h, d) for (h, d) in body]
        + [a["剂量文本"] for a in added]
        + [text_map.get(h) or _fmt(h, d) for (h, d) in tail]
    )

    # ── 药证映射 ──
    mapping: List[dict] = []
    focus_parts = [part for part in re.split(r"[，,]", fx.主治 or "") if part]
    focus = "、".join(focus_parts[:3]) or "—"
    for herb, dose in body + tail:
        info = HERB_WUWEI.get(herb)
        mapping.append({
            "药物": text_map.get(herb) or f"{herb} {dose}{_UNIT.get(herb, 'g')}",
            "君臣佐使": _position(herb, fx),
            "功效": info.功效 if info else "",
            "归经": "、".join(info.归经) if info else "",
            "针对": focus,
            "来源": "主方",
        })
    for item in added:
        info = HERB_WUWEI.get(item["药物"])
        mapping.append({
            "药物": item["剂量文本"],
            "君臣佐使": item["君臣佐使"],
            "功效": info.功效 if info else item["功效"],
            "归经": "、".join(info.归经) if info else "",
            "针对": item["依据"],
            "来源": "加味",
        })

    # ── 配伍校验 ──
    final_names = {h for (h, _) in kept} | added_names
    conflicts = [
        note for (a, b, note) in INCOMPATIBLE_PAIRS
        if a in final_names and b in final_names
    ]
    unknown = [h for (h, _) in kept if h not in HERB_WUWEI] + [
        a["药物"] for a in added if a["药物"] not in HERB_WUWEI
    ]
    broken = [h for h in fx.君 if h in removed_names]

    return {
        "主方": base_name,
        "功效": fx.功效,
        "主治": fx.主治,
        "方解": fx.方解,
        "组成": composition,
        "君臣佐使": analysis.get("君臣佐使", {}),
        "加味": added,
        "减味": removed,
        "药证映射": mapping,
        "配伍校验": {
            "通过": not conflicts,
            "冲突": conflicts,
            "未收录药味": unknown,
            "妊娠禁忌": "孕妇" in text or "妊娠" in text,
        },
        "方义提示": (
            f"主方君药（{'、'.join(broken)}）已减，原方方义不成立，须由医师另选方" if broken else ""
        ),
        "用法": "水煎服，日一剂，分早晚温服；剂量、煎服法与加减须由执业中医师核定。",
    }
