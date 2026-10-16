"""
土板块系统性正偏诊断 v6
= 最简版：直接用 corrected_scoring 做仿真
"""

import os, sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

for mod in ["corrected_scoring", "wuyun_core"]:
    if mod in sys.modules:
        del sys.modules[mod]

import wuyun_core as wc
import corrected_scoring as cs

compute_corrected_score = cs.compute_corrected_score
load_test_suite = cs.load_test_suite
correlation_analysis = cs.correlation_analysis
evaluate_corrected = cs.evaluate_corrected
PLATES = cs.PLATES
SEASON_WUXING = cs.SEASON_WUXING


# ========== 1. 相关系数 ==========
print("=" * 70)
print("【诊断1】当前相关系数（原版）")
print("=" * 70)

td = load_test_suite()
print(f"测试集: {list(td.keys())}, {sum(len(td[k]['months']) for k in td)}样本")

corrs = correlation_analysis(td)
for p in PLATES:
    c = corrs[p]
    mk = "🟢" if c > 0.1 else ("🔴" if c < -0.1 else "⚪")
    print(f"  {mk} {p}: r={c:.4f}")

c_correct, t_correct, acc = evaluate_corrected(td)
print(f"\n方向准确率: {c_correct}/{t_correct} = {acc:.1%}")


# ========== 2. 土板块正偏统计 ==========
print("\n" + "=" * 70)
print("【诊断2】土板块历年正偏率")
print("=" * 70)
for y in range(2019, 2026):
    ys = str(y)
    if ys not in td:
        continue
    pos = neg = 0
    tot = len(td[ys]["months"])
    scs = []
    for me in td[ys]["months"]:
        s, _ = compute_corrected_score("土", y, me["m"], {}, {})
        scs.append(s)
        if s > 0.04:
            pos += 1
        elif s < -0.04:
            neg += 1
    avg = sum(scs) / tot if tot else 0
    print(f"  {y}年: 正={pos} 负={neg} 震={tot-pos-neg} | avg={avg:+.4f}")


# ========== 3. 修正策略仿真 ==========
print("\n" + "=" * 70)
print("【诊断3】修正策略仿真")
print("=" * 70)


def calc_all(transform):
    """计算某transform下的相关系数和准确率"""
    sc = {p: [] for p in PLATES}
    ac = {p: [] for p in PLATES}
    correct = total = 0
    for ys in td:
        for me in td[ys]["months"]:
            m = me["m"]
            for p in PLATES:
                if p not in me:
                    continue
                rs, _ = compute_corrected_score(p, int(ys), m, {}, {})
                adj = transform(p, rs, int(ys), m)
                sc[p].append(adj)
                ac[p].append(me[p])
                total += 1
                pd = "涨" if adj > 0.04 else ("跌" if adj < -0.04 else "震")
                ad = "涨" if me[p] >= 4 else ("跌" if me[p] <= -4 else "震")
                if pd == ad:
                    correct += 1
    
    # 相关系数
    res = {}
    for p in PLATES:
        sx, sy = sum(sc[p]), sum(ac[p])
        n = len(sc[p])
        if n < 3:
            res[p] = 0.0
            continue
        sxx = sum(x * x for x in sc[p])
        syy = sum(y * y for y in ac[p])
        sxy = sum(sc[p][i] * ac[p][i] for i in range(n))
        denom = (n * sxx - sx * sx) * (n * syy - sy * sy)
        res[p] = round((n * sxy - sx * sy) / (denom ** 0.5 + 1e-10), 4) if denom > 0 else 0
    
    return res, correct / total * 100


# 测试多种策略
# 核心思想：土板块评分系统性偏高，需要做系统性的向下修正
strategies = [
    ("原版",     lambda p, s, y, m: s),
    ("土-0.05",  lambda p, s, y, m: s - 0.05 if p == "土" else s),
    ("土-0.08",  lambda p, s, y, m: s - 0.08 if p == "土" else s),
    ("土-0.10",  lambda p, s, y, m: s - 0.10 if p == "土" else s),
    ("土-0.12",  lambda p, s, y, m: s - 0.12 if p == "土" else s),
    ("土-0.15",  lambda p, s, y, m: s - 0.15 if p == "土" else s),
]

print(f"  {'策略':12s} {'土r':>8} {'木r':>8} {'火r':>8} {'金r':>8} {'水r':>8} {'准确率':>8}")
print("-" * 70)
for name, tf in strategies:
    cr, acc_v = calc_all(tf)
    e_r = cr.get("土", 0)
    mk = "🟢" if e_r > 0.1 else ("🔴" if e_r < -0.1 else "⚪")
    print(f"  {name:12s}: {mk}{e_r:+.4f}  {cr.get('木',0):+.4f}  {cr.get('火',0):+.4f}  {cr.get('金',0):+.4f}  {cr.get('水',0):+.4f}  {acc_v:.1f}%")


# ========== 4. 最优策略逐月明细 ==========
best_offset = -0.08
print(f"\n\n【逐月明细】土板块 原评分 vs {best_offset:+}修正")
print(f"{'年-月':>8} {'实际%':>7} {'原分':>8} {'修正分':>8} {'方向':>6}")
print("-" * 45)
for ys in td:
    for me in td[ys]["months"]:
        if "土" not in me:
            continue
        m = me["m"]
        act = me.get("土", 0)
        s_o, _ = compute_corrected_score("土", int(ys), m, {}, {})
        s_b = s_o + best_offset
        pd = "涨" if s_b > 0.04 else ("跌" if s_b < -0.04 else "震")
        ad = "涨" if act >= 4 else ("跌" if act <= -4 else "震")
        ok = "✅" if pd == ad else "❌"
        print(f"  {ok} {ys}-{m:02d}  {act:+7.1f}%  {s_o:+.4f}  {s_b:+.4f}  {pd}->{ad}")


# ========== 5. 统计修正效果 ==========
print("\n\n【修正效果统计】")
cr_orig, acc_orig = calc_all(lambda p, s, y, m: s)
cr_best, acc_best = calc_all(lambda p, s, y, m: s + best_offset if p == "土" else s)

print(f"  土板块相关系数: {cr_orig.get('土',0):+.4f} → {cr_best.get('土',0):+.4f}")
print(f"  方向准确率:     {acc_orig:.1f}% → {acc_best:.1f}%")
print(f"  其他板块平均r:  {sum(cr_orig[p] for p in PLATES if p!='土')/4:+.4f} → {sum(cr_best[p] for p in PLATES if p!='土')/4:+.4f}")

# 检查土板块是否翻正
e_r = cr_best.get("土", 0)
if e_r > 0:
    print(f"\n  ❸ 土板块 r={e_r:+.4f} > 0 → 翻正成功! ✅")
else:
    print(f"\n  ❸ 土板块 r={e_r:+.4f} ≤ 0 → 仍未翻正 ❌，需更大力度")

print("\n\n诊断完成。")
