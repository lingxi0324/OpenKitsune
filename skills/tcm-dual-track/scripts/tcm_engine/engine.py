# -*- coding: utf-8 -*-
"""
TCM Clinical Engine — 体用相悖检测 + 火候次第推荐
（Python 原生翻译自 engine.rs）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .clinical_types import (
    ContradictionResult,
    EvidenceDetail,
    EvidenceItem,
    FireRecommendation,
    FireStage,
    FireStep,
    MatchedPattern,
    ParadoxPattern,
    PulseMatch,
    SymptomMapEntry,
    SymptomMatch,
    TongueMatch,
)


# ════════════════════════════════════════════════════════════════════════════
# 症状 -> 体用翻译表 (SYMPTOM_MAP)，键按长度降序
# ════════════════════════════════════════════════════════════════════════════

_RAW_SYMPTOM_MAP = [
    # ── 舌体 → 体 ──
    ("舌淡", SymptomMapEntry("寒", "体", -0.5, 0.8, "血体不足/火体不充")),
    ("舌淡胖", SymptomMapEntry("寒", "体", -0.7, 0.9, "火体不足（虚寒底子）")),
    ("舌红", SymptomMapEntry("热", "体", 0.6, 0.8, "火用亢/水体不足")),
    ("舌红瘦", SymptomMapEntry("热", "体", 0.4, 0.7, "阴虚有热（虚热）")),
    ("舌紫暗", SymptomMapEntry("瘀", "体", -0.4, 0.7, "脉体瘀（血瘀）")),
    ("舌有齿痕", SymptomMapEntry("痰", "体", -0.3, 0.6, "土体湿（脾体湿盛）")),
    ("舌有裂纹", SymptomMapEntry("阴", "体", -0.5, 0.7, "水体不足（阴虚津亏）")),
    # ── 舌苔 → 用 ──
    ("苔白滑", SymptomMapEntry("寒", "用", -0.5, 0.7, "寒湿（寒证明显）")),
    ("苔白", SymptomMapEntry("寒", "用", -0.3, 0.5, "寒/无热象")),
    ("苔黄腻", SymptomMapEntry("热", "用", 0.7, 0.9, "湿热/郁热（用热明显）")),
    ("苔黄", SymptomMapEntry("热", "用", 0.5, 0.7, "热")),
    ("苔黄燥", SymptomMapEntry("热", "用", 0.7, 0.8, "热甚伤津")),
    ("苔腻", SymptomMapEntry("痰", "用", 0.4, 0.6, "土体湿（湿浊不化）")),
    ("苔腐", SymptomMapEntry("热", "用", 0.6, 0.7, "发酵已成（浊毒上泛）")),
    ("苔燥", SymptomMapEntry("阴", "用", -0.5, 0.6, "津液耗伤")),
    ("苔剥脱", SymptomMapEntry("阴", "用", -0.7, 0.8, "胃阴/肾阴枯竭")),
    ("苔少", SymptomMapEntry("阴", "用", -0.5, 0.6, "阴伤/胃气不足")),
    ("少苔", SymptomMapEntry("阴", "用", -0.5, 0.6, "阴伤/胃气不足")),
    # ── 脉 → 体/用 ──
    ("脉浮", SymptomMapEntry("气", "用", 0.3, 0.5, "邪在表/虚阳浮越")),
    ("脉沉", SymptomMapEntry("气", "体", -0.3, 0.5, "邪在里/体不足")),
    ("脉迟", SymptomMapEntry("寒", "体", -0.4, 0.6, "火体不足（寒证）")),
    ("脉数无力", SymptomMapEntry("热", "用", 0.3, 0.6, "虚热（真热假寒/虚阳）")),
    ("脉数", SymptomMapEntry("热", "用", 0.5, 0.7, "火用亢（热证）")),
    ("脉滑数无力", SymptomMapEntry("热", "用", 0.3, 0.6, "虚热（正虚邪恋）")),
    ("脉滑数", SymptomMapEntry("热", "用", 0.6, 0.8, "湿热/实热")),
    ("脉滑", SymptomMapEntry("痰", "用", 0.4, 0.6, "土体湿/实热")),
    ("脉涩", SymptomMapEntry("瘀", "体", -0.4, 0.6, "血瘀/津亏")),
    ("脉弦", SymptomMapEntry("气", "体", -0.3, 0.6, "肝气郁/痛证")),
    ("脉细", SymptomMapEntry("阴", "体", -0.4, 0.6, "阴虚/血虚")),
    ("脉洪大", SymptomMapEntry("热", "用", 0.8, 0.8, "阳明热盛")),
    ("脉洪", SymptomMapEntry("热", "用", 0.7, 0.7, "火用太过（实热）")),
    ("脉弱", SymptomMapEntry("气", "体", -0.5, 0.7, "气虚/阳衰")),
    ("脉沉弱", SymptomMapEntry("气", "体", -0.5, 0.7, "正虚（气体不足）")),
    ("脉沉迟", SymptomMapEntry("寒", "体", -0.5, 0.7, "虚寒（体寒明显）")),
    # ── 症状 → 体/用 ──
    ("畏寒", SymptomMapEntry("寒", "体", -0.6, 0.8, "火体不足")),
    ("怕热", SymptomMapEntry("热", "用", 0.6, 0.7, "火用亢")),
    ("口臭", SymptomMapEntry("热", "用", 0.5, 0.7, "浊气上泛")),
    ("大便黏", SymptomMapEntry("痰", "体", -0.4, 0.6, "土体湿")),
    ("大便溏", SymptomMapEntry("寒", "体", -0.4, 0.6, "火体不足/土体湿")),
    ("大便干", SymptomMapEntry("阴", "体", -0.4, 0.6, "水体不足")),
    ("口干", SymptomMapEntry("热", "用", 0.3, 0.5, "津不上承")),
    ("乏力", SymptomMapEntry("气", "体", -0.5, 0.7, "气体不足")),
    ("心烦", SymptomMapEntry("热", "用", 0.4, 0.5, "火用浮越")),
    ("失眠", SymptomMapEntry("热", "用", 0.3, 0.5, "心肾不交")),
    ("自汗", SymptomMapEntry("气", "体", -0.4, 0.6, "卫用不密")),
    ("恶心", SymptomMapEntry("痰", "用", -0.3, 0.5, "湿浊犯胃")),
    ("纳呆", SymptomMapEntry("气", "体", -0.3, 0.5, "土体不运")),
    ("胸闷", SymptomMapEntry("气", "体", -0.3, 0.5, "气机不畅")),
    ("腰冷", SymptomMapEntry("寒", "体", -0.5, 0.7, "肾阳虚")),
    ("足冷", SymptomMapEntry("寒", "体", -0.4, 0.6, "阳气不达四末")),
    ("口疮", SymptomMapEntry("热", "用", 0.5, 0.6, "虚火上炎")),
    ("咽痛", SymptomMapEntry("热", "用", 0.4, 0.5, "火用上扰")),
    ("面红", SymptomMapEntry("热", "用", 0.4, 0.5, "虚阳上浮")),
    ("盗汗", SymptomMapEntry("阴", "体", -0.4, 0.6, "阴虚不敛阳")),
    ("胸腹灼热", SymptomMapEntry("热", "体", 0.7, 0.8, "内热炽盛")),
    ("四肢冷", SymptomMapEntry("寒", "用", -0.6, 0.7, "阳不外达")),
    ("腰酸", SymptomMapEntry("阴", "体", -0.4, 0.6, "肾精不足")),
]

# 键按长度降序（最长匹配优先），稳定排序保持原始次序
SYMPTOM_MAP: List[tuple] = sorted(_RAW_SYMPTOM_MAP, key=lambda kv: -len(kv[0]))


# ════════════════════════════════════════════════════════════════════════════
# 体用相悖模式库 (PARADOX_PATTERNS)
# ════════════════════════════════════════════════════════════════════════════

PARADOX_PATTERNS: List[ParadoxPattern] = [
    ParadoxPattern(
        name="虚寒发酵（湿热发酵模型）",
        pattern={"体": "寒", "用": "热"},
        舌象_match=TongueMatch(
            舌质=["淡", "淡胖"],
            苔=["黄", "黄腻", "黄厚"],
        ),
        脉象_match=PulseMatch(脉=["滑", "数", "滑数", "滑数无力"]),
        symptom_match=SymptomMatch(
            体寒=["畏寒", "乏力", "大便溏"],
            用热=["口臭", "心烦", "口干"],
        ),
        description="虚寒底子+郁热发酵=典型的体用相悖",
        体用口诀="体寒用热，舌淡胖苔黄腻",
        发酵阶段="③郁热→④腐化",
        代表方="半夏泻心汤+平胃散+败酱草",
        治法原则="温体不助热（干姜/白术），泄用不伤体（竹茹/黄芩）",
        误治风险={
            "纯清热": "冰伏虚火→发酵更甚",
            "纯温补": "火上浇油→热毒内陷",
            "纯化湿": "无济于事→发酵已非湿邪",
        },
    ),
    ParadoxPattern(
        name="痰湿阻遏虚火",
        pattern={"体": "热", "用": "寒"},
        舌象_match=TongueMatch(
            舌质=["红", "红瘦"],
            苔=["白", "白厚", "白腻"],
        ),
        脉象_match=PulseMatch(脉=["沉", "滑", "沉滑"]),
        symptom_match=SymptomMatch(
            体热=["怕热", "口干", "心烦"],
            用寒=["大便溏", "纳呆", "胸闷"],
        ),
        description="热体+寒用→痰湿阻遏气机，火郁于内",
        体用口诀="体热用寒，舌红苔白厚",
        发酵阶段="",
        代表方="温胆汤+连翘（透热达表）",
        治法原则="透热为主，化湿为辅。不可过热",
        误治风险={
            "误用温热": "助热内陷",
            "过分苦寒": "冰伏气机",
        },
    ),
    ParadoxPattern(
        name="阴虚火旺（水不制火）",
        pattern={"体": "虚", "用": "亢"},
        舌象_match=TongueMatch(
            舌质=["红", "红瘦", "红干"],
            苔=["少", "剥", "燥", "无"],
        ),
        脉象_match=PulseMatch(脉=["细", "数", "细数"]),
        symptom_match=SymptomMatch(
            体虚=["乏力", "腰酸", "盗汗"],
            用亢=["心烦", "失眠", "口干", "怕热"],
        ),
        description="物质储备不足（体虚）→功能代偿亢进（用亢）",
        体用口诀="体虚用亢，舌红少苔脉细数",
        发酵阶段="",
        代表方="六味地黄丸+知母+地骨皮",
        治法原则="补体为主（滋阴），泄用为辅（降虚火）",
        误治风险={
            "过度降火": "伤正→更虚",
            "纯补不泄": "虚火更盛",
        },
    ),
    ParadoxPattern(
        name="上热下寒（阴阳格拒）",
        pattern={"体": "寒（下）", "用": "热（上）"},
        舌象_match=TongueMatch(
            舌质=["淡", "淡胖"],
            苔=["白", "滑"],
        ),
        脉象_match=PulseMatch(脉=["浮", "数", "沉"]),
        symptom_match=SymptomMatch(
            上热=["口疮", "咽痛", "面红", "心烦"],
            下寒=["畏寒", "腰冷", "便溏", "足冷"],
        ),
        description="下焦虚寒→虚阳上浮→上焦假热",
        体用口诀="上热下寒，寸浮尺沉",
        发酵阶段="",
        代表方="交泰丸（黄连+肉桂）+潜阳丹",
        治法原则="引火归元，温下清上",
        误治风险={
            "清上过度": "引邪入下→寒更甚",
            "温下过度": "热更浮越",
        },
    ),
    ParadoxPattern(
        name="真热假寒（热深厥深）",
        pattern={"体": "热", "用": "寒"},
        舌象_match=TongueMatch(
            舌质=["红", "绛", "深红"],
            苔=["黄", "黄燥", "焦"],
        ),
        脉象_match=PulseMatch(脉=["沉", "伏", "沉滑有力"]),
        symptom_match=SymptomMatch(
            体热=["胸腹灼热", "口渴"],
            用寒=["四肢冷", "恶寒"],
        ),
        description="热郁于内→阳不外达→四肢假寒",
        体用口诀="真热假寒，胸腹灼热四肢冷",
        发酵阶段="",
        代表方="白虎汤类（石膏为君）",
        治法原则="透热达表，不可误用温热",
        误治风险={
            "误用温热": "热毒内陷→危证",
            "误用发汗": "火上浇油",
        },
    ),
]


# ════════════════════════════════════════════════════════════════════════════
# 体用检测器
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ContradictionDetector:
    evidence_ti: List[EvidenceItem] = field(default_factory=list)
    evidence_yong: List[EvidenceItem] = field(default_factory=list)
    ti_score: float = 0.0
    yong_score: float = 0.0
    matched_patterns: List[MatchedPattern] = field(default_factory=list)
    detection_log: List[str] = field(default_factory=list)

    def add_symptom(self, text: str) -> None:
        """添加一条症状/舌/脉文本并自动匹配翻译表"""
        for key, entry in SYMPTOM_MAP:
            if key in text:
                scored_val = entry.val * entry.weight
                item = EvidenceItem(
                    source=text,
                    key=key,
                    dim=entry.dim,
                    type=entry.type,
                    val=scored_val,
                    weight=entry.weight,
                    label=entry.label,
                )
                if entry.type == "体":
                    self.evidence_ti.append(item)
                    self.ti_score += scored_val
                else:
                    self.evidence_yong.append(item)
                    self.yong_score += scored_val
                self.detection_log.append(
                    f"  [+] {entry.type}·{entry.dim}: {key} → "
                    f"{entry.label} ({scored_val:+.2f})")
                return
        self.detection_log.append(f"  [·] {text} → 未匹配")

    @staticmethod
    def _classify(score: float):
        """定性: 返回 (方向, 幅度)"""
        if score < -0.8:
            return ("寒/虚/郁", "极")
        if score < -0.4:
            return ("寒/虚/郁", "显")
        if score < -0.15:
            return ("微寒/虚", "轻")
        if score > 0.8:
            return ("热/实/亢", "极")
        if score > 0.4:
            return ("热/实/亢", "显")
        if score > 0.15:
            return ("微热/亢", "轻")
        return ("平和", "无")

    def _match_patterns(self, tongue: str, coat: str, pulse: str,
                         symptoms: str) -> None:
        """匹配预设体用相悖模式"""
        if self.ti_score * self.yong_score >= 0.0:
            return

        for pattern in PARADOX_PATTERNS:
            score = 0.0
            max_score = 0.0

            # 舌质匹配
            if tongue:
                max_score += 3.0
                for kw in pattern.舌象_match.舌质:
                    if kw in tongue:
                        score += 3.0
                        break

            # 舌苔匹配
            if coat:
                max_score += 2.0
                for kw in pattern.舌象_match.苔:
                    if kw in coat:
                        score += 2.0
                        break

            # 脉象匹配
            if pulse:
                max_score += 2.0
                for kw in pattern.脉象_match.脉:
                    if kw in pulse:
                        score += 2.0
                        break

            # 症状匹配（体侧/用侧各 +1）
            if symptoms:
                max_score += 2.0
                sm = pattern.symptom_match
                all_kws = [
                    sm.体寒, sm.用热, sm.体热, sm.用寒,
                    sm.体虚, sm.用亢, sm.上热, sm.下寒,
                ]
                for side_kws in all_kws:
                    for kw in side_kws:
                        if kw in symptoms:
                            score += 1.0
                            break

            if max_score > 0.0:
                confidence = min(score / max_score, 1.0)
                if confidence >= 0.4:
                    self.matched_patterns.append(MatchedPattern(
                        模式=pattern.name,
                        置信度=f"{confidence * 100.0:.0f}%",
                        描述=pattern.description,
                        体用口诀=pattern.体用口诀,
                        代表方=pattern.代表方,
                        治法原则=pattern.治法原则,
                        发酵阶段=pattern.发酵阶段,
                        误治风险=dict(pattern.误治风险),
                    ))

    def detect(self, tongue: str, coat: str, pulse: str,
               symptoms: str) -> ContradictionResult:
        """运行体用相悖检测"""
        inputs: List[str] = []
        if tongue:
            inputs.append(f"舌{tongue}")
        if coat:
            inputs.append(f"苔{coat}")
        if pulse:
            inputs.append(f"脉{pulse}")
        if symptoms:
            for s in symptoms.replace("，", ",").replace(" ", ",").split(","):
                if s:
                    inputs.append(s)

        for inp in inputs:
            self.add_symptom(inp)

        ti_qual = self._classify(self.ti_score)
        yong_qual = self._classify(self.yong_score)

        ti_sign = 1 if self.ti_score >= 0.0 else -1
        yong_sign = 1 if self.yong_score >= 0.0 else -1
        ti_mag = min(abs(self.ti_score), 1.0)
        yong_mag = min(abs(self.yong_score), 1.0)

        # 体用分类：同向=一致，异向=偏颇/相悖
        if ti_sign == yong_sign:
            # 同向（俱寒或俱热）→ 体用一致
            tiyong_type = "体用一致"
        else:
            # 异向（体寒用热/体热用寒）→ 偏颇或相悖
            max_mag = max(ti_mag, yong_mag)
            if max_mag > 0.7:
                tiyong_type = "体用相悖（重）"
            else:
                tiyong_type = "体用偏颇（轻）"

        self._match_patterns(tongue, coat, pulse, symptoms)

        return ContradictionResult(
            引擎版本="体用相悖检测器 v2.0 (Python)",
            体用三型=tiyong_type,
            体总分=f"{self.ti_score:+.2f}",
            用总分=f"{self.yong_score:+.2f}",
            势能差=f"{abs(self.ti_score - self.yong_score):.2f}",
            体判定=f"{ti_qual[0]}体（幅度{ti_qual[1]}）",
            用判定=f"{yong_qual[0]}用（幅度{yong_qual[1]}）",
            匹配模式=self.matched_patterns,
            检测日志=self.detection_log,
            证据明细=EvidenceDetail(
                体证据=self.evidence_ti,
                用证据=self.evidence_yong,
            ),
        )


# ════════════════════════════════════════════════════════════════════════════
# 火候次第推荐器
# ════════════════════════════════════════════════════════════════════════════

FIRE_STAGES: Dict[str, FireStage] = {
    "武火": FireStage("10/10 极强", "急则治标·强力攻邪·峻剂", "🔥",
                      "药味多·剂量大·药力猛·剂数少(3-5剂)"),
    "文火": FireStage("6/10 温和", "缓则治本·渐调体质·平剂", "♨️",
                      "药味精·剂量中·药力缓·剂数多(7-14剂)"),
    "止火": FireStage("0/10 暂停", "停药观察·验证疗效·休整", "⏸️",
                      "不药·食疗·导引·情志调摄"),
    "沐浴": FireStage("4/10 疏泄", "行气化湿·疏通经络·透表", "🫧",
                      "轻宣·芳香·理气·以通为用"),
    "退符": FireStage("2/10 收敛", "固涩收敛·滋阴潜阳·封藏", "🔽",
                      "收涩·酸敛·重镇·归元"),
}

# 体用型 -> 火候策略
TIYONG_FIRE_MAP: Dict[str, tuple] = {
    "体用一致": (
        "单一方向·体用同治",
        "体与用同向（俱寒/俱热），直接补或泻即可",
        "7-14天",
        "火候单一，注意不及或太过",
    ),
    "体用偏颇": (
        "补偏救弊·偏用偏治",
        "一方偏亢一方偏弱，先平亢再补弱",
        "14-21天",
        "次序颠倒会加重偏颇",
    ),
    "体用相悖": (
        "分消双轨·标本异治",
        "体与用反向（体寒用热/体热用寒），需双轨分消",
        "21-28天",
        "必须分步治疗，体用兼顾不当会相互牵制",
    ),
}

# 湿热发酵阶段 -> 火候阶段
FERMENTATION_MAP: Dict[str, tuple] = {
    "阶段①湿蕴": ("沐浴", "芳化逐秽", "藿香正气散类", "5-7剂"),
    "阶段②气滞": ("沐浴+文火", "行气化湿", "平胃散+二陈汤", "5-7剂"),
    "阶段③郁热": ("武火", "辛开苦降", "半夏泻心汤类", "5-7剂"),
    "阶段④腐化": ("武火+文火", "逐秽开郁透毒", "半夏泻心汤+败酱草", "7-10剂"),
    "阶段⑤毒成": ("武火(急)+文火(缓)", "透毒排脓+扶正",
                  "五味消毒饮+托里消毒散", "10-14剂"),
}

# 体质 -> 火候偏好
CONSTITUTION_FIRE: Dict[str, tuple] = {
    "气虚质": ("忌武火过汗/过下", "文火为主，辅以沐浴"),
    "阳虚质": ("忌武火过泄/过寒", "文火+退符"),
    "阴虚质": ("忌武火过燥/过热", "文火+退符"),
    "痰湿质": ("忌大补/滋腻", "沐浴为主"),
    "湿热质": ("忌温补", "武火+沐浴"),
    "血瘀质": ("忌寒凝/呆补", "沐浴+文火"),
    "气郁质": ("忌收敛/补涩", "沐浴为主"),
    "特禀质": ("忌大热/大寒/大补", "文火"),
    "平和质": ("无特殊", "随证治之"),
}

# 发酵阶段别名
FERMENTATION_ALIASES: Dict[str, str] = {
    "阶段1湿蕴": "阶段①湿蕴",
    "阶段2气滞": "阶段②气滞",
    "阶段3郁热": "阶段③郁热",
    "阶段4腐化": "阶段④腐化",
    "阶段5毒成": "阶段⑤毒成",
    "湿蕴": "阶段①湿蕴",
    "气滞": "阶段②气滞",
    "郁热": "阶段③郁热",
    "腐化": "阶段④腐化",
    "毒成": "阶段⑤毒成",
}

# 剂型表 (方名 -> 剂型描述)
JIXING: Dict[str, str] = {
    "交泰丸": "汤剂(原丸改汤, 缓调心肾)",
    "半夏泻心汤": "汤剂",
    "半夏泻心汤类": "汤剂",
    "半夏泻心汤+平胃散+败酱草": "汤剂合方",
    "半夏泻心汤+败酱草": "汤剂合方",
    "六味地黄丸": "丸剂(亦可汤)",
    "温胆汤": "汤剂",
    "温胆汤+连翘": "汤剂",
    "交泰丸（黄连+肉桂）": "汤剂(原丸改汤, 缓调心肾)",
    "潜阳丹": "散剂",
    "五味消毒饮": "汤剂",
    "白虎汤": "汤剂",
    "藿香正气散": "散剂(亦可汤)",
    "平胃散": "散剂",
    "平胃散+黄连": "汤剂",
    "败酱草": "单味",
    "连翘": "单味",
    "甘露消毒丹": "丸/散(亦可汤)",
    "茵陈蒿汤": "汤剂",
    "托里消毒散": "散剂",
}


class FireStageRecommender:
    """火候次第推荐器"""

    @staticmethod
    def _stage_entry(stage_name: str, reason: str) -> FireStep:
        base_name = stage_name.split("（")[0]
        info = FIRE_STAGES.get(base_name)
        # 从 reason 提取方名并查剂型
        jixing = ""
        for kw, jx in JIXING.items():
            if kw in reason:
                jixing = jx
                break

        return FireStep(
            火候=stage_name,
            理由=reason,
            用度范围=info.用度 if info else "",
            用药特征=info.用药特征 if info else "",
            剂型=jixing,
        )

    def recommend(self, tiyong_type: str, fermentation_phase: str,
                  constitution: str, specialty: str,
                  urgency: str, severity_level: str = "中") -> FireRecommendation:
        default_strategy = (
            "单一方向·体用同治",
            "体与用同向（俱寒/俱热），直接补或泻即可",
            "7-14天",
            "火候单一，注意不及或太过",
        )
        strategy = TIYONG_FIRE_MAP.get(tiyong_type, default_strategy)
        stages: List[FireStep] = []

        # 急症前置处理
        if urgency == "急":
            stages.append(self._stage_entry(
                "武火", "急则治标，先快速控制症状（3-5剂）"))

        # 发酵阶段处理
        fp = FERMENTATION_ALIASES.get(fermentation_phase, fermentation_phase)
        if fp and fp in FERMENTATION_MAP:
            ph = FERMENTATION_MAP[fp]
            stages.append(self._stage_entry(
                ph[0], f"发酵{fp}：{ph[1]}（{ph[2]}，{ph[3]}）"))

        # 体用相悖的特别多步处理（按严重程度分级）
        if tiyong_type == "体用相悖":
            severity_level = severity_level or "中"  # 默认中等
            if severity_level == "重":
                # 重证：急攻→缓调→观察，武火不可省
                stages.append(self._stage_entry(
                    "武火", "急则治标：先泄标邪解除当前困扰（5-7剂）"))
                stages.append(self._stage_entry(
                    "文火", "缓调体质：标邪去后，缓调体质底子（7-14剂）"))
                stages.append(self._stage_entry(
                    "止火", "停药观察：观察体用是否调和（3-5天）"))
                stages.append(self._stage_entry(
                    "退符", "固本培元：收摄浮阳，封藏根本（5-7剂）"))
            elif severity_level == "轻":
                # 轻证：缓攻→缓调→观察，以文火为主
                stages.append(self._stage_entry(
                    "文火", "缓泄标邪：体用相悖较轻，温和分消（5-7剂）"))
                stages.append(self._stage_entry(
                    "沐浴", "行气疏泄：疏通气机，透达郁热（3-5剂）"))
                stages.append(self._stage_entry(
                    "止火", "停药观察：观察体用是否调和（3-5天）"))
            else:
                # 中等：标准三步
                stages.append(self._stage_entry(
                    "武火", "先泄标邪：体用相悖，解除当前困扰（5-7剂）"))
                stages.append(self._stage_entry(
                    "文火", "后调体质：标邪去后，缓调体质底子（7-14剂）"))
                stages.append(self._stage_entry(
                    "止火", "停药观察：观察体用是否调和（3-5天）"))
        else:
            # 标准方案（体用一致/偏颇且无发酵）
            if urgency == "急":
                stages.append(self._stage_entry(
                    "文火", "急中求稳：虽急，仍需兼顾体质底子（5-7剂）"))
            stages.append(self._stage_entry(
                "文火", f"{tiyong_type}基础调理（7-14剂）"))
            stages.append(self._stage_entry(
                "止火", "停药观察：疗效评估（3-5天）"))

        # 体质调理（避免与主方案重复）
        constitution_advice = ""
        if constitution:
            ci = CONSTITUTION_FIRE.get(constitution)
            if ci:
                # 提取建议中的所有基础火候名（如"文火为主，辅以沐浴"→["文火", "沐浴"]）
                advised_parts = ci[1].split("，")
                advised_keywords = []
                for part in advised_parts:
                    for kw in ["武火", "文火", "止火", "沐浴", "退符"]:
                        if kw in part:
                            advised_keywords.append(kw)
                # 收集已有序列中所有基础火候名
                existing_stages = set()
                for s in stages:
                    base = s.火候.split("（")[0]
                    for kw in ["武火", "文火", "止火", "沐浴", "退符"]:
                        if base == kw or base.startswith(kw):
                            existing_stages.add(kw)
                # 如果建议的任何火候已在序列中，跳过避免重复
                if not any(kw in existing_stages for kw in advised_keywords):
                    constitution_advice = f"{constitution}：{ci[0]}，宜{ci[1]}"
                    stages.append(self._stage_entry(
                        "文火", f"体质调护：{constitution_advice}"))

        return FireRecommendation(
            体用型=tiyong_type,
            火候策略=strategy[0],
            策略说明=strategy[1],
            疗程=strategy[2],
            风险=strategy[3],
            体质=constitution_advice,
            火候序列=stages,
            专科方案={"专科": specialty},
        )

    @staticmethod
    def format(plan: FireRecommendation) -> str:
        lines: List[str] = []
        lines.append("  ╔══ 火候次第方案 ══╗")
        lines.append(f"  ║  体用型：{plan.体用型}")
        lines.append(f"  ║  策略：{plan.火候策略}")
        lines.append(f"  ║  疗程：{plan.疗程}")
        if plan.体质:
            lines.append(f"  ║  体质：{plan.体质}")
        lines.append("  ╠══ 火候序列 ══╣")
        n = len(plan.火候序列)
        for i, s in enumerate(plan.火候序列):
            base = s.火候.split("（")[0]
            emoji = FIRE_STAGES.get(base).符号 if base in FIRE_STAGES else "·"
            prefix = "├─" if i < n - 1 else "└─"
            lines.append(f"  ║  {prefix} {emoji} {s.火候}")
            lines.append(f"  ║  │  └ {s.理由}")
            if s.用度范围:
                lines.append(f"  ║  │    用度{s.用度范围}")
            if s.剂型:
                lines.append(f"  ║  │    剂型: {s.剂型}")
        lines.append("  ╚" + "═" * 40 + "╝")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# 统一入口函数
# ════════════════════════════════════════════════════════════════════════════

def detect_contradiction(tongue: str, coat: str, pulse: str,
                         symptoms: str) -> ContradictionResult:
    """detect_contradiction() — 体用相悖检测"""
    detector = ContradictionDetector()
    return detector.detect(tongue, coat, pulse, symptoms)


def recommend_fire(tiyong_type: str, fermentation_phase: str,
                   constitution: str, specialty: str,
                   urgency: str, severity_level: str = "中") -> FireRecommendation:
    """recommend_fire() — 火候次第推荐"""
    r = FireStageRecommender()
    return r.recommend(tiyong_type, fermentation_phase, constitution,
                       specialty, urgency, severity_level)
