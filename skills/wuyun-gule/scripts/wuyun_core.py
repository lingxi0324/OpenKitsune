"""
五运六气核心计算引擎 (v2.0升级版)
==================================
新增：
- 主客气加临格局（顺化/同气/天刑/小逆/不和）
- 司天在泉间气分段
- 岁会/天符/同天符特殊格
- 迁正退位失常
"""

import json
from datetime import datetime, timedelta

# ─── 基础索引 ───
TIANGAN = "甲乙丙丁戊己庚辛壬癸"
DIZHI = "子丑寅卯辰巳午未申酉戌亥"

# 天干常规五行（用于日干判读）
TIANGAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火",
    "戊": "土", "己": "土", "庚": "金", "辛": "金",
    "壬": "水", "癸": "水",
}
# 五运：甲己土、乙庚金、丙辛水、丁壬木、戊癸火（用于岁运判读）
WUYUN_MAP = {"甲": "土", "乙": "金", "丙": "水", "丁": "木", "戊": "火",
              "己": "土", "庚": "金", "辛": "水", "壬": "木", "癸": "火"}

SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}
BEI_KE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}

# ─── 司天在泉（按年支定） ───
SITIAN_ZAIQUAN = {
    "子": ("少阴君火", "阳明燥金"),
    "午": ("少阴君火", "阳明燥金"),
    "丑": ("太阴湿土", "太阳寒水"),
    "未": ("太阴湿土", "太阳寒水"),
    "寅": ("少阳相火", "厥阴风木"),
    "申": ("少阳相火", "厥阴风木"),
    "卯": ("阳明燥金", "少阴君火"),
    "酉": ("阳明燥金", "少阴君火"),
    "辰": ("太阳寒水", "太阴湿土"),
    "戌": ("太阳寒水", "太阴湿土"),
    "巳": ("厥阴风木", "少阳相火"),
    "亥": ("厥阴风木", "少阳相火"),
}

LIUQI_WUXING = {
    "厥阴风木": "木", "少阴君火": "火", "少阳相火": "火",
    "太阴湿土": "土", "阳明燥金": "金", "太阳寒水": "水",
}

# ─── 六气分步（主气固定） ───
ZHUQI_STEPS = [
    ("厥阴风木", "大寒", "春分"),
    ("少阴君火", "春分", "小满"),
    ("少阳相火", "小满", "大暑"),
    ("太阴湿土", "大暑", "秋分"),
    ("阳明燥金", "秋分", "小雪"),
    ("太阳寒水", "小雪", "大寒"),
]

# ─── 节气近似日期（北半球） ───
JIEQI_DATES = {
    "大寒": (1, 20), "立春": (2, 4), "雨水": (2, 19),
    "惊蛰": (3, 6), "春分": (3, 21), "清明": (4, 5),
    "谷雨": (4, 20), "立夏": (5, 6), "小满": (5, 21),
    "芒种": (6, 6), "夏至": (6, 21), "小暑": (7, 7),
    "大暑": (7, 23), "立秋": (8, 7), "处暑": (8, 23),
    "白露": (9, 8), "秋分": (9, 23), "寒露": (10, 8),
    "霜降": (10, 23), "立冬": (11, 7), "小雪": (11, 22),
    "大雪": (12, 7), "冬至": (12, 22), "小寒": (1, 6),
}

# ─── 客气顺排规则 ───
# 客气顺排规则（修正版）
# 以司天为三之气（索引2），初之气=司天退2位，终之气=司天退2位+5=在泉
# 三阴三阳极数：厥阴(0) 少阴(1) 太阴(2) 少阳(3) 阳明(4) 太阳(5)
KEQI_ORDER = {
    # 少阴君火(1)司天：初=太阳(5), 二=厥阴(0), 三=少阴(少阴·司天), 四=太阴(2), 五=少阳(3), 终=阳明(4·在泉)
    "少阴君火": ["太阳寒水", "厥阴风木", "少阴君火", "太阴湿土", "少阳相火", "阳明燥金"],
    # 太阴湿土(2)司天：初=厥阴(0), 二=少阴(1), 三=太阴(太阴·司天), 四=少阳(3), 五=阳明(4), 终=太阳(5·在泉)
    "太阴湿土": ["厥阴风木", "少阴君火", "太阴湿土", "少阳相火", "阳明燥金", "太阳寒水"],
    # 少阳相火(3)司天：初=少阴(1), 二=太阴(2), 三=少阳(少阳·司天), 四=阳明(4), 五=太阳(5), 终=厥阴(0·在泉)
    "少阳相火": ["少阴君火", "太阴湿土", "少阳相火", "阳明燥金", "太阳寒水", "厥阴风木"],
    # 阳明燥金(4)司天：初=太阴(2), 二=少阳(3), 三=阳明(阳明·司天), 四=太阳(5), 五=厥阴(0), 终=少阴(1·在泉)
    "阳明燥金": ["太阴湿土", "少阳相火", "阳明燥金", "太阳寒水", "厥阴风木", "少阴君火"],
    # 太阳寒水(5)司天：初=少阳(3), 二=阳明(4), 三=太阳(太阳·司天), 四=厥阴(0), 五=少阴(1), 终=太阴(2·在泉)
    "太阳寒水": ["少阳相火", "阳明燥金", "太阳寒水", "厥阴风木", "少阴君火", "太阴湿土"],
    # 厥阴风木(0)司天：初=阳明(4), 二=太阳(5), 三=厥阴(厥阴·司天), 四=少阴(1), 五=太阴(2), 终=少阳(3·在泉)
    "厥阴风木": ["阳明燥金", "太阳寒水", "厥阴风木", "少阴君火", "太阴湿土", "少阳相火"],
}


