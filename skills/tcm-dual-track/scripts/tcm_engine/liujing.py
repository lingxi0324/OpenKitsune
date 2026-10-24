# -*- coding: utf-8 -*-
"""
六经辨证自动引擎 - 加权脉证合参评分（Python 原生翻译自 liujing.rs）

算法:
  脉象权重 = 0.4 x (匹配脉分 / 经最大脉分)
  症状权重 = 0.4 x (匹配症分 / 经最大症分)
  舌象权重 = 0.2 x (匹配舌苔分 / 经最大舌苔分)
  原始分 = raw_score x base_weight
  五运六气加权 = final_score x 年权重系数
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .wuyun import (
    TIAN_GAN_HUA_QI_MAP,
    TIAN_GAN_LIST,
    wuxing_relation,
)


# ════════════════════════════════════════════════════════════════════════════
# 类型定义
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class FormulaSyndrome:
    """方证定义"""
    方证: str
    方: str
    症状: List[str] = field(default_factory=list)
    型: Optional[str] = None


@dataclass
class ChannelData:
    """每经完整数据"""
    base_weight: float
    病位: str
    提纲: str
    体用倾向: str
    症状: List[Tuple[str, float]] = field(default_factory=list)
    脉象: List[Tuple[str, float]] = field(default_factory=list)
    舌象: List[Tuple[str, float]] = field(default_factory=list)
    方证: List[FormulaSyndrome] = field(default_factory=list)
    推荐方: List[str] = field(default_factory=list)
    方剂说明: str = ""
    体用映射: Tuple[float, float, str] = (0.0, 0.0, "")
    六经传变: str = ""
    体用映射_寒化: Optional[Tuple[float, float, str]] = None
    体用映射_热化: Optional[Tuple[float, float, str]] = None
    推荐方_寒化: Optional[List[str]] = None
    推荐方_热化: Optional[List[str]] = None


@dataclass
class BoundaryWarning:
    """边界（疑似）经警告"""
    经: str
    得分: float
    差距百分比: str
    提示: str


@dataclass
class CombinedChannelResult:
    """合病检测结果"""
    主经: str
    主经得分: float
    合病经: List[str] = field(default_factory=list)
    合病得分: Dict[str, float] = field(default_factory=dict)
    合方推荐: List[str] = field(default_factory=list)
    合病说明: str = ""
    合病类型: str = ""


@dataclass
class MatchedFormulaSyndrome:
    """匹配到的方证结果"""
    方证: str
    方: str
    匹配度: str


@dataclass
class EvidenceChainItem:
    """证据链条目"""
    经: str
    得分: float
    证据: str


@dataclass
class LiujingScoreResult:
    """liujing_score() 完整输出"""
    各经评分: Dict[str, float] = field(default_factory=dict)
    推荐经: str = ""
    置信度: str = ""
    原始得分: float = 0.0
    疑似经: List[BoundaryWarning] = field(default_factory=list)
    脉证合参: str = ""
    体用映射: Dict[str, float] = field(default_factory=dict)
    体用倾向: str = ""
    推荐方: List[str] = field(default_factory=list)
    方剂说明: str = ""
    匹配方证: List[MatchedFormulaSyndrome] = field(default_factory=list)
    六经传变: str = ""
    证据链: List[EvidenceChainItem] = field(default_factory=list)
    亚型: Optional[str] = None
    合病检测: Optional[CombinedChannelResult] = None


# ════════════════════════════════════════════════════════════════════════════
# 常量与数据
# ════════════════════════════════════════════════════════════════════════════

LIUJING_ORDER: List[str] = ["太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病"]


# 六经症状数据库
LIUJING_SYMPTOMS: Dict[str, ChannelData] = {
    "太阳病": ChannelData(
        base_weight=0.78,
        病位="表",
        提纲="脉浮、头项强痛而恶寒",
        体用倾向="体表用实",
        症状=[
            ("恶寒发热", 1.0), ("头项强痛", 1.0), ("鼻塞", 0.7), ("流涕", 0.6),
            ("无汗", 0.7), ("有汗", 0.6), ("身痛", 0.7), ("腰痛", 0.5),
            ("骨节疼痛", 0.7), ("恶风", 0.8), ("发热", 0.5), ("头痛", 0.4),
        ],
        脉象=[
            ("脉浮", 1.0), ("脉浮紧", 1.0), ("脉浮缓", 1.0), ("脉浮数", 0.8),
            ("脉浮滑", 0.6), ("浮", 0.9), ("浮紧", 0.9), ("浮缓", 0.9),
            ("浮数", 0.7),
        ],
        舌象=[
            ("苔薄白", 0.8), ("舌淡红", 0.6), ("苔白", 0.6), ("舌淡", 0.5),
        ],
        方证=[
            FormulaSyndrome("桂枝汤证", "桂枝汤", ["恶风", "汗出", "脉浮缓"]),
            FormulaSyndrome("麻黄汤证", "麻黄汤", ["恶寒", "无汗", "身痛", "脉浮紧"]),
            FormulaSyndrome("桂枝加葛根汤证", "桂枝加葛根汤", ["项背强几几", "恶风", "汗出"]),
            FormulaSyndrome("葛根汤证", "葛根汤", ["项背强几几", "无汗", "恶寒"]),
            FormulaSyndrome("小青龙汤证", "小青龙汤", ["恶寒发热", "无汗", "咳喘", "痰稀白"]),
            FormulaSyndrome("麻杏石甘汤证", "麻杏石甘汤", ["发热", "喘", "汗出", "无大热"]),
        ],
        推荐方=["桂枝汤", "麻黄汤", "桂枝加葛根汤", "葛根汤"],
        方剂说明="太阳主表，风寒外束。有汗用桂枝，无汗用麻黄",
        体用映射=(0.0, 0.5, "太阳为表，用热驱寒"),
        六经传变="太阳→阳明/少阳（顺传）或→少阴（逆传）",
    ),
    "阳明病": ChannelData(
        base_weight=0.85,
        病位="里",
        提纲="胃家实",
        体用倾向="体实用亢",
        症状=[
            ("壮热", 1.0), ("大汗", 0.9), ("大渴", 1.0), ("便秘", 0.9),
            ("腹满", 0.8), ("腹痛", 0.7), ("潮热", 0.8), ("谵语", 0.7),
            ("烦躁", 0.6), ("口臭", 0.6), ("口干", 0.6), ("口渴引饮", 0.9),
            ("小便黄", 0.5), ("腹满痛", 0.8), ("绕脐痛", 0.7), ("拒按", 0.6),
            ("手足濈然汗出", 0.7),
            ("发热", 0.7), ("咳嗽", 0.7), ("痰黄稠", 0.8), ("痰热", 0.8),
            ("痰多", 0.6), ("胸闷", 0.6), ("口渴", 0.8),
        ],
        脉象=[
            ("脉洪大", 1.0), ("脉洪", 0.9), ("脉滑", 0.7), ("脉沉实", 0.8),
            ("脉沉迟有力", 0.7), ("洪大", 0.9), ("洪", 0.8), ("滑", 0.6),
            ("沉实", 0.7), ("沉迟有力", 0.6),
        ],
        舌象=[
            ("苔黄", 0.8), ("苔黄燥", 1.0), ("苔黄厚", 0.9), ("苔焦", 0.9),
            ("舌红", 0.7), ("舌绛", 0.7), ("苔燥", 0.8), ("芒刺", 0.7),
        ],
        方证=[
            FormulaSyndrome("白虎汤证", "白虎汤", ["大热", "大渴", "汗出", "脉洪大"]),
            FormulaSyndrome("白虎加人参汤证", "白虎加人参汤", ["大热", "大渴", "汗出", "脉洪大无力"]),
            FormulaSyndrome("调胃承气汤证", "调胃承气汤", ["便秘", "腹满", "心烦"]),
            FormulaSyndrome("小承气汤证", "小承气汤", ["便秘", "腹满", "潮热"]),
            FormulaSyndrome("大承气汤证", "大承气汤", ["便秘", "腹满痛", "潮热", "谵语", "苔黄燥"]),
            FormulaSyndrome("麻子仁丸证", "麻子仁丸", ["便秘", "小便数"]),
        ],
        推荐方=[
            "白虎汤", "白虎加人参汤", "调胃承气汤", "小承气汤", "大承气汤",
        ],
        方剂说明="阳明主里，热结胃肠。经证用白虎，腑证用承气",
        体用映射=(0.5, 0.7, "阳明为里实热，体实用俱亢"),
        六经传变="阳明→太阴（传阴）或阳明→少阳（旁传）",
    ),
    "少阳病": ChannelData(
        base_weight=0.90,
        病位="半表半里",
        提纲="口苦、咽干、目眩",
        体用倾向="体郁用滞",
        症状=[
            ("寒热往来", 1.0), ("口苦", 0.6), ("咽干", 0.9), ("目眩", 0.9),
            ("胸胁苦满", 0.7), ("默默不欲饮食", 0.8), ("心烦", 0.7),
            ("喜呕", 0.8), ("呕吐", 0.7), ("胁痛", 0.6), ("耳鸣", 0.6),
            ("耳聋", 0.5), ("偏头痛", 0.6), ("痞满", 0.4),
            ("胸胁支满", 0.5), ("胸胁满", 0.7), ("脉弦", 0.5),
        ],
        脉象=[
            ("脉弦", 1.0), ("脉弦细", 0.9), ("脉弦数", 0.8), ("弦", 0.7),
            ("弦细", 0.8), ("弦数", 0.7),
            ("脉弦缓", 0.8), ("弦缓", 0.7),  # 肝郁乘脾/木郁土虚
            ("脉浮弦", 0.8), ("浮弦", 0.7),  # 风弦脉，少阳合病
        ],
        舌象=[
            ("苔白", 0.5), ("苔薄白", 0.6), ("苔黄", 0.5), ("舌边红", 0.6),
            ("苔白腻", 0.4),
        ],
        方证=[
            FormulaSyndrome("小柴胡汤证", "小柴胡汤", ["寒热往来", "口苦", "咽干", "目眩", "胸胁苦满"]),
            FormulaSyndrome("大柴胡汤证", "大柴胡汤", ["寒热往来", "便秘", "腹痛", "呕吐"]),
            FormulaSyndrome("柴胡桂枝汤证", "柴胡桂枝汤", ["发热", "微恶寒", "肢节烦痛"]),
            FormulaSyndrome("柴胡加龙骨牡蛎汤证", "柴胡加龙骨牡蛎汤", ["胸满", "烦躁", "谵语"]),
            FormulaSyndrome("四逆散证", "四逆散", ["手足冷", "胁痛", "脉弦"]),
        ],
        推荐方=["小柴胡汤", "大柴胡汤", "柴胡桂枝汤", "四逆散"],
        方剂说明="少阳主枢，半表半里。和解为主，小柴胡为代表",
        体用映射=(-0.2, 0.1, "少阳为枢，气郁化热"),
        六经传变="少阳→阳明（顺传）或→太阴（逆传）",
    ),
    "太阴病": ChannelData(
        base_weight=0.85,
        病位="里(阴)",
        提纲="腹满而吐、食不下、自利益甚",
        体用倾向="体寒用衰",
        症状=[
            ("腹满", 0.8), ("呕吐", 0.7), ("食不下", 0.8), ("自利", 0.9),
            ("时腹自痛", 0.8), ("大便溏", 0.8), ("大便稀", 0.8), ("不渴", 0.6),
            ("食少", 0.7), ("纳呆", 0.7), ("乏力", 0.5), ("畏寒", 0.5),
            ("喜温喜按", 0.7), ("口不渴", 0.6), ("腹胀", 0.6),
            ("肠鸣", 0.6), ("泄泻", 0.7), ("下利", 0.6),
            ("心下痞满", 0.8), ("心下痞", 0.8), ("寒热错杂", 0.9),
            ("呕吐下利", 0.8), ("肠鸣下利", 0.7),
            ("胸胁支满", 0.6), ("心悸", 0.7), ("短气", 0.7), ("眩晕", 0.6),
            ("目眩", 0.7), ("痰多", 0.6), ("呕吐清涎", 0.7), ("水饮", 0.6),
            ("口苦", 0.3), ("口苦咽干", 0.4),
        ],
        脉象=[
            ("脉沉缓", 0.9), ("脉缓", 0.7), ("脉沉", 0.6), ("脉弱", 0.7),
            ("脉迟", 0.6), ("沉缓", 0.8), ("缓", 0.6), ("沉", 0.5),
            ("弱", 0.6), ("迟", 0.5),
            ("脉弦", 0.4), ("弦", 0.3),  # 太阴兼肝郁乘脾/木郁土虚，弦为兼脉
        ],
        舌象=[
            ("舌淡", 0.8), ("舌淡胖", 0.7), ("苔白", 0.7), ("苔白滑", 0.8),
            ("苔白腻", 0.7), ("舌有齿痕", 0.6),
        ],
        方证=[
            FormulaSyndrome("理中汤证", "理中汤", ["腹满", "呕吐", "自利", "不渴"]),
            FormulaSyndrome("四君子汤证", "四君子汤", ["食少", "乏力", "便溏"]),
            FormulaSyndrome("桂枝人参汤证", "桂枝人参汤", ["发热", "恶寒", "自利"]),
            FormulaSyndrome("厚朴生姜半夏甘草人参汤证", "厚朴生姜半夏甘草人参汤", ["腹胀", "食少"]),
        ],
        推荐方=["理中汤", "四君子汤", "桂枝人参汤", "参苓白术散"],
        方剂说明="太阴主运化，虚寒则湿停。温中健脾为要",
        体用映射=(-0.5, -0.3, "太阴虚寒，体用俱衰"),
        六经传变="太阴→少阴（深入）或太阴→阳明（腑实）",
    ),
    "少阴病": ChannelData(
        base_weight=0.75,
        病位="里(心肾)",
        提纲="脉微细、但欲寐",
        体用倾向="体衰用微",
        症状=[
            ("但欲寐", 1.0), ("恶寒蜷卧", 0.9), ("下利清谷", 0.9),
            ("四肢厥逆", 0.9), ("手足冷", 0.8), ("畏寒", 0.7), ("心烦", 0.6),
            ("不寐", 0.6), ("失眠", 0.5), ("口燥咽干", 0.6), ("小便清长", 0.6),
            ("小便白", 0.5), ("汗出", 0.5), ("自汗", 0.5), ("腰冷", 0.5),
            ("足冷", 0.6), ("精神萎靡", 0.7), ("腰膝酸软", 0.6),
            ("腰膝冷痛", 0.7), ("耳鸣", 0.5), ("遗精", 0.5), ("滑胎", 0.5),
            ("水肿", 0.5), ("心悸", 0.6), ("小便不利", 0.5),
        ],
        脉象=[
            ("脉微细", 1.0), ("脉细", 0.8), ("脉沉", 0.7), ("脉微", 0.9),
            ("脉细数", 0.7), ("脉沉微", 0.9), ("微细", 0.9), ("细", 0.7),
            ("沉", 0.6), ("微", 0.8), ("细数", 0.6), ("沉微", 0.8),
            ("脉微欲绝", 1.0),
        ],
        舌象=[
            ("舌淡", 0.7), ("舌淡胖", 0.8), ("苔白", 0.6), ("苔白滑", 0.7),
            ("舌红", 0.5), ("少苔", 0.5), ("舌红少苔", 0.5), ("苔黑", 0.5),
        ],
        方证=[
            FormulaSyndrome("四逆汤证", "四逆汤", ["恶寒蜷卧", "四肢厥逆", "下利清谷", "脉微细"], "寒化"),
            FormulaSyndrome("通脉四逆汤证", "通脉四逆汤", ["下利清谷", "里寒外热", "脉微欲绝"], "寒化"),
            FormulaSyndrome("真武汤证", "真武汤", ["水肿", "小便不利", "心下悸"], "寒化"),
            FormulaSyndrome("附子汤证", "附子汤", ["恶寒", "手足冷", "骨节痛", "脉沉"], "寒化"),
            FormulaSyndrome("黄连阿胶汤证", "黄连阿胶汤", ["心烦", "不寐", "口燥咽干", "脉细数"], "热化"),
            FormulaSyndrome("猪苓汤证", "猪苓汤", ["心烦", "不寐", "小便不利", "渴"], "热化"),
        ],
        推荐方=["四逆汤", "黄连阿胶汤", "真武汤", "麻黄附子细辛汤"],
        方剂说明="少阴主心肾，水火之脏。寒化四逆辈，热化黄连阿胶",
        体用映射=(-0.6, -0.3, "少阴病位最深，体用俱损"),
        六经传变="少阴→厥阴（极深）或少阴→太阳（外出）",
        体用映射_寒化=(-0.8, -0.6, "少阴寒化，体用俱衰，阳虚阴盛"),
        体用映射_热化=(-0.3, 0.5, "少阴热化，体虚用亢，阴虚火旺"),
        推荐方_寒化=["四逆汤", "通脉四逆汤", "真武汤", "附子汤", "麻黄附子细辛汤"],
        推荐方_热化=["黄连阿胶汤", "猪苓汤"],
    ),
    "厥阴病": ChannelData(
        base_weight=0.75,
        病位="半表半里(阴)",
        提纲="消渴、气上撞心、心中疼热",
        体用倾向="体寒用热(相悖)",
        症状=[
            ("消渴", 0.9), ("气上撞心", 0.9), ("心中疼热", 0.9),
            ("饥不欲食", 0.8), ("厥热胜复", 1.0), ("呕吐", 0.6),
            ("蛔厥", 0.8), ("手足厥冷", 0.7), ("发热", 0.5), ("下利", 0.6),
            ("便血", 0.6), ("头痛", 0.5), ("巅顶痛", 0.7), ("干呕", 0.6),
            ("吐涎沫", 0.7), ("痛经", 0.8), ("经前腹痛", 0.8), ("血虚", 0.7),
            ("头晕", 0.6), ("面色苍白", 0.6), ("唇甲色淡", 0.7),
            ("月经不调", 0.7), ("经血有块", 0.7), ("小腹冷痛", 0.7),
            ("刺痛", 0.8), ("固定痛", 0.8), ("唇紫暗", 0.7), ("舌紫暗", 0.8),
            ("瘀斑", 0.7), ("胸痹", 0.8), ("心胸刺痛", 0.8), ("血瘀", 0.8),
            ("经行腹痛", 0.8), ("经色紫暗", 0.7), ("块下痛减", 0.8),
        ],
        脉象=[
            ("脉微", 0.7), ("脉细", 0.6), ("脉微细", 0.7), ("脉弦", 0.5),
            ("脉数", 0.5), ("脉滑", 0.4), ("脉涩", 0.6),
            ("微", 0.6), ("细", 0.5), ("弦", 0.4), ("数", 0.4), ("脉微欲绝", 0.8),
            ("涩", 0.6), ("沉涩", 0.7),
        ],
        舌象=[
            ("舌红", 0.5), ("苔黄", 0.4), ("苔白", 0.4), ("舌淡", 0.4),
            ("苔滑", 0.4),
        ],
        方证=[
            FormulaSyndrome("乌梅丸证", "乌梅丸", ["消渴", "气上撞心", "心中疼热", "饥不欲食", "蛔厥"]),
            FormulaSyndrome("当归四逆汤证", "当归四逆汤", ["手足厥冷", "脉微细"]),
            FormulaSyndrome("当归四逆加吴茱萸生姜汤证", "当归四逆加吴茱萸生姜汤", ["手足厥冷", "头痛", "干呕"]),
            FormulaSyndrome("吴茱萸汤证", "吴茱萸汤", ["干呕", "吐涎沫", "头痛", "巅顶痛"]),
            FormulaSyndrome("白头翁汤证", "白头翁汤", ["下利", "便血", "腹痛"]),
        ],
        推荐方=["乌梅丸", "当归四逆汤", "吴茱萸汤", "白头翁汤"],
        方剂说明="厥阴为阴尽阳生，寒热错杂。乌梅丸为总代表",
        体用映射=(-0.4, 0.3, "厥阴寒热错杂，体寒用热相悖"),
        六经传变="厥阴→太阳（外出）或厥阴→五脏（深入）",
    ),
}


# 六经 -> 五行属性映射，用于五运六气动态加权
LIUJING_WUXING: List[Tuple[str, str]] = [
    ("太阳病", "水"),
    ("阳明病", "金"),
    ("少阳病", "火"),
    ("太阴病", "土"),
    ("少阴病", "火"),
    ("厥阴病", "木"),
]


def compute_wuyun_weights(year_or_ganzhi: str) -> Optional[Dict[str, float]]:
    """
    从当年岁运（天干化气）动态计算六经权重系数。

    原理: 岁运与六经五行的生克关系决定加权方向
      - 同气: 太过年经病突出 -> *1.25；不及年 -> *0.80
      - 岁运生经: 经受岁运滋养 -> *1.15 / 0.85
      - 岁运克经: 经受岁运制约 -> *1.10 / 0.90
      - 经生岁运: 经泄于岁运 -> *1.05 / 0.95
      - 经克岁运: 经反制 -> *1.00 / 0.95
    """
    s = str(year_or_ganzhi)
    if s.isdigit():
        year = int(s)
        gan = TIAN_GAN_LIST[(year - 4) % 10]
    elif len(s) >= 1:
        first = s[0]
        matched = [g for g in TIAN_GAN_LIST if g[0] == first]
        if not matched:
            return None
        gan = matched[0]
    else:
        return None

    entry = TIAN_GAN_HUA_QI_MAP.get(gan)
    if entry is None:
        return None
    化气, 阴阳, _ = entry
    太过 = (阴阳 == "阳")

    weights: Dict[str, float] = {}
    for 经名, 经五行 in LIUJING_WUXING:
        rel = wuxing_relation(化气, 经五行)
        if rel == "同气":
            w = 1.25 if 太过 else 0.80
        elif rel == f"{化气}生{经五行}":
            w = 1.15 if 太过 else 0.85
        elif rel == f"{化气}克{经五行}":
            w = 1.10 if 太过 else 0.90
        elif rel == f"{经五行}生{化气}":
            w = 1.05 if 太过 else 0.95
        elif rel == f"{经五行}克{化气}":
            w = 1.00 if 太过 else 0.95
        else:
            w = 1.00
        weights[经名] = w
    return weights


HANHUA_KW: List[str] = [
    "畏寒", "恶寒", "下利清谷", "四肢厥逆", "手足冷", "但欲寐",
    "小便清长", "脉微细", "脉沉微",
]
REHUA_KW: List[str] = ["心烦", "不寐", "失眠", "口燥咽干", "脉细数"]


# ════════════════════════════════════════════════════════════════════════════
# 内部评分辅助
# ════════════════════════════════════════════════════════════════════════════

def _match_pattern(input_text: str,
                   patterns: List[Tuple[str, float]]) -> Tuple[float, List[str]]:
    """在 input_text 中匹配所有 patterns（最长优先，全部累加不中断）"""
    if not input_text:
        return (0.0, [])
    sorted_patterns = sorted(patterns, key=lambda a: -len(a[0]))
    total = 0.0
    matched: List[str] = []
    for pattern, weight in sorted_patterns:
        if pattern in input_text:
            total += weight
            matched.append(pattern)
    return (total, matched)


def _score_single_channel(
    channel: str,
    pulse_text: str,
    symptom_text: str,
    tongue_text: str,
    coat_text: str,
) -> Tuple[float, Optional[str], List[str], List[str], List[str]]:
    ch_data = LIUJING_SYMPTOMS[channel]

    # 脉象
    pulse_score, pulse_matched = _match_pattern(pulse_text, ch_data.脉象)
    top_pulse = sorted([w for (_, w) in ch_data.脉象], reverse=True)[:3]
    top_pulse_sum = sum(top_pulse)
    pulse_norm = min(pulse_score / top_pulse_sum, 1.0) if top_pulse_sum > 0.0 else 0.0

    # 症状
    symptom_score, symptom_matched = _match_pattern(symptom_text, ch_data.症状)
    top_symptom = sorted([w for (_, w) in ch_data.症状], reverse=True)[:5]
    top_symptom_sum = sum(top_symptom)
    symptom_norm = min(symptom_score / top_symptom_sum, 1.0) if top_symptom_sum > 0.0 else 0.0

    # 舌象（舌 + 苔 合并）
    tongue_combined = f"{tongue_text} {coat_text}"
    tongue_score, tongue_matched = _match_pattern(tongue_combined, ch_data.舌象)
    top_tongue = sorted([w for (_, w) in ch_data.舌象], reverse=True)[:3]
    top_tongue_sum = sum(top_tongue)
    tongue_norm = min(tongue_score / top_tongue_sum, 1.0) if top_tongue_sum > 0.0 else 0.0

    raw_score = pulse_norm * 0.4 + symptom_norm * 0.4 + tongue_norm * 0.2
    final_score = raw_score * ch_data.base_weight

    # 亚型判定（仅少阴病）
    subtype: Optional[str] = None
    if channel == "少阴病":
        han_count = sum(1 for kw in HANHUA_KW
                        if kw in pulse_text or kw in symptom_text)
        re_count = sum(1 for kw in REHUA_KW
                       if kw in pulse_text or kw in symptom_text)
        if han_count > re_count and han_count > 0:
            subtype = "寒化"
        elif re_count > han_count and re_count > 0:
            subtype = "热化"

    return (final_score, subtype, pulse_matched, symptom_matched, tongue_matched)


# ════════════════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════════════════

def detect_combined_channels(scores: Dict[str, float], detail: Dict[str, tuple]) -> Optional[CombinedChannelResult]:
    """
    合病检测：当 Top2 评分差距 < 15% 时，判定为合病。
    
    合病判定规则：
    1. Top2 差距 < 15% → 合病
    2. 阳经之间合病 → 三阳合病（太阳+阳明+少阳）
    3. 阴经之间合病 → 三阴合病（太阴+少阴+厥阴）
    4. 阴阳合病 → 表里同病或阴阳合病
    5. 返回参与经的合方推荐
    """
    sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(sorted_items) < 2:
        return None
    
    top_ch, top_score = sorted_items[0]
    second_ch, second_score = sorted_items[1]
    
    # 判断合病条件
    if top_score <= 0:
        return None
    
    diff_pct = abs(top_score - second_score) / max(top_score, second_score)
    
    if diff_pct > 0.15:
        return None  # 差距大，非合病
    
    # 获取参与经的推荐方
    combined_formulas = []
    combined_channels = []
    combined_scores = {}
    combined_desc_parts = []
    
    # 收集所有差距 < 15% 的经
    for ch, score in sorted_items:
        if abs(top_score - score) / max(top_score, score) <= 0.15 and ch != top_ch:
            combined_channels.append(ch)
            combined_scores[ch] = score
            if ch in LIUJING_SYMPTOMS and LIUJING_SYMPTOMS[ch].推荐方:
                combined_formulas.extend(LIUJING_SYMPTOMS[ch].推荐方)
    
    # 去重（保持顺序）
    seen = set()
    dedup_formulas = []
    for f in combined_formulas:
        if f not in seen:
            seen.add(f)
            dedup_formulas.append(f)
    
    # 判定合病类型
    yang_channels = {"太阳病", "阳明病", "少阳病"}
    yin_channels = {"太阴病", "少阴病", "厥阴病"}
    
    all_involved = {top_ch} | set(combined_channels)
    
    if all_involved.issubset(yang_channels):
        合病类型 = "三阳合病" if len(all_involved) >= 3 else "二阳合病"
    elif all_involved.issubset(yin_channels):
        合病类型 = "三阴合病" if len(all_involved) >= 3 else "二阴合病"
    else:
        合病类型 = "阴阳合病（表里同病）"
    
    主经_data = LIUJING_SYMPTOMS[top_ch]
    
    return CombinedChannelResult(
        主经=top_ch,
        主经得分=top_score,
        合病经=combined_channels,
        合病得分=combined_scores,
        合方推荐=dedup_formulas[:8],  # 最多推荐8首合方
        合病说明=f"{合病类型}：{top_ch}({top_score:.3f}) + {'、'.join(combined_channels)}({', '.join(f'{s:.3f}' for s in combined_scores.values())})",
        合病类型=合病类型,
    )


def liujing_score(
    tongue: str,
    coat: str,
    pulse: str,
    symptoms: str,
    tiyong_type: str = "",
    year: Optional[str] = None,
) -> LiujingScoreResult:
    """加权六经评分主入口"""
    all_symptoms = f"{symptoms} {coat}" if coat else symptoms

    channel_scores: Dict[str, float] = {}
    channel_details: Dict[str, tuple] = {}

    for ch in LIUJING_ORDER:
        score, subtype, pm, sm, tm = _score_single_channel(
            ch, pulse, all_symptoms, tongue, coat)
        channel_scores[ch] = score
        channel_details[ch] = (score, subtype, pm, sm, tm)

    # 五运六气动态加权
    if year:
        weights = compute_wuyun_weights(year)
        if weights:
            for ch, w in weights.items():
                if ch in channel_scores:
                    channel_scores[ch] = min(channel_scores[ch] * w, 1.0)

    # 排序
    sorted_items = sorted(channel_scores.items(), key=lambda kv: kv[1], reverse=True)

    top_channel = sorted_items[0][0]
    top_score = sorted_items[0][1]

    confidence = f"{top_score * 100.0:.0f}%"

    # 鉴别边界经
    boundary_warnings: List[BoundaryWarning] = []
    for ch_name, ch_score in sorted_items[1:]:
        if ch_name == top_channel:
            continue
        if top_score > 0.0 and ch_score > 0.0:
            diff_pct = abs(top_score - ch_score) / max(top_score, ch_score)
            if diff_pct <= 0.15:
                boundary_warnings.append(BoundaryWarning(
                    经=ch_name,
                    得分=ch_score,
                    差距百分比=f"{diff_pct * 100.0:.1f}%",
                    提示=(f"{top_channel}与{ch_name}仅差{diff_pct * 100.0:.1f}%"
                          f"，需进一步鉴别"),
                ))

    # 合病检测（新增）
    combined_detection = detect_combined_channels(channel_scores, channel_details)

    top_data = LIUJING_SYMPTOMS[top_channel]
    bu_ti, bu_yong, _bu_desc = top_data.体用映射
    body_use: Dict[str, float] = {"体分": bu_ti, "用分": bu_yong}

    sub_type: Optional[str] = None
    recommended_formulas: List[str] = list(top_data.推荐方)
    if top_channel == "少阴病":
        detail = channel_details.get("少阴病")
        sub_type = detail[1] if detail else None
        if sub_type == "寒化":
            if top_data.推荐方_寒化 is not None:
                body_use.clear()
                if top_data.体用映射_寒化 is not None:
                    ht, hu, _ = top_data.体用映射_寒化
                    body_use["体分"] = ht
                    body_use["用分"] = hu
                recommended_formulas = list(top_data.推荐方_寒化)
        elif sub_type == "热化":
            if top_data.推荐方_热化 is not None:
                body_use.clear()
                if top_data.体用映射_热化 is not None:
                    rt, ru, _ = top_data.体用映射_热化
                    body_use["体分"] = rt
                    body_use["用分"] = ru
                recommended_formulas = list(top_data.推荐方_热化)

    # 证据链
    evidence_chain: List[EvidenceChainItem] = []
    for ch in LIUJING_ORDER:
        score = channel_scores.get(ch)
        if score is not None and score >= 0.1:
            _, _, pm, sm, tm = channel_details[ch]
            parts: List[str] = []
            if pm:
                parts.append(f"脉：{','.join(pm)}")
            if sm:
                parts.append(f"症：{','.join(sm)}")
            if tm:
                parts.append(f"舌：{','.join(tm)}")
            if not parts:
                parts.append("证据不足")
            evidence_chain.append(EvidenceChainItem(
                经=ch, 得分=score, 证据="；".join(parts)))

    # 方证匹配
    fangzheng_matched: List[MatchedFormulaSyndrome] = []
    for fz in top_data.方证:
        match_count = sum(
            1 for s in fz.症状
            if s in all_symptoms or s in pulse or s in tongue or s in coat
        )
        required = int(len(fz.症状) * 0.5)
        if match_count >= required:
            fangzheng_matched.append(MatchedFormulaSyndrome(
                方证=fz.方证,
                方=fz.方,
                匹配度=f"{match_count}/{len(fz.症状)}",
            ))

    return LiujingScoreResult(
        各经评分=channel_scores,
        推荐经=top_channel,
        置信度=confidence,
        原始得分=top_score,
        疑似经=boundary_warnings,
        脉证合参=f"{top_data.推荐方[0]}证：{top_data.提纲}",
        体用映射=body_use,
        体用倾向=top_data.体用倾向,
        推荐方=recommended_formulas,
        方剂说明=top_data.方剂说明,
        匹配方证=fangzheng_matched,
        六经传变=top_data.六经传变,
        证据链=evidence_chain,
        亚型=sub_type,
        合病检测=combined_detection,
    )


def liujing_analyze(tongue: str, coat: str, pulse: str,
                    symptoms: str) -> str:
    """生成六经辨证文本报告"""
    result = liujing_score(tongue, coat, pulse, symptoms, "", None)
    lines: List[str] = []
    lines.append("=" * 56)
    lines.append("  六经辨证分析报告")
    lines.append("=" * 56)
    lines.append(f"  舌象：{tongue or '(未提供)'}    苔象：{coat or '(未提供)'}")
    lines.append(f"  脉象：{pulse or '(未提供)'}")
    lines.append(f"  症状：{symptoms or '(未提供)'}")
    lines.append("-" * 56)
    lines.append("  [各经评分]")
    scores_sorted = sorted(result.各经评分.items(), key=lambda kv: kv[1], reverse=True)
    for ch_name, ch_score in scores_sorted:
        bar_len = int(ch_score * 30.0)
        bar = "#" * bar_len + "." * max(0, 30 - min(bar_len, 30))
        lines.append(f"    {ch_name}：{ch_score * 100.0:>7.2f}%  [{bar}]")
    lines.append("-" * 56)
    lines.append(f"  [辨证结论]{result.推荐经}  置信度：{result.置信度}")
    lines.append(f"  [体用倾向]{result.体用倾向}")
    if result.亚型:
        lines.append(f"  [亚型]{result.亚型}")
    if result.疑似经:
        lines.append("-" * 56)
        lines.append("  [!] [疑似经边界警告]")
        for w in result.疑似经:
            lines.append(f"    - {w.提示}")
    lines.append("-" * 56)
    lines.append(
        f"  [体用映射]体分={result.体用映射.get('体分', 0.0):+.2f}  "
        f"用分={result.体用映射.get('用分', 0.0):+.2f}")
    lines.append(f"  [推荐经方]{', '.join(result.推荐方)}")
    if result.匹配方证:
        lines.append("  [方证匹配]")
        for fz in result.匹配方证:
            lines.append(f"    - {fz.方证} -> {fz.方} (匹配{fz.匹配度})")
    if result.六经传变:
        lines.append(f"  [传变提示]{result.六经传变}")
    lines.append("-" * 56)
    lines.append("  [证据链]")
    for item in result.证据链:
        lines.append(f"    {item.经}({item.得分 * 100.0:.2f}%)：{item.证据}")
    lines.append("=" * 56)
    return "\n".join(lines)


def liujing_compare(tongue: str, coat: str, pulse: str,
                    symptoms: str) -> List[BoundaryWarning]:
    """鉴别边界经"""
    return liujing_score(tongue, coat, pulse, symptoms, "", None).疑似经
