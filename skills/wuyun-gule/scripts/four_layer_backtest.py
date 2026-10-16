"""
四层框架 · 2024逐月逐板块全量回测
==================================
对比测试：
  A) 纯胜复校正（旧基线）
  B) 胜复校正 + 资本行为
  C) 胜复校正 + 资本行为 + 九宫奇门（v3.7.0 四层框架）
"""

import os, sys, json
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from corrected_scoring import batch_corrected_predict, PLATES
from capital_integration import CapitalIntegration
from qimen_jiugong import QimenJiugongEngine, integrate_qimen_score

# ===== 加载测试集 =====
def load_test_suite():
    path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ===== 方向判定 =====
def get_direction(value, threshold=0.03):
    """严格方向：涨/跌/震荡"""
    if value > threshold:
        return 1
    elif value < -threshold:
        return -1
    return 0

def get_actual_direction(value):
    """实际方向：±3%阈值"""
    if value > 3:
        return 1
    elif value < -3:
        return -1
    return 0

# ===== 方案A：纯胜复校正（基线） =====
def run_baseline(test_data):
    """纯胜复校正引擎"""
    results = batch_corrected_predict(2024)
    scores = []
    for row in results:
        scores.append({p: row[p] for p in PLATES})
    
    return _evaluate("A: 胜复校正(旧基线)", test_data, scores, "wuyun_only")

# ===== 方案B：胜复校正 + 资本行为 =====
def run_with_capital(test_data):
    """胜复校正 + 资本行为"""
    results = batch_corrected_predict(2024)
    cap_int = CapitalIntegration(active_level=1.0, capital_weight=0.20)
    
    scores = []
    prev_history = {p: [] for p in PLATES}  # 按板块记录历史评分
    for i, row in enumerate(results):
        month_scores = {}
        for p in PLATES:
            raw = row[p]
            # 传本板块历史列表，避免 dict slice 报错
            modulated = cap_int.modulate_score(p, raw, 2024, row["month"], prev_history[p])
            if isinstance(modulated, tuple):
                month_scores[p] = modulated[0]
            else:
                month_scores[p] = modulated
        scores.append(month_scores)
        # 更新各板块历史
        for p in PLATES:
            prev_history[p].append(month_scores[p])
    
    return _evaluate("B: 胜复+资本行为", test_data, scores, "with_capital")

# ===== 方案C：四层框架（含九宫奇门） =====
def run_four_layer(test_data):
    """胜复校正 + 资本行为 + 九宫奇门（v3.7.0）"""
    results = batch_corrected_predict(2024)
    cap_int = CapitalIntegration(active_level=1.0, capital_weight=0.20)
    
    scores = []
    prev = None
    for i, row in enumerate(results):
        # 1) 胜复校正原始评分
        raw_wuyun = {p: row[p] for p in PLATES}
        
        # 2) 资本行为调制
        modulated = {}
        for p in PLATES:
            m = cap_int.modulate_score(p, raw_wuyun[p], 2024, row["month"], prev)
            modulated[p] = m[0] if isinstance(m, tuple) else m
        prev = modulated
        
        # 3) 九宫奇门叠加（权重0.20，增强奇门在关键转换月的判断力）
        month = row["month"]
        integrated = integrate_qimen_score(
            modulated, 2024, month, qimen_weight=0.20
        )
        
        scores.append(integrated["final_scores"])
    
    return _evaluate("C: 四层框架(含奇门)", test_data, scores, "four_layer")

