"""
九宫奇门市场推演引擎 · QimenJiugongEngine v1.0
==============================================
核心公设：九宫飞星是天地气运在微观时空中的精确定位。
五运六气提供年度大势（宏观），九宫飞星提供月份/日期的能量聚焦点（微观）。

关键规则：
  一白(水)入中 → 水板块能量聚焦
  二黑(土)入中 → 土板块受病符影响，偏弱负向
  三碧(木)入中 → 木板块竞争加剧，偏动荡
  四绿(木)入中 → 木板块文昌，温和偏多
  五黄(土)入中 → 土板块大凶，绝对警戒
  六白(金)入中 → 金板块武曲，强势偏多
  七赤(金)入中 → 金板块破军，竞争激烈
  八白(土)入中 → 土板块当旺，最强偏多
  九紫(火)入中 → 火板块喜庆，高潮偏多

九星元素映射：
  1-水 | 2-土 | 3-木 | 4-木 | 5-土 | 6-金 | 7-金 | 8-土 | 9-火
"""

import math

# ─── 九星定义 ───
STAR_NAMES = {
    1: "一白贪狼", 2: "二黑巨门", 3: "三碧禄存",
    4: "四绿文曲", 5: "五黄廉贞", 6: "六白武曲",
    7: "七赤破军", 8: "八白左辅", 9: "九紫右弼",
}

STAR_ELEMENT = {
    1: "水", 2: "土", 3: "木", 4: "木", 5: "土",
    6: "金", 7: "金", 8: "土", 9: "火",
}

# 九星吉凶属性 (0=中性, 正=吉, 负=凶)
STAR_LUCK = {
    1: 0.8,   # 一白·水·吉（财星）
    2: -0.6,  # 二黑·土·凶（病符）
    3: -0.3,  # 三碧·木·凶（蚩尤）
    4: 0.5,   # 四绿·木·吉（文昌）
    5: -1.0,  # 五黄·土·大凶（正关）
    6: 0.7,   # 六白·金·吉（武曲）
    7: -0.4,  # 七赤·金·凶（破军）
    8: 1.0,   # 八白·土·大吉（当旺）
    9: 0.9,   # 九紫·火·吉（喜庆）
}

# 飞星月建（正月数 → 月飞星入中，基于子年寅月起一白）
# 口诀：子年寅起一白，丑年寅起九紫，寅年寅起八白...
# 年支阴→起例减，年支阳→起例加
# 简化：年支序数(i) → 正月入中 = ((12 - i) + 1) % 9 + 1... 
# 更简单：月飞星 = (年飞星入中 + 月份数 - 2) % 9 + 1
# 其中月份以寅月(≈2月)为起始

# 洛书九宫 → 五行映射（方位为本）
PALACE_ELEMENT = {
    "坎(北)": "水",   # 1
    "坤(西南)": "土",  # 2
    "震(东)": "木",   # 3
    "巽(东南)": "木",  # 4
    "中": "土",        # 5
    "乾(西北)": "金",  # 6
    "兑(西)": "金",   # 7
    "艮(东北)": "土",  # 8
    "离(南)": "火",   # 9
}

# 九宫数字 → 方位映射
PALACE_NUM_TO_DIR = {
    1: "坎(北)", 2: "坤(西南)", 3: "震(东)", 4: "巽(东南)",
    5: "中",
    6: "乾(西北)", 7: "兑(西)", 8: "艮(东北)", 9: "离(南)",
}

# ─── 五行生克 ───
SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}

