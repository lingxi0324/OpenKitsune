import sys
sys.path.insert(0, '.')
from sizhu_predictor import predict_month

A = {
    "mu": [-12,8,-3,-3,-5,-10,-8,-6,25,0,-4,-3],
    "huo": [-18,15,8,-4,-8,-12,-15,-8,37,12,-7,-4],
    "tu": [-8,2,-3,0,-2,-2,-3,-5,30,4,-3,-1],
    "jin": [2,0,2,-2,-1,1,0,-1,12,5,2,0],
    "shui": [3,-1,-1,0,1,2,1,0,-8,-2,0,1],
}
P2 = ["木","火","土","金","水"]
P = ["mu","huo","tu","jin","shui"]

def cls(a):
    if a > 2: return 1
    if a > 0: return 0.5
    if a == 0: return 0
    if a > -2: return -0.5
    return -1

def cls2(a):
    if a > 2: return "涨"
    if a > 0: return "微涨"
    if a == 0: return "震荡"
    if a > -2: return "微跌"
    return "跌"

th = tm = 0
print("=== 四柱引擎·2024月度回测 ===")
for pi, p2 in enumerate(P2):
    h = 0
    rows = []
    for m in range(1, 13):
        pr = predict_month(p2, 2024, m)
        dp = pr["direction"]
        a = A[P[pi]][m-1]
        da = cls2(a)
        # 匹配
        ok = False
        if dp == da:
            ok = True
        elif dp in ("涨","微涨") and da in ("涨","微涨"):
            ok = True
        elif dp in ("跌","微跌") and da in ("跌","微跌"):
            ok = True
        elif dp == "震荡" and da == "震荡":
            ok = True
        if ok:
            h += 1
            th += 1
        tm += 1
        rows.append(f"{m:02d}月 推{dp}|实{a:+.0f}%|{'OK' if ok else 'NO'}")
    print(f"\n{p2}: {h}/12 = {h/12*100:.0f}%")
    for r in rows:
        print(f"  {r}")
print(f"\n{'='*40}")
print(f"总吻合: {th}/{tm} = {th/tm*100:.1f}%")
print(f"总精度: {th/tm*100:.1f}%")
