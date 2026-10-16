"""临时：跑胜复校正 v4.0 相关系数"""
import sys, json, math
sys.path.insert(0, '.')
from corrected_scoring import compute_corrected_score, PLATES
from diagnose import load_test_suite

test_data = load_test_suite()
rows = []
for ys, yd in test_data.items():
    year = int(ys)
    for md in yd['months']:
        m = md['m']
        for p in PLATES:
            actual = md[p]
            score, _ = compute_corrected_score(p, year, m)
            rows.append({'plate': p, 'month': m, 'actual': actual, 'score': round(score, 4)})

# 整体相关性
all_s = [r['score'] for r in rows]
all_a = [r['actual'] for r in rows]
n = len(rows)
ms = sum(all_s)/n
ma = sum(all_a)/n
cv = sum((all_s[i]-ms)*(all_a[i]-ma) for i in range(n))/n
ss = (sum((s-ms)**2 for s in all_s)/n)**0.5
sa = (sum((a-ma)**2 for a in all_a)/n)**0.5
corr = cv/(ss*sa) if ss*sa>0 else 0
print(f'=== 胜复校正 v4.0 相关系数 ===')
print(f'整体: r={corr:.4f}')
print()
for p in PLATES:
    pr = [r for r in rows if r['plate']==p]
    ps = [r['score'] for r in pr]
    pa = [r['actual'] for r in pr]
    n2 = len(pr)
    mps = sum(ps)/n2
    mpa = sum(pa)/n2
    cv2 = sum((ps[i]-mps)*(pa[i]-mpa) for i in range(n2))/n2
    ss2 = (sum((s-mps)**2 for s in ps)/n2)**0.5
    sa2 = (sum((a-mpa)**2 for a in pa)/n2)**0.5
    cc2 = cv2/(ss2*sa2) if ss2*sa2>0 else 0
    print(f'{p}: r={cc2:.4f}')
print()

# 评分最高的前10
sb = sorted(rows, key=lambda r: r['score'])
print('=== 评分最高（看涨信号最强）的前12条 ===')
for r in sb[-12:]:
    print(f"  {r['plate']} {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+d}%")
print()
print('=== 评分最低（看跌信号最强）的前12条 ===')
for r in sb[:12]:
    print(f"  {r['plate']} {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+d}%")
print()

# 实际最大涨幅的对比
sb2 = sorted(rows, key=lambda r: r['actual'])
print('=== 实际涨幅最大的12条 ===')
for r in sb2[-12:]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+d}%  评分={r['score']:+.4f}")
print()
print('=== 实际跌幅最大的12条 ===')
for r in sb2[:12]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+d}%  评分={r['score']:+.4f}")