# 各星对五行板块的正负影响（入中时的原始方向系数）
# 星入中 → 八宫飞临 → 各宫位得某星 → 宫位元素 × 星属性 = 板块影响
# 简化：直接按入中星计算全月基调
STAR_TO_PLATE_IMPACT = {
    1: {"水": 0.5, "火": -0.3, "木": 0.2, "金": 0.1, "土": -0.1},
    2: {"水": -0.4, "土": -0.5, "火": 0.1, "金": 0.1, "木": 0.2},
    3: {"木": 0.3, "土": -0.4, "金": -0.2, "水": 0.1, "火": 0.1},
    4: {"木": 0.4, "火": 0.2, "土": 0.1, "金": -0.1, "水": 0.05},
    5: {"土": -0.8, "水": -0.5, "火": -0.3, "木": -0.2, "金": -0.1},
    6: {"金": 0.5, "水": 0.3, "土": 0.2, "木": -0.2, "火": -0.3},
    7: {"金": 0.3, "火": -0.4, "木": -0.2, "水": 0.2, "土": 0.1},
    8: {"土": 0.7, "火": 0.4, "金": 0.3, "木": 0.1, "水": -0.1},
    9: {"火": 0.6, "木": 0.3, "土": 0.2, "金": -0.2, "水": -0.4},
}

PLATES = ["木", "火", "土", "金", "水"]


class QimenJiugongEngine:
    """九宫奇门推演引擎"""

    @staticmethod
    def get_year_flying_star(year: int) -> int:
        """
        计算年飞星入中（2000年后标准）
        公式：入中 = (2022 - year) % 9，0→9
        """
        ru_zhong = (2022 - year) % 9
        return 9 if ru_zhong == 0 else ru_zhong

    @staticmethod
    def get_month_flying_star(year: int, month: int) -> int:
        """
        计算月飞星入中（基于年飞星推算）
        每月飞星在年飞星基础上递减（月序从立春寅月起）
        
        简化算法：以寅月(≈2月)为月序1
        月飞星 = (年飞星入中 + 月序 - 2) % 9 + 1
        其中月序 = (month - 2) % 12 + 1（寅月=1, 卯月=2, ...）
        """
        # 月序：寅=1, 卯=2, 辰=3, 巳=4, 午=5, ...
        # 实际月份2月≈寅月
        yue_xu = (month - 2) % 12 + 1
        
        year_star = QimenJiugongEngine.get_year_flying_star(year)
        
        # 月飞星 = (年飞星 - 月序 + 9) % 9 + 1
        result = (year_star - yue_xu) % 9
        return 9 if result == 0 else result

    @staticmethod
    def get_star_plate_score(star: int, plate: str) -> float:
        """
        给定入中星和五行板块，返回该板块的月度飞星影响系数 (-1 ~ 1)
        """
        impact = STAR_TO_PLATE_IMPACT.get(star, {})
        return impact.get(plate, 0.0)

    @staticmethod
    def get_full_monthly_assessment(year: int, month: int) -> dict:
        """
        获取某年某月的完整九宫飞星评估
        
        返回：
        {
            "year_star": 年飞星编号,
            "year_star_name": 名称,
            "month_star": 月飞星编号,
            "month_star_name": 名称,
            "plate_scores": {
                "木": 0.3, "火": 0.5, "土": -0.2, "金": 0.0, "水": -0.3
            },
            "dominant_plate": "火" 或 None
        }
        """
        year_star = QimenJiugongEngine.get_year_flying_star(year)
        month_star = QimenJiugongEngine.get_month_flying_star(year, month)

        # 年+月叠加评分
        plate_scores = {}
        for plate in PLATES:
            year_score = QimenJiugongEngine.get_star_plate_score(year_star, plate)
            month_score = QimenJiugongEngine.get_star_plate_score(month_star, plate)
            # 年飞星权重0.3（年度基调），月飞星权重0.7（当月影响）
            plate_scores[plate] = year_score * 0.3 + month_score * 0.7

        # 找主导板块
        dominant = max(plate_scores, key=plate_scores.get)
        max_score = plate_scores[dominant]
        if max_score < 0.2:
            dominant = None

        return {
            "year_star": year_star,
            "year_star_name": STAR_NAMES[year_star],
            "month_star": month_star,
            "month_star_name": STAR_NAMES[month_star],
            "year_star_element": STAR_ELEMENT[year_star],
            "month_star_element": STAR_ELEMENT[month_star],
            "plate_scores": plate_scores,
            "dominant_plate": dominant,
        }

    @staticmethod
    def get_daily_qimen_adjustment(year: int, month: int, day: int) -> dict:
        """
        日奇门简化评估
        基于日干支纳音 + 日飞星（各日飞星入中 = (年入中 + 日序) % 9）
        
        返回：各板块的日级调整系数
        """
        # 粗略日序（当年第几天）
        days_in_month = [0, 31, 28, 31, 30, 31, 30,
                         31, 31, 30, 31, 30, 31]
        is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        if is_leap:
            days_in_month[2] = 29
        
        day_of_year = sum(days_in_month[:month]) + day
        
        year_star = QimenJiugongEngine.get_year_flying_star(year)
        
        # 日飞星 = (年飞星 + 日序) % 9
        day_star = (year_star + day_of_year) % 9
        day_star = 9 if day_star == 0 else day_star
        
        # 日级影响（月飞星权重0.6 + 日飞星权重0.4 的细化）
        month_star = QimenJiugongEngine.get_month_flying_star(year, month)
        month_scores = QimenJiugongEngine.get_star_plate_score_vector(month_star)
        day_scores = QimenJiugongEngine.get_star_plate_score_vector(day_star)
        
        adjustments = {}
        for plate in PLATES:
            adjustments[plate] = month_scores[plate] * 0.6 + day_scores[plate] * 0.4
        
        return {
            "day_star": day_star,
            "day_star_name": STAR_NAMES[day_star],
            "adjustments": adjustments,
        }

    @staticmethod
    def get_star_plate_score_vector(star: int) -> dict:
        """返回给定星的五行板块评分向量"""
        impact = STAR_TO_PLATE_IMPACT.get(star, {})
        return {p: impact.get(p, 0.0) for p in PLATES}

    @staticmethod
    def name(star: int) -> str:
        return STAR_NAMES.get(star, f"未知星({star})")


