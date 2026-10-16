"""
土板块样本现状诊断 v1
- 统计现有测试集各板块样本量
- 计算现有土板块相关系数稳定性
- 给出扩充建议
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corrected_scoring import (
    compute_corrected_score, PLATES, correlation_analysis, 
    load_test_suite, evaluate_corrected
)

td = load_test_suite()
years = list(td.keys())

print("=" * 60)
print("【现状诊断】土板块样本量 & 相关系数稳定性")
print("=" * 60)

# 1. 各年份各板块样本量统计
print(f"\n📊 可用年份: {years}")
total_samples = 0
for y in years:
    n_m = len(td[y]['months'])
    total_samples += n_m
    print(f"  {y}年: {n_m}个月")
print(f"  总样本: {total_samples} 个月 × 5板块 = {total_samples*5} 个数据点")
print(f"  每板块样本: {total_samples} 个月（即 {total_samples} 个样本点）")

# 2. 现有相关系数
print(f"\n📈 当前相关系数（仅{years}年）:")
corrs = correlation_analysis(td)
for p in PLATES:
    c = corrs[p]
    tag = "✅" if c > 0.1 else ("⚠️" if c > 0 else "❌")
    print(f"  {tag} {p}: r={c:.4f}")

# 3. 方向准确率
c_correct, t_correct, acc = evaluate_corrected(td)
print(f"\n🎯 方向准确率: {c_correct}/{t_correct} = {acc:.1%}")

# 4. 土板块历年逐月评分明细
print(f"\n📋 土板块逐月评分明细:")
print(f"{'年-月':>8} {'实际%':>7} {'评分':>8} {'方向匹配':>10}")
print("-" * 40)
matches = 0
total_earth = 0
for y in years:
    for m_data in td[y]['months']:
        if '土' not in m_data:
            continue
        m = m_data['m']
        actual = m_data['土']
        score, _ = compute_corrected_score("土", int(y), m, {}, {})
        pred_dir = "涨" if score > 0.04 else ("跌" if score < -0.04 else "震")
        act_dir = "涨" if actual >= 4 else ("跌" if actual <= -4 else "震")
        match = "✅" if pred_dir == act_dir else "❌"
        if match == "✅":
            matches += 1
        total_earth += 1
        print(f"  {match} {y}-{m:02d}  {actual:+7.1f}%  {score:+.4f}  {pred_dir}->{act_dir}")

earth_acc = matches / total_earth * 100 if total_earth else 0
print(f"\n  土板块方向准确率: {matches}/{total_earth} = {earth_acc:.1f}%")

# 5. 稳定性分析：每去掉一年看变化
print(f"\n🔬 稳定性测试（留一法验证）:")
for leave_out in years:
    subset = {k: v for k, v in td.items() if k != leave_out}
    sub_corrs = correlation_analysis(subset)
    e_r = sub_corrs.get("土", 0)
    _, _, sub_acc = evaluate_corrected(subset)
    print(f"  去掉{leave_out}年 → 土r={e_r:+.4f}, 全板块精度={sub_acc:.1f}%")

# 6. 建议扩充量
print(f"\n💡 扩充建议:")
print(f"  现状: 每板块仅{total_samples}个月样本")
print(f"  目标: 扩充至至少5年（60个月/板块）")
print(f"  缺口: 需补充 {5*total_samples//len(years) - total_samples}+ 个月历史数据")
print(f"  建议补充年份: 2019-2023（5年 × 12月 = 60个月）")
print(f"  扩充后总样本: {total_samples + 5*12} 个月/板块")
print(f"  需要数据: 木/火/土/金/水 各板块2019-2023年月度涨跌幅")

print("\n诊断完成 ✅")
