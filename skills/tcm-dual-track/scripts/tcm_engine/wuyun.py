# -*- coding: utf-8 -*-
"""
Wuyun-Liuqi L1-L6 全链推演引擎（Python 原生翻译自 wuyun_deduction.rs）

以体用生克为第一性原理，从岁运 x 司天推演病机 / 治则 / 代表方剂。

层级:
  L1: 天干化气 (tian gan hua qi)
  L2: 岁运五音 (sui yun wu yin)
  L3: 司天在泉 (si tian zai yuan)
  L4: 客主加临 (ke zhu jia lin)
  L5: 体用验证 (ti yong yan zheng)
  L6: 推演处方 (tui yan chu fang)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


# ════════════════════════════════════════════════════════════════════════════
# 类型定义
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class TianGanHuaQi:
    """L1: 天干化气"""
    天干: str
    化气: str
    阴阳: str
    五音: str


@dataclass
class SuiYunWuYin:
    """L2: 岁运五音"""
    天干: str
    岁运: str
    五音: str
    太过: bool
    描述: str


@dataclass
class SiTianZaiYuan:
    """L3: 司天在泉"""
    干支: str
    司天: str
    在泉: str
    司天index: int
    在泉index: int
    左右间气: Dict[str, str] = field(default_factory=dict)


@dataclass
class KeZhuJiaLin:
    """L4: 客主加临"""
    客气: str
    主气: str
    客气五行: str
    主气五行: str
    顺逆: str
    判断: str
    客气全序: List[str] = field(default_factory=list)
    主气全序: List[str] = field(default_factory=list)
    六气定位: str = ""


@dataclass
class TiYongVerify:
    """L5: 体用验证"""
    体: str
    用: str
    体五行: str
    用五行: str
    生克: str
    病机特征: str
    治则方向: str
    体态: str
    验证结果: str
    验证备注: str


@dataclass
class TuiYanPrescription:
    """L6: 推演处方"""
    体用推演: Dict[str, str] = field(default_factory=dict)
    方剂匹配: List[str] = field(default_factory=list)


@dataclass
class WuyunFullChain:
    """全链输出"""
    L1_天干化气: TianGanHuaQi
    L2_岁运五音: SuiYunWuYin
    L3_司天在泉: SiTianZaiYuan
    L4_客主加临: KeZhuJiaLin
    L5_体用验证: TiYongVerify
    L6_推演处方: TuiYanPrescription


@dataclass
class OriginalEntry:
    rel: str
    disease: str
    formulas: List[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    体: str
    用: str
    原关系: str
    推关系: str
    关系匹配: bool
    原病机: str
    推病机: str
    原方: str
    推治则: str


# ════════════════════════════════════════════════════════════════════════════
# 五行基础
# ════════════════════════════════════════════════════════════════════════════

WUXING_CYCLE: List[str] = ["木", "火", "土", "金", "水"]


def wuxing_sheng(me: str, other: str) -> bool:
    """五行相生: me 生 other?"""
    try:
        i = WUXING_CYCLE.index(me)
        j = WUXING_CYCLE.index(other)
    except ValueError:
        return False
    return WUXING_CYCLE[(i + 1) % 5] == WUXING_CYCLE[j]


def wuxing_ke(me: str, other: str) -> bool:
    """五行相克: me 克 other?"""
    try:
        i = WUXING_CYCLE.index(me)
        j = WUXING_CYCLE.index(other)
    except ValueError:
        return False
    return WUXING_CYCLE[(i + 2) % 5] == WUXING_CYCLE[j]


def wuxing_relation(me: str, other: str) -> str:
    """返回五行生克关系类型（e.g. "木生火"、"水克火"、"同气"）"""
    if me == other:
        return "同气"
    if wuxing_sheng(me, other):
        return f"{me}生{other}"
    if wuxing_ke(me, other):
        return f"{me}克{other}"
    if wuxing_sheng(other, me):
        return f"{other}生{me}"
    if wuxing_ke(other, me):
        return f"{other}克{me}"
    return "无直接关系"


# ════════════════════════════════════════════════════════════════════════════
# 映射表
# ════════════════════════════════════════════════════════════════════════════

TIAN_GAN_LIST: List[str] = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI_LIST: List[str] = [
    "子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥",
]
SITIAN_FULL: List[str] = [
    "厥阴风木",
    "少阴君火",
    "太阴湿土",
    "少阳相火",
    "阳明燥金",
    "太阳寒水",
]

# 天干 -> 化气映射: 天干 -> (化气, 阴阳, 五音)
TIAN_GAN_HUA_QI_MAP: Dict[str, tuple] = {
    "甲": ("土", "阳", "太宫"),
    "乙": ("金", "阴", "少商"),
    "丙": ("水", "阳", "太羽"),
    "丁": ("木", "阴", "少角"),
    "戊": ("火", "阳", "太徵"),
    "己": ("土", "阴", "少宫"),
    "庚": ("金", "阳", "太商"),
    "辛": ("水", "阴", "少羽"),
    "壬": ("木", "阳", "太角"),
    "癸": ("火", "阴", "少徵"),
}

# 地支 -> 司天
DI_ZHI_SITIAN_MAP: Dict[str, str] = {
    "巳": "厥阴风木",
    "亥": "厥阴风木",
    "子": "少阴君火",
    "午": "少阴君火",
    "丑": "太阴湿土",
    "未": "太阴湿土",
    "寅": "少阳相火",
    "申": "少阳相火",
    "卯": "阳明燥金",
    "酉": "阳明燥金",
    "辰": "太阳寒水",
    "戌": "太阳寒水",
}


def suiyun_to_wuxing(name: str) -> str:
    """岁运名称 -> 五行"""
    if "木" in name:
        return "木"
    if "火" in name:
        return "火"
    if "土" in name:
        return "土"
    if "金" in name:
        return "金"
    if "水" in name:
        return "水"
    return ""


SITIAN_WUXING: Dict[str, str] = {
    "厥阴风木": "木",
    "少阴君火": "火",
    "少阳相火": "火",
    "太阴湿土": "土",
    "阳明燥金": "金",
    "太阳寒水": "水",
}

# 岁运五音映射: 天干 -> (岁运, 五音, 太过)
SUIYUN_WUYIN_MAP: Dict[str, tuple] = {
    "甲": ("土太过", "太宫", True),
    "乙": ("金不及", "少商", False),
    "丙": ("水太过", "太羽", True),
    "丁": ("木不及", "少角", False),
    "戊": ("火太过", "太徵", True),
    "己": ("土不及", "少宫", False),
    "庚": ("金太过", "太商", True),
    "辛": ("水不及", "少羽", False),
    "壬": ("木太过", "太角", True),
    "癸": ("火不及", "少徵", False),
}


# ════════════════════════════════════════════════════════════════════════════
# 体用推演核心
# ════════════════════════════════════════════════════════════════════════════

def _deduce_tooguo(体五行: str, 用五行: str, rel: str):
    """太过体态的病机特征与治则方向"""
    if rel == "同气":
        特征 = f"体用同{体五行}→用从体亢→体用俱亢"
        治则 = f"泄{体五行}用为主"
    elif rel == f"{体五行}生{用五行}":
        特征 = f"{体五行}生{用五行}→体泄于用→体用皆亢"
        治则 = f"泄{用五行}用为主，兼顾{体五行}体"
    elif rel == f"{体五行}克{用五行}":
        特征 = f"{体五行}克{用五行}→用被体郁→体亢用郁"
        治则 = f"疏{体五行}体以畅{用五行}用"
    elif rel == f"{用五行}生{体五行}":
        特征 = f"{用五行}生{体五行}→体更亢→体极"
        治则 = f"泄{体五行}体为主"
    elif rel == f"{用五行}克{体五行}":
        特征 = f"{用五行}克{体五行}→体被用制→体用交争"
        治则 = f"两解：泄{用五行}用+助{体五行}体"
    else:
        特征 = "关系不明"
        治则 = "随证治之"
    return 特征, 治则


def _deduce_buji(体五行: str, 用五行: str, rel: str):
    """不及体态的病机特征与治则方向"""
    if rel == "同气":
        特征 = f"体用同{体五行}→用从体衰→体用俱衰"
        治则 = f"补{体五行}体为主"
    elif rel == f"{体五行}生{用五行}":
        特征 = f"{体五行}生{用五行}→体更衰→体衰用亦不足"
        治则 = f"急补{体五行}体，兼助{用五行}用"
    elif rel == f"{体五行}克{用五行}":
        特征 = f"{体五行}克{用五行}→体衰不胜克→反被用侮"
        治则 = f"补{体五行}体+制{用五行}"
    elif rel == f"{用五行}生{体五行}":
        特征 = f"{用五行}生{体五行}→用助体→体有生机"
        治则 = f"补{体五行}体为君，助{用五行}用为臣"
    elif rel == f"{用五行}克{体五行}":
        特征 = f"{用五行}克{体五行}→体衰被乘→本脏大伤"
        治则 = f"急补{体五行}体+制{用五行}用"
    else:
        特征 = "关系不明"
        治则 = "随证治之"
    return 特征, 治则


def deduce_tiyong(体名: str, 用名: str, 体态: str) -> Dict[str, str]:
    """体用推演主函数"""
    体五行 = suiyun_to_wuxing(体名)
    用五行 = SITIAN_WUXING.get(用名, "")

    rel = wuxing_relation(体五行, 用五行)

    if 体态 == "太过":
        病机特征, 治则方向 = _deduce_tooguo(体五行, 用五行, rel)
    else:
        病机特征, 治则方向 = _deduce_buji(体五行, 用五行, rel)

    return {
        "体": 体名,
        "用": 用名,
        "体五行": 体五行,
        "用五行": 用五行,
        "生克": rel,
        "病机特征": 病机特征,
        "治则方向": 治则方向,
    }


# ════════════════════════════════════════════════════════════════════════════
# 方剂匹配表（基于岁运 + 生克关系）
# ════════════════════════════════════════════════════════════════════════════

FORMULA_MAP: Dict[tuple, List[str]] = {
    # 木
    ("木太过", "同气"): ["羚角钩藤汤", "镇肝熄风汤"],
    ("木太过", "木生火"): ["龙胆泻肝汤", "天麻钩藤饮"],
    ("木太过", "木克土"): ["逍遥散", "痛泻要方"],
    ("木太过", "火生木"): ["天麻钩藤饮", "龙胆泻肝汤"],
    ("木太过", "金克木"): ["柴胡疏肝散", "杏苏散"],
    ("木太过", "水生木"): ["暖肝煎", "天台乌药散"],
    # 火
    ("火太过", "同气"): ["黄连解毒汤", "泻心汤"],
    ("火太过", "火生土"): ["茵陈蒿汤", "甘露消毒丹"],
    ("火太过", "火克金"): ["泻白散", "清燥救肺汤"],
    ("火太过", "木生火"): ["导赤散", "泻青丸"],
    ("火太过", "水克火"): ["四逆散", "栀子豉汤"],
    ("火太过", "金生火"): ["清营汤", "犀角地黄汤"],
    # 土
    ("土太过", "同气"): ["平胃散", "藿香正气散"],
    ("土太过", "土生金"): ["参苓白术散", "六君子汤"],
    ("土太过", "土克水"): ["实脾饮", "五苓散"],
    ("土太过", "木克土"): ["逍遥散", "柴胡疏肝散"],
    ("土太过", "火生土"): ["平胃散+黄连", "香连丸"],
    ("土太过", "金生土"): ["参苓白术散", "补中益气汤"],
    # 金
    ("金太过", "同气"): ["杏苏散", "清燥救肺汤"],
    ("金太过", "金生水"): ["小青龙汤", "麻黄附子细辛汤"],
    ("金太过", "金克木"): ["柴胡疏肝散", "旋覆花汤"],
    ("金太过", "火克金"): ["泻白散", "麻杏石甘汤"],
    ("金太过", "土生金"): ["清燥救肺汤", "百合固金汤"],
    ("金太过", "木生金"): ["小青龙汤"],
    # 水
    ("水太过", "同气"): ["真武汤", "四逆汤", "麻黄附子细辛汤"],
    ("水太过", "水生木"): ["暖肝煎", "真武汤"],
    ("水太过", "水克火"): ["交泰丸", "黄连阿胶汤", "四逆散+栀子汤"],
    ("水太过", "土克水"): ["真武汤", "实脾饮"],
    ("水太过", "金生水"): ["麻黄附子细辛汤", "小青龙汤"],
    ("水太过", "火生水"): ["真武汤", "肾气丸"],
}


# ════════════════════════════════════════════════════════════════════════════
# L1: 天干化气
# ════════════════════════════════════════════════════════════════════════════

def year_to_ganzhi(year: int) -> str:
    """公历年 -> 干支字符串"""
    idx_gan = (year - 4) % 10
    idx_zhi = (year - 4) % 12
    return f"{TIAN_GAN_LIST[idx_gan]}{DI_ZHI_LIST[idx_zhi]}"


def tian_gan_hua_qi(year_or_gan: str) -> TianGanHuaQi:
    """L1: 天干化气"""
    valid_gans = set(TIAN_GAN_LIST)
    s = year_or_gan
    if s in valid_gans:
        tian_gan = s
    elif s.isdigit():
        year = int(s)
        tian_gan = TIAN_GAN_LIST[(year - 4) % 10]
    elif len(s) >= 1:
        first = s[0]
        matched = [g for g in TIAN_GAN_LIST if g[0] == first]
        if matched:
            tian_gan = matched[0]
        else:
            year = int(s) if s.lstrip("-").isdigit() else 2026
            tian_gan = TIAN_GAN_LIST[(year - 4) % 10]
    else:
        tian_gan = TIAN_GAN_LIST[0]

    化气, 阴阳, 五音 = TIAN_GAN_HUA_QI_MAP.get(tian_gan, ("", "", ""))
    return TianGanHuaQi(天干=tian_gan, 化气=化气, 阴阳=阴阳, 五音=五音)


# ════════════════════════════════════════════════════════════════════════════
# L2: 岁运五音
# ════════════════════════════════════════════════════════════════════════════

def sui_yun_wu_yin(year: int) -> SuiYunWuYin:
    """L2: 岁运五音"""
    tian_gan = TIAN_GAN_LIST[(year - 4) % 10]
    岁运, 五音, 太过 = SUIYUN_WUYIN_MAP.get(tian_gan, ("", "", False))
    tai_shao = "太" if 太过 else "少"
    yin_yang = "阳" if 太过 else "阴"
    描述 = (f"{year}年（{tian_gan}干）→ 岁运为{岁运}，"
            f"五音为{tai_shao}声·{五音}，{yin_yang}年")
    return SuiYunWuYin(
        天干=tian_gan, 岁运=岁运, 五音=五音, 太过=太过, 描述=描述,
    )


# ════════════════════════════════════════════════════════════════════════════
# L3: 司天在泉
# ════════════════════════════════════════════════════════════════════════════

def sitian_zaiyuan(year_or_ganzhi: str) -> SiTianZaiYuan:
    """L3: 司天在泉"""
    if year_or_ganzhi.isdigit():
        ganzhi = year_to_ganzhi(int(year_or_ganzhi))
    else:
        ganzhi = year_or_ganzhi

    di_zhi = ganzhi[1] if len(ganzhi) >= 2 else ""
    sitian_name = DI_ZHI_SITIAN_MAP.get(di_zhi, "厥阴风木")
    try:
        si_idx = SITIAN_FULL.index(sitian_name)
    except ValueError:
        si_idx = 0
    zai_idx = (si_idx + 3) % 6
    zaiyuan_name = SITIAN_FULL[zai_idx]

    左右间气 = {
        "司天左间": SITIAN_FULL[(si_idx + 1) % 6],
        "司天右间": SITIAN_FULL[(si_idx + 5) % 6],
        "在泉左间": SITIAN_FULL[(zai_idx + 1) % 6],
        "在泉右间": SITIAN_FULL[(zai_idx + 5) % 6],
    }

    return SiTianZaiYuan(
        干支=ganzhi,
        司天=sitian_name,
        在泉=zaiyuan_name,
        司天index=si_idx,
        在泉index=zai_idx,
        左右间气=左右间气,
    )


# ════════════════════════════════════════════════════════════════════════════
# L4: 客主加临
# ════════════════════════════════════════════════════════════════════════════

ZHUQI: List[str] = [
    "厥阴风木", "少阴君火", "少阳相火", "太阴湿土", "阳明燥金", "太阳寒水",
]
ZHUQI_PERIOD_NAMES: List[str] = [
    "初之气", "二之气", "三之气", "四之气", "五之气", "终之气",
]

# 主气日期范围 (起月, 起日, 止月, 止日)
ZHUQI_DATE_RANGES = [
    (1, 20, 3, 20),
    (3, 20, 5, 20),
    (5, 20, 7, 22),
    (7, 22, 9, 22),
    (9, 22, 11, 22),
    (11, 22, 1, 20),
]


def current_liuqi_index(now: Optional[datetime] = None) -> int:
    """返回当前日期的六气索引 (0-5)"""
    if now is None:
        now = datetime.now()
    m = now.month
    d = now.day
    # 终之气跨年: 11/22 ~ 1/19
    if (m == 11 and d >= 22) or m == 12 or (m == 1 and d <= 19):
        return 5
    # 中间四气
    for i in range(1, 5):
        sm, sd, em, ed = ZHUQI_DATE_RANGES[i]
        if (m == sm and d >= sd) or (sm < m < em) or (m == em and d < ed):
            return i
    # 初之气: 1/20 ~ 3/19
    if (m == 1 and d >= 20) or m == 2 or (m == 3 and d < 20):
        return 0
    return 5


def _build_keqi_order(si_idx: int) -> List[str]:
    """从司天索引构建客气六步顺序"""
    return [
        SITIAN_FULL[(si_idx + 4) % 6],   # 0: 初之气
        SITIAN_FULL[(si_idx + 5) % 6],   # 1: 二之气
        SITIAN_FULL[si_idx],             # 2: 三之气（司天本身）
        SITIAN_FULL[(si_idx + 1) % 6],   # 3: 四之气
        SITIAN_FULL[(si_idx + 2) % 6],   # 4: 五之气
        SITIAN_FULL[(si_idx + 3) % 6],   # 5: 终之气（在泉本身）
    ]


def _ke_zhu_shunni(ke_wx: str, zhu_wx: str) -> str:
    """判断客主加临顺逆"""
    if ke_wx == zhu_wx:
        return "同气"
    rel = wuxing_relation(ke_wx, zhu_wx)
    if rel == f"{ke_wx}生{zhu_wx}" or rel == f"{ke_wx}克{zhu_wx}":
        return "顺"
    return "逆"


def ke_zhu_jia_lin(year: int, liuqi_index: Optional[int] = None,
                   now: Optional[datetime] = None) -> KeZhuJiaLin:
    """L4: 客主加临"""
    idx = liuqi_index if liuqi_index is not None else current_liuqi_index(now)
    ganzhi = year_to_ganzhi(year)
    sitian_info = sitian_zaiyuan(ganzhi)
    si_idx = sitian_info.司天index

    keqi_order = _build_keqi_order(si_idx)
    ke_qi = keqi_order[idx]
    zhu_qi = ZHUQI[idx]

    ke_wx = SITIAN_WUXING.get(ke_qi, "")
    zhu_wx = SITIAN_WUXING.get(zhu_qi, "")

    shunni = _ke_zhu_shunni(ke_wx, zhu_wx)

    period_name = ZHUQI_PERIOD_NAMES[idx]
    if shunni == "顺":
        判断 = (f"{period_name}: 客气{ke_qi}({ke_wx})克/生主气"
                f"{zhu_qi}({zhu_wx}) → 顺")
    elif shunni == "逆":
        判断 = (f"{period_name}: 主气{zhu_qi}({zhu_wx})克/生客气"
                f"{ke_qi}({ke_wx}) → 逆")
    else:
        判断 = f"{period_name}: 客气{ke_qi}与主气{zhu_qi}同气"

    return KeZhuJiaLin(
        客气=ke_qi,
        主气=zhu_qi,
        客气五行=ke_wx,
        主气五行=zhu_wx,
        顺逆=shunni,
        判断=判断,
        客气全序=list(keqi_order),
        主气全序=list(ZHUQI),
        六气定位=period_name,
    )


# ════════════════════════════════════════════════════════════════════════════
# L5: 体用验证
# ════════════════════════════════════════════════════════════════════════════

TIYONG_SYMPTOM_MAP: Dict[str, tuple] = {
    "木克土": ("木旺克土→脾土受制", "疏肝以实脾"),
    "火克金": ("火旺克金→肺金受灼", "清心以降肺"),
    "土克水": ("土旺克水→肾水受抑", "运脾以利水"),
    "金克木": ("金旺克木→肝木被郁", "肃肺以达肝"),
    "水克火": ("水旺克火→心火受郁", "温阳以通脉"),
    "木生火": ("木旺生火→风火相扇", "滋水以涵木"),
    "火生土": ("火旺生土→湿热交蒸", "清热以化湿"),
    "土生金": ("土旺生金→痰湿壅肺", "补土以生金"),
    "金生水": ("金旺生水→寒水泛滥", "温肺以化饮"),
    "水生木": ("水旺生木→水不涵木", "利水以养木"),
}


def wuyun_tiyong_verify(suiyun_input: SuiYunWuYin,
                        sitian_input: SiTianZaiYuan) -> TiYongVerify:
    """L5: 体用验证"""
    tiyang_name = suiyun_input.岁运
    tai_state = "太过" if suiyun_input.太过 else "不及"
    yong_name = sitian_input.司天

    deduction = deduce_tiyong(tiyang_name, yong_name, tai_state)

    rel = deduction.get("生克", "")

    verify_notes: List[str] = []
    for key, (disease, hint) in TIYONG_SYMPTOM_MAP.items():
        if key in rel:
            verify_notes.append(disease)
            verify_notes.append(hint)

    病机特征 = deduction.get("病机特征", "")
    if 病机特征:
        验证结果 = (f"体用信度: {deduction.get('体','')}×{deduction.get('用','')} → "
                    f"{rel}，{病机特征}")
    else:
        验证结果 = f"体用关系: {rel}"

    return TiYongVerify(
        体=deduction.get("体", ""),
        用=deduction.get("用", ""),
        体五行=deduction.get("体五行", ""),
        用五行=deduction.get("用五行", ""),
        生克=rel,
        病机特征=病机特征,
        治则方向=deduction.get("治则方向", ""),
        体态=tai_state,
        验证结果=验证结果,
        验证备注="；".join(verify_notes),
    )


# ════════════════════════════════════════════════════════════════════════════
# L6: 推演处方 + 全链
# ════════════════════════════════════════════════════════════════════════════

def wuyun_full_chain(year: int, liuqi_index: Optional[int] = None,
                     now: Optional[datetime] = None) -> WuyunFullChain:
    """全链推演 L1 -> L2 -> L3 -> L4 -> L5 -> L6"""
    idx = liuqi_index if liuqi_index is not None else current_liuqi_index(now)

    l1 = tian_gan_hua_qi(str(year))
    l2 = sui_yun_wu_yin(year)
    l3 = sitian_zaiyuan(str(year))
    l4 = ke_zhu_jia_lin(year, idx, now)
    l5 = wuyun_tiyong_verify(l2, l3)

    # 方剂匹配
    rel = l5.生克
    matched_formulas: List[str] = []
    for (ti_key, rel_key), formulas in FORMULA_MAP.items():
        if ti_key == l2.岁运 and rel_key == rel:
            matched_formulas.extend(formulas)

    体用推演 = {
        "体": l5.体,
        "用": l5.用,
        "体五行": l5.体五行,
        "用五行": l5.用五行,
        "生克": l5.生克,
        "病机特征": l5.病机特征,
        "治则方向": l5.治则方向,
        "验证结果": l5.验证结果,
    }

    l6 = TuiYanPrescription(体用推演=体用推演, 方剂匹配=matched_formulas)

    return WuyunFullChain(
        L1_天干化气=l1,
        L2_岁运五音=l2,
        L3_司天在泉=l3,
        L4_客主加临=l4,
        L5_体用验证=l5,
        L6_推演处方=l6,
    )


def build_wuyun_output(chain: WuyunFullChain,
                       liuqi_index: Optional[int] = None,
                       now: Optional[datetime] = None) -> dict:
    """从全链结果构建 dialectic.WuyunDeductionOutput"""
    l2 = chain.L2_岁运五音
    l3 = chain.L3_司天在泉
    l4 = chain.L4_客主加临
    l5 = chain.L5_体用验证

    体用验证 = {
        "体": l5.体,
        "用": l5.用,
        "体五行": l5.体五行,
        "用五行": l5.用五行,
        "生克": l5.生克,
        "病机特征": l5.病机特征,
        "治则方向": l5.治则方向,
        "验证结果": l5.验证结果,
        "验证备注": l5.验证备注,
    }

    idx = liuqi_index if liuqi_index is not None else current_liuqi_index(now)
    period = ZHUQI_PERIOD_NAMES[idx]

    return {
        "纪元": l3.干支,
        "岁运": l2.岁运,
        "太过不及": "太过" if l2.太过 else "不及",
        "司天": l3.司天,
        "在泉": l3.在泉,
        "客气": l4.客气,
        "主气": l4.主气,
        "顺逆": l4.顺逆,
        "六气定位": period,
        "体用验证": 体用验证,
        "方剂匹配": chain.L6_推演处方.方剂匹配,
    }


# ════════════════════════════════════════════════════════════════════════════
# 原始 L6 知识库验证
# ════════════════════════════════════════════════════════════════════════════

def _parse_original(entry_str: str) -> OriginalEntry:
    parts = [s.strip() for s in entry_str.split("→")]
    rel = parts[0] if len(parts) > 0 else ""
    disease = parts[1] if len(parts) > 1 else ""
    raw_fang = parts[2] if len(parts) > 2 else ""

    if "／" in raw_fang:
        formulas = [s.strip() for s in raw_fang.split("／")]
    elif "/" in raw_fang:
        formulas = [s.strip() for s in raw_fang.split("/")]
    elif "+" in raw_fang:
        formulas = [s.strip() for s in raw_fang.split("+")]
    elif raw_fang:
        formulas = [raw_fang]
    else:
        formulas = []

    return OriginalEntry(rel=rel, disease=disease, formulas=formulas)


def _deduce_rel_match(orig: str, deduced: str) -> bool:
    if not orig or not deduced:
        return False
    if orig == deduced:
        return True
    # 同气匹配
    orig_no_tiyong = orig.replace("体用", "").replace("俱", "")
    if "同" in orig_no_tiyong and "同" in deduced:
        return True
    if ("同" in orig or "俱" in orig) and deduced == "同气":
        return True
    # 生克匹配
    for op in ("生", "克"):
        if op in orig and op in deduced:
            return True
    return False


def l6_original_data() -> Dict[str, Dict[str, str]]:
    """原始 L6 知识库（30 条）"""
    data: Dict[str, Dict[str, str]] = {}

    木太过 = {
        "厥阴风木": "体用同木→风极→羚角钩藤汤",
        "少阴君火": "木生火→风火相扇→龙胆泻肝汤",
        "太阴湿土": "木克土→肝脾不和→逍遥散+痛泻要方",
        "少阳相火": "木生火→风火更盛→天麻钩藤饮",
        "阳明燥金": "金克木→木被金郁→柴胡疏肝散+杏苏散",
        "太阳寒水": "水生木→木体更盛→暖肝煎",
    }
    data["木太过(壬)"] = 木太过

    火太过 = {
        "厥阴风木": "木生火→火体更盛→导赤散",
        "少阴君火": "体用同火→火极→黄连解毒汤",
        "太阴湿土": "火生土→湿热交蒸→茵陈蒿汤",
        "少阳相火": "体用俱火→火至极→清营汤",
        "阳明燥金": "火克金→金体被伤→泻白散+清燥救肺汤",
        "太阳寒水": "水克火→火被郁→四逆散+栀子豉汤",
    }
    data["火太过(戊)"] = 火太过

    土太过 = {
        "厥阴风木": "木克土→土被木疏→逍遥散",
        "少阴君火": "火生土→土体更壅→平胃散+黄连",
        "太阴湿土": "体用同土→湿极→藿香正气散",
        "少阳相火": "火生土→湿热交争→茵陈蒿汤",
        "阳明燥金": "土生金→土体泄→参苓白术散",
        "太阳寒水": "土克水→水体被抑→实脾饮",
    }
    data["土太过(甲)"] = 土太过

    金太过 = {
        "厥阴风木": "金克木→木体被抑→柴胡疏肝散",
        "少阴君火": "火克金→火克金体→泻白散",
        "太阴湿土": "土生金→金体更盛→清燥救肺汤",
        "少阳相火": "火克金→金体被灼→麻杏石甘汤",
        "阳明燥金": "体用同金→燥极→增液汤+杏苏散",
        "太阳寒水": "金生水→金体泄→小青龙汤",
    }
    data["金太过(庚)"] = 金太过

    水太过 = {
        "厥阴风木": "水生木→水泄于木→暖肝煎",
        "少阴君火": "水克火→火用被郁→交泰丸/黄连阿胶汤",
        "太阴湿土": "土克水→水体被抑→真武汤",
        "少阳相火": "水克火→火郁不发→四逆散+栀子汤",
        "阳明燥金": "金生水→水体更盛→麻黄附子细辛汤",
        "太阳寒水": "体用同水→寒极→四逆汤/真武汤",
    }
    data["水太过(丙)"] = 水太过

    return data


def verify_l6() -> List[VerificationResult]:
    """运行原始 L6 知识库验证"""
    data = l6_original_data()
    results: List[VerificationResult] = []

    for 体名, 司天dict in data.items():
        # 提取体态
        体纯 = 体名.replace("（", "(").replace("）", ")")
        idx = 体纯.find("(")
        if idx >= 0:
            体纯 = 体纯[:idx].strip()
        体态 = "太过" if "太过" in 体纯 else "不及"

        for 用名, 原文 in 司天dict.items():
            orig = _parse_original(原文)
            deduction = deduce_tiyong(体纯, 用名, 体态)
            deduced_rel = deduction.get("生克", "")
            deduced_disease = deduction.get("病机特征", "")
            deduced_treat = deduction.get("治则方向", "")

            rel_match = _deduce_rel_match(orig.rel, deduced_rel)

            results.append(VerificationResult(
                体=体名,
                用=用名,
                原关系=orig.rel,
                推关系=deduced_rel,
                关系匹配=rel_match,
                原病机=orig.disease,
                推病机=deduced_disease,
                原方="、".join(orig.formulas),
                推治则=deduced_treat,
            ))

    return results
