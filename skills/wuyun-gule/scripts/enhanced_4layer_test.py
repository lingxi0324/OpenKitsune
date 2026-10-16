"""
四层框架 v3.7.0 · 增强集成测试
================================
关键改进：
1. 资本行为改为独立加法信号（非乘性调制）
2. 九宫奇门权重从0.15提升至0.25（独立信号）
3. 加入qimen-only消融实验（单独看qimen的方向判读力）
4. 输出各层评分的详细分布，理解72.7%天花板的原因
"""

import os, sys, json
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from corrected_scoring import batch_corrected_predict, PLATES, evaluate_corrected
from diagnose import load_test_suite
from qimen_jiugong import QimenJiugongEngine, integrate_qimen_score

# ─── 方向判定 ───
def get_dir(val, thresh=0.03):
    if val > thresh: return 1
    if val < -thresh: return -1
    return 0

def get_actual_dir(val):
    if val > 3: return 1
    if val < -3: return -1
    return 0

# ─── 资本行为独立信号（加法模式） ───
def capital_independent_signal(scores_by_month, year=2024):
    """资本行为独立信号：基于历史评分连涨/连跌趋势，输出独立方向信号"""
    signals = []
    for i, scores in enumerate(scores_by_month):
        plate_signal = {}
        for p in PLATES:
            # 看前3个月的趋势来决定资本信号
            if i < 3:
                plate_signal[p] = 0.0
                continue
            recent = [scores_by_month[j][p] for j in range(i-3, i)]
            n_up = sum(1 for s in recent if s > 0)
            n_down = sum(1 for s in recent if s < 0)
            
            raw = scores[p]
            if n_up >= 3 and raw > 0.1:
                plate_signal[p] = -0.4  # 连涨3月→收割信号
            elif n_down >= 3 and raw < -0.1:
                plate_signal[p] = 0.4   # 连跌3月→抄底信号
            elif n_up >= 2 and raw > 0:
                plate_signal[p] = -0.2  # 趋势偏涨→轻度收割
            elif n_down >= 2 and raw < 0:
                plate_signal[p] = 0.2   # 趋势偏跌→轻度抄底
            else:
                plate_signal[p] = 0.0
        signals.append(plate_signal)
    return signals

# ─── 独立加强版四层集成 ───
def run_enhanced_test(test_data):
    """独立信号加法集成：胜复0.60 + 资本独立0.20 + 奇门独立0.20"""
    results = batch_corrected_predict(2024)
    scores_baseline = [{p: row[p] for p in PLATES} for row in results]
    
    # 资本独立信号
    cap_signals = capital_independent_signal(scores_baseline)
    
    # 奇门独立信号
    qimen_assessments = []
    for i, row in enumerate(results):
        m = row["month"]
        eng = QimenJiugongEngine()
        monthly = eng.get_full_monthly_assessment(2024, m)
        qimen_assessments.append(monthly["plate_scores"])
    
    # 三层合并叠加
    WEIGHT_WUYUN = 0.60
    WEIGHT_CAPITAL = 0.20
    WEIGHT_QIMEN = 0.20
    
    final_scores = []
    for i in range(len(scores_baseline)):
        combined = {}
        for p in PLATES:
            w = scores_baseline[i][p]
            c = cap_signals[i][p]
            q = qimen_assessments[i][p]
            combined[p] = w * WEIGHT_WUYUN + c * WEIGHT_CAPITAL + q * WEIGHT_QIMEN
        final_scores.append(combined)
    
    # 输出评分分布
    print("\n📊 各层评分分布对比：")
    print(f"{'月份':>4} |{'板块':>4}| {'胜复':>8}| {'资本':>8}| {'奇门':>8}| {'最终':>8}| {'实际%':>8}| {'判读':>6}")
    print("-" * 80)
    
    months_data = test_data["2024"]["months"]
    correct, total = 0, 0
    
    for i in range(min(len(scores_baseline), len(months_data))):
        m = months_data[i]["m"]
        for p in PLATES:
            actual_val = months_data[i].get(p, 0)
            w = scores_baseline[i][p]
            c = cap_signals[i][p]
            q = qimen_assessments[i][p]
            f = final_scores[i][p]
            
            actual_dir = get_actual_dir(actual_val)
            pred_dir = get_dir(f)
            
            if actual_dir != 0:
                total += 1
                if pred_dir == actual_dir:
                    correct += 1
                    # 只在关键转换月打印
                    if abs(w) < 0.15 or abs(c) > 0.2:
                        mark = "✅" if pred_dir == actual_dir else "❌"
                        print(f"{m:>4} |{p:>4}| {w:>+8.4f}| {c:>+8.4f}| {q:>+8.4f}| {f:>+8.4f}| {actual_val:>+8.2f}| {mark:>6}")
    
    # 只在有方向变化的月份打印
    print("\n📊 方向翻转案例（资本或奇门改变判读方向）：")
    flipped = 0
    for i in range(min(len(scores_baseline), len(months_data))):
        for p in PLATES:
            w = scores_baseline[i][p]
            f = final_scores[i][p]
            w_dir = get_dir(w)
            f_dir = get_dir(f)
            if w_dir != f_dir and w_dir != 0:
                flipped += 1
                print(f"  月份{i+1}·{p}: 胜复{w_dir} → 最终{f_dir} (w={w:+.4f}, f={f:+.4f})")
    print(f"  方向翻转总数: {flipped}")
    
    rate = correct / total if total > 0 else 0
    return rate, correct, total


