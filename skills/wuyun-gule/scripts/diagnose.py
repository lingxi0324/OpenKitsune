"""
诊断脚本：分析四柱评分与实际涨跌幅的相关性
找出：分界线在哪里？评分高的时候实际真涨吗？
"""
import os, sys, json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from sizhu_predictor import compute_sizhu_score, PLATES

def load_test_suite(path=None):
    if path is None:
        path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

test_data = load_test_suite()
rows = []

for ys, yd in test_data.items():
    year = int(ys)
    for md in yd["months"]:
        m = md["m"]
        for p in PLATES:
            actual = md[p]
            score = compute_sizhu_score(p, year, m)
            rows.append({"plate": p, "month": m, "actual": actual, "score": round(score, 4)})

# 按评分排序
sorted_by_score = sorted(rows, key=lambda r: r["score"])
sorted_by_actual = sorted(rows, key=lambda r: r["actual"])

print("=== 评分最高（看涨信号最强）的前10条 ===")
for r in sorted_by_score[-10:]:
    print(f"  {r['plate']} {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+.0f}%")

print("\n=== 评分最低（看跌信号最强）的前10条 ===")
for r in sorted_by_score[:10]:
    print(f"  {r['plate']} {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+.0f}%")

print("\n=== 实际涨幅最大的10条（模型评分对比）===")
for r in sorted_by_actual[-10:]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+.0f}%  评分={r['score']:+.4f}")

print("\n=== 实际跌幅最大的10条（模型评分对比）===")
for r in sorted_by_actual[:10]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+.0f}%  评分={r['score']:+.4f}")

# 相关性分析
all_scores = [r["score"] for r in rows]
all_actuals = [r["actual"] for r in rows]
n = len(rows)
mean_s = sum(all_scores)/n
mean_a = sum(all_actuals)/n
cov = sum((all_scores[i]-mean_s)*(all_actuals[i]-mean_a) for i in range(n))/n
std_s = (sum((s-mean_s)**2 for s in all_scores)/n)**0.5
std_a = (sum((a-mean_a)**2 for a in all_actuals)/n)**0.5
corr = cov/(std_s*std_a) if std_s*std_a > 0 else 0

print(f"\n=== 相关性分析 ===")
print(f"  评分与实际涨幅的皮尔逊相关系数: {corr:.4f}")
print(f"  {'→ 正向相关（评分高时确实涨）' if corr > 0.1 else '→ 基本不相关' if abs(corr) < 0.1 else '→ 负向相关（评分高时反而跌）'}")

# 分板块相关性
for p in PLATES:
    pr = [r for r in rows if r["plate"] == p]
    ps = [r["score"] for r in pr]
    pa = [r["actual"] for r in pr]
    n2 = len(pr)
    ms = sum(ps)/n2
    ma = sum(pa)/n2
    cv = sum((ps[i]-ms)*(pa[i]-ma) for i in range(n2))/n2
    ss = (sum((s-ms)**2 for s in ps)/n2)**0.5
    sa = (sum((a-ma)**2 for a in pa)/n2)**0.5
    cc = cv/(ss*sa) if ss*sa > 0 else 0
    print(f"  {p}: r={cc:.4f}")

# 检验不同阈值的准确率
print("\n=== 阈值敏感性分析 ===")
for th in [0.01, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]:
    corr_dir = sum(1 for r in rows if (r["score"] > th and r["actual"] > 0) or (r["score"] < -th and r["actual"] < 0))
    total_dir = sum(1 for r in rows if abs(r["score"]) > th)
    print(f"  阈值|score|>{th:.2f}: {corr_dir}/{total_dir} = {corr_dir/total_dir:.1%} 方向正确" if total_dir > 0 else f"  阈值|score|>{th:.2f}: 无信号")

# 最佳分界线搜索
print("\n=== 最佳分界线搜索 ===")
best_th = 0
best_acc = 0
for th in [x/100 for x in range(1, 51)]:
    corr_dir = sum(1 for r in rows if (r["score"] > th and r["actual"] > 0) or (r["score"] < -th and r["actual"] < 0))
    total_dir = sum(1 for r in rows if abs(r["score"]) > th)
    if total_dir >= 10:  # 至少10条信号才有意义
        acc = corr_dir/total_dir
        if acc > best_acc:
            best_acc = acc
            best_th = th
            best_corr = corr_dir
            best_total = total_dir

print(f"  最优阈值: |score|>{best_th:.2f} → {best_corr}/{best_total} = {best_acc:.1%}")
