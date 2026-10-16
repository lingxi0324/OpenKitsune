"""
三层干支日级判读 · 增强版 (v2.0)
=================================
新增：纳音五行 + 十二长生 + 辰戌丑未藏干
"""

# ─── 天干地支五行 ───
TIANGAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火",
    "戊": "土", "己": "土", "庚": "金", "辛": "金",
    "壬": "水", "癸": "水",
}
DIZHI_WUXING = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木",
    "辰": "土", "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土", "亥": "水",
}
SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}

# ─── 辰戌丑未藏干（本气60%，余气25%，墓气15%） ───
CANG_GAN = {
    "辰": {"本气": "土", "余气": "水", "墓气": "木"},
    "戌": {"本气": "土", "余气": "金", "墓气": "火"},
    "丑": {"本气": "土", "余气": "水", "墓气": "金"},
    "未": {"本气": "土", "余气": "火", "墓气": "木"},
}
CANG_GAN_WEIGHT = {"本气": 0.6, "余气": 0.25, "墓气": 0.15}

# ─── 纳音五行表（关键部分） ───
NAYIN_WUXING = {
    "甲子": "金", "乙丑": "金", "丙寅": "火", "丁卯": "火",
    "戊辰": "木", "己巳": "木", "庚午": "土", "辛未": "土",
    "壬申": "金", "癸酉": "金", "甲戌": "火", "乙亥": "火",
    "丙子": "水", "丁丑": "水", "戊寅": "土", "己卯": "土",
    "庚辰": "金", "辛巳": "金", "壬午": "木", "癸未": "木",
    "甲申": "水", "乙酉": "水", "丙戌": "土", "丁亥": "土",
    "戊子": "火", "己丑": "火", "庚寅": "木", "辛卯": "木",
    "壬辰": "水", "癸巳": "水", "甲午": "金", "乙未": "金",
    "丙申": "火", "丁酉": "火", "戊戌": "木", "己亥": "木",
    "庚子": "土", "辛丑": "土", "壬寅": "金", "癸卯": "金",
    "甲辰": "火", "乙巳": "火", "丙午": "水", "丁未": "水",
    "戊申": "土", "己酉": "土", "庚戌": "金", "辛亥": "金",
    "壬子": "木", "癸丑": "木", "甲寅": "水", "乙卯": "水",
    "丙辰": "土", "丁巳": "土", "戊午": "火", "己未": "火",
    "庚申": "木", "辛酉": "木", "壬戌": "水", "癸亥": "水",
}

