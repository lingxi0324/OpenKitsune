"""
五运六气 · 市场全链路推演主入口 (v2.0)
======================================
整合五层架构：
  运层 → 气层 → 特殊格局 → 日层 → 动态循环
"""

import os
import sys
import json
from datetime import datetime, timedelta

# 导入各模块 — 自动适应技能安装路径和直接运行路径
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import (
    analyze_year, get_ganzhi_for_year, get_day_ganzhi,
    get_sitian_zaiquan, judge_pattern,
)
from shengfu_yufa import (
    ShengfuYufaEngine, compute_market_correction,
    compute_wuyun_accumulation,
)
from three_layer_ganzhi_enhanced import evaluate_day

# ─── 五行偏差规则基础映射 ───
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}
BEI_KE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}

# ─── 行业→五行映射 ───
INDUSTRY_WUXING = {
    "木": ["新能源", "光伏", "锂电", "风电", "生物医药", "中药", "林业"],
    "火": ["AI", "芯片", "半导体", "算力", "传媒", "互联网", "通信", "软件"],
    "土": ["地产", "基建", "建材", "白酒", "食品", "农业"],
    "金": ["银行", "保险", "证券", "金融", "钢铁", "有色金属", "机械"],
    "水": ["公用事业", "能源", "运输", "物流", "水务", "环保"],
}


def judge_deviation(wuxing: str, actual_return: float, 
                     expected_return: float) -> str:
    """
    判定五行偏差类型
    
    参数：
        wuxing: 五行
        actual_return: 实际回报率（%）
        expected_return: 预期回报率（%）
    
    返回：偏高/太高/偏弱/太弱/正常
    """
    if expected_return == 0:
        return "正常"
    
    ratio = (actual_return - expected_return) / abs(expected_return)
    
    if ratio > 1.0:
        return "太高"
    elif ratio > 0.3:
        return "偏高"
    elif ratio < -1.0:
        return "太弱"
    elif ratio < -0.3:
        return "偏弱"
    else:
        return "正常"


def get_wuxing_for_stock(stock_name: str, stock_weights: dict = None) -> list:
    """
    获取个股的五行属性分布
    
    参数：
        stock_name: 股票名称
        stock_weights: 自定义权重字典 {五行: 权重}，None用默认
    
    返回：[("火", 0.85), ("金", 0.15), ...]
    """
    DEFAULT_WEIGHTS = {
        "寒武纪": {"火": 0.85, "金": 0.15},
        "宁德时代": {"木": 0.60, "火": 0.40},
        "贵州茅台": {"土": 0.70, "水": 0.30},
        "工商银行": {"金": 0.90, "土": 0.10},
        "长江电力": {"水": 0.80, "木": 0.20},
        "万科A": {"土": 0.90, "水": 0.10},
        "恒瑞医药": {"木": 0.70, "水": 0.30},
        "立讯精密": {"金": 0.55, "火": 0.45},
        "紫金矿业": {"金": 0.50, "土": 0.50},
        "分众传媒": {"火": 0.60, "木": 0.40},
    }
    
    if stock_weights:
        weights = stock_weights
    else:
        weights = DEFAULT_WEIGHTS.get(stock_name, {"火": 0.5, "土": 0.5})
    
    return sorted(weights.items(), key=lambda x: -x[1])


