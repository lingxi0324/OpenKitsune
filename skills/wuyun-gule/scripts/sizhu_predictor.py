"""
四柱综合市场推演引擎 (v1.0)
===========================
年月日时感知叠加，如四柱八字综合计算。

四柱分层：
  年柱（权重0.35）：大运+司天在泉+特殊格局 → 全年宏观基调
  月柱（权重0.30）：主运客运+主气客气+胜复郁发 → 当前气运节奏
  日柱（权重0.20）：日干支+纳音+藏干+长生 → 日级触发窗口
  时柱（权重0.05）：时干支+子午流注 → 时辰精调

每一层输出一个五行向量 [木,火,土,金,水] (归一化0~1)，
最终按权重叠加，再与板块五行属性比较生克，输出方向评分。
"""

import os, sys, math
from datetime import datetime, timedelta

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import (
    TIANGAN, DIZHI, TIANGAN_WUXING, WUYUN_MAP,
    SHENG_CYCLE, KE_CYCLE, BEI_KE,
    SITIAN_ZAIQUAN, LIUQI_WUXING,
    ZHUQI_STEPS, KEQI_ORDER, JIEQI_DATES,
    get_ganzhi_for_year, get_day_ganzhi,
    get_sitian_zaiquan, judge_pattern,
    get_zhuqi_at_step, get_keqi_at_step,
)
from three_layer_ganzhi_enhanced import (
    TIANGAN_WUXING as TG_WX,
    DIZHI_WUXING as DZ_WX,
    CANG_GAN, CANG_GAN_WEIGHT,
    NAYIN_WUXING, CHANGSHENG_TABLE,
)
from shengfu_yufa import ShengfuYufaEngine, KEQI_COEFF

PLATES = ["木", "火", "土", "金", "水"]

# ─── 十二时辰映射 ───
SHICHEN_MAP = [
    ("子时", 23, 1), ("丑时", 1, 3), ("寅时", 3, 5),
    ("卯时", 5, 7), ("辰时", 7, 9), ("巳时", 9, 11),
    ("午时", 11, 13), ("未时", 13, 15), ("申时", 15, 17),
    ("酉时", 17, 19), ("戌时", 19, 21), ("亥时", 21, 23),
]
SHICHEN_DIZHI = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]

# ─── 日干支绝对日期计算 ───
# 基准：1900-01-01 = 甲戌日（天干索引=0, 地支索引=10）
REF_DATE = datetime(1900, 1, 1)
REF_TIANGAN_IDX = 0   # 甲
REF_DIZHI_IDX = 10    # 戌

def get_absolute_day_ganzhi(year: int, month: int, day: int) -> str:
    """根据公历日期返回日干支（6字：如'甲子'）"""
    dt = datetime(year, month, day)
    offset = (dt - REF_DATE).days
    gan_idx = (REF_TIANGAN_IDX + offset) % 10
    zhi_idx = (REF_DIZHI_IDX + offset) % 12
    return TIANGAN[gan_idx] + DIZHI[zhi_idx]

# ─── 子午流注经络开阖（时辰→经络五行） ───
ZIWU_LIUZHU = {
    "寅": ("肺经", "金"), "卯": ("大肠经", "金"),
    "辰": ("胃经", "土"), "巳": ("脾经", "土"),
    "午": ("心经", "火"), "未": ("小肠经", "火"),
    "申": ("膀胱经", "水"), "酉": ("肾经", "水"),
    "戌": ("心包经", "火"), "亥": ("三焦经", "火"),
    "子": ("胆经", "木"), "丑": ("肝经", "木"),
}

# ─── 时辰五行旺衰 ───
SHICHEN_WANGQI = {
    "寅": ("木", 0.8), "卯": ("木", 1.0),
    "巳": ("火", 0.8), "午": ("火", 1.0),
    "辰": ("土", 0.6), "戌": ("土", 0.6), "丑": ("土", 0.6), "未": ("土", 0.6),
    "申": ("金", 0.8), "酉": ("金", 1.0),
    "亥": ("水", 0.8), "子": ("水", 1.0),
}


