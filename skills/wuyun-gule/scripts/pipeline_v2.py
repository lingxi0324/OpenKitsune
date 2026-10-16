"""
四层全链路 · 路径B+C 完整推演器
=================================
路径B：胜复校正v3.1 + 资本行为 + 九宫奇门 + 四柱多维叠加
路径C：月度→周度精度（基于四柱干支的周内推演）

v3.7.0 → v3.7.1 核心升级：
  ① 评分引擎升级至 v3.1（主客气接口修复 + 相关系数翻正）
  ② 资本行为二阶段（介入+收割，基于历史评分深度）
  ③ 九宫奇门月级微调
  ④ 四柱的月度调制权重
  ⑤ 周度推演：基于月度评分 × 周干支差分
"""

import os, sys, json, math
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ===== 各模块导入 =====
from corrected_scoring import (
    batch_corrected_predict, PLATES, evaluate_corrected,
    correlation_analysis, compute_corrected_score,
)
from capital_integration import CapitalIntegration
from qimen_jiugong import QimenJiugongEngine, integrate_qimen_score
from wuyun_core import (
    get_ganzhi_for_year, get_sitian_zaiquan,
    LIUQI_WUXING, SHENG_CYCLE, KE_CYCLE,
)
from sizhu_predictor import (
    get_absolute_day_ganzhi, compute_day_pillar,
)

# 天干→五行
TIANGAN_WUXING_MAP = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火",
    "戊": "土", "己": "土", "庚": "金", "辛": "金",
    "壬": "水", "癸": "水",
}

# ===== 测试集 =====
def load_test_suite():
    path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_direction(value, threshold=0.03):
    if value > threshold:
        return 1
    elif value < -threshold:
        return -1
    return 0


# ═══════════════════════════════════════════════════════════════
# 路径B：四层全链路集成
# ═══════════════════════════════════════════════════════════════

def run_four_layer_integration(year: int = 2024) -> dict:
    """
    四层全链路推演：
    第一层：胜复校正v3.1 → 基础评分
    第二层：资本行为 → 介入/收割信号调制
    第三层：九宫奇门 → 月飞星能量聚焦
    第四层：四柱 → 日干支五行修正
    """
    results = {}

    # ─── 第一层：胜复校正评分 ───
    scores_raw = batch_corrected_predict(year)

    # ─── 第二层：资本行为 ───
    cap_int = CapitalIntegration(active_level=1.0, capital_weight=0.20)

    # ─── 第三层：九宫奇门 ───
    qimen = QimenJiugongEngine()

    # ─── 逐月集成 ───
    layer_results = []
    prev_history = {p: [] for p in PLATES}

    for row in scores_raw:
        month = row["month"]
        month_scores = {"month": month}
        signals = []

        for p in PLATES:
            raw = row[p]

            # L1 → L2: 资本行为调制
            modulated = cap_int.modulate_score(
                p, raw, year, month, prev_history.get(p, [])
            )
            l2_score = modulated[0] if isinstance(modulated, tuple) else modulated

            # L3: 九宫奇门月飞星
            month_qimen = qimen.get_full_monthly_assessment(year, month)
            qimen_adj = month_qimen["plate_scores"].get(p, 0.0)
            l3_score = l2_score + qimen_adj

            # L4: 四柱月度调制（年柱五行 + 月柱五行）
            gan1, zhi1 = get_ganzhi_for_year(year)  # 年干支
            # 月干支：近似取 甲己之年丙作首
            month_gz_branch_map = {
                1: "寅", 2: "卯", 3: "辰", 4: "巳",
                5: "午", 6: "未", 7: "申", 8: "酉",
                9: "戌", 10: "亥", 11: "子", 12: "丑",
            }
            # 月天干：甲己年丙寅起
            _month_gan_start = {"甲": "丙", "乙": "戊", "丙": "庚",
                                "丁": "壬", "戊": "甲", "己": "丙",
                                "庚": "戊", "辛": "庚", "壬": "壬",
                                "癸": "甲"}
            gan_start = _month_gan_start.get(gan1[0] if isinstance(gan1, str) else gan1, "丙")
            gan_order = "甲乙丙丁戊己庚辛壬癸"
            month_gan_idx = (gan_order.index(gan_start) + (month - 1)) % 10
            month_gan = gan_order[month_gan_idx]
            month_zhi = month_gz_branch_map.get(month, "子")

            # 月柱五行
            month_wx = TIANGAN_WUXING_MAP.get(month_gan, "")
            zhi_wx_map = {
                "寅": "木", "卯": "木", "辰": "土",
                "巳": "火", "午": "火", "未": "土",
                "申": "金", "酉": "金", "戌": "土",
                "亥": "水", "子": "水", "丑": "土",
            }
            month_zhi_wx = zhi_wx_map.get(month_zhi, "")

            # 四柱调制：月柱五行生克
            sizhu_mod = 0.0
            if month_wx:
                if SHENG_CYCLE.get(month_wx) == p:
                    sizhu_mod += 0.03
                elif KE_CYCLE.get(month_wx) == p:
                    sizhu_mod -= 0.03
            if month_zhi_wx:
                if SHENG_CYCLE.get(month_zhi_wx) == p:
                    sizhu_mod += 0.02
                elif KE_CYCLE.get(month_zhi_wx) == p:
                    sizhu_mod -= 0.02

            final_score = max(-1.0, min(1.0, l3_score + sizhu_mod))
            month_scores[p] = round(final_score, 4)

            # 更新历史
            prev_history[p].append(final_score)
            if len(prev_history[p]) > 6:
                prev_history[p].pop(0)

        layer_results.append(month_scores)

    return {"year": year, "months": layer_results}


