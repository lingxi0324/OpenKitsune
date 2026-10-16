"""临时测试：查看火板块逐月郁发状态"""
import os, sys
sys.path.insert(0, r'I:\ai\openakita-main\skills\wuyun-gule\scripts')
os.chdir(r'I:\ai\openakita-main\skills\wuyun-gule\scripts')

from corrected_scoring import compute_corrected_score, PLATES

# 使用可变的积累和爆发历史
acc = {p: 0.0 for p in PLATES}
eru = {}

print("=== 火板块逐月完整信号追踪 ===")
for m in range(1, 13):
    # 传入可变的积累和爆发历史
    s, sigs = compute_corrected_score("火", 2024, m, acc, eru)
    # 检查郁发状态
    has_yufa = any("郁发" in sig for sig in sigs)
    print(f"  火月{m:>2}: score={s:+.4f}  acc[火]={acc['火']:.4f}  { '🔥郁发!' if has_yufa else ''}")
    for sig in sigs:
        print(f"          ↳ {sig}")
    print(f"          erup_hx={eru}")

print("\n=== 土板块逐月完整信号追踪 ===")
acc2 = {p: 0.0 for p in PLATES}
eru2 = {}
for m in range(1, 13):
    s, sigs = compute_corrected_score("土", 2024, m, acc2, eru2)
    has_yufa = any("郁发" in sig for sig in sigs)
    print(f"  土月{m:>2}: score={s:+.4f}  acc[土]={acc2['土']:.4f}  { '🔻郁发!' if has_yufa else ''}")
    for sig in sigs[:6]:
        print(f"          ↳ {sig}")
