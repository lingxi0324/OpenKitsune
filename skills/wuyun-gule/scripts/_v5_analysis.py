# -*- coding: utf-8 -*-
"""v4 vs v5 相关系数对比（用 test_suite.json）"""
import sys, json
sys.path.insert(0, "I:/ai/openakita-main/skills/wuyun-gule/scripts")
from corrected_scoring_v5 import compute_corrected_score, WUXING_LIST

# 读测试集
with open("../data/test_suite.json", "r", encoding="utf-8") as f:
    td = json.load(f)

PLATES = ["木", "火", "土", "金", "水"]

# 构建实际数据
actuals = {}
for ys, yd in td.items():
    year = int(ys)
    for md in yd["months"]:
        actuals[(year, md["m"])] = {p: md[p] for p in PLATES}

def calc_corr(x, y):
    n = len(x)
    if n < 3: return 0.0
    mx, my = sum(x)/n, sum(y)/n
    num = sum((xi-mx)*(yi-my) for xi, yi in zip(x, y))
    dx = (sum((xi-mx)**2 for xi in x))**0.5
    dy = (sum((yi-my)**2 for yi in y))**0.5
    return num/(dx*dy) if dx*dy > 0 else 0.0

# v4
acc = {w: 0.0 for w in WUXING_LIST}
v4 = {}
for yr in range(2011, 2026):
    for mo in range(1, 13):
        key = (yr, mo)
        if key not in actuals:
            continue
        r = compute_corrected_score(yr, mo, prev_accumulation=acc,
                                     options={"shengfu_enabled": False})
        acc = r["accumulation"]
        v4[key] = r["scores"]

# v5
acc = {w: 0.0 for w in WUXING_LIST}
v5 = {}
eruptions = []
for yr in range(2011, 2026):
    for mo in range(1, 13):
        key = (yr, mo)
        if key not in actuals:
            continue
        r = compute_corrected_score(yr, mo, prev_accumulation=acc,
                                     options={"shengfu_enabled": True})
        acc = r["accumulation"]
        v5[key] = r["scores"]
        for ev in r["eruption_events"]:
            eruptions.append({"year": yr, "month": mo, "element": ev[0], "strength": ev[1]})

print("=" * 70)
print("  胜复校正 v4.1 vs v5  相关系数对比")
print("=" * 70)

for wx in PLATES:
    acts, v4s, v5s = [], [], []
    for key in sorted(actuals):
        if key in v4 and key in v5:
            v4s.append(v4[key].get(wx, 0.0))
            v5s.append(v5[key].get(wx, 0.0))
            acts.append(actuals[key].get(wx, 0))
    r4 = calc_corr(v4s, acts)
    r5 = calc_corr(v5s, acts)
    diff = r5 - r4
    mark = " ◀ " if abs(diff) > 0.1 else (" • " if abs(diff) > 0.05 else "")
    print(f"\n  {wx}:")
    print(f"    v4.1 r = {r4:+7.4f}   v5 r = {r5:+7.4f}   Δ = {diff:+7.4f}{mark}")

# 总体
all_v4, all_v5, all_a = [], [], []
for key in sorted(actuals):
    if key in v4 and key in v5:
        for wx in PLATES:
            all_v4.append(v4[key].get(wx, 0.0))
            all_v5.append(v5[key].get(wx, 0.0))
            all_a.append(actuals[key].get(wx, 0))
r4_all = calc_corr(all_v4, all_a)
r5_all = calc_corr(all_v5, all_a)
print(f"\n  📊 总体: v4.1 r={r4_all:+7.4f} → v5 r={r5_all:+7.4f}  (Δ={r5_all-r4_all:+7.4f})")

# 郁发
print("\n" + "=" * 70)
print("  🌋  郁发事件统计")
print("=" * 70)
ec = {}
for ev in eruptions:
    ec[ev["element"]] = ec.get(ev["element"], 0) + 1
for el in WUXING_LIST:
    print(f"  {el}: {ec.get(el, 0)} 次")
print(f"  总计: {len(eruptions)} 次")

# 分年分布
print("\n  --- 按年郁发分布 ---")
ye = {}
for ev in eruptions:
    y = ev["year"]
    if y not in ye:
        ye[y] = {}
    ye[y][ev["element"]] = ye[y].get(ev["element"], 0) + 1
for y in sorted(ye):
    d = ", ".join([f"{e}x{c}" for e, c in ye[y].items()])
    print(f"    {y}: {d}")

# 土板块逐月
print("\n" + "=" * 70)
print("  土板块逐月对比")
print("=" * 70)
print(f"  {'月':>6} {'实际%':>6} {'v4评分':>8} {'v5评分':>8} {'郁发':>8}")
print("  " + "-" * 40)
for key in sorted(actuals):
    a = actuals[key].get("土", 0)
    v4v = v4[key].get("土", 0.0) if key in v4 else 0.0
    v5v = v5[key].get("土", 0.0) if key in v5 else 0.0
    ev_str = ""
    for ev in eruptions:
        if ev["year"] == key[0] and ev["month"] == key[1] and ev["element"] == "土":
            ev_str = f"+{ev['strength']:.3f}"
    print(f"  {key[0]}-{key[1]:>02d} {a:>+5d}% {v4v:>+8.4f} {v5v:>+8.4f} {ev_str:>8}")

print("\n✅ v4 vs v5 分析完成")
