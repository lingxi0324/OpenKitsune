"""
土板块相关系数 Bootstrap 稳定性验证 v1
不依赖 corrected_scoring（避免 WUYUN_MAP 结构兼容问题）
直接从 test_suite.json 读取数据 + 用 wuyun_core 原生 API
"""
import os, sys, json, math, random

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import wuyun_core as wc

# ---------- 准备评分数据 ----------
# 手动构造简单的 WUYUN_MAP 字典格式（兼容 corrected_scoring 的期望）
WUYUN_DICT = {
    "甲": {"wuxing": "土", "nature": "太过", "strength": 0.8},
    "乙": {"wuxing": "金", "nature": "不及", "strength": 0.3},
    "丙": {"wuxing": "水", "nature": "太过", "strength": 0.8},
    "丁": {"wuxing": "木", "nature": "不及", "strength": 0.3},
    "戊": {"wuxing": "火", "nature": "太过", "strength": 0.8},
    "己": {"wuxing": "土", "nature": "不及", "strength": 0.3},
    "庚": {"wuxing": "金", "nature": "太过", "strength": 0.8},
    "辛": {"wuxing": "水", "nature": "不及", "strength": 0.3},
    "壬": {"wuxing": "木", "nature": "太过", "strength": 0.8},
    "癸": {"wuxing": "火", "nature": "不及", "strength": 0.3},
}

PLATES = ["木", "火", "土", "金", "水"]

# 读取测试集
suite_path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
with open(suite_path, "r", encoding="utf-8") as f:
    raw = f.read()
td = json.loads(raw)

# 提取所有土板块实际值
earth_actuals = []  # [(year, month, actual_pct)]
for y in td:
    for m_data in td[y]["months"]:
        if "土" in m_data:
            earth_actuals.append((int(y), m_data["m"], m_data["土"]))

print("=" * 65)
print("🌱 土板块相关系数 Bootstrap 稳定性验证")
print("=" * 65)
print(f"\n📊 原始样本: {len(earth_actuals)} 个月（{sorted(set(y for y,_,_ in earth_actuals))} 年）")

# 计算原始相关系数（直接基于实际值）
# 用简单的单变量信号：年份的岁运五行信号
def get_earth_signal(year, month):
    """简化的土板块信号：岁运为土则正向"""
    tiangan = wc.get_ganzhi_for_year(year)
    if not tiangan or len(tiangan) < 2:
        return 0.0
    tg = tiangan[0]
    info = WUYUN_DICT.get(tg, {})
    wx = info.get("wuxing", "")
    if wx == "土":
        return 0.3  # 土运年基础正向信号
    elif wc.KE_CYCLE.get(wx) == "土":
        return -0.15  # 克土者负向
    elif wc.SHENG_CYCLE.get(wx) == "土":
        return 0.1  # 生土者正向
    return 0.0

# 计算原始相关系数
def calc_corr(x_list, y_list):
    n = len(x_list)
    if n < 3:
        return 0.0
    sx, sy = sum(x_list), sum(y_list)
    sxx = sum(x*x for x in x_list)
    syy = sum(y*y for y in y_list)
    sxy = sum(x_list[i]*y_list[i] for i in range(n))
    denom = (n*sxx - sx*sx) * (n*syy - sy*sy)
    if denom <= 0:
        return 0.0
    return (n*sxy - sx*sy) / (denom**0.5)

sigs = [get_earth_signal(y, m) for y, m, a in earth_actuals]
actuals = [a for _, _, a in earth_actuals]
orig_r = calc_corr(sigs, actuals)
print(f"  原始相关系数 r = {orig_r:.4f}")

# ---------- Bootstrap 验证 ----------
n_bootstrap = 10000
r_samples = []
n = len(earth_actuals)

random.seed(42)
for i in range(n_bootstrap):
    idxs = [random.randint(0, n-1) for _ in range(n)]
    bs_sigs = [sigs[j] for j in idxs]
    bs_actuals = [actuals[j] for j in idxs]
    r = calc_corr(bs_sigs, bs_actuals)
    r_samples.append(r)

r_samples.sort()
ci_low = r_samples[int(n_bootstrap * 0.025)]
ci_high = r_samples[int(n_bootstrap * 0.975)]
median_r = r_samples[int(n_bootstrap * 0.5)]
pos_ratio = sum(1 for r in r_samples if r > 0) / n_bootstrap
neg_ratio = sum(1 for r in r_samples if r < 0) / n_bootstrap

print(f"\n🎯 Bootstrap 验证（{n_bootstrap} 次重采样）:")
print(f"  中位数 r     = {median_r:.4f}")
print(f"  95% 置信区间 = [{ci_low:.4f}, {ci_high:.4f}]")
print(f"  正值占比     = {pos_ratio:.1%}")
print(f"  负值占比     = {neg_ratio:.1%}")

if ci_low > 0:
    print(f"\n  ✅ 结论：r>0 在统计上显著（95% CI 全正）")
elif pos_ratio > 0.85:
    print(f"\n  ⚠️ 结论：r>0 趋势明显但未达95%显著（正值占 {pos_ratio:.1%}）")
else:
    print(f"\n  ❌ 结论：r>0 不显著，需要更多样本或改进信号")

# ---------- 留一年验证 ----------
print(f"\n📋 留一年验证:")
years_avail = sorted(set(y for y,_,_ in earth_actuals))
for leave_y in years_avail:
    keep = [(s, a) for (y,_,_), s, a in zip(earth_actuals, sigs, actuals) if y != leave_y]
    if len(keep) < 3:
        continue
    r_keep = calc_corr([s for s,a in keep], [a for s,a in keep])
    n_keep = len(keep)
    print(f"  去掉 {leave_y}年 ({n_keep}样本) → r = {r_keep:.4f}")

# ---------- 最小样本量估算 ----------
print(f"\n🔬 最小样本量估算（要达到95%显著需要的样本数）:")
# 用逐步增加样本量的方法
random.seed(42)
for test_n in [12, 18, 24, 36, 48, 60, 84]:
    test_rs = []
    for _ in range(2000):
        idxs = [random.randint(0, n-1) for _ in range(test_n)]
        ts = [sigs[j] for j in idxs]
        ta = [actuals[j] for j in idxs]
        test_rs.append(calc_corr(ts, ta))
    test_rs.sort()
    pos_pct = sum(1 for r in test_rs if r > 0) / 2000
    ci = (test_rs[int(2000*0.025)], test_rs[int(2000*0.975)])
    flag = "✅显著" if ci[0] > 0 else "⚠️"
    print(f"  n={test_n:3d}: 中位数r={test_rs[1000]:+.4f}, 95%CI=[{ci[0]:+.4f},{ci[1]:+.4f}], 正值{pos_pct:.1%} {flag}")

print(f"\n{'='*65}")
print("✅ Bootstrap 验证完成")
print(f"{'='*65}")
