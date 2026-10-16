"""完整四层基线 + 诊断"""
import sys, os
sys.path.insert(0, r'I:\ai\openakita-main\skills\wuyun-gule\scripts')
os.chdir(r'I:\ai\openakita-main\skills\wuyun-gule\scripts')

import json, math
from corrected_scoring import batch_corrected_predict, PLATES, correlation_analysis
from diagnose import load_test_suite

test_data = load_test_suite()

# 1. 相关性分析
print("=== 相关系数 v3.1 ===")
corrs = correlation_analysis(test_data)
for p in PLATES:
    c = corrs[p]
    mark = "🟢" if c > 0.1 else ("🔴" if c < -0.1 else "⚪")
    print(f"  {p}: {mark} r = {c:.4f}")

# 2. 四层棘轮基线
print("\n=== 四层棘轮 v2.0 默认权重 ===")
from four_layer_ratchet import FourLayerIntegrator, DEFAULT_WEIGHTS, weight_scan

integrator = FourLayerIntegrator(DEFAULT_WEIGHTS)
result = integrator.evaluate(2024, test_data)
print(f"总精度: {result['accuracy']:.2%} ({result['correct']}/{result['total']})")
print(f"分板块: {result.get('plate_accuracy', {})}")

# 3. 重量扫描
print("\n=== 权重扫描 ===")
best, top10, _ = weight_scan(2024, test_data)
print(f"最优精度: {best['accuracy']:.2%}")
print(f"最优权重: {best['weights']}")
print(f"板块精度: {best.get('plate_accuracy', {})}")

# 4. 看看土板块每个月的具体信号
print("\n=== 土板块逐月信号追踪 ===")
from corrected_scoring import compute_corrected_score

accumulation = {p: 0.0 for p in PLATES}
eruption_hx = {}
for m in range(1, 13):
    s, sigs = compute_corrected_score("土", 2024, m, accumulation, eruption_hx)
    actual = next(d["土"] for d in test_data["2024"]["months"] if d["m"] == m)
    print(f"  土月{m:>2}: score={s:+.4f}  actual={actual:>+3}%  sigs={'; '.join(sigs[:4])}")

print("\n=== 火板块逐月信号追踪 ===")
accumulation = {p: 0.0 for p in PLATES}
eruption_hx = {}
for m in range(1, 13):
    s, sigs = compute_corrected_score("火", 2024, m, accumulation, eruption_hx)
    actual = next(d["火"] for d in test_data["2024"]["months"] if d["m"] == m)
    print(f"  火月{m:>2}: score={s:+.4f}  actual={actual:>+3}%  sigs={'; '.join(sigs[:4])}")

print("\n基线诊断完成。")