# ─── 十二长生状态 ───
CHANGSHENG_TABLE = {
    ("甲", "寅"): "临官", ("甲", "卯"): "帝旺",
    ("甲", "辰"): "衰", ("甲", "巳"): "病", ("甲", "午"): "死",
    ("甲", "未"): "墓", ("甲", "申"): "绝", ("甲", "酉"): "胎",
    ("甲", "戌"): "养", ("甲", "亥"): "长生", ("甲", "子"): "沐浴",
    ("甲", "丑"): "冠带",
    
    ("丙", "寅"): "长生", ("丙", "卯"): "沐浴", ("丙", "辰"): "冠带",
    ("丙", "巳"): "临官", ("丙", "午"): "帝旺", ("丙", "未"): "衰",
    ("丙", "申"): "病", ("丙", "酉"): "死", ("丙", "戌"): "墓",
    ("丙", "亥"): "绝", ("丙", "子"): "胎", ("丙", "丑"): "养",
    
    ("戊", "寅"): "长生", ("戊", "卯"): "沐浴", ("戊", "辰"): "冠带",
    ("戊", "巳"): "临官", ("戊", "午"): "帝旺", ("戊", "未"): "衰",
    ("戊", "申"): "病", ("戊", "酉"): "死", ("戊", "戌"): "墓",
    ("戊", "亥"): "绝", ("戊", "子"): "胎", ("戊", "丑"): "养",
    
    ("庚", "巳"): "长生", ("庚", "午"): "沐浴", ("庚", "未"): "冠带",
    ("庚", "申"): "临官", ("庚", "酉"): "帝旺", ("庚", "戌"): "衰",
    ("庚", "亥"): "病", ("庚", "子"): "死", ("庚", "丑"): "墓",
    ("庚", "寅"): "绝", ("庚", "卯"): "胎", ("庚", "辰"): "养",
    
    ("壬", "申"): "长生", ("壬", "酉"): "沐浴", ("壬", "戌"): "冠带",
    ("壬", "亥"): "临官", ("壬", "子"): "帝旺", ("壬", "丑"): "衰",
    ("壬", "寅"): "病", ("壬", "卯"): "死", ("壬", "辰"): "墓",
    ("壬", "巳"): "绝", ("壬", "午"): "胎", ("壬", "未"): "养",
    
    ("乙", "午"): "长生", ("乙", "未"): "沐浴", ("乙", "申"): "冠带",
    ("乙", "酉"): "临官", ("乙", "戌"): "帝旺", ("乙", "亥"): "衰",
    ("乙", "子"): "病", ("乙", "丑"): "死", ("乙", "寅"): "墓",
    ("乙", "卯"): "绝", ("乙", "辰"): "胎", ("乙", "巳"): "养",
    
    ("丁", "酉"): "长生", ("丁", "戌"): "沐浴", ("丁", "亥"): "冠带",
    ("丁", "子"): "临官", ("丁", "丑"): "帝旺", ("丁", "寅"): "衰",
    ("丁", "卯"): "病", ("丁", "辰"): "死", ("丁", "巳"): "墓",
    ("丁", "午"): "绝", ("丁", "未"): "胎", ("丁", "申"): "养",
    
    ("己", "酉"): "长生", ("己", "戌"): "沐浴", ("己", "亥"): "冠带",
    ("己", "子"): "临官", ("己", "丑"): "帝旺", ("己", "寅"): "衰",
    ("己", "卯"): "病", ("己", "辰"): "死", ("己", "巳"): "墓",
    ("己", "午"): "绝", ("己", "未"): "胎", ("己", "申"): "养",
    
    ("辛", "子"): "长生", ("辛", "丑"): "沐浴", ("辛", "寅"): "冠带",
    ("辛", "卯"): "临官", ("辛", "辰"): "帝旺", ("辛", "巳"): "衰",
    ("辛", "午"): "病", ("辛", "未"): "死", ("辛", "申"): "墓",
    ("辛", "酉"): "绝", ("辛", "戌"): "胎", ("辛", "亥"): "养",
    
    ("癸", "卯"): "长生", ("癸", "辰"): "沐浴", ("癸", "巳"): "冠带",
    ("癸", "午"): "临官", ("癸", "未"): "帝旺", ("癸", "申"): "衰",
    ("癸", "酉"): "病", ("癸", "戌"): "死", ("癸", "亥"): "墓",
    ("癸", "子"): "绝", ("癸", "丑"): "胎", ("癸", "寅"): "养",
}

CHANGSHENG_FACTOR = {
    "长生": 1.2, "沐浴": 1.1, "冠带": 1.15, "临官": 1.2,
    "帝旺": 1.5, "衰": 0.8, "病": 0.8, "死": 0.5,
    "墓": 0.5, "绝": 0.5, "胎": 0.7, "养": 0.7,
}


def get_nayin(gan: str, zhi: str) -> str:
    """获取纳音五行"""
    key = gan + zhi
    return NAYIN_WUXING.get(key, "")


def get_nayin_correction(nayin_wx: str, zheng_wx: str) -> float:
    """
    纳音对正五行的修正系数
    
    - 纳音生正五行 → 加持+0.2
    - 纳音克正五行 → 对冲-0.3
    - 正五行生纳音 → 泄气-0.1
    - 正五行克纳音 → 压制-0.15
    - 同气 → 0
    """
    if not nayin_wx or not zheng_wx:
        return 0
    if nayin_wx == zheng_wx:
        return 0
    if SHENG_CYCLE.get(nayin_wx) == zheng_wx:
        return 0.2  # 纳音生正五行
    if KE_CYCLE.get(nayin_wx) == zheng_wx:
        return -0.3  # 纳音克正五行
    if SHENG_CYCLE.get(zheng_wx) == nayin_wx:
        return -0.1  # 正五行生纳音
    if KE_CYCLE.get(zheng_wx) == nayin_wx:
        return -0.15  # 正五行克纳音
    return 0


def get_changsheng(gan: str, zhi: str) -> str:
    """获取天干在地支的十二长生状态"""
    return CHANGSHENG_TABLE.get((gan, zhi), "")


def get_changsheng_factor(gan: str, zhi: str) -> float:
    """获取长生力量系数"""
    state = get_changsheng(gan, zhi)
    return CHANGSHENG_FACTOR.get(state, 1.0)


def get_canggan_correction(zhi: str, target_wx: str) -> float:
    """
    辰戌丑未藏干修正
    
    返回藏干对目标五行的制衡系数
    """
    if zhi not in CANG_GAN:
        return 0
    cang = CANG_GAN[zhi]
    correction = 0
    for layer, wx in cang.items():
        weight = CANG_GAN_WEIGHT[layer]
        if wx == target_wx:
            correction += weight * 0.3  # 同气加持
        elif KE_CYCLE.get(wx) == target_wx:
            correction -= weight * 0.2  # 藏干克目标
        elif SHENG_CYCLE.get(wx) == target_wx:
            correction += weight * 0.15  # 藏干生目标
    return correction


