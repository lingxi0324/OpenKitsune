"""验证 corrected_scoring.py v3.2 修改是否生效"""
import sys, os
sys.path.insert(0, r'I:\ai\openakita-main\skills\wuyun-gule\scripts')
os.chdir(r'I:\ai\openakita-main\skills\wuyun-gule\scripts')

import importlib
import corrected_scoring
importlib.reload(corrected_scoring)

src = open(corrected_scoring.__file__, 'r', encoding='utf-8').read()
import re

print("=== 验证八大修正点 ===")

m = re.search(r'MR_STRENGTH = ([\d.]+)', src)
print(f"① MR_STRENGTH = {m.group(1)} (期望 0.08)" if m else "① MR_STRENGTH NOT FOUND")

m = re.search(r'EXCESS_THRESHOLD = ([\d.]+)', src)
print(f"② EXCESS_THRESHOLD = {m.group(1)} (期望 0.8)" if m else "② NOT FOUND")

m = re.search(r'strength \* ([\d.]+) \* keqi_mod', src)
print(f"③ 岁运太过 = {m.group(1)} (期望 0.25)" if m else "③ NOT FOUND")

for m in re.finditer(r'st_effect = ([\d.]+) \* grad', src):
    print(f"④ 司天效果 = {m.group(1)} (期望 0.10)")

for m in re.finditer(r'zq_effect = ([\d.]+) \* \(1.0 - grad\)', src):
    print(f"⑤ 在泉效果 = {m.group(1)} (期望 0.10)")

m = re.search(r'score -= st_effect \* ([\d.]+)', src)
print(f"⑥ 司天克 = {m.group(1)} (期望 0.4)" if m else "⑥ NOT FOUND")

m = re.search(r'strength \* ([\d.]+)', src[src.rfind('# 岁运所克'):])
print(f"⑦ 岁运所克 = {m.group(1)} (期望 0.12)" if m else "⑦ NOT FOUND")

m = re.search(r'accumulation_inc = abs\(qi_factor\) \* ([\d.]+)', src)
print(f"⑧ 复气积累 = {m.group(1)} (期望 0.12)" if m else "⑧ NOT FOUND")

m = re.search(r'suppression = -excess \* ([\d.]+)', src)
print(f"⑨ 反制力度 = {m.group(1)} (期望 0.40)" if m else "⑨ NOT FOUND")

print()
print("=== 预测 2024 各板块 ===")
from corrected_scoring import compute_corrected_score, PLATES

for plate in PLATES:
    acc = {p: 0.0 for p in PLATES}
    ehist = {}
    vals = []
    for m in range(1, 13):
        s, _ = compute_corrected_score(plate, 2024, m, acc, ehist)
        vals.append(s)
    mn = sum(vals) / 12
    rng = max(vals) - min(vals)
    print(f"  {plate}: 范围 [{min(vals):+.4f}, {max(vals):+.4f}] | 均值 {mn:+.4f} | 跨度 {rng:.4f}")