def get_hour_ganzhi(day_ganzhi: str, hour: int) -> str:
    """
    根据日干和时辰求时干（五鼠遁）
    
    五鼠遁口诀：
    甲己还加甲，乙庚丙作初，丙辛从戊起，丁壬庚子居，戊癸何方发，壬子是真途
    """
    tiangan_idx = TIANGAN.index(day_ganzhi[0])
    day_tg = TIANGAN[tiangan_idx]
    
    # 确定子时的天干
    if day_tg in "甲乙己":
        zi_tg_map = {"甲": "甲", "乙": "乙", "己": "甲"}
        zi_tg = zi_tg_map[day_tg]
    elif day_tg in "丙庚":
        zi_tg = {"丙": "戊", "庚": "丙"}[day_tg]
    elif day_tg in "丁壬":
        zi_tg = {"丁": "庚", "壬": "壬"}[day_tg]
    elif day_tg in "戊癸":
        zi_tg = {"戊": "壬", "癸": "甲"}[day_tg]
    else:
        # fallback: 甲己→甲
        zi_tg = "甲"
    
    # 确定时辰地支索引
    if hour == 23:
        dz_idx = 0  # 子时开始
    elif hour < 23:
        dz_idx = (hour + 1) // 2 % 12
    
    shichen_dz = DIZHI[dz_idx]
    
    # 时干 = 子时天干顺推dz_idx位
    zi_idx = TIANGAN.index(zi_tg)
    shichen_tg = TIANGAN[(zi_idx + dz_idx) % 10]
    
    return shichen_tg + shichen_dz


