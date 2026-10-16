#!/usr/bin/env python3
"""
奇门遁甲推演 — 老师推荐理工大学是否诱骗
当前时间：2026年6月12日 21:20 亥时
"""
import sys
sys.path.insert(0, r"I:\ai\openakita-main\skills\qimen-diagnosis\scripts")
from nine_dim_engine import NineDimEngine

engine = NineDimEngine()

# ── 当前时间：2026年6月12日 21:20 亥时 ──
year, month, day, hour, minute = 2026, 6, 12, 21, 20

# ── 事件绑定 ──
multi_dim_bind = {
    "person": "游兄之女（考生，文科背景）",
    "event": "老师推荐理工大学（华南理工），是否为诱骗/误导",
    "object": "志愿填报决策·理工大学的文科专业",
    "semantic": "担忧走过中西医结合的老路，再陷水土不服困境"
}

# ── 空间提示 ──
# 用神定位：
# 考生 → 丁奇 / 天辅星（文星）
# 老师 → 值符 / 天辅星（师者）
# 理工大学 → 景门（文书/信息）或 开门（公开信息）
# 诱骗 → 玄武（欺诈）/ 白虎（强压）/ 六合（信息不透明）
spatial_hints = {
    "person_zone": "巽宫",     # 考生年纪属巽（文昌）
    "event_zone": "离宫",      # 文书/信息属离
    "object_zone": "艮宫",     # 决策/方向属艮
    "teacher_zone": "震宫",    # 老师属震（动口）
    "deception_zone": "兑宫",  # 欺诈/口舌属兑
}

# ── 执行九维推演 ──
result = engine.deduce_3d(
    year=year, month=month, day=day, hour=hour, minute=minute,
    multi_dim_bind=multi_dim_bind,
    spatial_hints=spatial_hints,
    mode="static"
)

# ══════════════════════════════════════════════════
# 输出的详细九宫信息
# ══════════════════════════════════════════════════
print("=" * 70)
print("【九维奇门遁甲 · 老师推荐理工大学推演报告】")
print(f"📅 推演时间：{year}年{month}月{day}日 {hour}:{minute:02d}（亥时）")
print("=" * 70)

# ── 时空信息 ──
ts = result.timespace
if ts:
    print(f"\n① 时空局")
    print(f"{'─'*50}")
    for attr in ['ju_name','jushi','yinyang','ganzhi','ganzhi_str','season']:
        val = getattr(ts, attr, None)
        if val:
            print(f"   {attr}: {val}")

# ── 九宫信息 ──
print(f"\n② 九宫布局")
print(f"{'─'*50}")
for name in ["坎","坤","震","巽","中","乾","兑","艮","离"]:
    p = result.palaces_3d.get(name, {})
    if hasattr(p,'star') and p.star:
        print(f"   {name}: 星={p.star}, 门={p.gate}, 神={p.spirit}, 天干={p.tiangan}, 地支={p.dizhi}, 阴阳={p.yin_yang}, 权重={p.weight}")

# ── 九维分项 ──
print(f"\n③ 九维分析")
print(f"{'─'*50}")
if result.nine_dim_analysis:
    for k,v in result.nine_dim_analysis.items():
        print(f"   {k}: {str(v)[:300]}")

# ── 整体判断 ──
print(f"\n④ 整体判断")
print(f"{'─'*50}")
print(f"   {result.overall_judgment}")

# ── 用神状态 ──
print(f"\n⑤ 用神状态")
print(f"{'─'*50}")
print(f"   {result.yongshen_status}")

# ── 置信度 ──
print(f"   \n推演置信度：{result.confidence_score}")

# ── 格局 ──
if hasattr(result, 'pattern_summary') and result.pattern_summary:
    print(f"\n⑥ 格局")
    print(f"{'─'*50}")
    for p in result.pattern_summary:
        print(f"   {p}")

# ── 星门旺衰 ──
if hasattr(result, 'star_status_summary') and result.star_status_summary:
    print(f"\n⑦ 九星八门状态")
    print(f"{'─'*50}")
    print(f"   九星: {result.star_status_summary}")
    print(f"   八门: {result.gate_status_summary}")

# ── 门迫反伏吟 ──
if hasattr(result, 'menpo_summary') and result.menpo_summary:
    print(f"\n⑧ 门迫/反伏吟")
    print(f"{'─'*50}")
    print(f"   {result.menpo_summary}")

# ── 潜在变数 ──
if hasattr(result, 'potential_variables') and result.potential_variables:
    print(f"\n⑨ 潜在变数/注意事项")
    print(f"{'─'*50}")
    for v in result.potential_variables:
        print(f"   • {v}")

print(f"\n{'='*70}")
print(f"🪷 汐儿谨呈 — 天机示象，人心为断")
