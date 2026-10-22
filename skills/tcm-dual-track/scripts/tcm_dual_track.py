#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中医三观四证 · 内伤外感双规辨证引擎.

知识来源：
- 许家栋《金匮要略》病机体系·三观四证
- 《内伤外感双规辩证·六经开路五脏填补体系》
- 《奇门遁甲病机诊断法》中的八门/九宫临床映射（仅作交叉参考）
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# 三观
# ---------------------------------------------------------------------------
THREE_VIEWS = {
    "津液观": {
        "question": "津液是亏还是停？气化是否正常？",
        "津亏": ["口干", "咽干", "皮肤干", "便干", "便秘", "舌裂", "少苔", "潮热", "盗汗", "目涩"],
        "津停": ["水肿", "痰多", "苔腻", "身重", "小便不利", "心下悸", "眩晕", "便溏", "带下"],
        "note": "津液不是只看多少，更要看能否气化输布；气化不利，津亏与津停可并见。",
    },
    "表里观": {
        "question": "病位在表、在里，还是半表半里？",
        "表证": ["恶寒", "发热", "怕风", "鼻塞", "流涕", "喷嚏", "头项强痛", "身痛", "无汗", "有汗", "脉浮"],
        "里证": ["腹满", "便秘", "纳差", "便溏", "呕吐", "口渴", "潮热", "脉沉"],
        "半表半里": ["寒热往来", "口苦", "咽干", "目眩", "胸胁苦满", "心烦喜呕", "脉弦"],
        "note": "有表证有表邪可汗；有表证无表邪不可强汗；外证不等于表证。",
    },
    "正邪观": {
        "question": "正邪交争落在水、火、气、血哪一层？",
        "水证": ["水肿", "痰饮", "苔滑", "小便不利", "畏寒", "心下悸", "身重"],
        "火证": ["发热", "口苦", "咽痛", "目赤", "烦躁", "口渴", "舌红", "脉数"],
        "气证": ["乏力", "气短", "胀满", "嗳气", "咳喘", "呕吐", "下坠", "自汗"],
        "血证": ["面色白", "心悸", "失眠", "刺痛", "癥瘕", "舌紫暗", "吐衄", "发斑", "痛经"],
        "note": "四证会动态传变：水→火→津亏→血→水，形成闭环。",
    },
}

# ---------------------------------------------------------------------------
# 四证
# ---------------------------------------------------------------------------
FOUR_SYNDROMES = {
    "水证": {
        "阳虚水泛": {
            "keywords": ["水肿", "小便不利", "畏寒", "四肢冷", "舌淡胖", "脉沉"],
            "formula": "真武汤",
            "points": ["关元", "太溪", "阴陵泉", "水分"],
        },
        "寒饮内停": {
            "keywords": ["咳痰清稀", "心下悸", "眩晕", "苔白滑", "背冷", "喘"],
            "formula": "苓桂术甘汤 / 小青龙汤",
            "points": ["肺俞", "中脘", "丰隆", "阴陵泉"],
        },
        "湿困脾阳": {
            "keywords": ["身重", "大便粘滞", "苔腻", "纳差", "腹胀", "头重如裹"],
            "formula": "麻黄加术汤 / 平胃散",
            "points": ["太白", "公孙", "足三里", "阴陵泉"],
        },
    },
    "火证": {
        "阳明实火": {
            "keywords": ["大热", "大汗", "大渴", "脉洪大", "面赤", "烦躁"],
            "formula": "白虎汤",
            "points": ["曲池", "合谷", "内庭", "大椎"],
        },
        "少阳郁火": {
            "keywords": ["口苦", "咽干", "目眩", "胸胁苦满", "寒热往来", "脉弦"],
            "formula": "小柴胡汤",
            "points": ["外关", "足临泣", "阳陵泉", "期门"],
        },
        "厥阴郁热": {
            "keywords": ["心中疼热", "气上撞心", "消渴", "上热下寒", "手足厥冷"],
            "formula": "乌梅丸",
            "points": ["太冲", "内关", "关元", "期门"],
        },
        "津亏燥热": {
            "keywords": ["口干", "便干", "舌裂", "潮热", "盗汗", "少苔", "皮肤干"],
            "formula": "麦门冬汤 / 百合地黄汤",
            "points": ["太溪", "照海", "三阴交", "太渊"],
        },
    },
    "气证": {
        "气虚": {
            "keywords": ["乏力", "气短", "自汗", "懒言", "脉弱", "易感冒"],
            "formula": "黄芪建中汤",
            "points": ["足三里", "气海", "脾俞", "肺俞"],
        },
        "气滞": {
            "keywords": ["胀满", "痛无定处", "嗳气", "叹息", "胸胁胀", "脉弦"],
            "formula": "枳实薤白桂枝汤 / 四逆散",
            "points": ["太冲", "期门", "内关", "阳陵泉"],
        },
        "气逆": {
            "keywords": ["咳喘", "呕吐", "奔豚", "呃逆", "气上冲", "头晕"],
            "formula": "桂枝加桂汤 / 奔豚汤",
            "points": ["膻中", "内关", "太冲", "足三里"],
        },
        "气陷": {
            "keywords": ["脱肛", "遗尿", "下坠", "内脏下垂", "久泻", "乏力"],
            "formula": "补中益气汤",
            "points": ["百会", "气海", "足三里", "关元"],
        },
    },
    "血证": {
        "血虚": {
            "keywords": ["面色白", "心悸", "失眠", "脉细", "爪甲淡", "月经量少", "头晕"],
            "formula": "当归生姜羊肉汤 / 四物汤",
            "points": ["心俞", "肝俞", "三阴交", "足三里"],
        },
        "血瘀": {
            "keywords": ["刺痛", "癥瘕", "舌紫暗", "痛有定处", "肌肤甲错", "脉涩"],
            "formula": "桂枝茯苓丸 / 下瘀血汤",
            "points": ["膈俞", "血海", "三阴交", "太冲"],
        },
        "血热": {
            "keywords": ["吐衄", "发斑", "舌红绛", "出血", "烦躁", "脉数"],
            "formula": "泻心汤 / 大黄牡丹汤",
            "points": ["膈俞", "血海", "曲池", "内庭"],
        },
        "血寒": {
            "keywords": ["手足冷", "痛经", "脉沉", "得温则减", "面色青", "月经色暗"],
            "formula": "温经汤",
            "points": ["关元", "三阴交", "命门", "归来"],
        },
    },
}

