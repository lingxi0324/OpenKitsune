#!/usr/bin/env python3
"""
九维七步推演·整合调用器
用法：python nine_dim_wizard.py [y m d h min]
"""
import sys, json
from nine_dim_engine import NineDimEngine

def _season(m):
    return "春夏秋冬"[(m-1)//3]

def main():
    eng = NineDimEngine()
    a = sys.argv[1:]
    y, m, d, h, mn = 2026, 6, 4, 0, 30
    if len(a) >= 5: y, m, d, h, mn = map(int, a[:5])

    r = eng.deduce_3d(year=y, month=m, day=d, hour=h, minute=mn)
    ts = r.timespace

    print("=" * 56)
    print(f"  九维七步推演 · {y}年{m}月{d}日 {h}:{mn:02d}")
    print(f"  干支：{ts.ri_ganzhi} {ts.shi_ganzhi} | {ts.dun_type or '--'} | 季节：{_season(m)}")
    print("=" * 56)

    # ③ 格局
    print("\n【③ 天盘vs地盘·格局】")
    patterns = getattr(ts, 'patterns', []) or []
    for p in patterns:
        ic = {"大吉":"🟢","吉":"🟢","小吉":"🟡","平":"⚪","凶":"🔴","大凶":"🔴"}.get(p.get("nature",""),"⚪")
        print(f"  {ic} {p.get('palace','')}宫：{p.get('name','')} ({p.get('nature','')})")

    # ④ 旺衰
    print("\n【④ 星门旺衰】")
    sw = getattr(ts, 'star_wangshuai', {}) or {}
    for k, v in sw.items():
        print(f"  ⭐ {k}: {v}")
    gw = getattr(ts, 'gate_wangshuai', {}) or {}
    for k, v in gw.items():
        print(f"  🚪 {k}: {v}")

    # 门迫
    ml = getattr(ts, 'menpo_list', []) or []
    if ml:
        print("\n【门迫】")
        for x in ml: print(f"  ⚠️  {x}")

    # 犯吟
    fanyin = getattr(ts, 'fanyin_palaces', []) or []
    fuyin = getattr(ts, 'fuyin_palaces', []) or []
    if fanyin or fuyin:
        print("\n【犯吟】")
        for p in fanyin: print(f"  🔄 反吟：{p}")
        for p in fuyin: print(f"  🔄 伏吟：{p}")

    # ⑥ 应期
    print(f"\n【⑥ 应期】")
    print(f"  {getattr(ts,'yingqi_result','')}")
    nf = getattr(ts, 'yingqi_near_far', '')
    fs = getattr(ts, 'yingqi_fast_slow', '')
    mx = getattr(ts, 'ma_xing_palace', '')
    print(f"  远近：{nf} | 快慢：{fs} | 马星：{mx or '无'}")

    # 九维权重
    print(f"\n【九维权重】")
    for k, v in r.timespace.nine_dim_weights.items():
        bar = "█" * int(v * 10) + "░" * (10 - int(v * 10))
        print(f"  {k}: {bar} {v:.1f}")

    print("=" * 56)

if __name__ == "__main__":
    main()