def get_shichen_from_hour(hour: int) -> str:
    """根据小时数（0-23）返回时辰地支"""
    if hour == 23 or hour == 0:
        return "子"
    return DIZHI[(hour + 1) // 2 % 12]


def compute_year_pillar(year: int) -> dict:
    """
    年柱计算
    返回：{vector: {木:浮点, ...}, score: 浮点, details: str}
    """
    vector = {w: 0.0 for w in PLATES}
    details_list = []
    
    # 1. 大运之年
    ganzhi = get_ganzhi_for_year(year)
    tiangan = ganzhi[0]
    dizhi = ganzhi[1]
    
    dayun_wuxing = WUYUN_MAP.get(tiangan, "")
    if dayun_wuxing:
        vector[dayun_wuxing] += 0.30
        details_list.append(f"大运:{tiangan}→{dayun_wuxing}+0.30")
    
    # 2. 司天在泉
    sitian, zaiquan = get_sitian_zaiquan(year)
    st_wx = LIUQI_WUXING.get(sitian, "")
    zq_wx = LIUQI_WUXING.get(zaiquan, "")
    if st_wx:
        vector[st_wx] += 0.20
        details_list.append(f"司天:{sitian}→{st_wx}+0.20")
    if zq_wx:
        vector[zq_wx] += 0.10
        details_list.append(f"在泉:{zaiquan}→{zq_wx}+0.10")
    
    # 3. 岁会（年支与年干五行同）
    # 天干：甲己土、乙庚金、丙辛水、丁壬木、戊癸火
    # 地支：子丑寅卯辰巳午未申酉戌亥对应水土木木土火火土金金土水
    dz_wx = DZ_WX.get(dizhi, "")
    if dayun_wuxing and dz_wx and dayun_wuxing == dz_wx:
        vector[dayun_wuxing] += 0.15
        details_list.append(f"岁会:{dayun_wuxing}同气+0.15")
    
    # 4. 天符（岁运与司天同气）
    if dayun_wuxing and st_wx and dayun_wuxing == st_wx:
        vector[dayun_wuxing] += 0.20
        details_list.append(f"天符:{dayun_wuxing}同气+0.20")
    
    # 5. 同天符（天干与岁运同）
    # 年干所属的五行和岁运五行一致
    tg_wx = TG_WX.get(tiangan, "")
    if dayun_wuxing and tg_wx and dayun_wuxing == tg_wx:
        vector[tg_wx] += 0.10
        details_list.append(f"同天符:{tg_wx}+0.10")
    
    score = max(vector.values()) - min(vector.values())
    return {"vector": vector, "score": score, "details": ";".join(details_list)}


def compute_month_pillar(year: int, month: int) -> dict:
    """
    月柱计算
    返回：{vector: dict, score: float, details: str}
    """
    vector = {w: 0.0 for w in PLATES}
    details_list = []
    
    # 1. 主运（按节气分段）
    # 初运木(1.20~4.3) 二运火(4.3~6.16) 三运土(6.16~8.30) 四运金(8.30~11.11) 终运水(11.11~1.20)
    zhuyun = get_zhuyun_by_month(month)
    if zhuyun:
        vector[zhuyun] += 0.15
        details_list.append(f"主运:{zhuyun}+0.15")
    
    # 2. 客运（随岁运起算）
    tiangan = get_ganzhi_for_year(year)[0]
    dayun_wx = WUYUN_MAP.get(tiangan, "")
    keyun = get_keyun_by_month(month, dayun_wx)
    if keyun:
        vector[keyun] += 0.10
        details_list.append(f"客运:{keyun}+0.10")
    
    # 3. 客气加临格局
    keqi_seq = get_keqi_for_year(year)
    step = get_liuqi_step(year, month)
    zhuqi = get_zhuqi_at_step(step) if step >= 0 else ""
    keqi = get_keqi_at_step(keqi_seq, step) if keqi_seq and step >= 0 else ""
    
    if zhuqi and keqi:
        pattern = judge_pattern(zhuqi, keqi)
        coeff = KEQI_COEFF.get(pattern, 0)
        z_wx = LIUQI_WUXING.get(zhuqi, "")
        k_wx = LIUQI_WUXING.get(keqi, "")
        
        if k_wx:
            vector[k_wx] += coeff * 0.20
            details_list.append(f"客气{pattern}:{k_wx}+{coeff*0.20:.2f}")
        if z_wx:
            vector[z_wx] += 0.05
            details_list.append(f"主气:{z_wx}+0.05")
    
    # 4. 胜复郁发（动态循环）
    shengfu = ShengfuYufaEngine()
    # 模拟一个月的积累
    for w in PLATES:
        is_tai_guo = vector[w] > 0.30  # 超过阈值视为太过
        is_bu_ji = vector[w] < 0.05    # 低于阈值视为不及
        if is_tai_guo:
            shengfu.compute_tai_guo(w, days=15)
        elif is_bu_ji:
            shengfu.compute_bu_ji(w, days=15)
    
    # 胜复郁发对向量的修正
    for w in PLATES:
        acc = shengfu.accumulation.get(w, 0)
        if acc > 0.15:
            vector[w] += acc * 0.5
            details_list.append(f"郁发-{w}:+{acc*0.5:.2f}")
    
    score = max(vector.values()) - min(vector.values())
    return {"vector": vector, "score": score, "details": ";".join(details_list)}


def compute_day_pillar(date: datetime) -> dict:
    """
    日柱计算
    返回：{vector: dict, score: float, details: str}
    """
    vector = {w: 0.0 for w in PLATES}
    details_list = []
    
    # 1. 日干支基础
    day_ganzhi = get_absolute_day_ganzhi(date.year, date.month, date.day)
    tg = day_ganzhi[0]  # 天干
    dz = day_ganzhi[1]  # 地支
    
    tg_wx = TG_WX.get(tg, "")
    dz_wx = DZ_WX.get(dz, "")
    
    if tg_wx:
        vector[tg_wx] += 0.25
        details_list.append(f"日干{tg}→{tg_wx}+0.25")
    if dz_wx:
        vector[dz_wx] += 0.10
        details_list.append(f"日支{dz}→{dz_wx}+0.10")
    
    # 2. 纳音五行
    nayin_wx = NAYIN_WUXING.get(day_ganzhi, "")
    if nayin_wx:
        vector[nayin_wx] += 0.10
        details_list.append(f"纳音{day_ganzhi}→{nayin_wx}+0.10")
    
    # 3. 辰戌丑未藏干
    if dz in CANG_GAN:
        cang = CANG_GAN[dz]
        for level, wx in cang.items():
            weight = CANG_GAN_WEIGHT.get(level, 0)
            vector[wx] += weight * 0.10
            details_list.append(f"藏干{level}:{wx}+{weight*0.10:.2f}")
    
    # 4. 十二长生
    chs_key = (tg, dz)
    if chs_key in CHANGSHENG_TABLE:
        state = CHANGSHENG_TABLE[chs_key]
        chs_factor = {
            "长生": 0.15, "沐浴": 0.05, "冠带": 0.10,
            "临官": 0.20, "帝旺": 0.25, "衰": -0.05,
            "病": -0.10, "死": -0.15, "墓": -0.05,
            "绝": -0.20, "胎": 0.05, "养": 0.10,
        }.get(state, 0)
        if tg_wx:
            vector[tg_wx] += chs_factor
            details_list.append(f"长生{state}:{tg_wx}{chs_factor:+.2f}")
    
    # 5. 天干与地支关系（生克）
    if tg_wx and dz_wx:
        if SHENG_CYCLE.get(tg_wx) == dz_wx:
            # 天生地 → 正印，增强
            vector[tg_wx] += 0.08
            details_list.append(f"日干生支:{tg_wx}生{dz_wx}+0.08")
        elif SHENG_CYCLE.get(dz_wx) == tg_wx:
            # 地生天 → 食伤，减弱但有出路
            vector[dz_wx] += 0.05
            details_list.append(f"日支生干:{dz_wx}生{tg_wx}+0.05")
        elif KE_CYCLE.get(tg_wx) == dz_wx:
            # 天克地 → 自坐财，吉
            vector[tg_wx] += 0.10
            details_list.append(f"自坐财:{tg_wx}克{dz_wx}+0.10")
        elif KE_CYCLE.get(dz_wx) == tg_wx:
            # 地克天 → 自坐杀，凶
            vector[tg_wx] -= 0.10
            details_list.append(f"自坐杀:{dz_wx}克{tg_wx}-0.10")
    
    score = max(vector.values()) - min(vector.values())
    return {"vector": vector, "score": score, "details": ";".join(details_list)}


def compute_hour_pillar(date: datetime, hour: int) -> dict:
    """
    时柱计算（可选，默认用午时作为代表）
    返回：{vector: dict, score: float, details: str}
    """
    vector = {w: 0.0 for w in PLATES}
    details_list = []
    
    day_ganzhi = get_absolute_day_ganzhi(date.year, date.month, date.day)
    hour_ganzhi = get_hour_ganzhi(day_ganzhi, hour)
    shichen_dz = get_shichen_from_hour(hour)
    
    # 1. 时干支五行
    tg = hour_ganzhi[0]
    dz = shichen_dz
    tg_wx = TG_WX.get(tg, "")
    dz_wx = DZ_WX.get(dz, "")
    
    if tg_wx:
        vector[tg_wx] += 0.15
        details_list.append(f"时干{tg}→{tg_wx}+0.15")
    if dz_wx:
        vector[dz_wx] += 0.08
        details_list.append(f"时支{dz}→{dz_wx}+0.08")
    
    # 2. 子午流注经络开阖
    if shichen_dz in ZIWU_LIUZHU:
        meridian, mer_wx = ZIWU_LIUZHU[shichen_dz]
        vector[mer_wx] += 0.12
        details_list.append(f"流注{shichen_dz}:{meridian}({mer_wx})+0.12")
    
    # 3. 时辰旺衰
    if shichen_dz in SHICHEN_WANGQI:
        wq_wx, wq_factor = SHICHEN_WANGQI[shichen_dz]
        vector[wq_wx] += wq_factor * 0.08
        details_list.append(f"旺衰{shichen_dz}:{wq_wx}+{wq_factor*0.08:.2f}")
    
    score = max(vector.values()) - min(vector.values())
    return {"vector": vector, "score": score, "details": ";".join(details_list)}


# ─── 辅助函数 ───

def get_zhuyun_by_month(month: int) -> str:
    """根据月份返回主运五行"""
    if month in (1, 2, 3):
        return "木" if month >= 2 or (month == 1 and datetime.now().day >= 20) else "水"
        # 简化为：1月是终运水、2月后是初运木
    if month >= 2 and month <= 4:
        return "木"
    elif month >= 4 and month <= 6:
        return "火"
    elif month >= 6 and month <= 8:
        return "土"
    elif month >= 8 and month <= 10:
        return "金"
    else:
        return "水"


def get_keyun_by_month(month: int, dayun_wx: str) -> str:
    """根据月份和岁运返回客运五行"""
    # 客运以岁运为初运，顺排五步
    keyun_order = []
    for i in range(5):
        idx = PLATES.index(dayun_wx) if dayun_wx in PLATES else 0
        keyun_order.append(PLATES[(idx + i) % 5])
    
    if month <= 3:
        return keyun_order[0]
    elif month <= 5:
        return keyun_order[1]
    elif month <= 7:
        return keyun_order[2]
    elif month <= 10:
        return keyun_order[3]
    else:
        return keyun_order[4]


def get_keqi_for_year(year: int) -> list:
    """获取某年的客气六步序列"""
    _, dizhi = get_ganzhi_for_year(year)
    sitian_name, zaiquan_name = SITIAN_ZAIQUAN.get(dizhi, ("", ""))
    if sitian_name in KEQI_ORDER:
        return KEQI_ORDER[sitian_name]
    return []


def get_liuqi_step(year: int, month: int) -> int:
    """判断月份属于第几步六气（0-5）"""
    if month <= 2:
        return 0  # 初之气（大寒-春分）
    elif month in (3, 4):
        return 1  # 二之气
    elif month in (5, 6):
        return 2  # 三之气
    elif month in (7, 8):
        return 3  # 四之气
    elif month in (9, 10):
        return 4  # 五之气
    else:
        return 5  # 终之气


def compute_plate_score(
    plate_wuxing: str,
    pillars: dict,
    weights: dict = None
) -> float:
    """
    计算某板块/股票在这个四柱下的综合评分
    
    参数：
        plate_wuxing: 板块五行（如"火"）
        pillars: 四柱计算结果字典
        weights: 权重（默认年0.35,月0.30,日0.20,时柱0.15[含流注]）
    
    返回：
        score: -1~1，正向=看涨，负向=看跌
    """
    if weights is None:
        weights = {"year": 0.35, "month": 0.30, "day": 0.20, "hour": 0.15}
    
    total_score = 0.0
    
    for pillar_name, weight in weights.items():
        p = pillars.get(pillar_name, {})
        p_vector = p.get("vector", {})
        
        # 板块五行与四柱向量比较
        plate_val = p_vector.get(plate_wuxing, 0)
        max_val = max(p_vector.values()) if p_vector else 0
        min_val = min(p_vector.values()) if p_vector else 0
        
        # 如果板块五行是当前柱的强项 → 加分
        if plate_val >= max_val - 0.05:
            pillar_score = plate_val * 1.0
        elif plate_val <= min_val + 0.05:
            pillar_score = -plate_val * 0.5  # 弱势但有支撑
        else:
            pillar_score = plate_val * 0.3
        
        total_score += pillar_score * weight
    
    # 生克修正：板块五行 vs 四柱最强五行
    strongest = max(p_vector, key=p_vector.get) if p_vector else ""
    if strongest and plate_wuxing:
        if SHENG_CYCLE.get(strongest) == plate_wuxing:
            total_score += 0.10  # 生我
        elif SHENG_CYCLE.get(plate_wuxing) == strongest:
            total_score += 0.05  # 我生（泄气）
        elif KE_CYCLE.get(strongest) == plate_wuxing:
            total_score -= 0.15  # 克我
        elif KE_CYCLE.get(plate_wuxing) == strongest:
            total_score += 0.05  # 我克
    
    # 归一化到 -1 ~ 1
    return max(-1.0, min(1.0, total_score))


def full_predict(
    plate_wuxing: str,
    year: int, month: int, day: int, hour: int = 12,
    weights: dict = None
) -> dict:
    """
    四柱全链路预测
    """
    date = datetime(year, month, day)
    
    # 计算四柱
    year_pillar = compute_year_pillar(year)
    month_pillar = compute_month_pillar(year, month)
    day_pillar = compute_day_pillar(date)
    hour_pillar = compute_hour_pillar(date, hour)
    
    pillars = {
        "year": year_pillar,
        "month": month_pillar,
        "day": day_pillar,
        "hour": hour_pillar,
    }
    
    # 综合评分
    score = compute_plate_score(plate_wuxing, pillars, weights)
    
    # 判读
    if score >= 0.35:
        judgment = "强开"  # 强烈看涨
    elif score >= 0.10:
        judgment = "偏开"  # 温和看涨
    elif score >= -0.10:
        judgment = "震荡"  # 方向不明
    elif score >= -0.35:
        judgment = "偏闭"  # 温和看跌
    else:
        judgment = "强闭"  # 强烈看跌
    
    return {
        "plate_wuxing": plate_wuxing,
        "date": f"{year}-{month:02d}-{day:02d}",
        "score": round(score, 4),
        "judgment": judgment,
        "pillars": {
            "year": {"score": round(year_pillar["score"], 3), "vector": year_pillar["vector"], "details": year_pillar["details"]},
            "month": {"score": round(month_pillar["score"], 3), "vector": month_pillar["vector"], "details": month_pillar["details"]},
            "day": {"score": round(day_pillar["score"], 3), "vector": day_pillar["vector"], "details": day_pillar["details"]},
            "hour": {"score": round(hour_pillar["score"], 3), "vector": hour_pillar["vector"], "details": hour_pillar["details"]},
        }
    }


def batch_predict(
    plate_wuxing: str,
    year: int,
    months: list = None,
    weights: dict = None
) -> list:
    """批量预测某年各月"""
    if months is None:
        months = list(range(1, 13))
    
    results = []
    for m in months:
        # 取每月15日作为该月代表
        pred = full_predict(plate_wuxing, year, m, 15, hour=12, weights=weights)
        results.append(pred)
    
    return results


# ─── 用于回测的简化接口 ───

def compute_sizhu_score(plate_wuxing: str, year: int, month: int, weights: dict = None) -> float:
    """简化接口：只有年月（用于月度精度回测）"""
    if weights is None:
        weights = {"year": 0.50, "month": 0.35, "day": 0.10, "hour": 0.05}
    
    date = datetime(year, month, 15)
    
    year_pillar = compute_year_pillar(year)
    month_pillar = compute_month_pillar(year, month)
    day_pillar = compute_day_pillar(date)
    hour_pillar = compute_hour_pillar(date, 12)
    
    pillars = {
        "year": year_pillar,
        "month": month_pillar,
        "day": day_pillar,
        "hour": hour_pillar,
    }
    
    return compute_plate_score(plate_wuxing, pillars, weights)


def predict_month(plate_wuxing: str, year: int, month: int) -> dict:
    """月度方向预测"""
    score = compute_sizhu_score(plate_wuxing, year, month)
    
    if score >= 0.30:
        direction = "涨"
    elif score >= 0.05:
        direction = "微涨"
    elif score >= -0.05:
        direction = "震荡"
    elif score >= -0.30:
        direction = "微跌"
    else:
        direction = "跌"
    
    return {"direction": direction, "score": round(score, 3)}


if __name__ == "__main__":
    import json
    
    print("=" * 60)
    print("四柱综合市场推演引擎 · 快速测试")
    print("=" * 60)
    
    test_year = 2026
    test_month = 6
    
    # 逐板块测试
    for plate in PLATES:
        print(f"\n{'─'*40}")
        print(f"板块: {plate}")
        for m in [5, 6, 7, 8, 9]:
            pred = predict_month(plate, 2026, m)
            print(f"  2026年{m:02d}月: {pred['direction']} (score={pred['score']})")
    
    # 详细输出一个例子
    print(f"\n{'='*60}")
    print("2026年6月·火板块详细四柱拆解:")
    detail = full_predict("火", 2026, 6, 15)
    print(json.dumps(detail, indent=2, ensure_ascii=False))