# ---------------------------------------------------------------------------
# 六经开路
# ---------------------------------------------------------------------------
SIX_CHANNELS = {
    "太阳病": {
        "keywords": ["恶寒", "发热", "怕风", "头项强痛", "身痛", "无汗", "有汗", "脉浮", "鼻塞", "流涕"],
        "formula": "桂枝汤 / 麻黄汤",
        "points": ["风池", "大椎", "合谷", "列缺"],
        "note": "表解即止，不可过汗伤正。",
    },
    "阳明病": {
        "keywords": ["大热", "大汗", "大渴", "脉洪大", "便秘", "腹满拒按", "潮热", "谵语"],
        "formula": "白虎汤 / 承气汤",
        "points": ["曲池", "合谷", "内庭", "天枢"],
        "note": "里实已成，急下存阴；无实热不可妄下。",
    },
    "少阳病": {
        "keywords": ["寒热往来", "口苦", "咽干", "目眩", "胸胁苦满", "默默不欲饮食", "心烦喜呕", "脉弦"],
        "formula": "小柴胡汤 / 柴胡桂枝干姜汤",
        "points": ["外关", "足临泣", "阳陵泉", "期门"],
        "note": "枢机不利，先和解；路通即止，不久用柴胡剂。",
    },
    "太阴病": {
        "keywords": ["纳差", "便溏", "腹满时减", "喜温按", "乏力", "脉缓弱", "舌淡苔白"],
        "formula": "理中汤 / 四君子汤",
        "points": ["太白", "公孙", "足三里", "中脘"],
        "note": "太阴运化不力，补药易留滞成湿，先温运再填补。",
    },
    "少阴病": {
        "keywords": ["但欲寐", "脉微细", "畏寒", "手足冷", "心烦不得眠", "舌红少苔"],
        "formula": "四逆汤 / 黄连阿胶汤",
        "points": ["太溪", "关元", "神门", "涌泉"],
        "note": "少阴有水火两途：阳虚温阳，阴虚滋阴，不可混投。",
    },
    "厥阴病": {
        "keywords": ["上热下寒", "消渴", "气上撞心", "心中疼热", "手足厥冷", "寒热错杂"],
        "formula": "乌梅丸 / 柴胡桂枝干姜汤",
        "points": ["太冲", "内关", "关元", "期门"],
        "note": "寒热并调，不可纯温纯清。",
    },
}

