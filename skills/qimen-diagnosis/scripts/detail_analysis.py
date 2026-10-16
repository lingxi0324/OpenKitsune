#!/usr/bin/env python3
"""调试九宫数据"""
import sys, json
sys.path.insert(0, r"I:\ai\openakita-main\skills\qimen-diagnosis\scripts")
from nine_dim_engine import NineDimEngine

eng = NineDimEngine()
y, m, d, h, mn = 2026, 6, 22, 22, 35
r = eng.deduce_3d(year=y, month=m, day=d, hour=h, minute=mn)
ts = r.timespace

print(f"时柱：{ts.shi_ganzhi}  日柱：{ts.ri_ganzhi}")
print(f"局：{ts.dun_type} 局{ts.ju_number}  节气：{ts.jieqi}")

# 查看 palaces_3d 结构
print("\nType of palaces_3d:", type(r.palaces_3d))
if hasattr(r.palaces_3d, 'keys'):
    for k, v in r.palaces_3d.items():
        print(f"\n〖{k}〗")
        if hasattr(v, '__dict__'):
            print(f"  {v.__dict__}")
        elif isinstance(v, dict):
            # 安全打印
            for dk, dv in v.items():
                print(f"  {dk}: {dv}")
        else:
            print(f"  {v}")
else:
    print(str(r.palaces_3d)[:2000])