# ─── 便捷入口 ───
def integrate_qimen_score(
    wuyun_scores: dict,      # 四柱/胜复校正评分 {板块: 评分}
    year: int,
    month: int,
    day: int = None,
    qimen_weight: float = 0.15,
) -> dict:
    """
    将九宫奇门评分叠加到现有推演评分上
    
    参数：
        wuyun_scores: 现有评分 {板块: 数值}
        year, month, day: 年月日
        qimen_weight: 奇门权重（默认0.15，即15%）
    
    返回：
        final_scores: 叠加后评分
        qimen_assessment: 奇门评估详情
    """
    engine = QimenJiugongEngine()
    monthly = engine.get_full_monthly_assessment(year, month)

    final_scores = {}
    for plate in PLATES:
        wuyun = wuyun_scores.get(plate, 0.0)
        qimen = monthly["plate_scores"].get(plate, 0.0)
        if day is not None:
            daily = engine.get_daily_qimen_adjustment(year, month, day)
            qimen = qimen * 0.5 + daily["adjustments"][plate] * 0.5
        
        final_scores[plate] = wuyun * (1.0 - qimen_weight) + qimen * qimen_weight

    return {
        "final_scores": final_scores,
        "qimen_assessment": monthly,
    }


# ─── 自测 ───
if __name__ == "__main__":
    engine = QimenJiugongEngine()
    
    print("九宫奇门推演引擎 · 自测")
    print("=" * 50)
    
    for year in [2024, 2025, 2026]:
        ys = engine.get_year_flying_star(year)
        print(f"\n{year}年: 飞星入中={engine.name(ys)}（{STAR_ELEMENT[ys]}）")
        
        for month in [2, 4, 6, 8, 10, 12]:
            ms = engine.get_month_flying_star(year, month)
            assess = engine.get_full_monthly_assessment(year, month)
            scores = ", ".join([f"{p}{assess['plate_scores'][p]:+.2f}" for p in PLATES])
            print(f"  {year}年{month}月: 月飞星={engine.name(ms)} → {scores}")