def compute_stock_daily(stock_name: str, day: str, 
                         year_analysis: dict = None) -> dict:
    """
    逐日个股推演（含完整五层叠加）
    
    参数：
        stock_name: 股票名称
        day: 日期 "YYYY-MM-DD"
        year_analysis: 年度分析结果（可选，自动计算）
    
    返回：完整判读
    """
    dt = datetime.strptime(day, "%Y-%m-%d")
    year = dt.year
    month = dt.month
    day_num = dt.day
    
    # 年干支
    gan, zhi = get_ganzhi_for_year(year)
    
    # 简化月干支（按年干+月序推算）
    # 甲己年：丙寅起，乙庚年：戊寅起，丙辛年：庚寅起
    # 丁壬年：壬寅起，戊癸年：甲寅起
    month_start = {
        ("甲", 1): "丙", ("己", 1): "丙",
        ("乙", 1): "戊", ("庚", 1): "戊",
        ("丙", 1): "庚", ("辛", 1): "庚",
        ("丁", 1): "壬", ("壬", 1): "壬",
        ("戊", 1): "甲", ("癸", 1): "甲",
    }
    
    # 月干支（简化：取当月中气为基准）
    month_gan_map = {"丙": 0, "丁": 1, "戊": 2, "己": 3, "庚": 4,
                      "辛": 5, "壬": 6, "癸": 7, "甲": 8, "乙": 9}
    month_zhi_map = {"寅": 0, "卯": 1, "辰": 2, "巳": 3, "午": 4,
                      "未": 5, "申": 6, "酉": 7, "戌": 8, "亥": 9, "子": 10, "丑": 11}
    
    base_month_gan = month_start.get((gan, 1), "丙")
    base_gan_idx = month_gan_map.get(base_month_gan, 0)
    month_gan_idx = (base_gan_idx + month - 1) % 10
    month_zhi_idx = (month - 1 + 2) % 12  # 寅=0 → 寅月=1月+2偏移
    
    month_gan = "甲乙丙丁戊己庚辛壬癸"[month_gan_idx]
    month_zhi = "寅卯辰巳午未申酉戌亥子丑"[month_zhi_idx]
    
    # 日干支（基准：已知的某个日期干支）
    # 2026-01-01 = 癸亥日
    base_day = datetime(2026, 1, 1)
    base_day_gan, base_day_zhi = "癸", "亥"
    offset = (dt - base_day).days
    day_gan, day_zhi = get_day_ganzhi(base_day_gan, base_day_zhi, offset)
    
    # 1. 年度分析
    if year_analysis is None:
        year_analysis = analyze_year(year)
    
    # 2. 日级判读（纳音+长生+藏干）
    daily = evaluate_day(day_gan, day_zhi, gan, zhi, month_gan, month_zhi)
    
    # 3. 胜复郁发
    engine = ShengfuYufaEngine()
    
    # 4. 个股五行权重
    weights = get_wuxing_for_stock(stock_name)
    
    # 5. 综合评分
    base_score = daily["score"]
    
    # 年度特殊格局修正
    spec = year_analysis.get("special_pattern", {})
    special_factor = spec.get("factor", 1.0)
    
    # 主客气格局修正（当月）
    steps = year_analysis.get("steps", [])
    step_idx = getattr(dt, 'timetuple')  # 简化
    month_step_map = {1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 2, 
                       7: 2, 8: 3, 9: 3, 10: 4, 11: 4, 12: 5}
    current_step = month_step_map.get(month, 0)
    pattern_info = steps[current_step] if current_step < len(steps) else {}
    pattern = pattern_info.get("pattern", "正常")
    pattern_correction = {
        "顺化": 1.2, "同气": 1.5, "小逆": 0.8,
        "不和": 0.7, "天刑": 0.6, "正常": 1.0, "未知": 1.0,
    }.get(pattern, 1.0)
    
    # 综合评分 = 基础分 × 特殊格局 × 主客气格局 × 五行偏差
    final_score = base_score * special_factor * pattern_correction
    
    # 五行偏差分析
    # 按个股主力五行权重，与年度气运比对
    main_wx = weights[0][0] if weights else "火"
    main_weight = weights[0][1] if weights else 0.5
    
    # 预期 = 年度基调下的行业预期
    year_wx = year_analysis.get("wuxing", "")
    year_trend = 1.0 if year_analysis.get("tai_guo", False) else 0.5
    
    # 简单的预期收益模型
    shengwu = SHENG.get(main_wx, "")
    kewu = KE.get(main_wx, "")
    
    if shengwu == year_wx:
        expected = 5.0  # 年运生板块
    elif kewu == year_wx:
        expected = 3.0  # 年运克板块（偏低）
    elif main_wx == year_wx:
        expected = 8.0  # 年运同气
    else:
        expected = 2.0  # 其他
    
    # 偏差判定（假设当天回报=评分映射）
    actual = base_score / 10.0 - 2.0  # 简化为日级映射
    deviation = judge_deviation(main_wx, actual, expected / 30)
    
    # 胜复郁发修正
    correction = compute_market_correction(
        main_wx, deviation, 0.3, engine
    )
    
    return {
        "date": day,
        "stock": stock_name,
        "daily_score": daily["score"],
        "daily_level": daily["level"],
        "final_score": round(final_score, 1),
        "pattern": pattern,
        "special_pattern": spec["name"],
        "deviation": deviation,
        "correction": correction,
        "factors": daily["factors"],
    }


def predict_month(stock_name: str, year: int, month: int) -> list:
    """全月逐日推演"""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    
    year_analysis = analyze_year(year)
    results = []
    
    for i in range((end - start).days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        result = compute_stock_daily(stock_name, day, year_analysis)
        results.append(result)
    
    return results


# ─── 主入口 ───
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="五运六气市场推演")
    parser.add_argument("--year", type=int, default=2026, help="年份")
    parser.add_argument("--stock", type=str, default="寒武纪", help="股票名称")
    parser.add_argument("--month", type=int, default=0, 
                       help="月份（0=全年推演）")
    parser.add_argument("--date", type=str, default="", help="日期 YYYY-MM-DD")
    args = parser.parse_args()
    
    if args.date:
        result = compute_stock_daily(args.stock, args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.month > 0:
        results = predict_month(args.stock, args.year, args.month)
        print(json.dumps(results[:5] + ["..."] + results[-5:], 
                         ensure_ascii=False, indent=2))
    else:
        ya = analyze_year(args.year)
        print(json.dumps(ya, ensure_ascii=False, indent=2))
