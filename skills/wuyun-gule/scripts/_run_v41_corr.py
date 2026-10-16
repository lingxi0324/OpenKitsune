"""跑胜复校正 v4.1 相关系数"""
import sys
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
            score, sig = compute_corrected_score(p, year, m)
            rows.append({'plate': p, 'month': m, 'actual': actual, 'score': round(score, 4)})

all_s = [r['score'] for r in rows]
all_a = [r['actual'] for r in rows]
n = len(rows)
ms = sum(all_s)/n; ma = sum(all_a)/n
cv = sum((all_s[i]-ms)*(all_a[i]-ma) for i in range(n))/n
ss = (sum((s-ms)**2 for s in all_s)/n)**0.5
sa = (sum((a-ma)**2 for a in all_a)/n)**0.5
corr = cv/(ss*sa) if ss*sa>0 else 0
print(f'=== 胜复校正 v4.1 相关系数 ===')
print(f'整体: r={corr:.4f}')
print()
for p in PLATES:
    pr = [r for r in rows if r['plate']==p]
    ps = [r['score'] for r in pr]; pa = [r['actual'] for r in pr]
    n2 = len(pr); mps = sum(ps)/n2; mpa = sum(pa)/n2
    cv2 = sum((ps[i]-mps)*(pa[i]-mpa) for i in range(n2))/n2
    ss2 = (sum((s-mps)**2 for s in ps)/n2)**0.5
    sa2 = (sum((a-mpa)**2 for a in pa)/n2)**0.5
    cc2 = cv2/(ss2*sa2) if ss2*sa2>0 else 0
    print(f'{p}: r={cc2:.4f}')
print()

# 看极端情况
sb_act = sorted(rows, key=lambda r: r['actual'])
print('实际涨幅最大的10条:')
for r in sb_act[-10:]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+d}%  评分={r['score']:+.4f}")
print()
print('实际跌幅最大的10条:')
for r in sb_act[:10]:
    print(f"  {r['plate']} {r['month']}月: 实际={r['actual']:+d}%  评分={r['score']:+.4f}")
print()

# 看土的所有评分
print('土板块各月评分:')
for r in sorted([x for x in rows if x['plate']=='土'], key=lambda x: x['month']):
    print(f"  {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+d}%")
print()

# 看火的所有评分
print('火板块各月评分:')
for r in sorted([x for x in rows if x['plate']=='火'], key=lambda x: x['month']):
    print(f"  {r['month']}月: 评分={r['score']:+.4f}  实际={r['actual']:+d}%")
print()

# 阈值分析
for th in [0.05, 0.08, 0.10, 0.15, 0.20]:
    corr_dir = sum(1 for r in rows if (r['score'] > th and r['actual'] > 0) or (r['score'] < -th and r['actual'] < 0))
    total_dir = sum(1 for r in rows if abs(r['score']) > th)
    print(f"阈值|score|>{th:.2f}: {corr_dir}/{total_dir} = {corr_dir/total_dir:.1%}" if total_dir > 0 else f"阈值|score|>{th:.2f}: 无信号")