def evaluate_day(gan: str, zhi: str, 
                 year_gan: str = "", year_zhi: str = "",
                 month_gan: str = "", month_zhi: str = "") -> dict:
    """
    完整日级判读（含纳音+长生+藏干）
    
    返回：{
        "score": 0-100,
        "level": "强开穴/偏开穴/震荡偏强/震荡偏弱/偏闭穴/强闭穴",
        "factors": {...}
    }
    """
    day_wx = TIANGAN_WUXING.get(gan, "")
    day_zhi_wx = DIZHI_WUXING.get(zhi, "")
    
    score = 50  # 基础分
    factors = {}

    # 1. 三层干支基础分
    # 年层
    if year_gan:
        yr_wx = TIANGAN_WUXING.get(year_gan, "")
        if yr_wx:
            if SHENG_CYCLE.get(yr_wx) == day_wx:
                score += 15  # 年生日
                factors["年干生日"] = 15
            elif KE_CYCLE.get(yr_wx) == day_wx:
                score -= 10  # 年克日
                factors["年干克日"] = -10
            elif yr_wx == day_wx:
                score += 5  # 年日同气
                factors["年日同气"] = 5
    
    # 月层
    if month_gan:
        mr_wx = TIANGAN_WUXING.get(month_gan, "")
        if mr_wx:
            if SHENG_CYCLE.get(mr_wx) == day_wx:
                score += 15
                factors["月干生日"] = 15
            elif mr_wx == day_wx:
                score += 10  # 月日比和
                factors["月日比和"] = 10
            elif KE_CYCLE.get(mr_wx) == day_wx:
                score -= 10
                factors["月干克日"] = -10

    # 日坐
    if day_zhi_wx:
        if SHENG_CYCLE.get(day_zhi_wx) == day_wx:
            score += 10  # 日坐生
            factors["日坐生"] = 10
        elif KE_CYCLE.get(day_zhi_wx) == day_wx:
            score -= 15  # 日坐杀
            factors["日坐七杀"] = -15
        elif day_zhi_wx == day_wx:
            score += 10  # 日坐旺
            factors["日坐旺"] = 10

    # 2. 纳音修正
    nayin_wx = get_nayin(gan, zhi)
    if nayin_wx:
        nc = get_nayin_correction(nayin_wx, day_wx)
        score += nc * 10
        factors[f"纳音{nayin_wx}"] = round(nc * 10, 1)

    # 3. 十二长生修正
    cs_factor = get_changsheng_factor(gan, zhi)
    cs_state = get_changsheng(gan, zhi)
    if cs_factor != 1.0:
        add = (cs_factor - 1.0) * 20
        score += add
        factors[f"长生({cs_state})"] = round(add, 1)

    # 4. 辰戌丑未藏干修正
    cg = get_canggan_correction(zhi, day_wx)
    if cg != 0:
        add = cg * 15
        score += add
        factors[f"藏干修正"] = round(add, 1)

    # 5. 分级
    score = max(0, min(100, score))
    
    if score >= 80:
        level = "强开穴"
    elif score >= 60:
        level = "偏开穴"
    elif score >= 40:
        level = "震荡偏强"
    elif score >= 20:
        level = "震荡偏弱"
    elif score >= 10:
        level = "偏闭穴"
    else:
        level = "强闭穴"

    return {"score": round(score, 1), "level": level, "factors": factors}


# ─── 快速测试 ───
if __name__ == "__main__":
    # 2026年6月19日：丙午年 甲午月 庚午日
    # 年：丙午（火火） 月：甲午（木火） 日：庚午（金火）
    result = evaluate_day(
        gan="庚", zhi="午",
        year_gan="丙", year_zhi="午",
        month_gan="甲", month_zhi="午",
    )
    print(f"2026.06.19 (庚午日) 判读:")
    print(f"  评分: {result['score']}")
    print(f"  等级: {result['level']}")
    print(f"  因子: {result['factors']}")
    
    # 对比2024年9月24日（关键爆发日）：甲辰年 癸酉月 丁巳日
    result2 = evaluate_day(
        gan="丁", zhi="巳",
        year_gan="甲", year_zhi="辰",
        month_gan="癸", month_zhi="酉",
    )
    print(f"\n2024.09.24 (丁巳日) 判读:")
    print(f"  评分: {result2['score']}")
    print(f"  等级: {result2['level']}")
    print(f"  因子: {result2['factors']}")