# ===== 精度评估 =====
def _evaluate(label, test_data, predictions, version):
    """评估方向精度（双向判读：严格方向和宽松方向）"""
    test_2024 = test_data.get("2024", {})
    months_data = test_2024.get("months", [])
    
    total = 0
    correct = 0
    total_loose = 0
    correct_loose = 0
    
    plate_stats = {p: {"correct": 0, "total": 0} for p in PLATES}
    
    for i, month_entry in enumerate(months_data):
        m = month_entry["m"]
        if i >= len(predictions):
            break
        
        pred = predictions[i]
        
        for plate in PLATES:
            actual_val = month_entry.get(plate, 0)
            pred_val = pred.get(plate, 0)
            
            actual_dir = get_actual_direction(actual_val)
            pred_dir = get_direction(pred_val)
            
            if actual_dir != 0:
                total += 1
                plate_stats[plate]["total"] += 1
                
                if pred_dir == actual_dir:
                    correct += 1
                    plate_stats[plate]["correct"] += 1
                
                # 宽松：只排除0判读
                if pred_dir != 0 and pred_dir == actual_dir:
                    correct_loose += 1
                    total_loose += 1
                elif pred_dir != 0:
                    total_loose += 1
    
    strict_rate = correct / total if total > 0 else 0
    loose_rate = correct_loose / total_loose if total_loose > 0 else 0
    
    # 板块级精度
    plate_rates = {}
    for p in PLATES:
        s = plate_stats[p]
        plate_rates[p] = (s["correct"] / s["total"] if s["total"] > 0 else 0, s["correct"], s["total"])
    
    return {
        "label": label,
        "version": version,
        "strict_rate": strict_rate,
        "strict_correct": correct,
        "strict_total": total,
        "loose_rate": loose_rate,
        "loose_correct": correct_loose,
        "loose_total": total_loose,
        "plate_rates": plate_rates,
    }

# ===== 个股映射 =====
STOCKS = [
    {"name": "寒武纪", "code": "688256", "primary": "火", "weights": {"火": 0.85, "金": 0.15}},
    {"name": "宁德时代", "code": "300750", "primary": "木", "weights": {"木": 0.60, "火": 0.40}},
    {"name": "贵州茅台", "code": "600519", "primary": "土", "weights": {"土": 0.70, "水": 0.30}},
    {"name": "工商银行", "code": "601398", "primary": "金", "weights": {"金": 0.90, "土": 0.10}},
    {"name": "长江电力", "code": "600900", "primary": "水", "weights": {"水": 0.80, "木": 0.20}},
]

def stock_plate_score(stock, plate_scores):
    """将个股的五行权重映射到板块评分上"""
    total = 0.0
    for plate, weight in stock["weights"].items():
        score = plate_scores.get(plate, 0.0)
        total += score * weight
    return total

def run_stock_test(test_data, predictions):
    """按个股映射计算准确率"""
    result_rows = []
    
    for stock in STOCKS:
        stock_directions = []
        for i, month_entry in enumerate(test_data["2024"]["months"]):
            m = month_entry["m"]
            if i >= len(predictions):
                break
            
            pred = predictions[i]
            
            # 个股推演评分
            pred_stock = stock_plate_score(stock, pred)
            
            # 个股实际走势 = 按其五行权重映射实际板块涨跌
            actual_stock = 0.0
            for plate, weight in stock["weights"].items():
                actual_val = month_entry.get(plate, 0)
                actual_stock += actual_val * weight
            
            pred_dir = get_direction(pred_stock)
            actual_dir = get_actual_direction(actual_stock)
            
            stock_directions.append({
                "month": m,
                "pred_score": round(pred_stock, 4),
                "actual_val": round(actual_stock, 2),
                "pred_dir": pred_dir,
                "actual_dir": actual_dir,
            })
        
        # 统计
        correct = sum(1 for d in stock_directions if d["actual_dir"] != 0 and d["pred_dir"] == d["actual_dir"])
        total = sum(1 for d in stock_directions if d["actual_dir"] != 0)
        rate = correct / total if total > 0 else 0
        
        # 按季度分拆统计
        q_correct, q_total = 0, 0
        q2_correct, q2_total = 0, 0
        q3_correct, q3_total = 0, 0
        q4_correct, q4_total = 0, 0
        for d in stock_directions:
            if d["actual_dir"] == 0:
                continue
            m = d["month"]
            is_correct = d["pred_dir"] == d["actual_dir"]
            if m <= 3:
                q_total += 1
                if is_correct: q_correct += 1
            elif m <= 6:
                q2_total += 1
                if is_correct: q2_correct += 1
            elif m <= 9:
                q3_total += 1
                if is_correct: q3_correct += 1
            else:
                q4_total += 1
                if is_correct: q4_correct += 1
        
        result_rows.append({
            "stock": stock["name"],
            "primary": stock["primary"],
            "accuracy": rate,
            "correct": correct,
            "total": total,
            "q1": f"{q_correct}/{q_total}" if q_total > 0 else "-",
            "q2": f"{q2_correct}/{q2_total}" if q2_total > 0 else "-",
            "q3": f"{q3_correct}/{q3_total}" if q3_total > 0 else "-",
            "q4": f"{q4_correct}/{q4_total}" if q4_total > 0 else "-",
            "details": stock_directions,
        })
    
    return result_rows