def evaluate_four_layer(test_data: dict, predictions: list) -> dict:
    """评估四层框架 precision"""
    eval_by_plate = {p: {"correct": 0, "total": 0} for p in PLATES}
    all_correct = 0
    all_total = 0

    for pred_row in predictions:
        month = pred_row["month"]
        # 找测试集对应月
        for year_str, year_data in test_data.items():
            for m_entry in year_data.get("months", []):
                if m_entry["m"] == month:
                    for p in PLATES:
                        actual_val = m_entry.get(p, 0)
                        pred_val = pred_row.get(p, 0)
                        actual_dir = 1 if actual_val > 1 else (-1 if actual_val < -1 else 0)
                        pred_dir = get_direction(pred_val, 0.03)
                        if actual_dir != 0 and pred_dir != 0:
                            eval_by_plate[p]["total"] += 1
                            all_total += 1
                            if pred_dir == actual_dir:
                                eval_by_plate[p]["correct"] += 1
                                all_correct += 1
                    break

    return {
        "plate": {p: {"correct": v["correct"], "total": v["total"],
                       "rate": round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0}
                  for p, v in eval_by_plate.items()},
        "overall": {"correct": all_correct, "total": all_total,
                    "rate": round(all_correct / all_total, 3) if all_total > 0 else 0},
    }


# ═══════════════════════════════════════════════════════════════
# 路径C：周度推演器
# ═══════════════════════════════════════════════════════════════

DIZHI_WUXING_MAP = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木",
    "辰": "土", "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土", "亥": "水",
}