# ─── Qimen-only 消融实验 ───
def run_qimen_only_test(test_data):
    """纯九宫奇门判读（不加任何其他层），看它自己的方向判读力"""
    predictions = []
    months_data = test_data["2024"]["months"]
    
    for entry in months_data:
        m = entry["m"]
        eng = QimenJiugongEngine()
        assess = eng.get_full_monthly_assessment(2024, m)
        predictions.append(assess["plate_scores"])
    
    correct, total = 0, 0
    for i, entry in enumerate(months_data):
        if i >= len(predictions): break
        for p in PLATES:
            actual_dir = get_actual_dir(entry.get(p, 0))
            pred_dir = get_dir(predictions[i][p])
            if actual_dir != 0:
                total += 1
                if pred_dir == actual_dir:
                    correct += 1
    
    rate = correct / total if total > 0 else 0
    print(f"\n📊 Qimen-only 消融实验: {rate:.1%} ({correct}/{total})")
    return rate, correct, total


# ─── Qimen+Baseline 独立加法消融 ───
def run_qimen_baseline_only(test_data):
    """胜复校正0.70 + 奇门独立0.30（不加资本），测试奇门的独立增量贡献"""
    results = batch_corrected_predict(2024)
    scores_baseline = [{p: row[p] for p in PLATES} for row in results]
    
    eng = QimenJiugongEngine()
    
    correct, total = 0, 0
    for i, row in enumerate(results):
        m = row["m"]
        wuyun_scores = {p: row[p] for p in PLATES}
        assess = eng.get_full_monthly_assessment(2024, m)
        
        for p in PLATES:
            final = wuyun_scores[p] * 0.70 + assess["plate_scores"][p] * 0.30
            actual_val = None
            for entry in test_data["2024"]["months"]:
                if entry["m"] == m:
                    actual_val = entry.get(p, 0)
                    break
            
            actual_dir = get_actual_dir(actual_val or 0)
            pred_dir = get_dir(final)
            if actual_dir != 0:
                total += 1
                if pred_dir == actual_dir:
                    correct += 1
    
    rate = correct / total if total > 0 else 0
    print(f"  胜复0.70+奇门0.30: {rate:.1%} ({correct}/{total})")
    return rate, correct, total


if __name__ == "__main__":
    test_data = load_test_suite()
    
    # 基线
    results = batch_corrected_predict(2024)
    scores = [{p: row[p] for p in PLATES} for row in results]
    cor, tot, base_rate = evaluate_corrected(test_data)
    print(f"📊 基线(胜复校正): {base_rate:.1%} ({cor}/{tot})")
    
    # 增强四层
    enhanced_rate, ec, et = run_enhanced_test(test_data)
    
    # Qimen-only
    qimen_rate, qc, qt = run_qimen_only_test(test_data)
    
    # 资本行为信号统计
    results = batch_corrected_predict(2024)
    scores = [{p: row[p] for p in PLATES} for row in results]
    cap_sigs = capital_independent_signal(scores)
    nonzero = sum(1 for sig in cap_sigs for p in PLATES if sig[p] != 0)
    total_cells = len(cap_sigs) * len(PLATES)
    print(f"\n📊 资本行为信号活跃度: {nonzero}/{total_cells} = {nonzero/total_cells:.1%}")
    
    # 奇门信号范围统计
    eng = QimenJiugongEngine()
    qimen_min, qimen_max = 1.0, -1.0
    for m in range(1, 13):
        assess = eng.get_full_monthly_assessment(2024, m)
        for p in PLATES:
            s = assess["plate_scores"][p]
            qimen_min = min(qimen_min, s)
            qimen_max = max(qimen_max, s)
    print(f"📊 九宫奇门信号范围: [{qimen_min:.2f}, {qimen_max:.2f}]")
    
    print(f"\n{'='*60}")
    print(f"🏆 汇总:")
    print(f"  基线(胜复校正):         {base_rate:.1%}")
    print(f"  增强四层(加独立信号):   {enhanced_rate:.1%}")
    print(f"  奇门-only:              {qimen_rate:.1%}")