def get_ganzhi_for_year(year: int) -> tuple:
    """获取年干支"""
    gan = TIANGAN[(year - 4) % 10]
    zhi = DIZHI[(year - 4) % 12]
    return gan, zhi


def get_day_ganzhi(base_gan: str, base_zhi: str, offset: int) -> tuple:
    """根据基准干支+偏移日计算目标干支"""
    gan_idx = TIANGAN.index(base_gan)
    zhi_idx = DIZHI.index(base_zhi)
    target_gan = TIANGAN[(gan_idx + offset) % 10]
    target_zhi = DIZHI[(zhi_idx + offset) % 12]
    return target_gan, target_zhi


def get_sitian_zaiquan(year_or_zhi) -> tuple:
    """获取司天、在泉之气（兼容整数年份和字符串地支）"""
    if isinstance(year_or_zhi, int):
        zhi = DIZHI[(year_or_zhi - 4) % 12]
    else:
        zhi = year_or_zhi
    return SITIAN_ZAIQUAN.get(zhi, ("", ""))


def get_keqi_sequence(sitian: str) -> list:
    """获取客气六步序列（司天为三之气）"""
    return KEQI_ORDER.get(sitian, [])


def get_zhuqi_step(month: int, day: int) -> int:
    """根据月日获取当前主气步骤（0-5）"""
    # 简化：按月大致定位
    if month in (1, 2):
        if month == 1 and day >= 20:
            return 0  # 初之气·厥阴风木
        elif month == 2 and day < 19:
            return 0
        elif month == 2 and day >= 19:
            return 1  # 二之气·少阴君火
        return 0
    elif month in (3, 4):
        if month == 3 and day >= 21:
            return 1
        elif month == 4:
            return 1 if day < 20 else 2
        return 0
    elif month in (5, 6, 7):
        if month == 5 and day >= 21:
            return 2  # 三之气·少阳相火
        elif month == 6 and day >= 21:
            return 2
        elif month == 7 and day >= 23:
            return 3  # 四之气·太阴湿土
        return 2
    elif month in (8, 9, 10):
        if month == 8:
            return 3
        elif month == 9 and day >= 23:
            return 4  # 五之气·阳明燥金
        elif month == 10 and day >= 23:
            return 5  # 终之气
        return 4 if month >= 9 else 3
    elif month in (11, 12):
        return 5  # 终之气
    return 0


def get_zhuqi_at_step(step: int) -> str:
    """获取第step步的主气"""
    if 0 <= step < len(ZHUQI_STEPS):
        return ZHUQI_STEPS[step][0]
    return ""


def get_keqi_at_step(keqi_seq: list, step: int) -> str:
    """获取第step步的客气"""
    if keqi_seq and 0 <= step < len(keqi_seq):
        return keqi_seq[step]
    return ""


def judge_pattern(zhuqi: str, keqi: str) -> str:
    """判定主客气加临格局"""
    z_wx = LIUQI_WUXING.get(zhuqi, "")
    k_wx = LIUQI_WUXING.get(keqi, "")
    if not z_wx or not k_wx:
        return "未知"
    if z_wx == k_wx:
        return "同气"
    if SHENG_CYCLE.get(k_wx) == z_wx:
        return "顺化"
    if KE_CYCLE.get(k_wx) == z_wx:
        return "天刑"
    if SHENG_CYCLE.get(z_wx) == k_wx:
        return "小逆"
    if KE_CYCLE.get(z_wx) == k_wx:
        return "不和"
    return "未知"


