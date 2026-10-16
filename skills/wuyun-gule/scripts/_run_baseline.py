"""快速基线诊断"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from diagnose import load_test_suite
from four_layer_ratchet import FourLayerIntegrator, weight_scan

test_data = load_test_suite()

# 1. 看测试数据分布
print("=== 2024年各板块月度实际走势 ===")
print(f"{'月':>3} {'木':>6} {'火':>6} {'土':>6} {'金':>6} {'水':>6}")
print("-" * 35)
for m in test_data["2024"]["months"]:
    print(f"{m['m']:>3} {m['木']:>6} {m['火']:>6} {m['土']:>6} {m['金']:>6} {m['水']:>6}")

# 2. 胜复校正基线
print("\n=== 胜复校正评分基线 ===")
from corrected_scoring import compute_corrected_score, batch_corrected_predict, PLATES
base_scores = batch_corrected_predict(2024)
print(f"{'月':>3} ", end="")
for p in PLATES:
    print(f"  {p:>6}", end="")
print()
# batch_corrected_predict 返回的是 dict: {month: {plate: score}} 结构
if isinstance(base_scores, dict):
    # dict格式
    months_sorted = sorted(base_scores.keys())
    for mi in months_sorted:
        mdata = base_scores[mi]
        print(f"{mi:>3} ", end="")
        for p in PLATES:
            val = mdata.get(p, 0)
            print(f"  {val:+.4f}", end="")
        print()
elif isinstance(base_scores, list):
    # list格式
    for mi in range(len(base_scores)):
        print(f"{mi+1:>3} ", end="")
        item = base_scores[mi]
        if isinstance(item, dict):
            for p in PLATES:
                val = item.get(p, 0)
                print(f"  {val:+.4f}", end="")
        else:
            for pi, p in enumerate(PLATES):
                print(f"  {item[pi]:+.4f}", end="")
        print()
else:
    print(f"[未知格式: {type(base_scores)}]")
    print(base_scores)

# 3. 评估胜复校正方向准确率
print("\n=== 胜复校正方向评估 ===")
correct, total = 0, 0
plate_stats = {p: {"cor": 0, "tot": 0} for p in PLATES}
for mi, m_entry in enumerate(test_data["2024"]["months"]):
    for pi, p in enumerate(PLATES):
        actual = m_entry[p]
        pred = base_scores[mi][pi]
        # 方向判定
        actual_dir = 1 if actual > 0 else (-1 if actual < 0 else 0)
        # 胜复校正阈值 ±0.03
        pred_dir = 1 if pred >= 0.03 else (-1 if pred <= -0.03 else 0)
        if actual_dir != 0 and pred_dir != 0:
            total += 1
            plate_stats[p]["tot"] += 1
            if pred_dir == actual_dir:
                correct += 1
                plate_stats[p]["cor"] += 1
        elif actual_dir == 0 and pred_dir == 0:
            # 都中立 - 算正确但暂不计入
            pass

print(f"总方向准确率: {correct}/{total} = {correct/total:.2%}" if total > 0 else "无有效样本")
for p in PLATES:
    s = plate_stats[p]
    rate = s["cor"] / s["tot"] if s["tot"] > 0 else 0
    print(f"  {p}: {s['cor']}/{s['tot']} = {rate:.2%}")

# 4. 观察土板块的正偏问题
print("\n=== 土板块正偏分析 ===")
tu_scores = [base_scores[mi][PLATES.index("土")] for mi in range(len(base_scores))]
tu_actuals = [m_entry["土"] for m_entry in test_data["2024"]["months"]]
print(f"{'月':>3} {'预测':>8} {'实际':>6} {'方向一致?':>8}")
for mi in range(len(tu_scores)):
    pred_dir = 1 if tu_scores[mi] >= 0.03 else (-1 if tu_scores[mi] <= -0.03 else 0)
    actual_dir = 1 if tu_actuals[mi] > 0 else (-1 if tu_actuals[mi] < 0 else 0)
    match = "✓" if pred_dir == actual_dir else "✗" if pred_dir != 0 and actual_dir != 0 else "?"
    print(f"{mi+1:>3} {tu_scores[mi]:>+8.4f} {tu_actuals[mi]:>6} {match:>8}")

# 5. 四层棘轮重量扫描
print("\n=== 四层棘轮重量扫描 ===")
best, top10, _ = weight_scan(2024, test_data)
print(f"最优精度: {best['accuracy']:.2%} ({best.get('correct',0)}/{best.get('total',0)})")
print(f"最优权重: {best['weights']}")
print(f"板块精度: {best.get('plate_accuracy', {})}")

# 6. 各板块相关系数
print("\n=== 板块相关系数 (预测 vs 实际) ===")
for p in PLATES:
    preds = [base_scores[mi][PLATES.index(p)] for mi in range(len(base_scores))]
    actuals = [m_entry[p] for m_entry in test_data["2024"]["months"]]
    # 简单Pearson
    n = len(preds)
    mean_p = sum(preds) / n
    mean_a = sum(actuals) / n
    cov = sum((preds[i] - mean_p) * (actuals[i] - mean_a) for i in range(n))
    var_p = sum((preds[i] - mean_p) ** 2 for i in range(n))
    var_a = sum((actuals[i] - mean_a) ** 2 for i in range(n))
    r = cov / ((var_p * var_a) ** 0.5) if var_p * var_a > 0 else 0
    print(f"  {p}: r = {r:.4f}"  + (" ← 异常负相关!" if r < -0.2 else ""))

print("\n基线诊断完成。")
