"""北斗七星针法处方引擎 — 对齐 Python ``acupuncture_planner.py``

七星照路：天枢膻中 / 天璇神门 / 天玑期门 / 天权关元 / 玉衡(太溪|太白) / 开阳(太冲|足三里) / 摇光三阴交

仅使用 Python 标准库。Rust 的 struct 翻译为 ``@dataclass``，``HashMap`` 翻译为 ``dict``，
``Vec`` 翻译为 ``list``，``&'static str`` 翻译为字符串常量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class Acupoint:
    """单穴信息。"""

    name: str
    meridian: str
    technique: str
    depth_fen: int
    function: str
    indication: str


# 北斗七星主穴表：(星名, 穴)
STAR_ACUPOINTS: List[Tuple[str, Acupoint]] = [
    (
        "天枢",
        Acupoint("膻中", "任脉", "补法", 7, "开上焦气门", "胸闷打嗝"),
    ),
    (
        "天璇",
        Acupoint("神门", "心经", "补法", 9, "敛心安神", "焦虑失眠"),
    ),
    (
        "天玑",
        Acupoint("期门", "肝经", "泄法", 2, "疏肝定惊", "胁痛烦躁"),
    ),
    (
        "天权",
        Acupoint("关元", "任脉", "灸法", 4, "引火归元温阳", "虚寒"),
    ),
    (
        "玉衡",
        Acupoint("太溪", "肾经", "补法", 6, "滋肾纳气", "肾虚脾虚"),
    ),
    (
        "开阳",
        Acupoint("太冲", "肝经", "平补平泄", 7, "调肝舒筋", "肝郁胃胀"),
    ),
    (
        "摇光",
        Acupoint("三阴交", "脾经", "补法", 9, "收三阴固本", "五脏皆虚"),
    ),
]


def star_alternatives(star: str) -> List[Acupoint]:
    """玉衡/开阳可选穴。其它星返回空列表。"""
    if star == "玉衡":
        return [
            Acupoint("太白", "脾经", "补法", 6, "健脾益气", "脾虚"),
            Acupoint("太溪", "肾经", "补法", 6, "滋肾阴", "肾虚"),
        ]
    if star == "开阳":
        return [
            Acupoint("足三里", "胃经", "补法", 7, "健胃和胃", "胃胀打嗝"),
            Acupoint("太冲", "肝经", "平补平泄", 7, "疏肝解郁", "肝郁焦虑"),
        ]
    return []


@dataclass
class SyndromeMapEntry:
    """病证 → 玉衡/开阳配穴。"""

    yuheng: str
    kaiyang: str
    rationale: str


def syndrome_map(syn: str) -> SyndromeMapEntry:
    if syn == "太阴病":
        return SyndromeMapEntry(
            "太白", "足三里", "太阴脾虚—玉衡太白健脾，天权灸关元温阳"
        )
    if syn == "少阴病":
        return SyndromeMapEntry(
            "太溪", "太冲", "少阴肾虚—玉衡太溪滋肾，天权灸关元，天璇安神"
        )
    if syn == "厥阴病":
        return SyndromeMapEntry(
            "太溪", "太冲", "厥阴肝郁—天玑期门泻肝，开阳太冲舒筋"
        )
    return SyndromeMapEntry(
        "太白", "足三里", "合病—先灸关元固本，摇光收三阴"
    )


def addition_rules() -> Dict[str, List[str]]:
    """配穴加减规则（保持 Rust 字面量插入顺序，保证确定性）。"""
    return {
        "焦虑": ["印堂(补)", "大陵(泻)"],
        "打嗝": ["内关(补)", "公孙(补)"],
        "失眠": ["印堂(补)"],
        "纳差": ["中脘(补)", "足三里(补)"],
        "腹胀": ["天枢(泻)", "气海(补)"],
        "完谷不化": ["脾俞(灸)", "胃俞(灸)"],
        "胸闷": ["内关(泻)"],
        "咳嗽": ["肺俞(补)", "列缺(补)"],
    }


def _pick(alts: List[Acupoint], name: str) -> Acupoint:
    """从可选穴列表中按名选取（找不到取第一个）。"""
    for a in alts:
        if a.name == name:
            return a
    return alts[0]


def detect_syndrome(liujing_result: str, syndrome_name: str, symptoms: List[str]) -> str:
    """病证识别（与 Python ``_detect`` 一致）。"""
    joined = " ".join(symptoms)
    if syndrome_name:
        for s in ("太阴病", "少阴病", "厥阴病"):
            if s in syndrome_name:
                return s
    if liujing_result:
        for s in ("太阴病", "少阴病", "厥阴病"):
            if s in liujing_result:
                return s
    if "完谷" in joined or "腹胀" in joined or "纳差" in joined:
        return "太阴病"
    if "焦虑" in joined or "胁" in joined:
        return "厥阴病"
    if "脉沉" in joined or "腰" in joined:
        return "少阴病"
    return "太阴病"


def additions(symptoms: List[str]) -> List[str]:
    """生成配穴加减（去重保序）。"""
    rules = addition_rules()
    adds: List[str] = []
    for sym in symptoms:
        for k, vs in rules.items():
            if k in sym:
                for v in vs:
                    if v not in adds:
                        adds.append(v)
    return adds


def moxibustion(symptoms: List[str]) -> List[str]:
    """艾灸方案。"""
    m: List[str] = ["关元30壮"]
    joined = " ".join(symptoms)
    if "完谷" in joined:
        m.append("脾俞15壮(双)")
        m.append("胃俞15壮(双)")
    m.append("足三里15壮(双)")
    return m


def verse(syndrome: str) -> str:
    """七言要诀（病证 → 诀）。"""
    table = {
        "太阴病": (
            "太阴脾虚运化艰，七星玉衡太白转|天权关元灸火起，摇光三阴固本元|"
            "开阳三里和胃气，天枢膻中气门宽|三周调理太阴复，中州运化自归衡"
        ),
        "少阴病": (
            "少阴精亏脉沉弱，玉衡太溪滋肾阴|天权关元引火归，天璇神门敛心神|"
            "开阳太冲舒筋血，天枢膻中开气门|七星照路坎水济，三周调养元自还"
        ),
        "厥阴病": (
            "厥阴气逆风木动，天玑期门泻实邪|开阳太冲调肝血，天璇安定神魂谐|"
            "天枢开胸膻中启，三阴交合摇光接|七星阵转生阳复，春回大地冰雪解"
        ),
    }
    return table.get(syndrome, "七星照路，辨证施针")


@dataclass
class Formula:
    """完整七星针法处方（对齐 Python ``AcupuncturePlanner.plan`` 的确定性输出）。"""

    syndrome_name: str
    stars: List[Tuple[str, str, str, str]]  # (北斗星, 穴, 归经, 手法)
    rationale: str
    order: List[str]
    additions: List[str]
    moxibustion: List[str]
    course_plan: List[str]
    summary_verse: str


def plan(liujing_result: str, symptoms: List[str], syndrome_name: str) -> Formula:
    """规划处方。

    :param liujing_result: 六经辨证结果（如 "少阳病"）
    :param symptoms: 症状列表
    :param syndrome_name: 外部指定病证名（非空时优先采用）
    """
    syn = detect_syndrome(liujing_result, syndrome_name, symptoms)
    m = syndrome_map(syn)

    # 七星主穴（玉衡/开阳按病证选穴）
    yuheng = _pick(star_alternatives("玉衡"), m.yuheng)
    kaiyang = _pick(star_alternatives("开阳"), m.kaiyang)
    tianshu = STAR_ACUPOINTS[0][1]
    tianxuan = STAR_ACUPOINTS[1][1]
    tianji = STAR_ACUPOINTS[2][1]
    tianquan = STAR_ACUPOINTS[3][1]
    yaoguang = STAR_ACUPOINTS[6][1]

    stars: List[Tuple[str, str, str, str]] = [
        ("天枢", tianshu.name, tianshu.meridian, tianshu.technique),
        ("天璇", tianxuan.name, tianxuan.meridian, tianxuan.technique),
        ("天玑", tianji.name, tianji.meridian, tianji.technique),
        ("玉衡", yuheng.name, yuheng.meridian, yuheng.technique),
        ("天权", tianquan.name, tianquan.meridian, tianquan.technique),
        ("开阳", kaiyang.name, kaiyang.meridian, kaiyang.technique),
        ("摇光", yaoguang.name, yaoguang.meridian, yaoguang.technique),
    ]

    # 针序（Python _order：开气门→泻→安神→补→灸）
    order: List[str] = []
    for s in stars:
        if s[0] == "天枢":
            order.append(f"{s[1]}(开气门)")
    for s in stars:
        if s[3] == "泄法":
            order.append(f"{s[1]}(泻)")
    for s in stars:
        if s[0] == "天璇":
            order.append(f"{s[1]}(安神)")
    for s in stars:
        if s[3] == "补法" and s[0] != "天枢" and s[0] != "天璇":
            order.append(f"{s[1]}(补)")
    for s in stars:
        if s[3] == "灸法":
            order.append(f"{s[1]}(灸)")

    return Formula(
        syndrome_name=syn,
        stars=stars,
        rationale=f"七星照路，以{syn}为纲",
        order=order,
        additions=additions(symptoms),
        moxibustion=moxibustion(symptoms),
        course_plan=[
            "阶段A(7次): 每日一次",
            "阶段B(7次): 隔日一次",
            "阶段C(7次): 每周2次",
        ],
        summary_verse=verse(syn),
    )


def rx_pick_for_jing(main_jing: str) -> List[Tuple[str, str]]:
    """三元夹诊专用：按主经取玉衡/开阳配穴（对齐 build_rx 的针部逻辑）。"""
    syn = {"太阴": "太阴病", "少阴": "少阴病", "厥阴": "厥阴病"}.get(
        main_jing, "合病"
    )
    m = syndrome_map(syn)
    out: List[Tuple[str, str]] = []
    yuheng = _pick(star_alternatives("玉衡"), m.yuheng)
    out.append((yuheng.name, yuheng.function))
    kaiyang = _pick(star_alternatives("开阳"), m.kaiyang)
    out.append((kaiyang.name, kaiyang.function))
    return out