def get_jiangi(sitian: str, zaiquan: str) -> dict:
    """获取司天在泉四间气"""
    sitian_left = None
    sitian_right = None
    zaiquan_left = None
    zaiquan_right = None

    keqi_full = get_keqi_sequence(sitian)
    if len(keqi_full) >= 6:
        sitian_left = keqi_full[0]   # 初之气：司天左间
        sitian_right = keqi_full[1]  # 二之气：司天右间
        zaiquan_left = keqi_full[3]  # 四之气：在泉左间
        zaiquan_right = keqi_full[4] # 五之气：在泉右间

    return {
        "司天左间": sitian_left,
        "司天右间": sitian_right,
        "在泉左间": zaiquan_left,
        "在泉右间": zaiquan_right,
    }


def check_special_pattern(year_gan: str, year_zhi: str, sitian: str) -> dict:
    """
    检查特殊格局：岁会/天符/同天符/不和
    
    返回：{
        "name": "岁会" / "天符" / "同天符" / "不和" / "正常",
        "factor": 1.5 / 2.0 / 2.5 / 0.5 / 1.0,
    }
    """
    year_wx = WUYUN_MAP[year_gan]
    sitian_wx = LIUQI_WUXING.get(sitian, "")
    
    is_tai_guo = year_gan in "甲丙戊庚壬"
    year_zhi_wx = None
    for k, v in DIZHI_WUXING.items():
        if k == year_zhi:
            year_zhi_wx = v
            break
    
    # 岁会：岁运与年支同气
    if year_zhi_wx and year_wx == year_zhi_wx:
        return {"name": "岁会", "factor": 1.5}
    
    # 天符：岁运与司天同气
    if sitian_wx and year_wx == sitian_wx:
        return {"name": "天符", "factor": 2.0}
    
    # 同天符：岁运太过+司天同气
    if is_tai_guo and sitian_wx and year_wx == sitian_wx:
        return {"name": "同天符", "factor": 2.5}
    
    # 不和：岁运与司天相克
    if sitian_wx and KE_CYCLE.get(year_wx) == sitian_wx:
        return {"name": "不和", "factor": 0.5}
    
    return {"name": "正常", "factor": 1.0}


# 补充地支五行映射
DIZHI_WUXING = {"子": "水", "丑": "土", "寅": "木", "卯": "木",
                 "辰": "土", "巳": "火", "午": "火", "未": "土",
                 "申": "金", "酉": "金", "戌": "土", "亥": "水"}


def analyze_year(year: int) -> dict:
    """完整年度五运六气分析"""
    gan, zhi = get_ganzhi_for_year(year)
    year_wx = WUYUN_MAP[gan]
    is_tai_guo = gan in "甲丙戊庚壬"
    sitian, zaiquan = get_sitian_zaiquan(zhi)
    pattern = check_special_pattern(gan, zhi, sitian)
    jiangi = get_jiangi(sitian, zaiquan)
    
    # 六步逐气分析
    keqi_seq = get_keqi_sequence(sitian)
    steps = []
    for i in range(6):
        zhuqi = get_zhuqi_at_step(i)
        keqi = get_keqi_at_step(keqi_seq, i) if keqi_seq else ""
        p = judge_pattern(zhuqi, keqi)
        steps.append({
            "step": i + 1,
            "name": f"{['初','二','三','四','五','终'][i]}_气",
            "zhuqi": zhuqi,
            "keqi": keqi,
            "pattern": p,
        })
    
    return {
        "year": year,
        "gan": gan,
        "zhi": zhi,
        "wuxing": year_wx,
        "tai_guo": is_tai_guo,
        "sitian": sitian,
        "zaiquan": zaiquan,
        "jiangi": jiangi,
        "special_pattern": pattern,
        "steps": steps,
    }


if __name__ == "__main__":
    for year in [2024, 2025, 2026]:
        result = analyze_year(year)
        print(f"\n=== {year}年({result['gan']}{result['zhi']}) ===")
        print(f"  岁运: {result['wuxing']} ({'太过' if result['tai_guo'] else '不及'})")
        print(f"  司天: {result['sitian']}  在泉: {result['zaiquan']}")
        print(f"  特殊格局: {result['special_pattern']['name']} (系数×{result['special_pattern']['factor']})")
        for s in result['steps']:
            print(f"  {s['name']}: 主气{s['zhuqi']} vs 客气{s['keqi']} → {s['pattern']}")