def print_results(results, stock_results=None):
    """格式化输出"""
    print("=" * 70)
    print("四层框架（v3.7.0）· 2024逐月回测精度")
    print("=" * 70)
    
    for r in results:
        print(f"\n📊 {r['label']}")
        print(f"  ┌ 严格方向精度: {r['strict_rate']:.1%} ({r['strict_correct']}/{r['strict_total']})")
        print(f"  ├ 宽松方向精度: {r['loose_rate']:.1%} ({r['loose_correct']}/{r['loose_total']})")
        print(f"  └ 板块级精度:")
        for p in PLATES:
            rate, c, t = r['plate_rates'][p]
            bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
            print(f"      {p}: {bar} {rate:.0%} ({c}/{t})")
    
    if stock_results:
        print(f"\n{'=' * 70}")
        print("个股级精度（五行权重映射）")
        print(f"{'=' * 70}")
        
        for r in stock_results:
            bar = "█" * int(r['accuracy'] * 20) + "░" * (20 - int(r['accuracy'] * 20))
            print(f"\n{r['stock']} ({r['primary']}): {bar} {r['accuracy']:.0%} ({r['correct']}/{r['total']})")
            print(f"  季度分拆: Q1={r['q1']}  Q2={r['q2']}  Q3={r['q3']}  Q4={r['q4']}")
            
            # 显示逐月推演 vs 实际
            print(f"  逐月（推演→实际）: ", end="")
            for d in r["details"]:
                pred_mark = "↑" if d["pred_dir"] > 0 else ("↓" if d["pred_dir"] < 0 else "—")
                act_mark = "↑" if d["actual_dir"] > 0 else ("↓" if d["actual_dir"] < 0 else "—")
                match = "✅" if d["pred_dir"] == d["actual_dir"] and d["actual_dir"] != 0 else ("❌" if d["actual_dir"] != 0 else "○")
                print(f"{d['month']}月:{pred_mark}/{act_mark}{match} ", end="")
            print()
    
    # 汇总
    if stock_results:
        avg_accuracy = sum(r['accuracy'] for r in stock_results) / len(stock_results)
        total_correct = sum(r['correct'] for r in stock_results)
        total_total = sum(r['total'] for r in stock_results)
        print(f"\n{'=' * 70}")
        print(f"🏆 五只个股综合精度: {total_correct}/{total_total} = {avg_accuracy:.1%}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    test_data = load_test_suite()
    
    # 跑三个方案
    r_a = run_baseline(test_data)
    r_b = run_with_capital(test_data)
    
    # 方案C：基于B的评分，再叠九宫奇门
    cap_int = CapitalIntegration(active_level=1.0, capital_weight=0.20)
    results_b = batch_corrected_predict(2024)
    
    four_layer_pred = []
    prev_history_c = {p: [] for p in PLATES}
    for i, row in enumerate(results_b):
        raw = {p: row[p] for p in PLATES}
        modulated = {}
        for p in PLATES:
            m = cap_int.modulate_score(p, raw[p], 2024, row["month"], prev_history_c[p])
            modulated[p] = m[0] if isinstance(m, tuple) else m
        # 更新历史
        for p in PLATES:
            prev_history_c[p].append(modulated[p])
        
        integrated = integrate_qimen_score(modulated, 2024, row["month"], qimen_weight=0.20)
        four_layer_pred.append(integrated["final_scores"])
    
    r_c = _evaluate("C: 四层框架(胜复+资本+奇门)", test_data, four_layer_pred, "four_layer")
    
    # 个股测试（基于方案C）
    stock_results = run_stock_test(test_data, four_layer_pred)
    
    # 输出结果
    print_results([r_a, r_b, r_c], stock_results)
    
    # 保存结果
    output = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "test_label": "四层框架 v3.7.0 全量回测",
        "baseline": {k: v for k, v in r_a.items() if k != "plate_rates"},
        "with_capital": {k: v for k, v in r_b.items() if k != "plate_rates"},
        "four_layer": {k: v for k, v in r_c.items() if k != "plate_rates"},
        "stock_results": [
            {
                "stock": s["stock"],
                "primary": s["primary"],
                "accuracy": s["accuracy"],
                "correct": s["correct"],
                "total": s["total"],
            }
            for s in stock_results
        ],
    }
    out_path = os.path.join(_SCRIPT_DIR, "..", "data", "four_layer_backtest_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
