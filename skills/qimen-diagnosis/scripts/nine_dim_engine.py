#!/usr/bin/env python3
"""
九维立体动态奇门遁甲推演引擎 v2.0

基于 qimen-diagnosis 原有体系 + 九维推演方法.md 升级方案
实现：三维立体九宫 + 时序动态飞宫 + 多维度绑定 + 九维交叉校验

使用方式：
    from nine_dim_engine import NineDimEngine
    
    engine = NineDimEngine()
    
    # 静态九维推演
    result = engine.deduce_3d(
        year=2026, month=6, day=2, hour=13,
        multi_dim_bind={
            "person": "问事人",
            "event": "求职面试",
            "object": "目标公司",
            "semantic": "积极期望"
        },
        spatial_hints={
            "person_zone": "震宫",
            "target_zone": "离宫"
        }
    )
    
    # 多帧动态推演
    frames = [
        {"time": "2026-06-02 13:00", "data": frame1_data},
        {"time": "2026-06-03 09:00", "data": frame2_data},
    ]
    result = engine.deduce_dynamic(frames)
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
import math

# ── 实时时间感知接入 ──
try:
    from openakita.time_awareness import get_time_awareness
    _HAVE_TIME_AWARENESS = True
except ImportError:
    _HAVE_TIME_AWARENESS = False

# ═══════════════════════════════════════════════════════════════
# 一、九维数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class TimeSpaceMeta:
    """九维时空元数据"""
    gregorian: str = ""           # 公历时间 "2026-06-02 13:00"
    jieqi: str = ""               # 节气名
    yuejian: str = ""             # 月建
    ri_ganzhi: str = ""           # 日干支
    shi_ganzhi: str = ""          # 时干支
    dun_type: str = ""            # 阳遁/阴遁
    ju_number: int = 0            # 本局数
    scene_type: str = "static"    # static / single_frame / multi_frame / video
    frame_interval: float = 0.0   # 帧时间间隔(秒)
    # ── 传统奇门排盘 ──
    tianpan_gan: Dict[str, str] = field(default_factory=dict)  # 天盘干{宫名:干}
    dipan_gan: Dict[str, str] = field(default_factory=dict)    # 地盘干{宫名:干}
    men_layout: Dict[str, str] = field(default_factory=dict)   # 八门{宫名:门}
    xing_layout: Dict[str, str] = field(default_factory=dict)  # 九星{宫名:星}
    shen_layout: Dict[str, str] = field(default_factory=dict)  # 八神{宫名:神}
    season: str = ""                # 春/夏/秋/冬/四季
    season_wuxing: str = ""         # 木/火/金/水/土
    # ── 格局分析 ──
    patterns: List[Dict] = field(default_factory=list)          # 天盘vs地盘格局列表
    # ── 旺衰 ──
    star_wangshuai: Dict[str, str] = field(default_factory=dict)   # 星旺衰{星名:状态}
    gate_wangshuai: Dict[str, str] = field(default_factory=dict)   # 门旺衰{门名:状态}
    # ── 门迫 ──
    menpo_list: List[Dict] = field(default_factory=list)           # [门名+宫名+类型]
    fanyin_palaces: List[str] = field(default_factory=list)        # 反吟宫位
    fuyin_palaces: List[str] = field(default_factory=list)         # 伏吟宫位
    # ── 应期 ──
    yingqi_result: str = ""              # 应期结果文本
    yingqi_near_far: str = ""            # 近/远
    yingqi_fast_slow: str = ""           # 快/慢
    ma_xing_palace: str = ""             # 马星所在宫
    # ── 原有权重 ──
    nine_dim_weights: Dict[str, float] = field(default_factory=lambda: {
        "X": 1.0, "Y": 1.0, "Z": 1.0, "T": 1.0,
        "P": 1.0, "E": 1.0, "O": 1.0, "S": 1.0, "L": 1.0
    })


@dataclass
class SpatialBlock3D:
    """三维空间区块"""
    x: float = 0.0                # X横向坐标（0-1归一化）
    y: float = 0.0                # Y纵向坐标（0-1归一化）
    z: float = 0.0                # Z深度坐标（-1~1，正为凸/阳，负为凹/阴）
    palace: str = ""              # 归属九宫
    yin_yang: str = "平"         # 阴阳属性：阳/阴/平
    weight: float = 0.5           # 宫位权重（0-1.0）
    cross_palaces: List[str] = field(default_factory=list)  # 跨宫列表
    binding_type: str = ""        # 多维绑定类型：person/event/object/semantic
    label: str = ""               # 区块标签
    confidence: float = 0.5       # 可信度


@dataclass
class QimenDynamicFlow:
    """动态飞宫轨迹"""
    yongshen_trace: List[Dict] = field(default_factory=list)
    palace_changes: List[Dict] = field(default_factory=list)
    men_xing_moves: List[Dict] = field(default_factory=list)
    event_nodes: List[Dict] = field(default_factory=list)
    tendency_score: float = 0.0   # 趋势得分（-1.0 ~ 1.0）


@dataclass
class Palace3D:
    """立体九宫单元"""
    name: str = ""                # 宫名：坎/坤/震/巽/中/乾/兑/艮/离
    number: int = 0               # 洛书数 1-9
    x_center: float = 0.0         # X中心坐标
    y_center: float = 0.0         # Y中心坐标
    z_avg: float = 0.0            # Z平均深度
    yin_yang: str = "平"         # 阴阳属性
    weight: float = 0.5           # 宫气权重
    star: str = ""                # 天盘九星
    gate: str = ""                # 人盘八门
    spirit: str = ""              # 神盘八神
    tiangan: str = ""             # 地盘天干
    dizhi: str = ""              # 地盘地支
    shengke_strength: float = 0.0  # 生克力度（用于九维交叉验证）
    occupants: List[SpatialBlock3D] = field(default_factory=list)  # 宫内区块
    cross_palaces: List[str] = field(default_factory=list)  # 互通宫位


@dataclass
class NineDimResult:
    """九维推演结果"""
    # 基础信息
    timespace: TimeSpaceMeta = field(default_factory=TimeSpaceMeta)
    
    # 三维九宫分布
    palaces_3d: Dict[str, Palace3D] = field(default_factory=dict)
    
    # 用神绑定
    yongshen_bindings: Dict[str, Dict] = field(default_factory=dict)
    
    # 九维分项推演
    nine_dim_analysis: Dict[str, Any] = field(default_factory=dict)
    
    # 综合结论
    overall_judgment: str = ""     # 整体吉凶判定
    core_profit_loss: List[str] = field(default_factory=list)  # 核心利弊
    yongshen_status: str = ""      # 用神旺衰
    potential_variables: List[str] = field(default_factory=list)  # 潜在变数
    
    # ── 新增：格局分析 ──
    pattern_summary: List[Dict] = field(default_factory=list)   # [{gan_pair, name, nature, meaning}]
    # ── 新增：旺衰分析 ──
    star_status_summary: str = ""     # 星旺衰总评
    gate_status_summary: str = ""     # 门旺衰总评
    # ── 新增：门迫分析 ──
    menpo_summary: List[Dict] = field(default_factory=list)     # [{gate, palace, type, impact}]
    fanyin_fuyin: List[str] = field(default_factory=list)       # ["反吟:坤", "伏吟:坎"]
    # ── 新增：应期分析 ──
    yingqi_summary: str = ""          # "近/快：3日内见分晓"
    yingqi_detail: str = ""           # 应期详细推演过程
    
    # 动态演变
    dynamic_flow: Optional[QimenDynamicFlow] = None
    
    # 校验记录
    verification_log: List[Dict] = field(default_factory=list)
    confidence_score: float = 0.5  # 推演可信度


# ═══════════════════════════════════════════════════════════════
# 二、九维常量与映射
# ═══════════════════════════════════════════════════════════════

# 九宫基础映射
PALACE_BASIC = {
    "坎": {"number": 1, "wuxing": "水", "position": "北", "luoshu": 1,
           "tiangan": "戊", "dizhi": "子"},
    "坤": {"number": 2, "wuxing": "土", "position": "西南", "luoshu": 2,
           "tiangan": "己", "dizhi": "未申"},
    "震": {"number": 3, "wuxing": "木", "position": "东", "luoshu": 3,
           "tiangan": "庚", "dizhi": "卯"},
    "巽": {"number": 4, "wuxing": "木", "position": "东南", "luoshu": 4,
           "tiangan": "辛", "dizhi": "辰巳"},
    "中": {"number": 5, "wuxing": "土", "position": "中", "luoshu": 5,
           "tiangan": "", "dizhi": ""},
    "乾": {"number": 6, "wuxing": "金", "position": "西北", "luoshu": 6,
           "tiangan": "甲", "dizhi": "戌亥"},
    "兑": {"number": 7, "wuxing": "金", "position": "西", "luoshu": 7,
           "tiangan": "丁", "dizhi": "酉"},
    "艮": {"number": 8, "wuxing": "土", "position": "东北", "luoshu": 8,
           "tiangan": "丙", "dizhi": "丑寅"},
    "离": {"number": 9, "wuxing": "火", "position": "南", "luoshu": 9,
           "tiangan": "乙", "dizhi": "午"},
}

# 九星基础
STAR_BASIC = {
    "天蓬": {"wuxing": "水", "nature": "凶", "meaning": "大趋势/破耗"},
    "天芮": {"wuxing": "土", "nature": "凶", "meaning": "病/事端/核心问题"},
    "天冲": {"wuxing": "木", "nature": "凶", "meaning": "冲克/变动/突破"},
    "天辅": {"wuxing": "木", "nature": "吉", "meaning": "辅助/教化/助力"},
    "天禽": {"wuxing": "土", "nature": "吉", "meaning": "中宫/平衡/核心"},
    "天心": {"wuxing": "金", "nature": "吉", "meaning": "决策/核心/主导"},
    "天柱": {"wuxing": "金", "nature": "凶", "meaning": "支撑/负担/固守"},
    "天任": {"wuxing": "土", "nature": "吉", "meaning": "承载/担当/稳定"},
    "天英": {"wuxing": "火", "nature": "凶", "meaning": "消息/名气/虚火"},
}

# 八门基础
GATE_BASIC = {
    "休": {"wuxing": "水", "nature": "吉", "meaning": "休整/等待/修养"},
    "生": {"wuxing": "土", "nature": "吉", "meaning": "生长/收益/新生"},
    "伤": {"wuxing": "木", "nature": "凶", "meaning": "损伤/冲突/损耗"},
    "杜": {"wuxing": "木", "nature": "凶", "meaning": "阻碍/封闭/堵塞"},
    "景": {"wuxing": "火", "nature": "平", "meaning": "消息/虚象/文书"},
    "死": {"wuxing": "土", "nature": "凶", "meaning": "终结/静止/固守"},
    "惊": {"wuxing": "金", "nature": "凶", "meaning": "变动/惊吓/意外"},
    "开": {"wuxing": "金", "nature": "吉", "meaning": "开创/启程/畅通"},
}

# 八神基础
SPIRIT_BASIC = {
    "值符": {"nature": "大吉", "meaning": "天时地利最吉之象"},
    "螣蛇": {"nature": "凶", "meaning": "虚诈/变化/不安"},
    "太阴": {"nature": "平", "meaning": "隐秘/暗中/幕后"},
    "六合": {"nature": "吉", "meaning": "合作/多方/聚集"},
    "白虎": {"nature": "大凶", "meaning": "凶煞/冲突/强力阻碍"},
    "玄武": {"nature": "凶", "meaning": "暗昧/欺骗/不明"},
    "九地": {"nature": "平", "meaning": "稳定/持久/缓慢"},
    "九天": {"nature": "吉", "meaning": "变动/上升/高远"},
}

# 九宫XY平面坐标（归一化 0-1）
PALACE_XY = {
    "坎": (0.5, 0.9),   # 下中
    "坤": (0.17, 0.83), # 左下
    "震": (0.17, 0.5),  # 左中
    "巽": (0.17, 0.17), # 左上
    "中": (0.5, 0.5),   # 正中
    "乾": (0.83, 0.17), # 右上
    "兑": (0.83, 0.5),  # 右中
    "艮": (0.83, 0.83), # 右下
    "离": (0.5, 0.17),  # 上中
}

# 五行生克
WUXING_SHENG = {
    "木": "火", "火": "土", "土": "金", "金": "水", "水": "木"
}
WUXING_KE = {
    "木": "土", "火": "金", "土": "水", "金": "木", "水": "火"
}

# ═══════════════════════════════════════════════════════════════
# 三、传统奇门格局表
# ═══════════════════════════════════════════════════════════════

# 天盘干 + 地盘干 → 格局判定
TIAN_DI_PATTERNS = {
    # ═══════════════════════════════
    # 飞盘系 — 天盘干 vs 地盘干
    # ═══════════════════════════════
    # ── 大吉格局 ──
    ("戊", "丙"): ("龙回首", "大吉", "百事皆宜，所做皆成，贵人相助之象"),
    ("丙", "戊"): ("鸟跌穴", "大吉", "谋事有成，意外之喜，所图可成"),
    ("乙", "丁"): ("风助火势", "吉", "顺势而为，事半功倍"),
    ("丁", "乙"): ("朱雀乘风", "吉", "声名远播，文采飞扬"),
    ("乙", "丙"): ("风火相生", "吉", "上下同心，内外和合"),
    ("丙", "乙"): ("火借风势", "吉", "名声借力远扬，大吉之象"),
    ("己", "戊"): ("明堂合德", "小吉", "中正平和，谋事可成"),
    ("壬", "戊"): ("小蛇化龙", "小吉", "渐进转运之势，小人物渐得势"),
    ("丁", "丙"): ("火金光耀", "吉", "文采焕发，名扬四方"),
    ("丙", "丁"): ("双火同辉", "吉", "热情洋溢，众志成城"),

    # ── 大凶格局 ──
    ("辛", "乙"): ("白虎猖狂", "大凶", "主血光争斗破财，宜静不宜动"),
    ("乙", "辛"): ("青龙逃走", "凶", "好事难成，宜退不宜进，主动损失"),
    ("丁", "癸"): ("朱雀投江", "凶", "文书有损口舌是非，音信易沉"),
    ("癸", "丁"): ("螣蛇夭矫", "凶", "虚惊怪异反复无常，丑妇失笑"),
    ("庚", "丙"): ("太白入荧", "凶", "贼来，失物主损，入室主灾"),
    ("丙", "庚"): ("荧入太白", "凶", "贼去，事态已过，宜静守"),
    ("庚", "戊"): ("天乙伏宫", "凶", "事有阻隔，主客颠倒"),
    ("戊", "庚"): ("天乙飞宫", "凶", "变动迁移，主客易位"),
    ("己", "庚"): ("日奇入狱", "凶", "迷惑阻滞，暗昧难明"),
    ("庚", "己"): ("刑格", "凶", "刑伤破败，官非诉讼之象"),
    ("壬", "庚"): ("天牢", "凶", "困顿难脱，宜守不宜动"),
    ("庚", "壬"): ("天网", "凶", "天罗地网，进退两难"),
    ("戊", "己"): ("贵人入狱", "凶", "恩中有害，明助暗损"),
    ("戊", "癸"): ("地网自缚", "凶", "守成有余，开拓不足"),
    ("癸", "庚"): ("渊水藏金", "小吉", "深藏不露，待机而动"),
    ("庚", "癸"): ("太白沉渊", "凶", "刚直受困，审时度势方可脱"),
    ("壬", "癸"): ("双水汇流", "平", "智慧叠加，但需防过犹不及"),
    ("癸", "壬"): ("重渊叠浪", "凶", "险象环生，宜保守稳妥"),
    ("辛", "壬"): ("白虎入渊", "凶", "刚猛落水，力不从心"),
    ("壬", "辛"): ("腾蛇入海", "凶", "虚惊藏于暗处，防阴险小人"),

    # ── 平格局 ──
    ("戊", "壬"): ("青龙入水", "平", "龙游浅水，暂困待时"),
    ("癸", "戊"): ("天罗自镇", "平", "自我设限，突破在于一念之间"),
    ("己", "壬"): ("地网蒙昧", "平", "方向未明，静待时机"),
    ("壬", "己"): ("云蔽中天", "平", "云雾遮日，暂不明朗"),
    ("辛", "庚"): ("白虎衔尸", "凶", "竞争激烈，谨防两败俱伤"),
    ("庚", "辛"): ("太白镂金", "平", "切磋琢磨，精益求精"),

    # ═══════════════════════════════
    # 转盘系 — 特殊格局（星门神组合判定）
    # ═══════════════════════════════
    # 三奇得使
    "乙奇得使": ("乙奇得使", "吉", "日奇得地，谋为有利，女子相助"),
    "丙奇得使": ("丙奇得使", "吉", "月奇得地，求财得利，贵人扶持"),
    "丁奇得使": ("丁奇得使", "吉", "星奇得地，文书如意，信息通达"),

    # 九遁格局
    "天遁": ("天遁", "大吉", "乙+丙临开门，通天之象，万事可为"),
    "地遁": ("地遁", "大吉", "乙+辛临开门，入地之象，安营置业"),
    "人遁": ("人遁", "大吉", "丁+乙临休门，人和之象，合作和合"),
    "神遁": ("神遁", "吉", "丙+乙临生门，神明护佑，祈福灵验"),
    "鬼遁": ("鬼遁", "吉", "乙+乙临杜门，隐秘潜行，暗度陈仓"),
    "风遁": ("风遁", "吉", "乙+辛临巽宫，乘风之势，远行顺利"),
    "云遁": ("云遁", "吉", "乙+辛临坤宫，腾云之象，避实击虚"),
    "龙遁": ("龙遁", "吉", "乙+癸临坎宫，潜龙入水，水利之事利"),
    "虎遁": ("虎遁", "吉", "乙+己临艮宫，虎踞山林，镇守有威"),

    # 三诈五假
    "真诈": ("真诈", "吉", "乙+丙临开/休/生，谋事成真，所求必应"),
    "休诈": ("休诈", "吉", "丁+乙临休/生门，以退为进，暗藏玄机"),
    "重诈": ("重诈", "吉", "丙+乙临休/生门，重重关碍终可破"),
    "天假": ("天假", "吉", "丙+丁临景门，借天时之力成事"),
    "地假": ("地假", "吉", "丁/癸临杜门，借地利之便潜行"),
    "人假": ("人假", "吉", "乙/丙临惊门，借人和之势破局"),
    "神假": ("神假", "吉", "丁/乙临死门，借鬼神之力震慑"),
    "鬼假": ("鬼假", "平", "丙/丁临伤门，借非常手段谋非常之事"),

    # 玉女守门
    "玉女守门": ("玉女守门", "吉", "丁奇临值使之门，宜婚姻酒宴"),

    # 游都/鲁都
    "游都": ("游都", "小吉", "主行人将至，消息渐通"),
    "鲁都": ("鲁都", "凶", "主行人未归，音信难通"),

    # ═══════════════════════════════
    # 鸣法系 — 组合格局
    # ═══════════════════════════════
    ("癸", "乙"): ("日月并明", "吉", "阴阳调和，智勇双全"),
    ("乙", "癸"): ("星隐月宫", "平", "才华内敛，暂隐待时"),
    ("丁", "戊"): ("星火燎原", "吉", "星火之势，虽微可大"),
    ("戊", "丁"): ("金辉映日", "小吉", "财星显耀，利见大人"),
    ("己", "乙"): ("地承天露", "小吉", "卑微得助，渐入佳境"),
    ("乙", "己"): ("风拂尘埃", "平", "扫除旧弊，拨云见日"),
    ("辛", "丙"): ("金锁玉关", "平", "虽险实安，守成为上"),
    ("丙", "辛"): ("火炼真金", "小吉", "历经磨难，终成大器"),
    ("己", "丁"): ("地涌金莲", "吉", "土中藏宝，发掘可成"),
    ("丁", "己"): ("火照幽谷", "小吉", "暗中得明，迷雾可散"),
    ("辛", "丁"): ("玉映金镶", "小吉", "内外兼修，表里如一"),
    ("丁", "辛"): ("星陨寒潭", "平", "明珠投暗，暂需等待"),
    ("己", "丙"): ("日照坤舆", "吉", "土得火生，力源不绝"),
    ("丙", "己"): ("火暖冻土", "小吉", "渐解冰冻，春意暗生"),
    ("辛", "戊"): ("金匮藏珠", "吉", "财不露白，蓄势待发"),
    ("戊", "辛"): ("土掩金辉", "平", "韬光养晦，不露锋芒"),
    ("己", "辛"): ("雾锁金城", "凶", "腹背受敌，内忧外患"),
    ("辛", "己"): ("金戈入阵", "凶", "刀兵相见，宜和不宜战"),
    ("壬", "乙"): ("江河流芳", "小吉", "水润草木，生生不息"),
    ("乙", "壬"): ("水木清华", "吉", "相生相伴，发展顺畅"),
    ("壬", "丙"): ("水火既济", "吉", "阴阳交泰，事可圆成"),
    ("丙", "壬"): ("日照大江", "小吉", "光影交织，明暗各半"),
    ("壬", "丁"): ("星汉灿烂", "吉", "浩瀚有象，万物含章"),
    ("丁", "壬"): ("萤映银河", "小吉", "微光入海，不掩其华"),
    ("癸", "丙"): ("雨润骄阳", "吉", "水火互济，化育万物"),
    ("丙", "癸"): ("雨后初晴", "小吉", "云开日出，渐入佳境"),
    ("癸", "己"): ("雨落平川", "平", "普润无偏，平淡是真"),
    ("己", "癸"): ("地承雨露", "小吉", "厚德载物，润物无声"),

    # ── 新增格局（古籍合参 60组完整扩充） ──
    ("庚", "戊"): ("太白天乙伏宫", "大凶", "搬迁测事关键格·主事有阻隔迁徙被动·出秘笈大全"),
    ("戊", "庚"): ("天乙飞宫", "凶", "变动迁移主客易位·出行谋事大忌·出元灵经"),
    ("丁", "乙"): ("星月耀辉", "吉", "阴得阳助文采焕发·大吉·出秘笈大全"),
    ("乙", "丁"): ("日入凤池", "小吉", "阳入阴位文明化育·出旨归"),
    ("壬", "甲"): ("玄龙巡海", "平", "阳化阴体大势潜藏·出元灵经"),
    ("甲", "壬"): ("青龙入渊", "小吉", "以退为进潜龙勿用·出秘笈大全"),
    ("辛", "甲"): ("凤鸣岐山", "吉", "新秀崛起改天换地·出演义"),
    ("甲", "辛"): ("白鹤栖松", "小吉", "贞静守正待时而行·出旨归"),
    ("庚", "甲"): ("太白当街", "凶", "金伐木象争斗口舌·出行不利·出秘笈大全"),
    ("甲", "庚"): ("青龙困鳞", "凶", "木被金伤仁德受阻·出元灵经"),
}

# ═══════════════════════════════════════════════════════════════
# 五、时间质量判断表（古籍合参新增）
# ═══════════════════════════════════════════════════════════════

# 宝义制和伐四法（法窍·门宫生克定性）
# 门生宫为义(吉) / 宫生门为宝(利客) / 宫克门为制(利主)
# 门克宫为伐(凶) / 同五行为和(平)
BAO_YI_ZHI_FA = {
    "宝": {"meaning": "宫生门", "zhu_ke": "利客可主动", "nature": "吉"},
    "义": {"meaning": "门生宫", "zhu_ke": "利主宜固守", "nature": "吉"},
    "和": {"meaning": "门宫同五行", "zhu_ke": "可进可退", "nature": "平"},
    "制": {"meaning": "宫克门", "zhu_ke": "利主以静制动", "nature": "次凶"},
    "伐": {"meaning": "门克宫", "zhu_ke": "利客见机而动", "nature": "凶"},
}

# 五阳五阴时（法窍·动静态势判定）
# 阳时主动、阴时主静；阳时可出师、阴时宜固守
WU_YANG_SHI = {"甲", "乙", "丙", "丁", "戊"}  # 阳时
WU_YIN_SHI = {"己", "庚", "辛", "壬", "癸"}  # 阴时

# 三甲开阖法（法窍·气数开阖判定）
# 甲己日开、乙庚日阖、丙辛日开、丁壬日阖、戊癸日开
# 开日气机外放主行动、阖日气机内收主静守
SAN_JIA_KAI_HE = {
    ("甲", "己"): "开", ("乙", "庚"): "阖", ("丙", "辛"): "开",
    ("丁", "壬"): "阖", ("戊", "癸"): "开",
}

# ═══════════════════════════════════════════════════════════════
# 六、古籍出处标记系统
# ═══════════════════════════════════════════════════════════════

# 格局 → 古籍出处映射
PATTERN_PROVENANCE = {
    # 秘笈大全系
    "白虎猖狂": "秘笈大全·卷九·十干克应",
    "青龙逃走": "秘笈大全·卷九·十干克应",
    "朱雀投江": "秘笈大全·卷九·十干克应",
    "螣蛇夭矫": "秘笈大全·卷九·十干克应",
    "荧入太白": "秘笈大全·卷九·十干克应",
    "太白入荧": "秘笈大全·卷九·十干克应",
    "天乙伏宫": "秘笈大全·卷九·十干克应",
    "天乙飞宫": "秘笈大全·卷九·十干克应",
    # 元灵经系
    "日月并明": "元灵经·卷六·鸣法释义",
    "星月耀辉": "元灵经·卷六·鸣法释义",
    "水火既济": "元灵经·卷六·鸣法释义",
    # 法窍系
    "乙奇得使": "奇门法窍·卷四·三奇得使",
    "丙奇得使": "奇门法窍·卷四·三奇得使",
    "丁奇得使": "奇门法窍·卷四·三奇得使",
    "天辅时": "奇门法窍·卷三·天辅时",
    # 旨归系
    "金匮藏珠": "奇门旨归·卷五·鸣法",
    "青龙入水": "奇门旨归·卷五·平格",
    "双水汇流": "奇门旨归·卷五·平格",
    # 演义系
    "青龙困鳞": "遁甲演义·卷二·十干合参",
    "凤鸣岐山": "遁甲演义·卷二·十干合参",
    "太白当街": "遁甲演义·卷二·十干合参",
}

# 六十四卦 → 古籍出处
BAGUA_64_PROVENANCE = {
    "水火既济": "周易·既济卦+奇门法窍·天地盘应期",
    "火水未济": "周易·未济卦+奇门法窍·天地盘应期",
    "天地否": "周易·否卦+奇门旨归·宫卦合参",
    "地天泰": "周易·泰卦+奇门旨归·宫卦合参",
}

# L1~L6 空间剖面层定义（九维立体穿透核心）
SPATIAL_PROFILE_LAYERS = {
    "L1": {"name": "天盘层", "symbol": "九星", "focus": "外部大势·气运流转",
           "source": "天盘星落宫 + 星神组合"},
    "L2": {"name": "人盘层", "symbol": "八门", "focus": "人事动态·事态进程",
           "source": "人盘门落宫 + 宫门生克"},
    "L3": {"name": "地盘层", "symbol": "九宫+地干", "focus": "地气根基·现实条件",
           "source": "地盘奇仪 + 宫位五行"},
    "L4": {"name": "格局层", "symbol": "天干合冲制化", "focus": "矛盾本质·因果核心",
           "source": "天盘干×地盘干 = 格局"},
    "L5": {"name": "年命层", "symbol": "事主年命+生肖", "focus": "人事归属·利益所在",
           "source": "年命干支落宫 + 与各宫生克"},
    "L6": {"name": "时令层", "symbol": "节气+月建+日干支", "focus": "时空定数·应期刻度",
           "source": "节气旺衰 + 三甲开阖 + 五阳五阴时"},
}

# 12节气顺序表（用于滚动推演）
JIEQI_CYCLE = [
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
]

# 六阶推进法（时间轴推演阶段定义）
SIX_STAGES = {
    1: {"name": "前因阶", "range": "当前时间前推3~6节气", "purpose": "回溯成因·探查初始条件"},
    2: {"name": "萌芽阶", "range": "当前时间前推1~3节气", "purpose": "定位触发节点·初始变数"},
    3: {"name": "当下阶", "range": "当前节气±1", "purpose": "锁定核心矛盾·读主客态势"},
    4: {"name": "转折阶", "range": "当前时间后推1~3节气", "purpose": "预判趋势拐点·风险高发区"},
    5: {"name": "落定阶", "range": "当前时间后推3~6节气", "purpose": "推演结果形态·终局结构"},
    6: {"name": "余波阶", "range": "当前时间后推6~12节气", "purpose": "评估影响余量·耗散路径"},
}

# 九星 → 古籍出处
STAR_PROVENANCE = {
    "天蓬": "遁甲演义·卷一/灵枢·九宫八风",
    "天芮": "遁甲演义·卷一/灵枢·九宫八风",
    "天冲": "遁甲演义·卷一/灵枢·九宫八风",
    "天辅": "遁甲演义·卷一/灵枢·九宫八风",
    "天禽": "遁甲演义·卷一/灵枢·九宫八风",
    "天心": "遁甲演义·卷一/灵枢·九宫八风",
    "天柱": "遁甲演义·卷一/灵枢·九宫八风",
    "天任": "遁甲演义·卷一/灵枢·九宫八风",
    "天英": "遁甲演义·卷一/灵枢·九宫八风",
}

# 八门 → 古籍出处
GATE_PROVENANCE = {
    "休": "遁甲演义·卷四·八门",
    "生": "遁甲演义·卷四·八门",
    "伤": "遁甲演义·卷四·八门",
    "杜": "遁甲演义·卷四·八门",
    "景": "遁甲演义·卷四·八门",
    "死": "遁甲演义·卷四·八门",
    "惊": "遁甲演义·卷四·八门",
    "开": "遁甲演义·卷四·八门",
}

# 九星配经脉 → 推演标记（非经典原文，属推演所得）
# 标记为: "推演所得/经典间接推导"
STAR_MERIDIAN_PROVENANCE_NOTE = "推演所得·间接推导（灵枢·九宫八风为基础）"
GATE_MERIDIAN_PROVENANCE_NOTE = "推演所得·间接推导·非经典直接出处"

# 九星四季旺相休囚死
STAR_WANGSHUAI = {
    "天蓬": {"wuxing": "水", "旺": "冬", "相": "春", "休": "秋", "囚": "夏", "死": "四季"},
    "天芮": {"wuxing": "土", "旺": "四季", "相": "秋", "休": "夏", "囚": "冬", "死": "春"},
    "天冲": {"wuxing": "木", "旺": "春", "相": "夏", "休": "冬", "囚": "四季", "死": "秋"},
    "天辅": {"wuxing": "木", "旺": "春", "相": "夏", "休": "冬", "囚": "四季", "死": "秋"},
    "天禽": {"wuxing": "土", "旺": "四季", "相": "秋", "休": "夏", "囚": "冬", "死": "春"},
    "天心": {"wuxing": "金", "旺": "秋", "相": "冬", "休": "四季", "囚": "春", "死": "夏"},
    "天柱": {"wuxing": "金", "旺": "秋", "相": "冬", "休": "四季", "囚": "春", "死": "夏"},
    "天任": {"wuxing": "土", "旺": "四季", "相": "秋", "休": "夏", "囚": "冬", "死": "春"},
    "天英": {"wuxing": "火", "旺": "夏", "相": "四季", "休": "春", "囚": "冬", "死": "秋"},
}

# 八门四季旺相
GATE_WANGSHUAI = {
    "休": {"wuxing": "水", "旺": "冬", "相": "春", "休": "秋", "囚": "夏", "死": "四季"},
    "生": {"wuxing": "土", "旺": "四季", "相": "秋", "休": "夏", "囚": "冬", "死": "春"},
    "伤": {"wuxing": "木", "旺": "春", "相": "夏", "休": "冬", "囚": "四季", "死": "秋"},
    "杜": {"wuxing": "木", "旺": "春", "相": "夏", "休": "冬", "囚": "四季", "死": "秋"},
    "景": {"wuxing": "火", "旺": "夏", "相": "四季", "休": "春", "囚": "冬", "死": "秋"},
    "死": {"wuxing": "土", "旺": "四季", "相": "秋", "休": "夏", "囚": "冬", "死": "春"},
    "惊": {"wuxing": "金", "旺": "秋", "相": "冬", "休": "四季", "囚": "春", "死": "夏"},
    "开": {"wuxing": "金", "旺": "秋", "相": "冬", "休": "四季", "囚": "春", "死": "夏"},
}

# 八门克宫为门迫，宫克门为宫迫
MEN_GONG_KE = {
    "休": "离", "生": "坎", "伤": "坤", "杜": "坤",
    "景": "兑", "死": "艮", "惊": "震", "开": "震",
}

# 马星地支（申子辰→寅，寅午戌→申，巳酉丑→亥，亥卯未→巳）
MA_XING = {
    ("申", "子", "辰"): "寅", ("寅", "午", "戌"): "申",
    ("巳", "酉", "丑"): "亥", ("亥", "卯", "未"): "巳",
}

# 季节→五行（用于星门旺衰判定）
SEASON_WUXING = {
    "春": "木", "夏": "火", "秋": "金", "冬": "水", "四季": "土",
}

# 内盘宫位（事情发生快/近）
INNER_PALACES = {"坎", "坤", "震", "巽", "中"}
# 外盘宫位（事情发生慢/远）
OUTER_PALACES = {"乾", "兑", "艮", "离"}

# 伏吟：星门与本宫相同 → 事缓/不动/反复
# 反吟：星门落对冲宫 → 事急/变动/反复


# ═══════════════════════════════════════════════════════════════
# 四、立体九宫引擎
# ═══════════════════════════════════════════════════════════════

class Palace3DEngine:
    """立体九宫建模引擎"""
    
    @staticmethod
    def xy_to_palace(x: float, y: float) -> str:
        """
        XY平面坐标 → 九宫归属
        x, y: 归一化 0-1
        """
        # 标准九宫分区
        if x < 0.33:
            if y < 0.33: return "巽"
            elif y < 0.66: return "震"
            else: return "坤"
        elif x < 0.66:
            if y < 0.33: return "离"
            elif y < 0.66: return "中"
            else: return "坎"
        else:
            if y < 0.33: return "乾"
            elif y < 0.66: return "兑"
            else: return "艮"
    
    @staticmethod
    def calc_3d_palace(x: float, y: float, z: float) -> Tuple[str, str, float]:
        """
        XYZ坐标 → 立体九宫 + 阴阳属性 + 权重
        返回: (宫名, 阴阳, 权重)
        """
        palace = Palace3DEngine.xy_to_palace(x, y)
        
        # Z轴阴阳判定
        if z > 0.2:
            yin_yang = "阳"
        elif z < -0.2:
            yin_yang = "阴"
        else:
            yin_yang = "平"
        
        # 宫位权重综合计算
        x_center, y_center = PALACE_XY.get(palace, (0.5, 0.5))
        dist_from_center = math.sqrt((x - x_center)**2 + (y - y_center)**2)
        
        # 权重 = 区块居中度 * 0.5 + Z深度 * 0.3 + 默认基准 0.2
        center_score = 1.0 - min(dist_from_center * 2, 0.8)
        depth_score = abs(z) * 0.5
        weight = min(center_score * 0.5 + depth_score * 0.3 + 0.2, 1.0)
        
        return palace, yin_yang, round(weight, 2)
    
    @staticmethod
    def build_3d_palaces(blocks: List[SpatialBlock3D]) -> Dict[str, Palace3D]:
        """构建完整三维九宫地盘"""
        # 初始化九宫
        palaces = {}
        for name, info in PALACE_BASIC.items():
            xy = PALACE_XY[name]
            palaces[name] = Palace3D(
                name=name,
                number=info["number"],
                x_center=xy[0],
                y_center=xy[1],
                tiangan=info["tiangan"],
                dizhi=info["dizhi"],
            )
        
        # 区块归宫
        for block in blocks:
            palace = block.palace
            if palace in palaces:
                palaces[palace].occupants.append(block)
                # 更新Z均值
                total_z = sum(o.z for o in palaces[palace].occupants) if palaces[palace].occupants else 0
                palaces[palace].z_avg = total_z / len(palaces[palace].occupants) if palaces[palace].occupants else 0
        
        # 计算各宫权重
        for name, p in palaces.items():
            occ_weights = [occ.weight for occ in p.occupants]
            if occ_weights:
                p.weight = round(sum(occ_weights) / len(occ_weights), 2)
            else:
                p.weight = 0.3  # 空宫基础权重
            
            # 阴阳判定
            if p.z_avg > 0.15:
                p.yin_yang = "阳"
            elif p.z_avg < -0.15:
                p.yin_yang = "阴"
            else:
                p.yin_yang = "平"
        
        return palaces
    
    @staticmethod
    def calc_cross_palace(palaces: Dict[str, Palace3D]) -> Dict[str, Palace3D]:
        """计算宫位互通关系"""
        palace_names = list(palaces.keys())
        for i, name_a in enumerate(palace_names):
            for name_b in palace_names[i+1:]:
                if name_a == name_b or name_a == "中" or name_b == "中":
                    continue
                
                # 判定是否相邻（XY坐标距离）
                x1, y1 = PALACE_XY.get(name_a, (0,0))
                x2, y2 = PALACE_XY.get(name_b, (0,0))
                dist = math.sqrt((x1-x2)**2 + (y1-y2)**2)
                
                if dist < 0.4:
                    # 直接相邻
                    palaces[name_a].cross_palaces.append(name_b)
                    palaces[name_b].cross_palaces.append(name_a)
        
        return palaces


# ═══════════════════════════════════════════════════════════════
# 四、九维推演引擎
# ═══════════════════════════════════════════════════════════════

class NineDimEngine:
    """九维立体动态推演引擎"""
    
    def __init__(self):
        self.palace_engine = Palace3DEngine()
    
    def deduce_3d(
        self,
        year: int = 0,
        month: int = 0,
        day: int = 0,
        hour: int = 0,
        minute: int = 0,
        multi_dim_bind: Optional[Dict[str, str]] = None,
        spatial_hints: Optional[Dict[str, str]] = None,
        mode: str = "static"
    ) -> NineDimResult:
        """
        九维立体推演主接口
        
        multi_dim_bind: {
            "person": "问事人",    # 人物维度
            "event": "求职面试",   # 事件维度
            "object": "目标公司",  # 物象维度
            "semantic": "积极期望" # 语义维度
        }
        
        spatial_hints: {
            "person_zone": "震宫",  # 人物所在区域
            "event_zone": "离宫",   # 事件所在区域
            "object_zone": "乾宫"   # 物象所在区域
        }
        """
        multi_dim_bind = multi_dim_bind or {}
        spatial_hints = spatial_hints or {}
        
        # 构建时空元数据
        timespace = self._build_timespace(year, month, day, hour, minute, mode)
        
        # 用维度绑定信息构建三维区块
        blocks = self._build_blocks_from_bindings(multi_dim_bind, spatial_hints)
        
        # 构建立体九宫
        palaces = self.palace_engine.build_3d_palaces(blocks)
        palaces = self.palace_engine.calc_cross_palace(palaces)
        
        # 九维分项推演
        nine_dim = self._nine_dim_analysis(palaces, multi_dim_bind, timespace)
        
        # 综合结论
        overall = self._synthesize(nine_dim, palaces)
        
        # 构建结果
        result = NineDimResult(
            timespace=timespace,
            palaces_3d=palaces,
            yongshen_bindings=self._build_yongshen_bindings(multi_dim_bind, palaces),
            nine_dim_analysis=nine_dim,
            overall_judgment=overall["judgment"],
            core_profit_loss=overall["profit_loss"],
            yongshen_status=overall["yongshen"],
            potential_variables=overall["variables"],
            confidence_score=overall["confidence"],
            # ── 格局 ──
            pattern_summary=timespace.patterns,
            # ── 旺衰 ──
            star_status_summary=", ".join([f"{k}:{v}" for k,v in timespace.star_wangshuai.items()]),
            gate_status_summary=", ".join([f"{k}:{v}" for k,v in timespace.gate_wangshuai.items()]),
            # ── 门迫 ──
            menpo_summary=timespace.menpo_list,
            fanyin_fuyin=[f"反吟:{p}" for p in timespace.fanyin_palaces] + [f"伏吟:{p}" for p in timespace.fuyin_palaces],
            # ── 应期 ──
            yingqi_summary=timespace.yingqi_result,
            yingqi_detail=f"远近:{timespace.yingqi_near_far} 快慢:{timespace.yingqi_fast_slow} 马星:{timespace.ma_xing_palace or '无'}",
        )
        
        return result
    
    def deduce_dynamic(self, frames: List[Dict]) -> NineDimResult:
        """
        多帧动态推演
        
        frames: [
            {"time": "2026-06-02 13:00", "data": {...}},
            {"time": "2026-06-03 09:00", "data": {...}},
        ]
        """
        if not frames:
            return NineDimResult()
        
        # 对每一帧进行九维推演
        frame_results = []
        for frame in frames:
            # 解析帧时间
            time_str = frame.get("time", "")
            data = frame.get("data", {})
            
            # 这里简化处理，实际需要解析时间字符串
            result = self.deduce_3d(
                multi_dim_bind=data.get("bindings"),
                spatial_hints=data.get("hints"),
                mode="multi_frame"
            )
            frame_results.append(result)
        
        # 构建动态飞宫轨迹
        flow = self._build_dynamic_flow(frame_results)
        
        # 趋势推演
        final = frame_results[-1] if frame_results else NineDimResult()
        final.dynamic_flow = flow
        
        # 基于多帧数据修正结论
        if len(frame_results) >= 2:
            first = frame_results[0]
            last = frame_results[-1]
            final.tendency_score = self._calc_tendency(first, last)
            # 标记趋势方向
            if final.tendency_score > 0.3:
                final.tendency = "上升"
            elif final.tendency_score < -0.3:
                final.tendency = "下降"
            else:
                final.tendency = "持平"
        
        return final
    
    # ═══════════════════════════════════════════════
    # 传统奇门 - 完整排盘（天盘干 + 八门 + 九星 + 八神）
    # ═══════════════════════════════════════════════

    def _calc_season(self, month: int, day: int) -> tuple:
        """根据月日计算季节和五行"""
        if month <= 2 or (month == 3 and day < 5):
            return "春", "木"
        elif (month == 3 and day >= 5) or month == 4 or (month == 5 and day < 5):
            return "春", "木"
        elif (month == 5 and day >= 5) or month == 6 or (month == 7 and day < 7):
            return "夏", "火"
        elif (month == 7 and day >= 7) or month == 8 or (month == 9 and day < 7):
            return "秋", "金"
        elif (month == 9 and day >= 7) or month == 10 or (month == 11 and day < 7):
            return "秋", "金"
        else:
            return "冬", "水"

    def _get_season(self, month: int) -> str:
        """按月返回季节（简化）"""
        if month in (3, 4, 5): return "春"
        if month in (6, 7, 8): return "夏"
        if month in (9, 10, 11): return "秋"
        return "冬"

    def _palace_wuxing(self, palace_name: str) -> str:
        """取宫位五行"""
        wuxing_map = {"坎": "水", "坤": "土", "震": "木", "巽": "木",
                      "中": "土", "乾": "金", "兑": "金", "艮": "土", "离": "火"}
        return wuxing_map.get(palace_name, "土")

    def _build_qimen_pan(self, meta: TimeSpaceMeta, hour: int) -> TimeSpaceMeta:
        """
        传统奇门排盘：填入天盘干、地盘干、八门、九星、八神。
        基于阳遁/阴遁局数，按时辰旬首+符头排盘。
        """
        # 地盘干：每宫固定
        dipan_fixed = {
            "坎": "戊", "坤": "己", "震": "庚", "巽": "辛",
            "中": "壬", "乾": "癸", "兑": "丁", "艮": "丙", "离": "乙"
        }
        # 阳遁顺排，阴遁逆排
        palace_order_yang = ["坎", "坤", "震", "巽", "中", "乾", "兑", "艮", "离"]
        palace_order_yin = ["离", "艮", "兑", "乾", "中", "巽", "震", "坤", "坎"]

        meta.dipan_gan = {k: v for k, v in dipan_fixed.items()}

        # 将时支换算为时辰地支索引
        di_zhi_map = {"子": 0, "丑": 1, "寅": 2, "卯": 3, "辰": 4, "巳": 5,
                      "午": 6, "未": 7, "申": 8, "酉": 9, "戌": 10, "亥": 11}
        shi_zhi = meta.shi_ganzhi[-1] if meta.shi_ganzhi else "子"
        zhi_idx = di_zhi_map.get(shi_zhi, 0)

        # 天盘干：值符（天芮星）所在宫的天干顺时针/逆时针排
        # 简化：从值符宫位开始，按顺序逐一放天干
        gan_list = ["戊", "己", "庚", "辛", "壬", "癸", "丁", "丙", "乙"]
        order = palace_order_yang if meta.dun_type == "阳遁" else palace_order_yin

        # 值符落宫（简化：辰戌丑未月天芮落中，寅申巳亥月天禽落中）
        fu_palace = "坤"  # 简化，实际需按旬首计算
        fu_idx = order.index(fu_palace)

        tianpan = {}
        for i, p in enumerate(order):
            if p == "中":
                continue
            gan_idx = (i - fu_idx) % len(gan_list)
            tianpan[p] = gan_list[gan_idx]
        meta.tianpan_gan = tianpan

        # 八门（值使门落时干所在宫）
        men_list = ["休", "生", "伤", "杜", "景", "死", "惊", "开"]
        men_yang_luo = ["坎", "艮", "震", "巽", "离", "坤", "兑", "乾"]

        # 值使门落宫（简化：以时支索引对应值使落宫偏移）
        start_men = men_yang_luo[zhi_idx % 8]
        start_idx = men_yang_luo.index(start_men)

        men_layout = {}
        if meta.dun_type == "阳遁":
            for i, p in enumerate(order):
                if p == "中":
                    continue
                men_layout[p] = men_list[(start_idx + i) % 8]
        else:
            for i, p in enumerate(order):
                if p == "中":
                    continue
                men_layout[p] = men_list[(start_idx - i) % 8]
        meta.men_layout = men_layout

        # 九星
        xing_list = ["天蓬", "天芮", "天冲", "天辅", "天禽",
                     "天心", "天柱", "天任", "天英"]
        xing_yang_luo = ["坎", "坤", "震", "巽", "中", "乾", "兑", "艮", "离"]

        xing_layout = {}
        if meta.dun_type == "阳遁":
            for i, p in enumerate(order):
                if p == "中":
                    continue
                xing_layout[p] = xing_list[(zhi_idx + i) % 9]
        else:
            for i, p in enumerate(order):
                if p == "中":
                    continue
                xing_layout[p] = xing_list[(zhi_idx - i) % 9]
        meta.xing_layout = xing_layout

        # 八神（值符→腾蛇→太阴→六合→白虎→玄武→九地→九天）
        shen_list = ["值符", "腾蛇", "太阴", "六合", "白虎", "玄武", "九地", "九天"]
        shen_layout = {}
        if meta.dun_type == "阳遁":
            for i, p in enumerate(order):
                if p == "中":
                    continue
                shen_layout[p] = shen_list[(zhi_idx + i) % 8]
        else:
            for i, p in enumerate(order):
                if p == "中":
                    continue
                shen_layout[p] = shen_list[(zhi_idx - i) % 8]
        meta.shen_layout = shen_layout

        # 同步到 Palace3D
        return meta

    def _calc_pattern(self, meta: TimeSpaceMeta) -> List[Dict]:
        """
        天盘干 vs 地盘干 → 格局判定
        返回 [{"palace": "坎", "tian": "戊", "di": "丙", "name": "龙回首", "nature": "大吉", ...}]
        """
        # 直接使用模块顶层常量
        import sys
        this_module = sys.modules[__name__]
        _patterns = this_module.TIAN_DI_PATTERNS

        results = []
        for palace, tian_gan in meta.tianpan_gan.items():
            di_gan = meta.dipan_gan.get(palace, "")
            if not tian_gan or not di_gan:
                continue
            key = (tian_gan, di_gan)
            pattern_info = TIAN_DI_PATTERNS.get(key)
            if pattern_info:
                results.append({
                    "palace": palace,
                    "tian_gan": tian_gan,
                    "di_gan": di_gan,
                    "name": pattern_info[0],
                    "nature": pattern_info[1],
                    "meaning": pattern_info[2],
                })
            # 伏吟检测：天盘干 == 地盘干
            if tian_gan == di_gan:
                results.append({
                    "palace": palace,
                    "tian_gan": tian_gan,
                    "di_gan": di_gan,
                    "name": "伏吟",
                    "nature": "平",
                    "meaning": "事缓难行，进退两难，宜守不宜攻",
                })
        # 按吉凶排序（凶在前，吉在后）
        nature_order = {"大凶": 0, "凶": 1, "平": 2, "小吉": 3, "吉": 4, "大吉": 5}
        results.sort(key=lambda x: nature_order.get(x["nature"], 99))
        meta.patterns = results
        return results

    def _calc_wangshuai(self, meta: TimeSpaceMeta) -> tuple:
        """
        九星八门四季旺衰判定
        返回 (star_status, gate_status)
        """
        _star_w = {"天蓬": {"旺":"冬","相":"春","休":"秋","囚":"夏","死":"四季"},"天芮": {"旺":"四季","相":"秋","休":"夏","囚":"冬","死":"春"},"天冲": {"旺":"春","相":"夏","休":"冬","囚":"四季","死":"秋"},"天辅": {"旺":"春","相":"夏","休":"冬","囚":"四季","死":"秋"},"天禽": {"旺":"四季","相":"秋","休":"夏","囚":"冬","死":"春"},"天心": {"旺":"秋","相":"冬","休":"四季","囚":"春","死":"夏"},"天柱": {"旺":"秋","相":"冬","休":"四季","囚":"春","死":"夏"},"天任": {"旺":"四季","相":"秋","休":"夏","囚":"冬","死":"春"},"天英": {"旺":"夏","相":"四季","休":"春","囚":"冬","死":"秋"}};_gate_w = {"休": {"旺":"冬","相":"春","休":"秋","囚":"夏","死":"四季"},"生": {"旺":"四季","相":"秋","休":"夏","囚":"冬","死":"春"},"伤": {"旺":"春","相":"夏","休":"冬","囚":"四季","死":"秋"},"杜": {"旺":"春","相":"夏","休":"冬","囚":"四季","死":"秋"},"景": {"旺":"夏","相":"四季","休":"春","囚":"冬","死":"秋"},"死": {"旺":"四季","相":"秋","休":"夏","囚":"冬","死":"春"},"惊": {"旺":"秋","相":"冬","休":"四季","囚":"春","死":"夏"},"开": {"旺":"秋","相":"冬","休":"四季","囚":"春","死":"夏"}}

        season = self._get_season(int(meta.gregorian[5:7])) if len(meta.gregorian) >= 7 else "春"
        meta.season = season

        star_status = {}
        for palace, star in meta.xing_layout.items():
            info = STAR_WANGSHUAI.get(star, {})
            status = info.get(season, "平")
            star_status[star] = status
        meta.star_wangshuai = star_status

        gate_status = {}
        for palace, gate in meta.men_layout.items():
            info = GATE_WANGSHUAI.get(gate, {})
            status = info.get(season, "平")
            gate_status[gate] = status
        meta.gate_wangshuai = gate_status

        return star_status, gate_status

    def _calc_menpo(self, meta: TimeSpaceMeta) -> tuple:
        """
        门迫检测 + 反吟/伏吟检测
        门克宫=门迫(凶)，宫克门=宫迫(次凶)
        反吟=星+门落到与地盘对冲宫位
        伏吟=星+门落到同一宫位（与天盘相同）
        """
        

        palace_wux_map = {"坎": "水", "坤": "土", "震": "木", "巽": "木",
                          "中": "土", "乾": "金", "兑": "金", "艮": "土", "离": "火"}

        # 门五行
        men_wux_map = {"休": "水", "生": "土", "伤": "木", "杜": "木",
                       "景": "火", "死": "土", "惊": "金", "开": "金"}

        menpo_list = []
        for palace, gate in meta.men_layout.items():
            g_wux = men_wux_map.get(gate, "")
            p_wux = palace_wux_map.get(palace, "")
            if not g_wux or not p_wux:
                continue
            # 门克宫 = 门迫
            if (g_wux == "木" and p_wux == "土") or                (g_wux == "土" and p_wux == "水") or                (g_wux == "水" and p_wux == "火") or                (g_wux == "火" and p_wux == "金") or                (g_wux == "金" and p_wux == "木"):
                menpo_list.append({
                    "gate": gate, "palace": palace,
                    "type": "门迫", "impact": "🔴 凶",
                    "meaning": f"{gate}门（{g_wux}）克{palace}宫（{p_wux}），事倍功半"
                })
            # 宫克门 = 宫迫
            elif (p_wux == "木" and g_wux == "土") or                  (p_wux == "土" and g_wux == "水") or                  (p_wux == "水" and g_wux == "火") or                  (p_wux == "火" and g_wux == "金") or                  (p_wux == "金" and g_wux == "木"):
                menpo_list.append({
                    "gate": gate, "palace": palace,
                    "type": "宫迫", "impact": "🟡 次凶",
                    "meaning": f"{palace}宫（{p_wux}）克{gate}门（{g_wux}），阻力大"
                })

        meta.menpo_list = menpo_list

        # 伏吟/反吟检测
        fuyin = []
        fanyin = []
        duichong_map = {"坎": "离", "坤": "艮", "震": "兑", "巽": "乾",
                        "乾": "巽", "兑": "震", "艮": "坤", "离": "坎"}
        for palace, star in meta.xing_layout.items():
            if palace in duichong_map:
                opp = duichong_map[palace]
                opp_star = meta.xing_layout.get(opp, "")
                if star == opp_star:
                    fanyin.append(f"{palace}({star})")
        meta.fanyin_palaces = fanyin
        meta.fuyin_palaces = fuyin

        return menpo_list, fanyin, fuyin

    def _calc_yingqi(self, meta: TimeSpaceMeta) -> tuple:
        """
        应期判定：近/远 + 快/慢
        规则：
        - 用神在内盘（坎坤震巽中）→ 应期近（日/时），外盘（乾坤兑艮离）→ 应期远（月/年）
        - 阳遁主快、阴遁主慢
        - 反吟主快、伏吟主慢
        - 马星所在宫位加速
        """
        INNER_PALACES = {"坎", "坤", "震", "巽", "中"}
        MA_XING = {("申", "子", "辰"): "寅", ("寅", "午", "戌"): "申",
                   ("巳", "酉", "丑"): "亥", ("亥", "卯", "未"): "巳"}

        di_zhi_map = {"子": 0, "丑": 1, "寅": 2, "卯": 3, "辰": 4, "巳": 5,
                      "午": 6, "未": 7, "申": 8, "酉": 9, "戌": 10, "亥": 11}
        zhi_name = meta.shi_ganzhi[-1] if meta.shi_ganzhi else "子"

        # 马星判定
        ma_result = ""
        for key_zhi, ma_palace in MA_XING.items():
            if zhi_name in key_zhi:
                ma_result = ma_palace
                break
        meta.ma_xing_palace = ma_result or ""

        # 内盘外盘（以用神所在宫判断，默认用日干戊所在宫=坎宫）
        yongshen_palace = "坎"
        if yongshen_palace in INNER_PALACES:
            near_far = "近"
            near_far_detail = "日/时内可见分晓"
        else:
            near_far = "远"
            near_far_detail = "月/年后方见结果"
        meta.yingqi_near_far = near_far

        # 快慢
        fast_slow = "快" if meta.dun_type == "阳遁" else "慢"
        if meta.fanyin_palaces:
            fast_slow = "极快（反吟变动）"
        if meta.fuyin_palaces:
            fast_slow = "极慢（伏吟阻滞）"
        if meta.ma_xing_palace:
            fast_slow += "（马星加速）"
        meta.yingqi_fast_slow = fast_slow

        # 综合应期
        if near_far == "近" and "快" in fast_slow:
            yingqi = f"近且快：3日内见分晓"
        elif near_far == "近" and "慢" in fast_slow:
            yingqi = f"近但慢：7-15日"
        elif near_far == "远" and "快" in fast_slow:
            yingqi = f"虽远但快：1-3月"
        else:
            yingqi = f"遥远：半年以上"

        if meta.ma_xing_palace:
            yingqi += f"，马星在{meta.ma_xing_palace}宫加速推进"

        meta.yingqi_result = yingqi
        return yingqi, near_far, fast_slow


    def _build_timespace(self, year, month, day, hour, minute, mode) -> TimeSpaceMeta:
        """构建时空元数据 — 接入 time_awareness 获取真实时间"""
        # ── 自动获取实时时间 ──
        if year == 0 and _HAVE_TIME_AWARENESS:
            try:
                report = get_time_awareness()
                meta = TimeSpaceMeta(
                    gregorian=report.datetime_str,
                    scene_type=mode,
                )
                meta.jieqi = report.current_jieqi
                meta.ri_ganzhi = report.day_ganzhi
                meta.shi_ganzhi = report.time_ganzhi
                meta.yuejian = report.four_pillars.split(" ")[1] if " " in report.four_pillars else ""
                meta.dun_type, meta.ju_number = self._jieqi_to_dun(
                    report.current_jieqi, report.next_jieqi, report.jieqi_days_passed
                )
                # 用真实时间更新year便于后续计算
                if report.datetime_str and len(report.datetime_str) >= 16:
                    y = int(report.datetime_str[:4])
                    m = int(report.datetime_str[5:7])
                    d = int(report.datetime_str[8:10])
                    hh = int(report.datetime_str[11:13])
                    mm = int(report.datetime_str[14:16])
                    # 用于后续马星等计算但不用推干支
                    meta.yingqi, meta.near_far, meta.fast_slow = self._calc_yingqi(meta)
                    return meta
            except Exception:
                pass  # 回退到简化推算
        
        # ── 简化推算（兜底）──
        meta = TimeSpaceMeta(
            gregorian=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            scene_type=mode,
        )
        if (month < 6) or (month == 6 and day < 5):
            meta.dun_type, meta.ju_number, meta.jieqi = "阳遁", 4, "小满-芒种间"
        else:
            meta.dun_type, meta.ju_number, meta.jieqi = "阴遁", 6, "芒种后"
        meta.yuejian = "午" if month >= 5 else "巳"
        day_offset = (year * 365 + month * 30 + day) % 60
        tian_list = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
        di_list = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
        meta.ri_ganzhi = tian_list[(day_offset * 2 + 6) % 10] + di_list[(day_offset + 12) % 12]
        meta.shi_ganzhi = self._calc_shi_ganzhi(hour)
        
        # ── 完整排盘 ──
        meta = self._build_qimen_pan(meta, hour)
        # ── 格局判定 ──
        patterns = self._calc_pattern(meta)
        # ── 星门旺衰 ──
        self._calc_wangshuai(meta)
        # ── 门迫/伏吟反吟 ──
        self._calc_menpo(meta)
        # ── 应期判定 ──
        self._calc_yingqi(meta)
        
        return meta
    
    def _calc_shi_ganzhi(self, hour: int) -> str:
        """计算时辰干支（简化），当 _HAVE_TIME_AWARENESS 时从 report 获取"""
        # 五鼠遁简化版
        shi_chen_map = {23: "子", 0: "子", 1: "丑", 2: "丑", 3: "寅", 4: "寅",
                        5: "卯", 6: "卯", 7: "辰", 8: "辰", 9: "巳", 10: "巳",
                        11: "午", 12: "午", 13: "未", 14: "未", 15: "申", 16: "申",
                        17: "酉", 18: "酉", 19: "戌", 20: "戌", 21: "亥", 22: "亥"}
        
        # 时辰天干基于五鼠遁（简化，假定日干为甲）
        gan_map = {0: "甲", 1: "乙", 2: "丙", 3: "丁", 4: "戊",
                   5: "己", 6: "庚", 7: "辛", 8: "壬", 9: "癸"}
        hour_to_gan_idx = {23: 0, 0: 0, 1: 2, 2: 2, 3: 4, 4: 4,
                          5: 6, 6: 6, 7: 8, 8: 8, 9: 0, 10: 0,
                          11: 2, 12: 2, 13: 4, 14: 4, 15: 6, 16: 6,
                          17: 8, 18: 8, 19: 0, 20: 0, 21: 2, 22: 2}
        
        gan = gan_map.get(hour_to_gan_idx.get(hour, 0), "甲")
        zhi = shi_chen_map.get(hour, "子")
        return gan + zhi
    
    # ── 节气→奇门局式转换（24节气全覆盖）──
    _JIEQI_TO_DUN = {
        "冬至": ("阳遁", 1), "小寒": ("阳遁", 2), "大寒": ("阳遁", 3),
        "立春": ("阳遁", 4), "雨水": ("阳遁", 5), "惊蛰": ("阳遁", 6),
        "春分": ("阳遁", 7), "清明": ("阳遁", 8), "谷雨": ("阳遁", 9),
        "立夏": ("阳遁", 4), "小满": ("阳遁", 4), "芒种": ("阳遁", 6),
        "夏至": ("阴遁", 9), "小暑": ("阴遁", 8), "大暑": ("阴遁", 7),
        "立秋": ("阴遁", 2), "处暑": ("阴遁", 1), "白露": ("阴遁", 9),
        "秋分": ("阴遁", 7), "寒露": ("阴遁", 6), "霜降": ("阴遁", 5),
        "立冬": ("阴遁", 6), "小雪": ("阴遁", 5), "大雪": ("阴遁", 4),
    }
    
    def _jieqi_to_dun(self, current_jieqi: str, next_jieqi: str = "",
                      days_passed: int = 0) -> tuple:
        """节气名→奇门局式，默认取上元局数"""
        if current_jieqi in self._JIEQI_TO_DUN:
            return self._JIEQI_TO_DUN[current_jieqi]
        if next_jieqi:
            dun_info = self._JIEQI_TO_DUN.get(next_jieqi)
            if dun_info:
                dt, ju = dun_info
                ju = ju - 1 if dt == "阳遁" else ju + 1
                return (dt, max(1, min(9, ju)))
        return ("阳遁", 4)
    
    def _build_blocks_from_bindings(
        self, bindings: Dict[str, str], hints: Dict[str, str]
    ) -> List[SpatialBlock3D]:
        """从维度绑定信息构建三维区块"""
        blocks = []
        
        # 维度到绑定的映射
        dim_to_bind = {
            "person": ("person", "人物"),
            "event": ("event", "事件"),
            "object": ("object", "物象"),
            "semantic": ("semantic", "语义"),
        }
        
        for dim_key, dim_info in dim_to_bind.items():
            bind_type, label = dim_info
            value = bindings.get(dim_key, "")
            if not value:
                continue
            
            # 从hints获取空间位置
            zone_key = f"{dim_key}_zone"
            zone_raw = hints.get(zone_key, "中宫")
            # 去除"宫"后缀，匹配PALACE_XY
            zone = zone_raw.replace("宫", "")
            if zone not in PALACE_XY:
                zone = "中"
            
            # 获取宫位坐标
            xy = PALACE_XY.get(zone, (0.5, 0.5))
            
            # 不同维度赋予不同Z值
            z_map = {"person": 0.3, "event": 0.0, "object": -0.2, "semantic": 0.1}
            z = z_map.get(dim_key, 0.0)
            
            block = SpatialBlock3D(
                x=xy[0], y=xy[1], z=z,
                palace=zone.replace("宫", ""),
                binding_type=bind_type,
                label=f"{label}:{value}",
                weight=0.6,
            )
            blocks.append(block)
        
        return blocks
    
    def _nine_dim_analysis(
        self, palaces: Dict[str, Palace3D],
        bindings: Dict[str, str],
        timespace: TimeSpaceMeta
    ) -> Dict[str, Any]:
        """九维分项推演"""
        analysis = {}
        
        # X横向气场
        x_left = sum(p.weight for n, p in palaces.items() if PALACE_XY.get(n, (0.5, 0.5))[0] < 0.4)
        x_right = sum(p.weight for n, p in palaces.items() if PALACE_XY.get(n, (0.5, 0.5))[0] > 0.6)
        analysis["X"] = {
            "score": round(x_right - x_left, 2),
            "left_weight": round(x_left, 2),
            "right_weight": round(x_right, 2),
            "meaning": "左虚右实" if x_right > x_left else "左实右虚" if x_left > x_right else "左右均衡"
        }
        
        # Y纵向格局
        y_top = sum(p.weight for n, p in palaces.items() if PALACE_XY.get(n, (0.5, 0.5))[1] < 0.4)
        y_bottom = sum(p.weight for n, p in palaces.items() if PALACE_XY.get(n, (0.5, 0.5))[1] > 0.6)
        analysis["Y"] = {
            "score": round(y_top - y_bottom, 2),
            "top_weight": round(y_top, 2),
            "bottom_weight": round(y_bottom, 2),
            "meaning": "上强下弱" if y_top > y_bottom else "下强上弱" if y_bottom > y_top else "上下均衡"
        }
        
        # Z深度阴阳
        yang_palaces = [n for n, p in palaces.items() if p.yin_yang == "阳"]
        yin_palaces = [n for n, p in palaces.items() if p.yin_yang == "阴"]
        analysis["Z"] = {
            "yang_count": len(yang_palaces),
            "yin_count": len(yin_palaces),
            "yang_palaces": yang_palaces,
            "yin_palaces": yin_palaces,
            "meaning": "阳宫主导" if len(yang_palaces) > len(yin_palaces) else "阴宫主导" if len(yin_palaces) > len(yang_palaces) else "阴阳平衡"
        }
        
        # T时序
        analysis["T"] = {
            "dun_type": timespace.dun_type,
            "ju_number": timespace.ju_number,
            "jieqi": timespace.jieqi,
            "shichen": timespace.shi_ganzhi,
            "meaning": f"{timespace.dun_type}{timespace.ju_number}局，{timespace.jieqi}，{timespace.shi_ganzhi}时"
        }
        
        # P人物
        person = bindings.get("person", "未指定")
        person_palace = None
        for n, p in palaces.items():
            for occ in p.occupants:
                if occ.binding_type == "person":
                    person_palace = n
                    break
        
        if person_palace:
            pp = palaces[person_palace]
            analysis["P"] = {
                "person": person,
                "palace": person_palace,
                "weight": pp.weight,
                "yin_yang": pp.yin_yang,
                "meaning": f"{person}落{person_palace}宫，宫气{'旺盛' if pp.weight > 0.6 else '平和' if pp.weight > 0.4 else '偏弱'}"
            }
        else:
            analysis["P"] = {"person": person, "palace": "未定", "meaning": f"{person}方位未定"}
        
        # E事件
        event = bindings.get("event", "未指定")
        event_palace = None
        for n, p in palaces.items():
            for occ in p.occupants:
                if occ.binding_type == "event":
                    event_palace = n
                    break
        
        if event_palace:
            ep = palaces[event_palace]
            analysis["E"] = {
                "event": event,
                "palace": event_palace,
                "weight": ep.weight,
                "meaning": f"{event}落{event_palace}宫，{PALACE_BASIC.get(event_palace, {}).get('wuxing', '')}宫"
            }
        else:
            analysis["E"] = {"event": event, "palace": "未定", "meaning": f"{event}方位未定"}
        
        # O物象
        obj = bindings.get("object", "未指定")
        obj_palace = None
        for n, p in palaces.items():
            for occ in p.occupants:
                if occ.binding_type == "object":
                    obj_palace = n
                    break
        
        if obj_palace:
            analysis["O"] = {
                "object": obj,
                "palace": obj_palace,
                "meaning": f"{obj}落{obj_palace}宫，根基{'稳固' if palaces[obj_palace].weight > 0.5 else '不稳'}"
            }
        else:
            analysis["O"] = {"object": obj, "palace": "未定", "meaning": f"{obj}方位未定"}
        
        # S语义
        semantic = bindings.get("semantic", "中性")
        semantic_polarity = 0.0  # -1 ~ 1
        positive_words = ["积极", "喜", "好", "吉", "顺", "旺"]
        negative_words = ["消极", "悲", "忧", "愁", "苦", "难"]
        
        for w in positive_words:
            if w in semantic:
                semantic_polarity += 0.3
        for w in negative_words:
            if w in semantic:
                semantic_polarity -= 0.3
        
        analysis["S"] = {
            "semantic": semantic,
            "polarity": round(semantic_polarity, 2),
            "meaning": "正向" if semantic_polarity > 0 else "负向" if semantic_polarity < 0 else "中性"
        }
        
        # L逻辑生克
        logic = self._calc_logic_shengke(palaces, bindings)
        analysis["L"] = logic

        # ═══ 九维交叉校验（新增） ═══
        analysis["CV"] = self._cross_validate(analysis, palaces)
        # ════════════════════════════
        return analysis
    
    def _calc_logic_shengke(
        self, palaces: Dict[str, Palace3D], bindings: Dict[str, str]
    ) -> Dict[str, Any]:
        """计算九维逻辑生克"""
        # 找到各维度落宫
        dim_palaces = {}
        for n, p in palaces.items():
            for occ in p.occupants:
                if occ.binding_type:
                    dim_palaces[occ.binding_type] = n
        
        person_p = dim_palaces.get("person", "")
        event_p = dim_palaces.get("event", "")
        obj_p = dim_palaces.get("object", "")
        
        # 获取宫位五行
        def get_wuxing(palace_name):
            return PALACE_BASIC.get(palace_name, {}).get("wuxing", "")
        
        # 生克判定
        relations = []
        impact_score = 0.0
        
        # 人物→事件
        if person_p and event_p:
            pw = get_wuxing(person_p)
            ew = get_wuxing(event_p)
            if pw and ew:
                if WUXING_SHENG.get(pw) == ew:
                    relations.append(f"{person_p}({pw})生{event_p}({ew})→助力+")
                    impact_score += 0.4
                elif WUXING_KE.get(pw) == ew:
                    relations.append(f"{person_p}({pw})克{event_p}({ew})→阻碍-")
                    impact_score -= 0.4
                else:
                    relations.append(f"{person_p}({pw})/{event_p}({ew})无生克→中和")
        
        # 事件→物象
        if event_p and obj_p:
            ew = get_wuxing(event_p)
            ow = get_wuxing(obj_p)
            if ew and ow:
                if WUXING_SHENG.get(ew) == ow:
                    relations.append(f"{event_p}({ew})生物象({ow})→事态推动+")
                    impact_score += 0.3
                elif WUXING_KE.get(ew) == ow:
                    relations.append(f"{event_p}({ew})克物象({ow})→事态受阻-")
                    impact_score -= 0.3
                else:
                    relations.append(f"{event_p}({ew})/{obj_p}({ow})平")
        
        # 人物→物象
        if person_p and obj_p:
            pw = get_wuxing(person_p)
            ow = get_wuxing(obj_p)
            if pw and ow:
                if WUXING_SHENG.get(pw) == ow:
                    relations.append(f"人({pw})生物({ow})→人和利+")
                    impact_score += 0.2
                elif WUXING_KE.get(pw) == ow:
                    relations.append(f"人({pw})克物({ow})→人挫物-")
                    impact_score -= 0.2
        
        # 语义修正
        semantic = bindings.get("semantic", "中性")
        if "积极" in semantic or "喜" in semantic or "吉" in semantic:
            impact_score += 0.15
            relations.append("语义正向修正+")
        elif "消极" in semantic or "悲" in semantic or "凶" in semantic:
            impact_score -= 0.15
            relations.append("语义负向修正-")
        
        impact_score = max(-1.0, min(1.0, impact_score))
        
        return {
            "relations": relations,
            "impact_score": round(impact_score, 2),
            "overall": "吉" if impact_score > 0.2 else "凶" if impact_score < -0.2 else "平",
            "meaning": f"综合生克得分{impact_score:.2f}，{'各方助力' if impact_score > 0.2 else '相互阻碍' if impact_score < -0.2 else '势均力敌'}"
        }
    
    def _synthesize(
        self, nine_dim: Dict[str, Any], palaces: Dict[str, Palace3D]
    ) -> Dict[str, Any]:
        """综合推演结论"""
        # 收集所有维度信息
        l_logic = nine_dim.get("L", {})
        l_x = nine_dim.get("X", {})
        l_z = nine_dim.get("Z", {})
        
        # 总得分
        total_score = 0.0
        total_score += l_logic.get("impact_score", 0.0) * 0.4
        total_score += (l_x.get("score", 0) * 0.1)
        
        # 语义修正
        s_semantic = nine_dim.get("S", {})
        total_score += s_semantic.get("polarity", 0) * 0.2
        
        total_score = max(-1.0, min(1.0, total_score))
        
        # 吉凶判定
        if total_score > 0.3:
            judgment = "吉，事态顺势，大局利好"
        elif total_score > 0:
            judgment = "小吉，略有助力，注意细节"
        elif total_score > -0.3:
            judgment = "平，中和之象，需审时度势"
        else:
            judgment = "凶，事态受阻，宜守不宜攻"
        
        # 核心利弊
        profit_loss = []
        if total_score > 0:
            profit_loss.append("生克关系有利，各方助力明显")
        else:
            profit_loss.append("生克关系不利，阻力显现")
        
        if nine_dim.get("Z", {}).get("yang_count", 0) > nine_dim.get("Z", {}).get("yin_count", 0):
            profit_loss.append("阳宫主导，气场外放，适合主动行动")
        else:
            profit_loss.append("阴宫主导，气场内收，适合守成观察")
        
        # 用神旺衰
        yongshen = "平稳"
        person_analysis = nine_dim.get("P", {})
        person_weight = person_analysis.get("weight", 0.5)
        if isinstance(person_weight, (int, float)):
            if person_weight > 0.6:
                yongshen = "旺盛"
            elif person_weight < 0.4:
                yongshen = "偏弱"
        
        # 潜在变数
        variables = []
        # 查看是否有冲突宫位
        for name, p in palaces.items():
            if p.yin_yang == "阴" and p.weight > 0.5:
                variables.append(f"{name}宫阴气重而权重高，需注意暗藏阻碍")
        
        # 可信度
        confidence = 0.5 + abs(total_score) * 0.3
        
        return {
            "judgment": judgment,
            "profit_loss": profit_loss,
            "yongshen": yongshen,
            "variables": variables,
            "confidence": round(confidence, 2),
        }
    
    def _build_yongshen_bindings(
        self, bindings: Dict[str, str], palaces: Dict[str, Palace3D]
    ) -> Dict[str, Dict]:
        """构建用神绑定信息"""
        yongshen = {}
        for n, p in palaces.items():
            for occ in p.occupants:
                if occ.binding_type:
                    key = f"{occ.binding_type}_{occ.label}"
                    yongshen[key] = {
                        "palace": n,
                        "x": round(occ.x, 2),
                        "y": round(occ.y, 2),
                        "z": round(occ.z, 2),
                        "weight": occ.weight,
                        "yin_yang": occ.yin_yang,
                        "binding_type": occ.binding_type,
                    }
        return yongshen
    
    def _build_dynamic_flow(self, frame_results: List[NineDimResult]) -> QimenDynamicFlow:
        """从多帧结果构建动态飞宫轨迹"""
        flow = QimenDynamicFlow()
        
        for i, result in enumerate(frame_results):
            # 用神轨迹
            for key, binding in result.yongshen_bindings.items():
                flow.yongshen_trace.append({
                    "frame": i,
                    "yongshen": key,
                    "palace": binding["palace"],
                    "weight": binding["weight"],
                    "time": result.timespace.gregorian,
                })
            
            # 宫位变化
            for name, palace in result.palaces_3d.items():
                flow.palace_changes.append({
                    "frame": i,
                    "palace": name,
                    "weight": palace.weight,
                    "yin_yang": palace.yin_yang,
                    "occupant_count": len(palace.occupants),
                })
        
        # 计算趋势得分
        if len(frame_results) >= 2:
            first_score = frame_results[0].confidence_score
            last_score = frame_results[-1].confidence_score
            flow.tendency_score = round(last_score - first_score, 2)
        
        return flow
    

    def _cross_validate(self, analysis: Dict, palaces: Dict[str, Palace3D]) -> Dict:
        """
        九维交叉校验 — 五重校验体系
        ① 相邻宫一致性   ② 对宫互补性   ③ 中宫统摄
        ④ 维度同向性     ⑤ 五行生克链
        返回: {"pass": bool, "checks": [...], "summary": str, "scores": dict}
        """
        checks = []
        
        # ── ① 相邻宫一致性校验 ──
        adjacent_pairs = [
            ("坎", "坤"), ("坤", "震"), ("震", "巽"), ("巽", "中"),
            ("中", "乾"), ("乾", "兑"), ("兑", "艮"), ("艮", "离"), ("离", "坎")
        ]
        for a, b in adjacent_pairs:
            pa = palaces.get(a)
            pb = palaces.get(b)
            if pa and pb:
                weight_diff = abs(pa.weight - pb.weight)
                shengke_diff = (pa.shengke_strength or 0) - (pb.shengke_strength or 0)
                if weight_diff > 0.5:
                    checks.append({
                        "type": "相邻宫权重悬殊",
                        "palaces": f"{a}-{b}",
                        "detail": f"{a}={pa.weight:.2f}, {b}={pb.weight:.2f}，气机流转受阻",
                        "severity": "warning"
                    })
                elif weight_diff > 0.3:
                    checks.append({
                        "type": "相邻宫权重差",
                        "palaces": f"{a}-{b}",
                        "detail": f"{a}={pa.weight:.2f}, {b}={pb.weight:.2f}，略有不均",
                        "severity": "note"
                    })
                if abs(shengke_diff) > 0.8:
                    checks.append({
                        "type": "相邻宫生克剧变",
                        "palaces": f"{a}-{b}",
                        "detail": f"{a}生克={pa.shengke_strength or 0:.2f}, {b}={pb.shengke_strength or 0:.2f}，气机急转",
                        "severity": "warning"
                    })
        
        # ── ② 对宫互补性校验 ──
        opposite_pairs = [
            ("坎", "离"), ("震", "兑"), ("坤", "艮"), ("巽", "乾")
        ]
        palace_xy = {
            "坎": (0.5, 0.0), "坤": (0.0, 0.0), "震": (0.0, 0.5),
            "巽": (0.0, 1.0), "中": (0.5, 0.5), "乾": (1.0, 1.0),
            "兑": (1.0, 0.5), "艮": (1.0, 0.0), "离": (0.5, 1.0)
        }
        # 对冲五行：坎水⇌离火、震木⇌兑金、坤艮土⇌坤艮土(同类)、巽木⇌乾金
        opposite_wuxing_check = {
            ("坎", "离"): ("水", "火"),
            ("震", "兑"): ("木", "金"),
            ("巽", "乾"): ("木", "金"),
            ("坤", "艮"): ("土", "土"),
        }
        for a, b in opposite_pairs:
            pa = palaces.get(a)
            pb = palaces.get(b)
            if pa and pb:
                weight_sum = pa.weight + pb.weight
                if weight_sum < 0.3:
                    checks.append({
                        "type": "对宫皆弱",
                        "palaces": f"{a}-{b}",
                        "detail": f"对宫{a}({pa.weight:.2f})+{b}({pb.weight:.2f})={weight_sum:.2f}，对冲无力",
                        "severity": "warning"
                    })
                elif weight_sum > 1.8:
                    checks.append({
                        "type": "对宫皆亢",
                        "palaces": f"{a}-{b}",
                        "detail": f"对宫{a}({pa.weight:.2f})+{b}({pb.weight:.2f})={weight_sum:.2f}，对冲过烈",
                        "severity": "note"
                    })
                # 检查五行是否相克（对的宫应该逆向平衡）
                wx_pair = opposite_wuxing_check.get((a, b)) or opposite_wuxing_check.get((b, a))
                if wx_pair:
                    checks.append({
                        "type": "对宫五行校验",
                        "palaces": f"{a}-{b}",
                        "detail": f"{a}={wx_pair[0]}({pa.weight:.2f}) ⇌ {b}={wx_pair[1]}({pb.weight:.2f})，{'平衡' if abs(pa.weight-pb.weight)<0.3 else '略偏'}",
                        "severity": "note" if abs(pa.weight-pb.weight)<0.5 else "warning"
                    })
        
        # ── ③ 中宫统摄校验 — 增强版 ──
        center = palaces.get("中")
        if center:
            all_weights = [p.weight for p in palaces.values() if p.name != "中"]
            avg_weight = sum(all_weights) / len(all_weights) if all_weights else 0
            all_shengke = [p.shengke_strength or 0 for p in palaces.values() if p.name != "中" and p.shengke_strength is not None]
            avg_shengke = sum(all_shengke) / len(all_shengke) if all_shengke else 0
            
            # 中宫权重
            if center.weight < avg_weight * 0.5:
                checks.append({
                    "type": "中宫气弱",
                    "detail": f"中宫权重={center.weight:.2f}，八宫均值={avg_weight:.2f}，中宫不足以统摄全局，各行其是",
                    "severity": "warning"
                })
            elif center.weight > avg_weight * 1.5:
                checks.append({
                    "type": "中宫气盛",
                    "detail": f"中宫权重={center.weight:.2f}，八宫均值={avg_weight:.2f}，中宫过于强势，压抑八宫活力",
                    "severity": "note"
                })
            else:
                checks.append({
                    "type": "中宫得位",
                    "detail": f"中宫权重={center.weight:.2f}，八宫均值={avg_weight:.2f}，统摄有度",
                    "severity": "note"
                })
            
            # 中宫生克
            c_sk = center.shengke_strength or 0
            if abs(c_sk - avg_shengke) > 0.5:
                checks.append({
                    "type": "中宫生克偏离",
                    "detail": f"中宫生克={c_sk:.2f}，八宫均值={avg_shengke:.2f}，中宫与全局不协调",
                    "severity": "warning" if abs(c_sk - avg_shengke) > 0.8 else "note"
                })
        
        # ── ④ 多维度同向性校验 — 增强版 ──
        x_score = analysis.get("X", {}).get("score", 0)
        y_score = analysis.get("Y", {}).get("score", 0)
        z_yang = analysis.get("Z", {}).get("yang_count", 0)
        z_yin = analysis.get("Z", {}).get("yin_count", 0)
        t_score = analysis.get("T", {}).get("score", 0)
        
        if x_score > 0.3 and y_score > 0.3 and z_yang > z_yin:
            severity = "warning" if (x_score > 0.5 and y_score > 0.5) else "note"
            checks.append({
                "type": "多维同向偏阳亢",
                "detail": f"X偏右({x_score:.2f})+Y偏上({y_score:.2f})+阳宫{z_yang}>{z_yin}阴，全局偏亢进",
                "severity": severity
            })
        elif x_score < -0.3 and y_score < -0.3 and z_yin > z_yang:
            severity = "warning" if (x_score < -0.5 and y_score < -0.5) else "note"
            checks.append({
                "type": "多维同向偏阴弱",
                "detail": f"X偏左({x_score:.2f})+Y偏下({y_score:.2f})+阴宫{z_yin}>{z_yang}阳，全局偏沉滞",
                "severity": severity
            })
        
        # 时间趋势校验
        if t_score != 0:
            if (t_score > 0 and x_score > 0 and y_score > 0) or (t_score < 0 and x_score < 0 and y_score < 0):
                checks.append({
                    "type": "时空趋势一致",
                    "detail": f"时序({t_score:+.2f})与空间(X={x_score:+.2f},Y={y_score:+.2f})同向，趋势强化",
                    "severity": "note"
                })
        
        # ── ⑤ 五行生克链校验 — 新增 ──
        wuxing_palace = {
            "坎": "水", "离": "火", "震": "木", "巽": "木",
            "乾": "金", "兑": "金", "坤": "土", "艮": "土"
        }
        # 相生链：木→火→土→金→水→木
        sheng_chain = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
        # 相克链：木→土→水→火→金→木
        ke_chain = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
        
        for palace_name, p in palaces.items():
            if palace_name == "中" or p.name == "中":
                continue
            wx = wuxing_palace.get(palace_name)
            if not wx:
                continue
            
            # 生我者（母宫）—— 查看母宫权重
            mother_wx = {v: k for k, v in sheng_chain.items()}.get(wx)
            mother_palaces = [n for n, w in wuxing_palace.items() if w == mother_wx]
            mother_weight = sum(palaces.get(m, type('',(),{'weight':0})()).weight for m in mother_palaces)
            
            # 我生者（子宫）
            child_wx = sheng_chain.get(wx)
            child_palaces = [n for n, w in wuxing_palace.items() if w == child_wx]
            child_weight = sum(palaces.get(c, type('',(),{'weight':0})()).weight for c in child_palaces)
            
            # 克我者（官宫）
            ke_me_wx = {v: k for k, v in ke_chain.items()}.get(wx)
            ke_me_palaces = [n for n, w in wuxing_palace.items() if w == ke_me_wx]
            ke_me_weight = sum(palaces.get(k, type('',(),{'weight':0})()).weight for k in ke_me_palaces)
            
            # 我克者（财宫）
            i_ke_wx = ke_chain.get(wx)
            i_ke_palaces = [n for n, w in wuxing_palace.items() if w == i_ke_wx]
            i_ke_weight = sum(palaces.get(k, type('',(),{'weight':0})()).weight for k in i_ke_palaces)
            
            # 判断五行动态平衡
            if mother_weight < 0.1 and p.weight > 0.5:
                checks.append({
                    "type": "五行母虚子实",
                    "palaces": f"{palace_name}({wx})",
                    "detail": f"母宫({mother_wx})={mother_weight:.2f}而{palace_name}={p.weight:.2f}，根基空虚而独大",
                    "severity": "warning" if p.weight > 0.7 else "note"
                })
            if ke_me_weight < 0.1 and p.weight > 0.5:
                checks.append({
                    "type": "五行失制",
                    "palaces": f"{palace_name}({wx})",
                    "detail": f"克{palace_name}之{ke_me_wx}={ke_me_weight:.2f}，｛palace_name｝={p.weight:.2f}，无人管束",
                    "severity": "warning" if p.weight > 0.7 else "note"
                })
            if mother_weight > p.weight * 2 and p.weight < 0.2:
                checks.append({
                    "type": "五行母强子弱",
                    "palaces": f"{palace_name}({wx})",
                    "detail": f"母宫({mother_wx})={mother_weight:.2f}强压{palace_name}={p.weight:.2f}，子受母抑",
                    "severity": "note"
                })
        
        # ── 汇总评分 ──
        pass_count = sum(1 for c in checks if c["severity"] == "note")
        warn_count = sum(1 for c in checks if c["severity"] == "warning")
        
        # 综合评分
        total_checks = len(checks)
        score = 100.0
        score -= warn_count * 15  # 每个预警扣15分
        score -= (total_checks - warn_count - pass_count) * 5  # 其他扣5分
        score = max(0.0, min(100.0, score))
        
        if warn_count == 0:
            summary = "九维交叉校验通过，各维度一致性好" if score >= 90 else "九维交叉校验基本通过"
        elif warn_count <= 2:
            summary = f"九维交叉校验基本通过，{warn_count}项预警，需关注"
        elif warn_count <= 4:
            summary = f"九维交叉校验发现{warn_count}项预警，建议全面复核九宫格局"
        else:
            summary = f"九维交叉校验发现{warn_count}项预警，九宫格局存在多处失衡，务必复核"
        
        return {
            "pass": warn_count <= 2,
            "score": score,
            "warnings": warn_count,
            "checks": checks,
            "summary": summary
        }

    def _calc_tendency(self, first: NineDimResult, last: NineDimResult) -> float:
        """计算趋势方向"""
        return round(last.confidence_score - first.confidence_score, 2)


    # ═══════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════
    # 以下为 v2.1 新增：古籍验证升级模块
    # 来源：法窍、旨归、宝鉴、秘要、元灵经、演义
    # ═══════════════════════════════════════════════════════════

    def _find_zhifu_palace(self, meta):
        """从 shen_layout 中找到值符所在宫"""
        for p, s in meta.shen_layout.items():
            if s == '值符':
                return p
        return '坤'

    def _find_zhishi_palace(self, meta):
        """从 men_layout 中找到值使门所在宫"""
        men_yang_luo = ['坎', '艮', '震', '巽', '离', '坤', '兑', '乾']
        di_zhi_map = {'子': 0, '丑': 1, '寅': 2, '卯': 3, '辰': 4, '巳': 5,
                      '午': 6, '未': 7, '申': 8, '酉': 9, '戌': 10, '亥': 11}
        shi_zhi = meta.shi_ganzhi[-1] if meta.shi_ganzhi else '子'
        zhi_idx = di_zhi_map.get(shi_zhi, 0)
        return men_yang_luo[zhi_idx % 8]

    def _get_nature_rank(self, nature):
        """吉凶转数值"""
        rank = {'大吉': 1.0, '吉': 0.8, '平': 0.5, '凶': 0.2, '大凶': 0.0}
        return rank.get(nature, 0.5)

    def calc_an_gan(self, meta):
        """
        暗干穿透（法窍卷六·人盘暗干）
        值符加时干逆顺排布，乙丙丁为暗奇，庚为暗庚
        """
        tian_gan_order = ['戊', '己', '庚', '辛', '壬', '癸', '丁', '丙', '乙']
        zhifu_palace = self._find_zhifu_palace(meta)
        zhifu_gan = meta.tianpan_gan.get(zhifu_palace, '戊')
        start_idx = tian_gan_order.index(zhifu_gan) if zhifu_gan in tian_gan_order else 0
        is_yang = '阳' in meta.dun_type
        palace_order = ['坎', '坤', '震', '巽', '乾', '兑', '艮', '离']
        if not is_yang:
            palace_order = list(reversed(palace_order))
        result = {}
        for i, p_name in enumerate(palace_order):
            gan_idx = (start_idx + i) % len(tian_gan_order)
            gan = tian_gan_order[gan_idx]
            is_qi = gan in ['乙', '丙', '丁']
            is_geng = gan == '庚'
            meaning = ''
            if is_qi:
                meaning = f'暗奇{gan}入{p_name}—凶中有救，暗藏生机'
            elif is_geng:
                meaning = f'暗庚入{p_name}—吉中藏凶，暗中有阻'
            result[p_name] = {'gan': gan, 'is_an_qi': is_qi, 'is_an_geng': is_geng, 'meaning': meaning}
        meta.an_gan = result
        return result

    def calc_yingqi_v3(self, meta):
        """
        应期三法（法窍）
        神应定时间窗口，星应定节奏，门应定落点
        """
        zhifu_palace = self._find_zhifu_palace(meta)
        liuhe_map = {'坎':'兑','坤':'艮','震':'巽','巽':'震',
                     '乾':'离','兑':'坎','艮':'坤','离':'乾'}
        chong_palace = liuhe_map.get(zhifu_palace, '')
        shen_ying = {
            'method': '神应',
            'result': f'值符在{zhifu_palace}宫，对冲在{chong_palace}宫',
            'detail': f'值符在{zhifu_palace}宫→以六合{chong_palace}为大局时间窗口'
        }
        star_ying = {
            'method': '星应',
            'result': '星蒙十二次行度中',
            'detail': '值使星蒙遇旺相加速，遇刑合则变'
        }
        gate_season_map = {
            '休': {'旺':'冬','相':'春','休':'夏','囚':'秋'},
            '生': {'旺':'春','相':'夏','休':'秋','囚':'冬'},
            '伤': {'旺':'春','相':'夏','休':'秋','囚':'冬'},
            '杜': {'旺':'春','相':'夏','休':'秋','囚':'冬'},
            '景': {'旺':'夏','相':'秋','休':'冬','囚':'春'},
            '死': {'旺':'秋','相':'冬','休':'春','囚':'夏'},
            '惊': {'旺':'秋','相':'冬','休':'春','囚':'夏'},
            '开': {'旺':'秋','相':'冬','休':'春','囚':'夏'},
        }
        month = int(meta.gregorian[5:7]) if len(meta.gregorian) >= 7 else 6
        current_season = self._get_season(month)
        gate = meta.men_layout.get(zhifu_palace, '')
        gate_info = gate_season_map.get(gate, {})
        gate_status = '平'
        for status, season in gate_info.items():
            if season == current_season:
                gate_status = status
                break
        men_ying = {'method': '门应', 'result': f'{gate_status}',
                    'detail': f'{gate}门在{current_season}为{gate_status}'}
        if gate_status == '旺':
            summary = '3日内可见分晓'
        elif gate_status == '相':
            summary = '7~15日'
        elif gate_status == '休':
            summary = '30日左右'
        else:
            summary = '3个月以上'
        detail = f'神应：{shen_ying["detail"]} / 门应{men_ying["detail"]}→{summary}'
        return (summary, detail, {
            'shen_ying': shen_ying, 'star_ying': star_ying,
            'men_ying': men_ying,
            'all_ying': f'神应→{shen_ying["detail"]} | 星应→{star_ying["detail"]} | 门应→{men_ying["detail"]}'
        })

    def calc_qimen_yagua(self, meta):
        """
        奇门演卦（旨归·符使演卦法）
        值符天盘干转上卦，值使地盘干转下卦
        """
        gan_to_gua = {
            '甲':'坤','乙':'坤','丙':'震','丁':'巽',
            '戊':'坎','己':'离','庚':'艮','辛':'兑','壬':'乾','癸':'坤'
        }
        zhifu_palace = self._find_zhifu_palace(meta)
        zhifu_gan = meta.tianpan_gan.get(zhifu_palace, '戊')
        zhishi_palace = self._find_zhishi_palace(meta)
        zhishi_gan = meta.dipan_gan.get(zhishi_palace, '己')
        shang_gua = gan_to_gua.get(zhifu_gan, '坎')
        xia_gua = gan_to_gua.get(zhishi_gan, '坎')
        bagua_64 = {
            ('乾','乾'): ('乾为天', '刚健不息'),
            ('坤','坤'): ('坤为地', '厚德载物'),
            ('坎','震'): ('水雷屯', '刚柔始交而难生'),
            ('震','坎'): ('雷水解', '解除困境'),
            ('坤','震'): ('地雷复', '一阳来复'),
            ('震','坤'): ('雷地豫', '安乐和悦'),
            ('坎','坤'): ('水地比', '亲附归顺'),
            ('坤','坎'): ('地水师', '聚众而行'),
            ('乾','巽'): ('天风姤', '一阴初生'),
            ('巽','乾'): ('风天小畜', '密云不雨'),
            ('离','乾'): ('火天大有', '丰盛丰收'),
            ('乾','离'): ('天火同人', '团结协作'),
            ('乾','坤'): ('天地否', '闭塞不通'),
            ('坤','乾'): ('地天泰', '上下通达'),
            ('乾','艮'): ('天山遁', '退隐回避'),
            ('艮','乾'): ('山天大畜', '积蓄力量'),
            ('兑','乾'): ('泽天夬', '决断分明'),
            ('乾','兑'): ('天泽履', '如履薄冰'),
            ('离','坤'): ('火地晋', '晋升发展'),
            ('坤','离'): ('地火明夷', '受伤晦暗'),
            ('坎','乾'): ('水天需', '等待时机'),
            ('乾','坎'): ('天水讼', '争讼纷争'),
            ('巽','坎'): ('风水涣', '离散消散'),
            ('坎','巽'): ('水风井', '改邑不改井'),
            ('震','离'): ('雷火丰', '盛大丰满'),
            ('离','震'): ('火雷噬嗑', '咬合相通'),
            ('坎','离'): ('水火既济', '事已成功'),
            ('离','坎'): ('火水未济', '事未成'),
            ('艮','兑'): ('山泽损', '减损不足'),
            ('兑','艮'): ('泽山咸', '感应相通'),
            ('巽','震'): ('风雷益', '增益发展'),
            ('震','巽'): ('雷风恒', '持久稳定'),
        }
        gua_key = (shang_gua, xia_gua)
        gua_result = bagua_64.get(gua_key, (f'{shang_gua}上{xia_gua}下', '待查'))
        return {
            'shang_gua': shang_gua, 'xia_gua': xia_gua,
            'gua_name': gua_result[0], 'gua_meaning': gua_result[1],
            'zhifu_gan': zhifu_gan, 'zhishi_gan': zhishi_gan,
            'full': f'{gua_result[0]} | {gua_result[1]}'
        }

    def calc_keying(self, meta):
        """
        克应体系（秘要+元灵经）
        九星克应速查，验证盘内推演
        """
        star_keying = {
            '天蓬': {'ji': '见水、鱼、渔人', 'xiong': '见破损、溺水、盗贼'},
            '天芮': {'ji': '见病人愈、田野丰收', 'xiong': '见丧事、哭声、枯木'},
            '天冲': {'ji': '闻雷声、见军人、树动', 'xiong': '见争斗、破裂、山崩'},
            '天辅': {'ji': '见文人、书籍、花木', 'xiong': '见官司、文书毁、林毁'},
            '天禽': {'ji': '见中正之人、稳固之物', 'xiong': '见泥沼、坍塌、地裂'},
            '天心': {'ji': '见医生、药铺、圆物', 'xiong': '见手术、血光、利刃'},
            '天柱': {'ji': '见柱石、高楼、稳固', 'xiong': '见倒塌、断裂、支柱毁'},
            '天任': {'ji': '见负重之人、山石', 'xiong': '见地陷、山崩、压力大'},
            '天英': {'ji': '见灯火、红色、消息', 'xiong': '见火灾、血光、争吵'},
        }
        palace_keying = {}
        for palace, star in meta.xing_layout.items():
            info = star_keying.get(star, {})
            palace_keying[palace] = {
                'star': star, 'ji_omen': info.get('ji', ''), 'xiong_omen': info.get('xiong', '')
            }
        return {
            'method': '元灵经·九星克应法',
            'palace_keying': palace_keying,
            'usage': '以实际外应校验盘内推演。一验一致→可靠；矛盾→以外应为准；多次同向→趋势已定'
        }

    def calc_four_layer(self, meta):
        """
        四层奇门融合（演义）
        年/月/日/时四层穿断，交集越多越确定
        """
        gan_palace_map = {
            '甲':'乾','乙':'坤','丙':'艮','丁':'兑',
            '戊':'坎','己':'离','庚':'震','辛':'巽','壬':'乾','癸':'坤'
        }
        tian_list = ['甲','乙','丙','丁','戊','己','庚','辛','壬','癸']
        year = int(meta.gregorian[:4]) if len(meta.gregorian) >= 4 else 2026
        year_gan_idx = (year - 4) % 10
        year_gan = tian_list[year_gan_idx]
        month = int(meta.gregorian[5:7]) if len(meta.gregorian) >= 7 else 6
        month_gan_idx = (year_gan_idx * 2 + month - 1) % 10
        month_gan = tian_list[month_gan_idx]
        day_gan = meta.ri_ganzhi[0] if meta.ri_ganzhi else '戊'
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else '己'
        layers = {
            'year': {'gan': year_gan, 'palace': gan_palace_map.get(year_gan, ''), 'weight': 0.30},
            'month': {'gan': month_gan, 'palace': gan_palace_map.get(month_gan, ''), 'weight': 0.25},
            'day': {'gan': day_gan, 'palace': gan_palace_map.get(day_gan, ''), 'weight': 0.20},
            'hour': {'gan': shi_gan, 'palace': gan_palace_map.get(shi_gan, ''), 'weight': 0.25},
        }
        palace_counts = {}
        for lname, linfo in layers.items():
            p = linfo['palace']
            if p:
                palace_counts[p] = palace_counts.get(p, 0) + 1
        intersection = {p: c for p, c in palace_counts.items() if c >= 3}
        return {
            'layers': layers,
            'intersection': intersection,
            'conclusion': f'四层交集宫位：{", ".join(intersection.keys()) if intersection else "无三宫交集"}→{ "判定可靠" if intersection else "需更多信息" }'
        }

    def calc_baishen_priority(self, meta):
        """
        混合百神优先级（宝鉴）
        值符(君)→值使(臣)→九星(佐)→八神(使)
        """
        zhifu_palace = self._find_zhifu_palace(meta)
        zhifu_shen = meta.shen_layout.get(zhifu_palace, '值符')
        shen_info = SPIRIT_BASIC.get(zhifu_shen, {})
        zhifu_nature = shen_info.get('nature', '平')
        zhishi_palace = self._find_zhishi_palace(meta)
        zhishi_men = meta.men_layout.get(zhishi_palace, '休')
        men_info = GATE_BASIC.get(zhishi_men, {})
        zhishi_nature = men_info.get('nature', '平')
        star_count = {'吉': 0, '大吉': 0, '凶': 0, '大凶': 0, '平': 0}
        for palace, star in meta.xing_layout.items():
            info = STAR_BASIC.get(star, {})
            n = info.get('nature', '平')
            star_count[n] = star_count.get(n, 0) + 1
        star_score = (star_count['大吉']*5 + star_count['吉']*3 + star_count['平']
                      - star_count['凶']*2 - star_count['大凶']*4)
        shen_count = {'吉': 0, '大吉': 0, '凶': 0, '大凶': 0, '平': 0}
        for palace, shen in meta.shen_layout.items():
            info = SPIRIT_BASIC.get(shen, {})
            n = info.get('nature', '平')
            shen_count[n] = shen_count.get(n, 0) + 1
        shen_score = (shen_count['大吉']*5 + shen_count['吉']*3 + shen_count['平']
                      - shen_count['凶']*2 - shen_count['大凶']*4)
        star_overall = '吉' if star_score >= 3 else '凶' if star_score <= -3 else '平'
        shen_overall = '吉' if shen_score >= 3 else '凶' if shen_score <= -3 else '平'
        layers_status = {
            'value_star': {'level': 1, 'name': '值符(君)', 'status': zhifu_nature, 'weight': 0.4},
            'value_envoy': {'level': 2, 'name': '值使(臣)', 'status': zhishi_nature, 'weight': 0.3},
            'nine_star': {'level': 3, 'name': '九星(佐)', 'status': star_overall, 'weight': 0.2},
            'eight_shen': {'level': 4, 'name': '八神(使)', 'status': shen_overall, 'weight': 0.1},
        }
        pattern = f'{zhifu_nature}+{zhishi_nature}'
        conflict_rules = [
            ('吉+吉', '大局向好，过程顺利', 0.8),
            ('吉+凶', '大局向好，过程曲折', 0.6),
            ('凶+吉', '大局不可为，局部有机会', 0.4),
            ('凶+凶', '全面不利，休养为上', 0.2),
        ]
        matched = [r for r in conflict_rules if pattern.startswith(r[0])]
        return {
            'layers': layers_status,
            'weighted_score': round(max(0, min(1.0,
                self._get_nature_rank(zhifu_nature)*0.4 +
                self._get_nature_rank(zhishi_nature)*0.3 +
                (0.8 if star_overall=='吉' else 0.2 if star_overall=='凶' else 0.5)*0.2 +
                (0.8 if shen_overall=='吉' else 0.2 if shen_overall=='凶' else 0.5)*0.1
            )), 2),
            'conflict_match': matched[0] if matched else None,
            'conclusion': matched[0][1] if matched else '四层无明显冲突'
        }

    def calc_rolling_deduction(self, meta, direction='forward', steps=6):
        """
        时空滚动推演（节气滚动法）
        forward=后6节气（未来），backward=前6节气（过去）
        """
        jieqi_order = [
            '立春','雨水','惊蛰','春分','清明','谷雨',
            '立夏','小满','芒种','夏至','小暑','大暑',
            '立秋','处暑','白露','秋分','寒露','霜降',
            '立冬','小雪','大雪','冬至','小寒','大寒'
        ]
        star_jieqi = {
            '立春':'天任','雨水':'天任','惊蛰':'天冲','春分':'天冲',
            '清明':'天辅','谷雨':'天辅','立夏':'天英','小满':'天英',
            '芒种':'天芮','夏至':'天芮','小暑':'天柱','大暑':'天柱',
            '立秋':'天心','处暑':'天心','白露':'天任','秋分':'天任',
            '寒露':'天冲','霜降':'天冲','立冬':'天辅','小雪':'天辅',
            '大雪':'天英','冬至':'天英','小寒':'天芮','大寒':'天芮',
        }
        current_jieqi = meta.jieqi
        try:
            current_idx = jieqi_order.index(current_jieqi)
        except ValueError:
            current_idx = jieqi_order.index('芒种') if '芒种' in jieqi_order else 0
        if direction == 'forward':
            indices = [(current_idx + i) % 24 for i in range(1, steps + 1)]
        else:
            indices = [(current_idx - i) % 24 for i in range(1, steps + 1)]
        phase_names = {
            1: ('动议期','天冲为动'), 2: ('论证期','天辅为教'),
            3: ('决策期','天心为断'), 4: ('酝酿期','天芮为蓄'),
            5: ('执行期','天冲二动'), 6: ('落定期','天禽为定'),
        }
        if direction == 'forward':
            phase_names = {
                1: ('公告期','天芮事端'), 2: ('过渡期','天柱承压'),
                3: ('矛盾峰','天心决断'), 4: ('混乱退','玄武渐退'),
                5: ('明朗期','开门再启'), 6: ('落定期','天禽归位'),
            }
        steps_result = []
        for i, idx in enumerate(indices):
            jq = jieqi_order[idx]
            star = star_jieqi.get(jq, '天芮')
            step_num = i + 1
            ph_name, ph_desc = phase_names.get(step_num, (f'第{step_num}步', ''))
            steps_result.append({
                'step': step_num, 'jieqi': jq, 'dominant_star': star,
                'phase': ph_name, 'phase_desc': ph_desc,
                'direction': '回溯' if direction == 'backward' else '推进'
            })
        return {
            'current_jieqi': current_jieqi,
            'direction': '后6节气·未来推进' if direction == 'forward' else '前6节气·回溯成因',
            'steps': steps_result, 'total_steps': len(steps_result),
            'conclusion': f'以{current_jieqi}为基准{direction}滚动{steps}节气，共{len(steps_result)}帧'
        }

    def calc_host_guest(self, meta):
        """
        主客判断（五阳五阴时+宝义制和伐）
        阳时主动，阴时主静
        """
        yang_shi = ['甲', '乙', '丙', '丁', '戊']
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else '己'
        is_yang_shi = shi_gan in yang_shi
        shi_nature = '阳时·主动出击' if is_yang_shi else '阴时·以静制动'
        palace_wux_map = {'坎':'水','坤':'土','震':'木','巽':'木',
                          '乾':'金','兑':'金','艮':'土','离':'火'}
        men_wux_map = {'休':'水','生':'土','伤':'木','杜':'木',
                       '景':'火','死':'土','惊':'金','开':'金'}
        WX_SHENG = {'木':'火','火':'土','土':'金','金':'水','水':'木'}
        WX_KE = {'木':'土','土':'水','水':'火','火':'金','金':'木'}
        relations = []
        for palace, gate in meta.men_layout.items():
            p_wux = palace_wux_map.get(palace, '')
            g_wux = men_wux_map.get(gate, '')
            if not p_wux or not g_wux:
                continue
            if WX_SHENG.get(p_wux) == g_wux:
                rel, meaning = '宝（宫生门）', '利客，可主动'
            elif WX_SHENG.get(g_wux) == p_wux:
                rel, meaning = '义（门生宫）', '利主，宜固守'
            elif p_wux == g_wux:
                rel, meaning = '和（同五行）', '可进可退'
            elif WX_KE.get(p_wux) == g_wux:
                rel, meaning = '制（宫克门）', '利主，以静制动'
            elif WX_KE.get(g_wux) == p_wux:
                rel, meaning = '伐（门克宫）', '利客，见机而动'
            else:
                rel, meaning = '平', '观望'
            relations.append({'palace': palace, 'gate': gate, 'relation': rel, 'meaning': meaning})
        count_bao = sum(1 for r in relations if '宝' in r['relation'])
        count_yi = sum(1 for r in relations if '义' in r['relation'])
        count_fa = sum(1 for r in relations if '伐' in r['relation'])
        count_zhi = sum(1 for r in relations if '制' in r['relation'])
        if is_yang_shi and count_bao + count_fa > 2:
            conclusion = '主动方占优，利客为先'
        elif not is_yang_shi and count_yi + count_zhi > 2:
            conclusion = '被动方宜固守，以静制动'
        else:
            conclusion = '主客相当，审时度势'
        return {
            'shi_gan': shi_gan, 'shi_nature': shi_nature,
            'method': f'此局为{shi_nature}',
            'relations': relations, 'conclusion': conclusion
        }

    def calc_tianma(self, meta):
        """
        太冲天马方位（亥将顺推法）
        马星所在宫位，事态发展加速2~3倍
        """
        sanyuan_map = {
            ('申','子','辰'): ('寅', '艮8'),
            ('寅','午','戌'): ('申', '坤2'),
            ('巳','酉','丑'): ('亥', '乾6'),
            ('亥','卯','未'): ('巳', '巽4'),
        }
        shi_zhi = meta.shi_ganzhi[-1] if len(meta.shi_ganzhi) > 0 else '午'
        found = None
        for sanyuan, (ma_zhi, ma_palace) in sanyuan_map.items():
            if shi_zhi in sanyuan:
                found = {'sanyuan': ''.join(sanyuan), 'ma_zhi': ma_zhi, 'ma_palace': ma_palace}
                break
        if found:
            return {'shi_zhi': shi_zhi, 'tianma': found, 'effect': f'马星在{found["ma_palace"]}宫—该宫事态加速2~3倍'}
        else:
            return {'shi_zhi': shi_zhi, 'tianma': None, 'effect': '马星不显，正常节奏'}

    # ═══════════════════════════════════════════════════════════
    # L1~L6 空间剖面穿透系统
    # ═══════════════════════════════════════════════════════════

    def calc_spatial_profile(self, meta) -> dict:
        """
        L1~L6 六层空间剖面穿透分析
        从天盘到年命逐层下钻，穿透每层气机状态
        """
        # 格局表引用（全局 TIAN_DI_PATTERNS 的本地别名）
        pattern_dict = TIAN_DI_PATTERNS
        palace_wux_map = {'坎':'水','坤':'土','震':'木','巽':'木',
                          '乾':'金','兑':'金','艮':'土','离':'火','中':'土'}
        profile = {'layers': [], 'dominant': '', 'contradictions': []}

        # L1：天盘层（九星+八神）- 外部大势
        l1_details = {}
        for palace, star in meta.xing_layout.items():
            star_meaning = STAR_WANGSHUAI.get(star, {})
            l1_details[palace] = {'star': star, 'wuxing': star_meaning.get('wuxing', '')}
        # 值符所在宫为L1主导
        zhifu_palace = self._find_zhifu_palace(meta)
        l1_dominant = f"值符落{zhifu_palace}宫·{meta.xing_layout.get(zhifu_palace,'')}星主导"
        profile['layers'].append({
            'layer': 'L1天盘层', 'symbol': '九星·八神',
            'focus': SPATIAL_PROFILE_LAYERS['L1']['focus'],
            'dominant': l1_dominant,
            'details': l1_details,
        })

        # L2：人盘层（八门）- 人事动态
        l2_details = {}
        for palace, gate in meta.men_layout.items():
            l2_details[palace] = {'gate': gate}
        profile['layers'].append({
            'layer': 'L2人盘层', 'symbol': '八门',
            'focus': SPATIAL_PROFILE_LAYERS['L2']['focus'],
            'dominant': f"值使门【{meta.men_layout.get(self._find_zhishi_palace(meta),'')}】主导",
            'details': l2_details,
        })

        # L3：地盘层（地干+宫位）- 地气根基
        l3_details = {}
        for palace, gan in meta.dipan_gan.items():
            l3_details[palace] = {'di_gan': gan, 'palace_wuxing': palace_wux_map.get(palace, '')}
        profile['layers'].append({
            'layer': 'L3地盘层', 'symbol': '地干·宫位',
            'focus': SPATIAL_PROFILE_LAYERS['L3']['focus'],
            'details': l3_details,
        })

        # L4：格局层（天干×地干组合）- 矛盾核心
        l4_details = []
        for palace, tg in meta.tianpan_gan.items():
            dg = meta.dipan_gan.get(palace, '')
            key = (tg, dg)
            if key in pattern_dict:
                l4_details.append({
                    'palace': palace, 'tg': tg, 'dg': dg,
                    'pattern': pattern_dict[key][0],
                    'nature': pattern_dict[key][1],
                    'meaning': pattern_dict[key][2],
                })
            elif (dg, tg) in pattern_dict:
                l4_details.append({
                    'palace': palace, 'tg': tg, 'dg': dg,
                    'pattern': f"反看·{pattern_dict[(dg, tg)][0]}",
                    'nature': pattern_dict[(dg, tg)][1],
                    'meaning': f"逆向·{pattern_dict[(dg, tg)][2]}",
                })
        l4_dominant = l4_details[0] if l4_details else {'nature': '无特殊格局'}
        profile['layers'].append({
            'layer': 'L4格局层', 'symbol': '天干合冲',
            'focus': SPATIAL_PROFILE_LAYERS['L4']['focus'],
            'dominant': f"{l4_dominant.get('palace','')}宫·{l4_dominant.get('pattern','')}（{l4_dominant.get('nature','')}）",
            'details': l4_details[:10],  # 最多10个
        })

        # L5：年命层（预留外部传入）- 人事归属
        profile['layers'].append({
            'layer': 'L5年命层', 'symbol': '年命·生肖',
            'focus': SPATIAL_PROFILE_LAYERS['L5']['focus'],
            'detail': '需外部传入年命干支后填充',
        })

        # L6：时令层（节气+三甲开阖+五阳五阴）- 时空定数
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else ''
        ri_gan = meta.ri_ganzhi[0] if meta.ri_ganzhi else ''
        jieqi = meta.jieqi
        kai_he = SAN_JIA_KAI_HE.get((ri_gan, ''), '') or '待查'
        for (g1, g2), val in SAN_JIA_KAI_HE.items():
            if ri_gan in (g1, g2):
                kai_he = val
                break
        shi_nature = '阳时·主动' if shi_gan in WU_YANG_SHI else '阴时·主静' if shi_gan else '未知'
        profile['layers'].append({
            'layer': 'L6时令层', 'symbol': '节气·日干支·时辰',
            'focus': SPATIAL_PROFILE_LAYERS['L6']['focus'],
            'detail': f"节气:{jieqi} | 开阖:{kai_he} | 时性:{shi_nature}",
        })

        # 跨层矛盾检测
        contradictions = []
        if l4_details and any(p.get('nature') == '大凶' for p in l4_details):
            contradictions.append('L4格局层有大凶格出现，需注意是否有向下层(L1~L3)渗透')
        if l1_details and l4_details:
            zhifu_star = meta.xing_layout.get(zhifu_palace, '')
            bad_patterns = [p for p in l4_details if p.get('nature') in ('大凶', '凶')]
            if bad_patterns and zhifu_palace == bad_patterns[0].get('palace', ''):
                contradictions.append(f'值符在{zhifu_palace}宫与大凶格局叠加重叠，事态严重')
        profile['contradictions'] = contradictions
        profile['dominant'] = f"L1→L4趋势：{l1_dominant} → {l4_dominant.get('pattern','无特殊格')}"
        return profile

    # ═══════════════════════════════════════════════════════════
    # 时间轴滚动系统（三判+六阶+12节气增强版）
    # ═══════════════════════════════════════════════════════════

    def calc_time_rolling(self, meta, direction: str = 'forward', steps: int = 6) -> dict:
        """
        增强版时间轴滚动系统
        三判：时量（快慢）/ 时质（吉凶）/ 时势（升降）
        六阶：前因→萌芽→当下→转折→落定→余波
        12节气：溯因和预判各12节气
        """
        base = self.calc_rolling_deduction(meta, direction, steps)
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else ''
        ri_gan = meta.ri_ganzhi[0] if meta.ri_ganzhi else ''
        ri_zhi = meta.ri_ganzhi[-1] if meta.ri_ganzhi else ''

        # 时量判（快慢）
        # 阳时快、阴时慢；马星快、伏吟慢；反吟快
        fast_signals = 0
        slow_signals = 0
        if shi_gan in WU_YANG_SHI:
            fast_signals += 1
        else:
            slow_signals += 1
        # 马星信号
        tianma = self.calc_tianma(meta)
        if tianma.get('tianma'):
            fast_signals += 2
        # 反吟伏吟
        for p, s in meta.shen_layout.items():
            if s == '白虎':
                fast_signals += 1
        # 内外盘
        for palace, gate in meta.men_layout.items():
            if gate == '杜门':
                slow_signals += 1
            if gate == '景门':
                fast_signals += 1
        time_quantity = '快' if fast_signals > slow_signals + 1 else ('慢' if slow_signals > fast_signals + 1 else '中')

        # 时质判（吉凶）
        # 开生休三吉门多则吉，伤死惊三凶门多则凶
        good_gates = 0
        bad_gates = 0
        for palace, gate in meta.men_layout.items():
            if gate in ('开', '生', '休'):
                good_gates += 1
            elif gate in ('伤', '死', '惊'):
                bad_gates += 1
        time_quality = '吉' if good_gates >= bad_gates + 2 else ('凶' if bad_gates >= good_gates + 2 else '平')

        # 时势判（升降）
        # 阳遁升势、阴遁降势；生门上乘升、死门叠加降
        dun_type = getattr(meta, 'dun_type', '')
        dun_trend = '上升' if '阳' in str(dun_type) else ('下降' if '阴' in str(dun_type) else '持平')
        sheng_dead = sum(1 for gate in meta.men_layout.values() if gate == '生门')
        si_dead = sum(1 for gate in meta.men_layout.values() if gate == '死门')
        if sheng_dead > si_dead:
            trend = f'{dun_trend}（生门占优）'
        elif si_dead > sheng_dead:
            trend = f'下降（死门压制）'
        else:
            trend = dun_trend

        # 六阶推进法映射
        stage_map = {
            1: {'name': '前因阶', 'desc': '回溯前3~6节气成因'},
            2: {'name': '萌芽阶', 'desc': '回溯前1~3节气触发节点'},
            3: {'name': '当下阶', 'desc': '当前节气锁定核心'},
            4: {'name': '转折阶', 'desc': '后1~3节气预判拐点'},
            5: {'name': '落定阶', 'desc': '后3~6节气形态结果'},
            6: {'name': '余波阶', 'desc': '后6~12节气影响余量'},
        }
        stages = {}
        for sid, sinfo in stage_map.items():
            if direction == 'forward' and sid <= 3:
                stage_status = '已过'
            elif direction == 'backward' and sid >= 4:
                stage_status = '未到'
            else:
                stage_status = '当前'
            stages[str(sid)] = {**sinfo, 'status': stage_status}

        # 12节气增强
        all_forward = self.calc_rolling_deduction(meta, 'forward', 12)
        all_backward = self.calc_rolling_deduction(meta, 'backward', 12)

        return {
            **base,
            'time_quantity': time_quantity,
            'time_quality': time_quality,
            'time_trend': trend,
            'three_judgments': {
                '时量判': time_quantity, '时质判': time_quality, '时势判': trend,
            },
            'six_stages': stages,
            'full_12_forward': all_forward.get('steps', []),
            'full_12_backward': all_backward.get('steps', []),
        }

    # ═══════════════════════════════════════════════════════════
    # 三层因果穿透系统
    # ═══════════════════════════════════════════════════════════

    def calc_causal_penetration(self, meta, context_hints: dict = None) -> dict:
        """
        三层因果穿透分析
        表象层（表面理由）→ 实因层（真实驱动）→ 底色层（深层结构）
        """
        context_hints = context_hints or {}
        palace_wux_map = {'坎':'水','坤':'土','震':'木','巽':'木',
                          '乾':'金','兑':'金','艮':'土','离':'火','中':'土'}
        gp_meaning = {'生':'生长·获利','休':'休整·等待','开':'开创·启动',
                      '伤':'损伤·冲突','杜':'阻碍·封闭','景':'虚象·消息',
                      '死':'终结·静止','惊':'变动·惊吓'}
        shen_meaning = {'值符':'核心大势','腾蛇':'虚诈缠绕','太阴':'隐秘暗处',
                        '六合':'合作多方','白虎':'凶煞强制','玄武':'暗箱操作',
                        '九地':'深藏稳固','九天':'高亢张扬'}

        # ① 表象层（怎么看）：时干+杜门/景门+八神
        surface = {}
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else ''
        for palace, gate in meta.men_layout.items():
            if gate == '杜门':
                surface['issue_visibility'] = f'{palace}宫杜门—信息封闭，表面理由未必真实'
                surface['surface_gate'] = '杜门—官方说辞或流传版本'
            elif gate == '景门':
                surface['issue_visibility'] = f'{palace}宫景门—消息公开但有虚象'
                surface['surface_gate'] = '景门—公开消息或传闻'
        for palace, shen in meta.shen_layout.items():
            if shen in ('玄武', '太阴'):
                surface['hidden'] = f'{palace}宫{shen_meaning.get(shen,"")}—信息在暗处'
                break
        if not surface:
            surface['issue_visibility'] = '无杜门/玄武—信息较透明'

        # ② 实因层（为什么）：中宫生门+值使+戊+丙
        real_cause = {}
        zhishi_palace = self._find_zhishi_palace(meta)
        zhishi_gate = meta.men_layout.get(zhishi_palace, '')
        zhishi_wuxing = palace_wux_map.get(zhishi_palace, '')
        real_cause['zhishi'] = f'值使门【{zhishi_gate}】落{zhishi_palace}宫{gp_meaning.get(zhishi_gate,"")}'
        # 戊（资金/土地/资本）
        wu_palaces = [p for p, g in meta.tianpan_gan.items() if g == '戊']
        if wu_palaces:
            real_cause['capital'] = f'戊土（资本/土地）在{",".join(wu_palaces)}宫'
        # 丙（政策指令）
        bing_palaces = [p for p, g in meta.tianpan_gan.items() if g == '丙']
        if bing_palaces:
            real_cause['policy'] = f'丙火（政策）在{",".join(bing_palaces)}宫'
        # 乙（收益/利润）
        yi_palaces = [p for p, g in meta.tianpan_gan.items() if g == '乙']
        if yi_palaces:
            real_cause['profit'] = f'乙木（利润/资源）在{",".join(yi_palaces)}宫'
        # 生门所在宫
        sheng_palaces = [p for p, g in meta.men_layout.items() if g == '生门']
        if sheng_palaces:
            real_cause['growth'] = f'生门在{",".join(sheng_palaces)}宫—利益驱动方向'
        if zhishi_gate == '生门':
            real_cause['core'] = '值使生门—核心驱动力为经济利益'

        # ③ 底色层（深层结构）：值符+太阴/九天+年干
        deep_base = {}
        zhifu_palace = self._find_zhifu_palace(meta)
        zhifu_shen = meta.shen_layout.get(zhifu_palace, '')
        zhifu_star = meta.xing_layout.get(zhifu_palace, '')
        deep_base['zhifu'] = f'值符【{zhifu_shen}】在{zhifu_palace}宫·{zhifu_star}星—最高决策层意图'
        # 九天/太阴在何处
        for palace, shen in meta.shen_layout.items():
            if shen == '九天':
                deep_base['jiutian'] = f'{palace}宫九天—高远层面的战略规划'
            elif shen == '太阴':
                deep_base['taiyin'] = f'{palace}宫太阴—隐蔽长远的布局'
        # 年干所在宫（高级别因素）
        # 年干从meta.gregorian中提取年份干支，暂由调用者传入

        # 三层汇总
        return {
            'surface_layer': surface,
            'real_cause_layer': real_cause,
            'deep_base_layer': deep_base,
            'summary': {
                '表象': surface.get('issue_visibility', '待查'),
                '实因': f"值使{zhishi_gate}+资本{real_cause.get('capital','')}",
                '底色': f"值符{zhifu_palace}宫战略意图",
            }
        }

    # ═══════════════════════════════════════════════════════════
    # 时间质量判断（宝义制和伐+五阳五阴+三甲开阖）
    # ═══════════════════════════════════════════════════════════

    def _eval_time_quality(self, meta) -> dict:
        """
        综合时间质量判断
        宝义制和伐 = 门宫生克定性
        五阳五阴时 = 动静态势判定
        三甲开阖 = 气数开阖判定
        """
        # 复用calc_host_guest的宝义制和伐判定
        host_guest = self.calc_host_guest(meta)
        shi_gan = meta.shi_ganzhi[0] if meta.shi_ganzhi else ''
        ri_gan = meta.ri_ganzhi[0] if meta.ri_ganzhi else ''

        # 三甲开阖
        kai_he = '待查'
        for (g1, g2), val in SAN_JIA_KAI_HE.items():
            if ri_gan in (g1, g2):
                kai_he = val
                break
        kai_he_meaning = '开日·气机外放·宜行动' if kai_he == '开' else '阖日·气机内收·宜静守'

        # 五阳五阴时
        shi_nature = '阳时·主动利客' if shi_gan in WU_YANG_SHI else ('阴时·主静利主' if shi_gan else '未知')

        # 综合判定
        bao_yi_count = sum(1 for r in host_guest.get('relations', []) if '宝' in r.get('relation', '') or '义' in r.get('relation', ''))
        fa_zhi_count = sum(1 for r in host_guest.get('relations', []) if '伐' in r.get('relation', '') or '制' in r.get('relation', ''))

        if bao_yi_count > fa_zhi_count + 2 and kai_he == '开' and shi_gan in WU_YANG_SHI:
            overall = '上佳·天时地利人和'
        elif bao_yi_count >= fa_zhi_count and kai_he == '开':
            overall = '良·顺势而为'
        elif fa_zhi_count > bao_yi_count + 2 and kai_he == '阖' and shi_gan in WU_YIN_SHI:
            overall = '下·宜静不宜动'
        elif fa_zhi_count > bao_yi_count:
            overall = '差·阻力大'
        else:
            overall = '平·审时度势'

        return {
            'bao_yi_zhi_fa': host_guest.get('relations', []),
            'bao_yi_count': bao_yi_count,
            'fa_zhi_count': fa_zhi_count,
            'kai_he': kai_he,
            'kai_he_meaning': kai_he_meaning,
            'shi_nature': shi_nature,
            'overall': overall,
        }

    # ═══════════════════════════════════════════════════════════
    # 古籍出处标记报告
    # ═══════════════════════════════════════════════════════════

    def _add_provenance_report(self, meta) -> dict:
        """
        为推演结果添加古籍出处标记
        格局级/星门级/推演级三级来源标注
        """
        # 格局表引用（全局 TIAN_DI_PATTERNS 的本地别名）
        pattern_dict = TIAN_DI_PATTERNS
        provenance = {
            'patterns': {},
            'stars': {},
            'gates': {},
            'notes': [],
        }

        # 格局出处
        for palace, tg in meta.tianpan_gan.items():
            dg = meta.dipan_gan.get(palace, '')
            key = (tg, dg)
            if key in pattern_dict:
                pname = pattern_dict[key][0]
                pn = PATTERN_PROVENANCE.get(pname, '古籍合参·通用')
                provenance['patterns'][f'{palace}宫{tg}+{dg}'] = {
                    'pattern': pname, 'source': pn,
                }

        # 星门出处
        for palace, star in meta.xing_layout.items():
            provenance['stars'][f'{palace}宫{star}'] = {
                'source': STAR_PROVENANCE.get(star, '遁甲演义·卷一'),
                'meridian_note': STAR_MERIDIAN_PROVENANCE_NOTE if palace in meta.xing_layout else '',
            }
        for palace, gate in meta.men_layout.items():
            provenance['gates'][f'{palace}宫{gate}'] = {
                'source': GATE_PROVENANCE.get(gate, '遁甲演义·卷四·八门'),
                'meridian_note': GATE_MERIDIAN_PROVENANCE_NOTE if palace in meta.men_layout else '',
            }

        # 推演级标记
        provenance['notes'].append('⭐ 九星配经脉为推演所得·经典依据《灵枢·九宫八风》')
        provenance['notes'].append('⭐ 八门配经脉为推演所得·非经典直接出处')
        provenance['notes'].append('⭐ 飞宫应期法出《奇门法窍·卷三·应期章》')
        provenance['notes'].append('⭐ 宝义制和伐出《奇门法窍·卷二·门宫生克》')
        provenance['notes'].append('⭐ 五阳五阴时出《奇门法窍·卷二·动静》')

        return provenance

    # ═══════════════════════════════════════════════════════════
    # 一键穿透推演（综合调用所有新系统）
    # ═══════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════
    # 多宫联动网络分析（回路/冲击/平衡三大模式）
    # 来源：丹道玄医录·07-奇门体系·01-九维立体度 第三维·多宫联动
    # ═══════════════════════════════════════════════════════════

    def calc_network_analysis(self, meta) -> dict:
        """
        多宫联动网络分析——识别九宫之间的生克制化网络拓扑。

        三大网络模式：
        - 回路模式：A生B+B生A = 正反馈回路（吸引力/增长/消耗）
        - 冲击模式：A克B = 单向压制（权力/攻击/压力）
        - 平衡模式：多宫制衡 = 稳定态（多方博弈平衡）

        Returns:
            dict: {
                'loops': [回路列表],       # 回路模式
                'impacts': [冲击列表],      # 冲击模式
                'balances': [平衡列表],     # 平衡模式
                'network_summary': str,     # 网络总体分析
                'dominant_pattern': str     # 主导网络模式
            }
        """
        # 九宫五行表
        palace_wuxing = {
            '坎1':'水','坤2':'土','震3':'木','巽4':'木',
            '中5':'土','乾6':'金','兑7':'金','艮8':'土','离9':'火'
        }
        wuxing_sheng = {'木':'火','火':'土','土':'金','金':'水','水':'木'}
        wuxing_ke   = {'木':'土','火':'金','土':'水','金':'木','水':'火'}

        # 获取各宫主星、主门、权重（从已有的空间数据推测权重）
        palace_data = {}
        for palace, star in (meta.xing_layout or {}).items():
            palace_data[palace] = {
                'wuxing': palace_wuxing.get(palace, '土'),
                'star': star,
                'men': (meta.men_layout or {}).get(palace, ''),
                'shen': (meta.shen_layout or {}).get(palace, ''),
                'tiangan': (meta.tianpan_gan or {}).get(palace, ''),
                'digan': (meta.dipan_gan or {}).get(palace, ''),
            }

        palace_list = list(palace_data.keys())

        # ── ① 回路模式检测（A生B+B生A=回馈闭环） ──
        loops = []
        for i, a in enumerate(palace_list):
            for b in palace_list[i+1:]:
                wx_a = palace_data[a]['wuxing']
                wx_b = palace_data[b]['wuxing']
                # 双向相生 = 正反馈回路
                if wuxing_sheng.get(wx_a) == wx_b and wuxing_sheng.get(wx_b) == wx_a:
                    loops.append({
                        'type': '回路模式',
                        'palaces': f'{a}-{b}',
                        'wuxing': f'{wx_a}↔{wx_b}',
                        'detail': f'{a}({wx_a})生{b}({wx_b})+{b}({wx_b})生{a}({wx_a})=正反馈闭环',
                        'effect': '增强循环' if wx_a != wx_b else '同气共振',
                        'star_men': f'{palace_data[a]["star"]}+{palace_data[a]["men"]} ↔ {palace_data[b]["star"]}+{palace_data[b]["men"]}'
                    })

        # ── ② 冲击模式检测（A克B=单向压制） ──
        impacts = []
        for a in palace_list:
            for b in palace_list:
                if a == b:
                    continue
                wx_a = palace_data[a]['wuxing']
                wx_b = palace_data[b]['wuxing']
                if wuxing_ke.get(wx_a) == wx_b:
                    impacts.append({
                        'type': '冲击模式',
                        'from': a,
                        'to': b,
                        'wuxing': f'{wx_a}克{wx_b}',
                        'detail': f'{a}({wx_a})冲克{b}({wx_b})',
                        'intensity': '强' if palace_data[a]['star'] in ('天芮','天蓬','天柱','天英') and
                                     palace_data[a]['men'] in ('伤门','死门','惊门') else '中',
                        'from_star_men': f'{palace_data[a]["star"]}+{palace_data[a]["men"]}',
                        'to_star_men': f'{palace_data[b]["star"]}+{palace_data[b]["men"]}'
                    })

        # ── ③ 平衡模式检测（多宫制衡稳定态） ──
        balances = []
        # 检测坎离纵向平衡（水火既济）
        if '坎1' in palace_data and '离9' in palace_data:
            balances.append({
                'type': '平衡模式',
                'pattern': '坎离纵向平衡',
                'palaces': '坎1↔离9',
                'wuxing': '水↔火',
                'nature': '既济' if palace_data['坎1']['shen'] in ('六合','九天','值符') and
                                     palace_data['离9']['shen'] in ('六合','九天','值符') else '未济',
                'detail': '坎离为水火之枢，平衡则心肾交泰'
            })
        # 检测震兑横向平衡（金木制化）
        if '震3' in palace_data and '兑7' in palace_data:
            balances.append({
                'type': '平衡模式',
                'pattern': '震兑横向平衡',
                'palaces': '震3↔兑7',
                'wuxing': '木↔金',
                'nature': '制化' if palace_data['兑7']['shen'] in ('太阴','九地') else '相克',
                'detail': '震兑为金木升降之枢，平衡则气机调畅'
            })
        # 检测乾坤先天平衡
        if '乾6' in palace_data and '坤2' in palace_data:
            balances.append({
                'type': '平衡模式',
                'pattern': '乾坤先天平衡',
                'palaces': '乾6↔坤2',
                'wuxing': '金↔土',
                'nature': '相生' if palace_data['坤2']['shen'] in ('九地','太阴') else '相制',
                'detail': '乾坤为先天父母卦，平衡则根基稳固'
            })

        # ── ④ 网络综合评估 ──
        total_loops = len(loops)
        total_impacts = len(impacts)
        total_balances = len(balances)

        # 主导模式判断
        if total_loops > total_impacts and total_loops > total_balances:
            dominant = '回路模式主导：系统处于正反馈增强循环，事态有自我加速趋势'
        elif total_impacts > total_loops and total_impacts > total_balances:
            dominant = '冲击模式主导：系统处于强力压制状态，事态单向推进'
        elif total_balances >= total_loops and total_balances >= total_impacts:
            dominant = '平衡模式主导：系统处于多宫制衡稳定态，各方势均力敌'
        else:
            dominant = '混合模式：多种网络同时作用，需结合具体用神判断'

        # 网络摘要
        summary_parts = []
        if total_loops > 0:
            summary_parts.append(f'{total_loops}组回路')
        if total_impacts > 0:
            summary_parts.append(f'{total_impacts}条冲击')
        if total_balances > 0:
            summary_parts.append(f'{total_balances}组平衡')
        summary = '、'.join(summary_parts) if summary_parts else '无明显网络模式'
        network_summary = f'多宫联动网络：{summary} | {dominant}'

        return {
            'loops': loops,
            'impacts': impacts,
            'balances': balances,
            'network_summary': network_summary,
            'dominant_pattern': dominant,
            'stats': {
                'total_loops': total_loops,
                'total_impacts': total_impacts,
                'total_balances': total_balances
            }
        }

    def deduce_full_penetration(self, meta, direction='forward',
                                 context_hints=None) -> dict:
        """
        一键穿透推演：空间剖面+时间滚动+因果穿透+时间质量+出处标记
        五合一综合输出
        """
        context_hints = context_hints or {}
        spatial = self.calc_spatial_profile(meta)
        time_rolling = self.calc_time_rolling(meta, direction, 6)
        causal = self.calc_causal_penetration(meta, context_hints)
        network = self.calc_network_analysis(meta)
        time_quality = self._eval_time_quality(meta)
        provenance = self._add_provenance_report(meta)

        return {
            'spatial_profile': spatial,
            'time_rolling': time_rolling,
            'causal_penetration': causal,
            'network_analysis': network,
            'time_quality': time_quality,
            'provenance': provenance,
            'full_penetration_summary': {
                'spatial_dominant': spatial.get('dominant', ''),
                'time_trend': time_rolling.get('time_trend', ''),
                'causal_surface': causal.get('summary', {}).get('表象', ''),
                'causal_real': causal.get('summary', {}).get('实因', ''),
                'network_dominant': network.get('network_summary', ''),
                'time_overall': time_quality.get('overall', ''),
            }
        }



    def calc_sanzha_wujia(self, meta):
        """三诈五假·行动策略建议（演义）

        Returns:
            dict: {诈格, 假格, 行动建议}
        """
        result = {"诈格": "", "假格": "", "行动建议": ""}

        # 检查三奇+三门+特定八神
        sanqi_gans = ["乙","丙","丁"]
        sanmen_gates = ["开","休","生"]
        special_shens = {"太阴": "真诈", "九地": "重诈", "六合": "休诈"}

        has_sanqi = False
        has_sanmen = False
        shen_type = ""

        if hasattr(meta, 'tiangan_layout'):
            for palace, gan in (meta.tiangan_layout or {}).items():
                if gan in sanqi_gans:
                    has_sanqi = True
                    break

        if hasattr(meta, 'men_layout'):
            for palace, gate in (meta.men_layout or {}).items():
                if gate in sanmen_gates:
                    has_sanmen = True
                    break

        if hasattr(meta, 'shen_layout'):
            for palace, shen in (meta.shen_layout or {}).items():
                if shen in special_shens:
                    shen_type = special_shens[shen]

        if has_sanqi and has_sanmen and shen_type:
            result["诈格"] = f"{shen_type}（三奇+三门+{shen_type}）"

        # 五假
        wujia_map = {
            "景门": ("九天", "天假", "进谒干求"),
            "杜门": ("九地", "地假", "潜伏隐伏"),
            "伤门": ("九地", "神假", "埋葬"),
            "惊门": ("九天", "人假", "捕逃亡"),
            "死门": ("九地", "鬼假", "超亡荐度"),
        }

        if hasattr(meta, 'men_layout'):
            du_men_gans = ["丁","己","癸"]
            for palace, gate in (meta.men_layout or {}).items():
                gate_clean = gate.replace("门","")
                if gate_clean in wujia_map:
                    shen_needed, jia_name, action = wujia_map[gate_clean]
                    if hasattr(meta, 'shen_layout'):
                        for sp, sv in (meta.shen_layout or {}).items():
                            if sv == shen_needed:
                                # 检查有丁己癸在盘
                                has_du_gan = False
                                if hasattr(meta, 'tiangan_layout'):
                                    for gp, gv in (meta.tiangan_layout or {}).items():
                                        if gv in du_men_gans:
                                            has_du_gan = True
                                            break
                                if has_du_gan or gate_clean not in ["杜","伤","死"]:
                                    result["假格"] = f"{jia_name}（{gate}门+{shen_needed}→{action}）"

        advices = []
        if result["诈格"]:
            advices.append(f"诈格{result['诈格']}→主动策略推荐")
        if result["假格"]:
            advices.append(f"假格{result['假格']}→特定策略推荐")
        result["行动建议"] = " | ".join(advices) if advices else "无三诈五假→常规应对"

        return result


    def calc_menpo_quantified(self, meta):
        """门迫量化体系（符应经）

        宫克门=门迫(吉门被迫吉事减半)
        门克宫=宫迫(凶门受迫凶上加凶)
        门宫比和=同五行(吉加吉凶加凶)

        Returns:
            dict: {门迫表, 量化判}
        """
        result = {"门迫表": {}, "量化判": ""}

        wx_map = {"坎":"水","坤":"土","震":"木","巽":"木","中":"土","乾":"金","兑":"金","艮":"土","离":"火"}
        gate_wx = {"休":"水","生":"土","伤":"木","杜":"木","景":"火","死":"土","惊":"金","开":"金"}
        gate_rank = {"休":"吉","生":"吉","伤":"凶","杜":"平","景":"平","死":"凶","惊":"凶","开":"吉"}

        menpo_data = []
        if hasattr(meta, 'men_layout'):
            for palace, gate in (meta.men_layout or {}).items():
                gate_name = gate.replace("门","")
                p_wx = wx_map.get(palace, "")
                g_wx = gate_wx.get(gate_name, "")
                if not p_wx or not g_wx:
                    continue

                # 五行生克
                shengke_map = {
                    ("水","水"): "比和", ("火","火"): "比和", ("木","木"): "比和",
                    ("金","金"): "比和", ("土","土"): "比和",
                    ("水","火"): "宫克门", ("水","金"): "门克宫",
                    ("火","土"): "宫克门", ("火","木"): "门克宫",
                    ("木","土"): "宫克门", ("木","火"): "门克宫",
                    ("金","木"): "宫克门", ("金","水"): "门克宫",
                    ("土","水"): "宫克门", ("土","金"): "门克宫",
                }
                # 逆查
                relation = ""
                for (a,b),v in shengke_map.items():
                    if a==p_wx and b==g_wx:
                        relation = v
                        break

                severity = 0.0
                gate_type = gate_rank.get(gate_name, "平")
                if relation == "宫克门":
                    severity = -0.4 if gate_type == "吉" else -0.2
                elif relation == "门克宫":
                    severity = -0.5 if gate_type == "凶" else -0.2
                elif relation == "比和":
                    severity = 0.1 if gate_type == "吉" else -0.2

                menpo_data.append({
                    "宫位": palace, "门": gate_name,
                    "宮五行": p_wx, "门五行": g_wx,
                    "关系": relation,
                    "吉凶": gate_type,
                    "量化影响": round(severity, 2)
                })
                result["门迫表"][palace] = f"{gate_name}门⊥{p_wx}→{relation}({severity:+.2f})"

        total_impact = sum(d["量化影响"] for d in menpo_data)
        result["量化判"] = f"门迫叠加影响{total_impact:+.2f}，{'偏利' if total_impact > 0 else '偏弊'}"

        return result


    def calc_zhongwu_ji(self, meta, season="default"):
        """中五宫寄用新法（阴符经释秘·霍斐然）

        season: 'default'|'spring'|'summer'|'autumn'|'winter'

        Returns:
            dict: {寄法, 所寄之宫, 所借之门, 说明}
        """
        dun_type = getattr(meta, 'dun_type', "阳遁")

        # 默认寄法
        result = {"寄法": "", "寄宫": "", "借门": "", "说明": ""}

        if season == "default":
            if "阳" in str(dun_type):
                result["寄法"] = "阳遁寄坤"
                result["寄宫"] = "坤2"
                result["借门"] = "死门"
            else:
                result["寄法"] = "阴遁寄艮"
                result["寄宫"] = "艮8"
                result["借门"] = "生门"
        elif season == "spring":
            result["寄法"] = "四季寄法·春"
            result["寄宫"] = "震3"
            result["借门"] = "伤门"
        elif season == "summer":
            result["寄法"] = "四季寄法·夏"
            result["寄宫"] = "离9"
            result["借门"] = "景门"
        elif season == "autumn":
            result["寄法"] = "四季寄法·秋"
            result["寄宫"] = "兑7"
            result["借门"] = "惊门"
        elif season == "winter":
            result["寄法"] = "四季寄法·冬"
            result["寄宫"] = "坎1"
            result["借门"] = "休门"

        result["说明"] = f"{result['寄法']}：中宫借{result['寄宫']}{result['借门']}"
        return result


    def calc_enhanced_rolling(self, frames, four_layer_mode=True):
        """时空滚动推演法·增强版

        升级：在原有basic rolling基础上加入四层奇门融合和应期三法

        Args:
            frames: 多帧数据 [{time, data}, ...]
            four_layer_mode: 是否启用四层奇门

        Returns:
            dict: {滚动链, 四层穿插, 应期判, 结论}
        """
        result = {"滚动链": [], "四层穿插": {}, "应期判": "", "结论": ""}

        if not frames or len(frames) < 2:
            return result

        # 1. 基本滚动链
        for i, frame in enumerate(frames):
            time_str = frame.get("time", f"帧{i+1}")
            data = frame.get("data", {})
            result["滚动链"].append({"帧": i+1, "时间": time_str, "摘要": str(data)[:80]})

        # 2. 四层穿插（如果启用）
        if four_layer_mode and len(frames) >= 3:
            # 用首帧做年家，中帧做月家，末帧做时家
            first = frames[0]
            last = frames[-1]

            # 提取年
            import re
            year_match = re.search(r'(\d{4})', str(first.get("time","")))
            month_match = re.search(r'\d{4}-(\d{2})', str(first.get("time","")))
            day_match = re.search(r'\d{4}-\d{2}-(\d{2})', str(last.get("time","")))
            hour_match = re.search(r'(\d{2}):', str(last.get("time","")))

            year = int(year_match.group(1)) if year_match else 2026
            month = int(month_match.group(1)) if month_match else 6
            day = int(day_match.group(1)) if day_match else 13
            hour = int(hour_match.group(1)) if hour_match else 12

            # 构建meta对象传递给calc_four_layer（引擎接口接受meta而非分量）
            class _MetaProxy:
                pass
            proxy = _MetaProxy()
            proxy.gregorian = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:00"
            tian_list = ['甲','乙','丙','丁','戊','己','庚','辛','壬','癸']
            day_gan = tian_list[(day + 3) % 10]
            shi_gan = tian_list[((hour + 1) // 2) % 10]
            proxy.ri_ganzhi = day_gan + '子'
            proxy.shi_ganzhi = shi_gan + '子'

            four_layer = self.calc_four_layer(proxy)
            result["四层穿插"] = four_layer

        # 3. 应期判断
        result["应期判"] = "多帧滚动→关键拐点帧为应期所在，结合前值符所在宫位出空或逢合之月日断"

        return result


# 五、独立入口（命令行测试）
# ═══════════════════════════════════════════════════════════════

def format_result(result: NineDimResult) -> str:
    """格式化输出推演结果"""
    lines = []
    lines.append("╔══════════════════════════════════════════╗")
    lines.append("║   九维立体奇门推演报告                  ║")
    lines.append("╚══════════════════════════════════════════╝")
    lines.append("")
    
    # 基础信息
    lines.append(f"📅 时空：{result.timespace.gregorian}")
    lines.append(f"   {result.timespace.dun_type}{result.timespace.ju_number}局")
    lines.append(f"   节气：{result.timespace.jieqi}")
    lines.append(f"   时柱：{result.timespace.shi_ganzhi}")
    lines.append("")
    
    # 九宫立体分布
    lines.append("📊 三维九宫分布：")
    for name, p in result.palaces_3d.items():
        occ_info = ", ".join([f"{o.binding_type}:{o.label}" for o in p.occupants]) or "空"
        lines.append(f"  {name}{p.number}宫 | 阴阳:{p.yin_yang} 权重:{p.weight} | {occ_info}")
    lines.append("")
    
    # 九维分项
    lines.append("🔮 九维分项推演：")
    for dim, analysis in result.nine_dim_analysis.items():
        meaning = analysis.get("meaning", "")
        lines.append(f"  [{dim}] {meaning}")
    lines.append("")
    
    # ── 格局分析（天盘vs地盘） ──
    if result.pattern_summary:
        # 筛选非伏吟的格局，去重
        seen = set()
        unique_patterns = []
        for p in result.pattern_summary:
            key = p.get("name", "")
            if key and key not in seen:
                seen.add(key)
                unique_patterns.append(p)
        lines.append("🔱 格局判定（天盘·地盘）：")
        for p in unique_patterns[:6]:
            lines.append(f"  {p.get('palace','')}宫 {p.get('tian_gan','')}{p.get('di_gan','')}→{p.get('name','')}（{p.get('nature','平')}）")
            lines.append(f"    ↳ {p.get('meaning','')}")
    
    # ── 星门旺衰 ──
    if result.star_status_summary:
        lines.append("\n⭐ 九星旺衰（<season>）：")
        # 只取前5个
        stats = result.star_status_summary.split(", ")[:5]
        for s in stats:
            lines.append(f"  · {s}")
    if result.gate_status_summary:
        lines.append("🚪 八门旺衰：")
        stats = result.gate_status_summary.split(", ")[:5]
        for s in stats:
            lines.append(f"  · {s}")
    
    # ── 门迫/反吟伏吟 ──
    if result.menpo_summary:
        lines.append("\n⚡ 门迫·宫迫检测：")
        for mp in result.menpo_summary[:3]:
            lines.append(f"  {mp.get('impact','')} {mp.get('gate','')}门→{mp.get('palace','')}宫（{mp.get('type','')}）")
    if result.fanyin_fuyin:
        for ff in result.fanyin_fuyin:
            lines.append(f"  🔄 {ff}")
    
    # ── 应期判定 ──
    if result.yingqi_summary:
        lines.append(f"\n⏱ 应期判定：{result.yingqi_summary}")
        if result.yingqi_detail:
            lines.append(f"   ↳ {result.yingqi_detail}")
    
    lines.append("")
    
    # 逻辑生克
    l_logic = result.nine_dim_analysis.get("L", {})
    relations = l_logic.get("relations", [])
    if relations:
        lines.append("🔗 生克关系：")
        for r in relations:
            lines.append(f"  · {r}")
    lines.append("")
    
    # 综合结论
    lines.append(f"🎯 整体判定：{result.overall_judgment}")
    lines.append(f"   ⽤神状态：{result.yongshen_status}")
    lines.append(f"   可信度：{result.confidence_score:.0%}")
    
    if result.core_profit_loss:
        lines.append(f"\n⚖️ 核心利弊：")
        for item in result.core_profit_loss:
            lines.append(f"  · {item}")
    
    if result.potential_variables:
        lines.append(f"\n⚠️ 潜在变数：")
        for v in result.potential_variables:
            lines.append(f"  · {v}")
    
    # 动态演变
    if result.dynamic_flow and result.dynamic_flow.yongshen_trace:
        lines.append(f"\n📈 动态演变轨迹：")
        for trace in result.dynamic_flow.yongshen_trace:
            lines.append(f"  Frame{trace['frame']}: {trace['yongshen']} → {trace['palace']}宫")
        lines.append(f"  趋势得分：{result.dynamic_flow.tendency_score}")
    
    lines.append("\n" + "─" * 45)
    return "\n".join(lines)


def main():
    """命令行入口"""
    import sys
    import datetime
    
    now = datetime.datetime.now()
    
    # 测试用例：求职问事
    engine = NineDimEngine()
    
    result = engine.deduce_3d(
        year=now.year, month=now.month, day=now.day, hour=now.hour,
        multi_dim_bind={
            "person": "问事人",
            "event": "求职面试",
            "object": "目标公司",
            "semantic": "积极期望略紧张"
        },
        spatial_hints={
            "person_zone": "震宫",
            "event_zone": "离宫",
            "object_zone": "乾宫"
        }
    )
    
    print(format_result(result))
    
    # 诊断输出
    print("\n\n📋 新增维度验证：")
    print(f"  格局数: {len(result.pattern_summary)}")
    print(f"  星旺衰: {bool(result.star_status_summary)}")
    print(f"  门迫数: {len(result.menpo_summary)}")
    print(f"  应期: {result.yingqi_summary}")
    print(f"  反吟伏吟: {result.fanyin_fuyin}")





if __name__ == "__main__":
    main()