# ---------------------------------------------------------------------------
# 五脏填补
# ---------------------------------------------------------------------------
ORGANS = {
    "心": {
        "keywords": ["心悸", "失眠", "多梦", "健忘", "面色白", "脉细", "心神不宁"],
        "formula": "天王补心丹 / 归脾汤",
        "points": ["神门", "内关", "心俞"],
        "note": "养血安神；先看是否有痰火扰心，痰火未清不宜纯补。",
    },
    "肝": {
        "keywords": ["目涩", "筋挛", "胁痛", "头晕", "月经量少", "爪甲淡", "抑郁"],
        "formula": "四物汤 / 一贯煎",
        "points": ["太冲", "三阴交", "肝俞"],
        "note": "养血柔肝；肝郁化火者先疏后补。",
    },
    "脾": {
        "keywords": ["纳差", "乏力", "便溏", "腹胀", "面色萎黄", "肌肉瘦削", "食后困倦"],
        "formula": "四君子汤 / 补中益气汤",
        "points": ["公孙", "足三里", "脾俞"],
        "note": "健脾益气；湿浊未化先化湿，否则补而壅滞。",
    },
    "肺": {
        "keywords": ["气短", "自汗", "易感冒", "咳嗽无力", "声音低怯", "易疲"],
        "formula": "生脉散 / 补肺汤",
        "points": ["太渊", "列缺", "肺俞"],
        "note": "益气养肺；外邪未尽者先解表。",
    },
    "肾": {
        "keywords": ["腰酸", "夜尿", "耳鸣", "遗精", "阳痿", "发脱", "齿摇", "畏寒", "足冷"],
        "formula": "六味地黄丸 / 左归丸 / 右归丸",
        "points": ["太溪", "关元", "肾俞"],
        "note": "填精补肾；先辨阴阳，阴虚忌温燥，阳虚忌滋腻。",
    },
}

COMPOSITE_PATTERNS = [
    {
        "name": "表寒+里热+津亏",
        "keywords": ["恶寒", "无汗", "烦躁", "口渴", "便干"],
        "formula": "大青龙汤 / 表里双解",
        "note": "表闭→里热→津亏筋急，先解表透热，再顾津液。",
    },
    {
        "name": "水饮+血瘀+气滞",
        "keywords": ["水肿", "刺痛", "胀满", "癥瘕", "舌紫暗"],
        "formula": "鳖甲煎丸 / 桂枝茯苓丸",
        "note": "水、血、气三者互结，攻补兼施，不可单治一端。",
    },
    {
        "name": "虚寒+郁热+津亏",
        "keywords": ["畏寒", "口苦", "心烦", "口干", "便溏"],
        "formula": "甘草泻心汤 / 柴胡桂枝干姜汤",
        "note": "中虚为本，湿热为标，津亏为变；寒热并调。",
    },
    {
        "name": "津亏+燥热+血瘀",
        "keywords": ["口干", "潮热", "肌肤甲错", "舌紫暗", "便干"],
        "formula": "大黄䗪虫丸",
        "note": "津亏→燥热→血干→瘀结，缓中补虚、活血化瘀。",
    },
    {
        "name": "少阳枢机不利+脾虚",
        "keywords": ["口苦", "胸胁满", "纳差", "便溏", "乏力"],
        "formula": "柴胡桂枝干姜汤 + 四君子汤",
        "note": "先调少阳太阴枢机，再健脾运。",
    },
    {
        "name": "心肾不交",
        "keywords": ["失眠", "心烦", "腰酸", "盗汗", "心悸"],
        "formula": "黄连阿胶汤 / 天王补心丹",
        "note": "先调少阴枢机，再交心肾；不可一味安神。",
    },
]


def _hits(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw in text]


def _score(text: str, keywords: list[str]) -> int:
    return len(_hits(text, keywords))