def compute_weekly_score(year: int, month: int, day: int,
                         monthly_scores: dict = None) -> dict:
    """
    周度/日度推演器：基于月度评分 × 日干支调制
    
    原理：
      月度评分给出该月的方向性势能（慢变量）
      日干支给出当天五行偏向（快变量）
      最终方向 = 月势能 × (1 + 日干支调制)
    """
    if monthly_scores is None:
        monthly_scores = batch_corrected_predict(year, [month])[0]
        for p in PLATES:
            monthly_scores[p] = monthly_scores.get(p, 0.0)

    # 获取日干支
    try:
        gz_str = get_absolute_day_ganzhi(year, month, day)
        day_gan = gz_str[0]
        day_zhi = gz_str[1]
    except Exception:
        day_gan = ""
        day_zhi = ""

    day_gan_wx = TIANGAN_WUXING_MAP.get(day_gan, "")
    day_zhi_wx = DIZHI_WUXING_MAP.get(day_zhi, "")

    weekly_scores = {}
    for p in PLATES:
        base = monthly_scores.get(p, 0.0)

        # 日干支调制：当天五行与板块五行的生克
        daily_mod = 0.0
        if day_gan_wx:
            if SHENG_CYCLE.get(day_gan_wx) == p:
                daily_mod += 0.05  # 天干生板块
            elif KE_CYCLE.get(day_gan_wx) == p:
                daily_mod -= 0.05  # 天干克板块
            elif SHENG_CYCLE.get(p) == day_gan_wx:
                daily_mod += 0.03  # 板块生天干（泄气但非压制）
        if day_zhi_wx:
            if SHENG_CYCLE.get(day_zhi_wx) == p:
                daily_mod += 0.04
            elif KE_CYCLE.get(day_zhi_wx) == p:
                daily_mod -= 0.04

        # 综合：月势能 × (1 + 日内日生克)
        weekly = base + daily_mod
        weekly_scores[p] = round(max(-1.0, min(1.0, weekly)), 4)

    return weekly_scores


def demo_weekly_for_2024(month: int = 9):
    """展示2024年某月的周度推演"""
    days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    max_day = days_in_month[month]

    monthly_scores = batch_corrected_predict(2024, [month])[0]

    print(f"\n{'=' * 70}")
    print(f"【路径C演示】2024年{month}月 · 周度推演")
    print(f"{'=' * 70}")
    print(f"{'日':>3} {'干支':>7}", end="")
    for p in PLATES:
        print(f"  {p:>4} ", end="")
    print()
    print("-" * 70)

    for day in range(1, max_day + 1, 3):  # 每3天采样
        try:
            gz_str = get_absolute_day_ganzhi(2024, month, day)
            day_gan = gz_str[0]
            day_zhi = gz_str[1]
            gz_str = f"{day_gan}{day_zhi}"
        except Exception:
            gz_str = "???"

        ws = compute_weekly_score(2024, month, day, monthly_scores)
        print(f"{day:>3} {gz_str:>7}", end="")
        for p in PLATES:
            v = ws[p]
            mark = "🟢" if v >= 0.1 else ("🔴" if v <= -0.1 else "○")
            print(f" {mark}{v:+.3f}", end="")
        print()


# ═══════════════════════════════════════════════════════════════
# 主运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_data = load_test_suite()

    print("=" * 70)
    print("〖路径B〗四层全链路 · 2024逐月逐板块")
    print("=" * 70)

    result = run_four_layer_integration(2024)
    months = result["months"]

    # 打印
    print(f"{'月':>3} ", end="")
    for p in PLATES:
        print(f"  {p:>4} ", end="")
    print()
    print("-" * 45)
    for row in months:
        print(f"{row['month']:>3} ", end="")
        for p in PLATES:
            v = row[p]
            mark = "🟢" if v >= 0.1 else ("🔴" if v <= -0.1 else "○")
            print(f" {mark}{v:+.3f}", end="")
        print()

    # 评估
    eval_result = evaluate_four_layer({"2024": test_data.get("2024", {})}, months)
    print(f"\n{'─' * 70}")
    print("四层集成 · 严格方向评估")
    print(f"  综合: {eval_result['overall']['correct']}/{eval_result['overall']['total']} = {eval_result['overall']['rate']:.1%}")
    for p in PLATES:
        pe = eval_result["plate"][p]
        if pe["total"] > 0:
            print(f"  {p}: {pe['correct']}/{pe['total']} = {pe['rate']:.1%}")

    # 路径C演示
    demo_weekly_for_2024(9)

    # 保存
    out_path = os.path.join(_SCRIPT_DIR, "..", "data", "four_layer_v31_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "version": "v3.7.1",
            "layers": ["胜复校正v3.1", "资本行为", "九宫奇门", "四柱"],
            "evaluation": eval_result,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