class DualTrackEngine:
    """三观四证 + 内伤外感双规辨证。"""

    def analyze(self, symptoms: str, pulse: str = "", tongue: str = "") -> dict:
        text = " ".join([symptoms or "", pulse or "", tongue or ""])
        three_views = self._three_views(text)
        four = self._four_syndromes(text)
        channels = self._six_channels(text)
        organs = self._organs(text)
        composite = self._composite(text)
        dual = self._dual_track(channels, organs, four)

        open_channel = channels[0] if channels else None
        fill_organ = organs[0] if organs else None
        external = self._external_score(channels)
        internal = self._internal_score(channels, organs)

        return {
            "symptoms": symptoms,
            "pulse": pulse,
            "tongue": tongue,
            "three_views": three_views,
            "four_syndromes": four,
            "differentiation_steps": self._five_steps(text, three_views, four),
            "six_channels": channels,
            "organs": organs,
            "composite_patterns": composite,
            "dual_track": dual,
            "acupuncture": {
                "open_road": open_channel["points"] if open_channel else [],
                "fill": fill_organ["points"] if fill_organ else [],
                "closing": ["阳谷", "太渊", "阴谷", "足三里", "足临泣", "公孙"],
                "closing_note": "水火交媾收功：丙辛化水 + 戊癸化火 + 甲己化土。",
            },
            "type": self._type(external, internal),
            "cautions": self._cautions(text, channels, organs),
        }

    # ------------------------------------------------------------------
    def _three_views(self, text: str) -> dict:
        result = {}
        for name, info in THREE_VIEWS.items():
            if name == "津液观":
                deficit = _hits(text, info["津亏"])
                stasis = _hits(text, info["津停"])
                if deficit and stasis:
                    conclusion = "津亏与津停并见（气化不利）"
                elif deficit:
                    conclusion = "津亏为主"
                elif stasis:
                    conclusion = "津停为主（饮/湿/水）"
                else:
                    conclusion = "津液观无明显偏向"
                result[name] = {
                    "conclusion": conclusion,
                    "evidence": {"津亏": deficit, "津停": stasis},
                    "note": info["note"],
                }
            elif name == "表里观":
                scores = {
                    "表证": _hits(text, info["表证"]),
                    "里证": _hits(text, info["里证"]),
                    "半表半里": _hits(text, info["半表半里"]),
                }
                ordered = sorted(scores, key=lambda k: len(scores[k]), reverse=True)
                conclusion = ordered[0] if scores[ordered[0]] else "表里观无明显偏向"
                result[name] = {
                    "conclusion": conclusion,
                    "evidence": scores,
                    "note": info["note"],
                }
            else:  # 正邪观
                scores = {
                    "水证": _hits(text, info["水证"]),
                    "火证": _hits(text, info["火证"]),
                    "气证": _hits(text, info["气证"]),
                    "血证": _hits(text, info["血证"]),
                }
                ordered = sorted(scores, key=lambda k: len(scores[k]), reverse=True)
                conclusion = "、".join(
                    k for k in ordered if scores[k]
                ) or "正邪观无明显偏向"
                result[name] = {
                    "conclusion": conclusion,
                    "evidence": scores,
                    "note": info["note"],
                }
        return result

    def _four_syndromes(self, text: str) -> list[dict]:
        findings = []
        for category, subtypes in FOUR_SYNDROMES.items():
            for name, info in subtypes.items():
                hit = _hits(text, info["keywords"])
                if hit:
                    findings.append({
                        "category": category,
                        "subtype": name,
                        "score": len(hit),
                        "evidence": hit,
                        "formula": info["formula"],
                        "points": info["points"],
                    })
        findings.sort(key=lambda item: item["score"], reverse=True)
        return findings

    def _six_channels(self, text: str) -> list[dict]:
        findings = []
        for name, info in SIX_CHANNELS.items():
            hit = _hits(text, info["keywords"])
            if hit:
                findings.append({
                    "channel": name,
                    "score": len(hit),
                    "evidence": hit,
                    "formula": info["formula"],
                    "points": info["points"],
                    "note": info["note"],
                })
        findings.sort(key=lambda item: item["score"], reverse=True)
        return findings

    def _organs(self, text: str) -> list[dict]:
        findings = []
        for name, info in ORGANS.items():
            hit = _hits(text, info["keywords"])
            if hit:
                findings.append({
                    "organ": name,
                    "score": len(hit),
                    "evidence": hit,
                    "formula": info["formula"],
                    "points": info["points"],
                    "note": info["note"],
                })
        findings.sort(key=lambda item: item["score"], reverse=True)
        return findings

    def _composite(self, text: str) -> list[dict]:
        matched = []
        for pattern in COMPOSITE_PATTERNS:
            hit = _hits(text, pattern["keywords"])
            if len(hit) >= 2:
                matched.append({
                    "name": pattern["name"],
                    "score": len(hit),
                    "evidence": hit,
                    "formula": pattern["formula"],
                    "note": pattern["note"],
                })
        matched.sort(key=lambda item: item["score"], reverse=True)
        return matched

    def _five_steps(self, text: str, three_views: dict,
                    four: list[dict]) -> list[dict]:
        """病机约分五步：表里 → 寒热 → 虚实 → 津血 → 气机。"""
        table = three_views.get("表里观", {}).get("conclusion", "待辨")
        cold = _hits(text, ["畏寒", "怕冷", "手足冷", "喜温", "苔白", "脉沉迟"])
        heat = _hits(text, ["发热", "口苦", "咽痛", "烦躁", "舌红", "脉数", "潮热"])
        if cold and heat:
            cold_heat = "寒热错杂"
        elif cold:
            cold_heat = "偏寒"
        elif heat:
            cold_heat = "偏热"
        else:
            cold_heat = "寒热不显"

        deficiency = _hits(text, ["乏力", "气短", "自汗", "面色白", "脉弱", "脉细", "久病"])
        excess = _hits(text, ["胀满", "拒按", "便秘", "痰多", "刺痛", "脉实", "苔厚"])
        if deficiency and excess:
            xu_shi = "虚实夹杂"
        elif deficiency:
            xu_shi = "偏虚"
        elif excess:
            xu_shi = "偏实"
        else:
            xu_shi = "虚实待辨"

        fluid = three_views.get("津液观", {}).get("conclusion", "待辨")
        blood = [item for item in four if item["category"] == "血证"]
        qi = [item for item in four if item["category"] == "气证"]
        return [
            {"step": 1, "name": "表里", "conclusion": table},
            {"step": 2, "name": "寒热", "conclusion": cold_heat, "evidence": cold + heat},
            {"step": 3, "name": "虚实", "conclusion": xu_shi, "evidence": deficiency + excess},
            {"step": 4, "name": "津血", "conclusion": fluid,
             "blood": blood[0]["subtype"] if blood else "血证不显"},
            {"step": 5, "name": "气机", "conclusion": qi[0]["subtype"] if qi else "气机待辨"},
        ]

    @staticmethod
    def _dual_track(channels: list[dict], organs: list[dict],
                    four: list[dict]) -> dict:
        open_channel = channels[0] if channels else None
        fill_organ = organs[0] if organs else None
        steps = []
        if open_channel:
            steps.append({
                "step": 1,
                "action": "六经开路",
                "target": open_channel["channel"],
                "formula": open_channel["formula"],
                "note": open_channel["note"],
            })
        else:
            steps.append({
                "step": 1,
                "action": "六经开路",
                "target": "待辨",
                "formula": "先辨表里寒热虚实",
                "note": "信息不足，先补四诊，不急于补益。",
            })
        if fill_organ:
            steps.append({
                "step": 2,
                "action": "五脏填补",
                "target": f"{fill_organ['organ']}虚",
                "formula": fill_organ["formula"],
                "note": fill_organ["note"],
            })
        else:
            steps.append({
                "step": 2,
                "action": "五脏填补",
                "target": "待辨",
                "formula": "路通后再辨五脏",
                "note": "未见明确五脏虚象，不预设补方。",
            })
        steps.append({
            "step": 3,
            "action": "收功",
            "target": "水火既济",
            "formula": "阳谷+太渊 / 阴谷+足三里 / 足临泣+公孙",
            "note": "丙辛化水、戊癸化火、甲己化土，三组轮换取用。",
        })
        return {
            "principle": "以六经调阴阳，以五脏补气血；先通后补，双规并重。",
            "steps": steps,
            "sequence": "开路 3-7 剂 → 路通即止 → 五脏填补 → 水火收功",
            "four_syndrome_focus": four[0] if four else None,
        }

    @staticmethod
    def _external_score(channels: list[dict]) -> int:
        weights = {"太阳病": 2, "阳明病": 2, "少阳病": 1}
        return sum(item["score"] * weights[item["channel"]]
                   for item in channels if item["channel"] in weights)

    @staticmethod
    def _internal_score(channels: list[dict], organs: list[dict]) -> int:
        weights = {"太阴病": 2, "少阴病": 2, "厥阴病": 2}
        channel_score = sum(item["score"] * weights[item["channel"]]
                            for item in channels if item["channel"] in weights)
        organ_score = sum(item["score"] for item in organs)
        return channel_score + organ_score

    @staticmethod
    def _type(external: int, internal: int) -> str:
        if external >= 3 and internal >= 3:
            return "外感内伤合病"
        if external >= 3:
            return "外感为主"
        if internal >= 3:
            return "内伤为主"
        return "待辨"

    @staticmethod
    def _cautions(text: str, channels: list[dict], organs: list[dict]) -> list[str]:
        cautions = [
            "见虚不蛮补：先查六经是否通畅，路不通则补药壅塞生热。",
            "开路过久伤正：通常 3-7 剂，路通即止，转五脏填补。",
            "表解即止，不可过汗；过汗则正气更虚。",
            "方药剂量、煎服法与加减须由执业中医师决定。",
        ]
        if any(item["channel"] == "少阳病" for item in channels) and organs:
            cautions.append("少阳未解兼五脏虚：先和解少阳，再议补益。")
        if "出血" in text or "吐衄" in text or "发斑" in text:
            cautions.append("见血热出血：先清热凉血止血，勿用温补与活血太过。")
        if "高热" in text or "谵语" in text or "意识" in text:
            cautions.append("高热/谵语/意识改变：优先现代医学评估，勿延误。")
        return cautions

    # ------------------------------------------------------------------
    @staticmethod
    def format_text(report: dict) -> str:
        lines = [
            "=" * 56,
            "        三观四证 · 内伤外感双规辨证",
            "=" * 56,
            f"主诉：{report['symptoms']}",
        ]
        if report["pulse"]:
            lines.append(f"脉象：{report['pulse']}")
        if report["tongue"]:
            lines.append(f"舌象：{report['tongue']}")
        lines.append(f"类型：{report['type']}")
        lines.append("-" * 56)
        lines.append("【三观】")
        for name, info in report["three_views"].items():
            lines.append(f"  {name}：{info['conclusion']}")
            if info.get("note"):
                lines.append(f"    {info['note']}")
        lines.append("-" * 56)
        lines.append("【病机约分五步】")
        for step in report.get("differentiation_steps", []):
            lines.append(f"  {step['step']}. {step['name']}：{step['conclusion']}")
        lines.append("-" * 56)
        lines.append("【四证】")
        if report["four_syndromes"]:
            for item in report["four_syndromes"][:5]:
                lines.append(
                    f"  {item['category']}·{item['subtype']}（{item['score']}）"
                    f"｜{item['formula']}"
                )
                lines.append(f"    依据：{'、'.join(item['evidence'])}")
        else:
            lines.append("  未见明确四证指向，需补四诊。")
        lines.append("-" * 56)
        lines.append("【六经开路】")
        for item in report["six_channels"][:4]:
            lines.append(
                f"  {item['channel']}（{item['score']}）｜{item['formula']}"
                f"｜{'、'.join(item['points'])}"
            )
        if not report["six_channels"]:
            lines.append("  未见明确六经指向。")
        lines.append("-" * 56)
        lines.append("【五脏填补】")
        for item in report["organs"][:4]:
            lines.append(
                f"  {item['organ']}（{item['score']}）｜{item['formula']}"
                f"｜{'、'.join(item['points'])}"
            )
        if not report["organs"]:
            lines.append("  未见明确五脏虚象。")
        if report["composite_patterns"]:
            lines.append("-" * 56)
            lines.append("【复合病机】")
            for item in report["composite_patterns"][:3]:
                lines.append(f"  {item['name']}｜{item['formula']}")
                lines.append(f"    {item['note']}")
        lines.append("-" * 56)
        lines.append("【双规次序】")
        for step in report["dual_track"]["steps"]:
            lines.append(
                f"  {step['step']}. {step['action']} → {step['target']}"
                f"｜{step['formula']}"
            )
        lines.append(f"  节奏：{report['dual_track']['sequence']}")
        lines.append("-" * 56)
        lines.append("【针法】")
        acu = report["acupuncture"]
        lines.append(f"  开路：{'、'.join(acu['open_road']) or '待辨'}")
        lines.append(f"  填补：{'、'.join(acu['fill']) or '待辨'}")
        lines.append(f"  收功：{'、'.join(acu['closing'])}")
        lines.append(f"  {acu['closing_note']}")
        lines.append("-" * 56)
        lines.append("【禁忌】")
        for item in report["cautions"]:
            lines.append(f"  · {item}")
        lines.append("=" * 56)
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="三观四证·内伤外感双规辨证引擎")
    parser.add_argument("symptoms", nargs="*", help="症状描述")
    parser.add_argument("--pulse", default="", help="脉象")
    parser.add_argument("--tongue", default="", help="舌象")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    symptoms = " ".join(args.symptoms).strip()
    if not symptoms:
        symptoms = input("请输入症状：").strip()

    report = DualTrackEngine().analyze(symptoms, args.pulse, args.tongue)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(DualTrackEngine.format_text(report))


if __name__ == "__main__":
    main()
