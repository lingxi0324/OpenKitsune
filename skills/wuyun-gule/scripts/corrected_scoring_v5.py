"""
胜复校正评分引擎 v5  ·  五层全链路闭环 + 胜复郁发 + 🅲🅱开关
============================================================
v5 新增：
  ✅ 第5层：胜复郁发 — 完整五运胜气→复气→郁气积累→郁发释放闭环
  ✅ 🅲开关：season_half — 季节阻逆全部减半（默认关）
  ✅ 🅱开关：earth_bias — 土板块最终评分 -0.08（默认关）
  ✅ 修复：accumulation_data 真正跨月持久化（旧版每次传{}作废）
  ✅ 优化：整合散在各层的复气/郁发逻辑到第5层

四层保留（从 v4.1）：
  ① 岁运太过/不及 ② 司天在泉 ③ 季节阻逆 ④ 客主加临

八项修复要点（从 v4.1 继承）：
  ① 岁运太过加成 0.40→0.22
  ② 均值回归 0.08→0.015
  ③ 郁发释放 0.40→0.55，触发阈值 0.08→0.06
  ④ 复气积累 0.12→0.18
  ⑤ 天刑:直接扣分→转郁气积累
  ⑥ 季节阻逆补全五行
  ⑦ 信号强度统一为×0.25
  ⑧ earth板春季(木克土)负向、长夏(土)正向、冬季(水克土)负向
"""

import os, sys, json
from copy import deepcopy

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import (
    WUYUN_MAP, SHENG_CYCLE as WY_SHENG_CYCLE,
    KE_CYCLE as WY_KE_CYCLE, SITIAN_ZAIQUAN,
    LIUQI_WUXING, get_sitian_zaiquan, get_keqi_sequence,
    get_zhuqi_step, get_zhuqi_at_step, get_keqi_at_step,
    judge_pattern, analyze_year,
)

# ═══════════════════════════════════════════════
# 第0层·基础常量
# ═══════════════════════════════════════════════

WUXING_LIST = ["木", "火", "土", "金", "水"]

# 相生 cycle: 木→火→土→金→水→木
SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}

# 相克 cycle: 木→土→水→火→金→木
KE_CYCLE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

# 子复母仇链: A胜B → B生C → C克A
# 即：A 胜其所克 → 所克之行的子行来复仇
# 木胜土 → 土生金 → 金克木（木的复气是金）
FUXI_CYCLE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}

# 五运太过/不及信号对应的元素
TIANGAN_WUXING = {
    "甲": ("土", "太过"), "乙": ("金", "不及"), "丙": ("水", "太过"),
    "丁": ("木", "不及"), "戊": ("火", "太过"), "己": ("土", "不及"),
    "庚": ("金", "太过"), "辛": ("水", "不及"), "壬": ("木", "太过"),
    "癸": ("火", "不及"),
}

# 月份→季节映射（1=寅月）
MONTH_SEASON = {
    1: "春", 2: "春", 3: "春",  # 寅卯辰
    4: "夏", 5: "夏", 6: "夏",  # 巳午未
    7: "长夏",                     # 未（长夏）
    8: "秋", 9: "秋", 10: "秋",   # 申酉戌
    11: "冬", 12: "冬",           # 亥子
}
EARTH_MONTH = 7  # 未月=长夏

SEASON_WUXING = {"春": "木", "夏": "火", "长夏": "土", "秋": "金", "冬": "水"}

# ─── 季节阻逆表（v4.1补全版）───
SEASON_BLOCK = {
    ("春", "木"):  0.00,  # 春木=同气
    ("春", "火"):  0.04,  # 春木生火=吉
    ("春", "土"): -0.06,  # 木克土=负(阻逆)
    ("春", "金"): -0.04,  # 金克木=阻逆
    ("春", "水"):  0.02,  # 水生木=吉
    ("夏", "木"):  0.02,  # 木生火=吉
    ("夏", "火"):  0.00,  # 同气
    ("夏", "土"):  0.08,  # 火生土=吉
    ("夏", "金"): -0.04,  # 火克金(反)-夏季火旺压金
    ("夏", "水"): -0.04,  # 水克火=阻逆
    ("长夏","木"): -0.04,  # 木克土=阻逆
    ("长夏","火"):  0.06,  # 火生土=吉
    ("长夏","土"):  0.00,  # 同气
    ("长夏","金"):  0.04,  # 土生金=吉
    ("长夏","水"): -0.04,  # 土克水=碾压
    ("秋", "木"): -0.04,  # 金克木=阻逆
    ("秋", "火"): -0.04,  # 火克金(反)-秋季金旺见火压
    ("秋", "土"):  0.06,  # 土生金=吉
    ("秋", "金"):  0.00,  # 同气
    ("秋", "水"):  0.04,  # 金生水=吉
    ("冬", "木"):  0.04,  # 水生木=吉
    ("冬", "火"): -0.06,  # 水克火=阻逆
    ("冬", "土"): -0.06,  # 土克水(反)-冬季水旺见土压
    ("冬", "金"):  0.04,  # 金生水=吉
    ("冬", "水"):  0.00,  # 同气
}

# 岁运太过加成（v4.1调低）
TAIGUO_BONUS = 0.22
# 不及减益
BUJI_MALUS = -0.15

# 均值回归（v4.1调低）
MEAN_REVERSION = 0.015

# 天刑→郁气积累系数
TIANXING_TO_YUQI = 0.04

# ═══════════════════════════════════════════════
# 第5层·胜复郁发模型 — 核心参数
# ═══════════════════════════════════════════════

# 胜气强度系数（太过→所克）
SHENGQI_COEF = 0.15
# 复气反应系数（子复母仇）
FUQI_COEF = 0.18
# 郁气自然月衰减
YUQI_DECAY = 0.02
# 郁发触发阈值
YUFA_THRESHOLD = 0.06
# 郁发释放系数（超阈值→爆发）
YUFA_COEF = 0.55
# 郁发后残值（郁气爆发后不清零，留底继续积累）
YUFA_RESIDUAL = 0.01


def compute_shengfu_yufa(month_idx, wuyun_scores, prev_accumulation=None):
    """
    第5层：胜复郁发模型
    ─────────────────────────────────
    输入：
      month_idx: 月份序号（从1开始）
      wuyun_scores: dict {行: 岁运强度值}，如 {"木": 0.3, "火": -0.1, ...}
      prev_accumulation: dict {行: 郁气积累值}，来自上月的郁气状态

    返回：
      layer5_scores: dict {行: 胜复郁发综合评分}
      new_accumulation: dict {行: 更新的郁气积累（供下月使用）}
      eruption_events: list [行, 强度] 本月发生郁发行的列表
    """
    if prev_accumulation is None:
        prev_accumulation = {wx: 0.0 for wx in WUXING_LIST}

    # ── 1. 胜气计算 ──
    # 每个元素对其所克元素产生胜气
    victory_qi = {wx: 0.0 for wx in WUXING_LIST}

    for wx_a in WUXING_LIST:
        wx_b = KE_CYCLE[wx_a]  # A克B
        a_strength = wuyun_scores.get(wx_a, 0.0)

        # 仅当A的岁运强度>0（太过为正）才产生胜气
        victory = a_strength * SHENGQI_COEF
        if victory > 0:
            # 胜气作用于被克行的B——实际上是对B的压制
            victory_qi[wx_a] = victory
            victory_qi[wx_b] = victory_qi.get(wx_b, 0.0) - victory

    # 司天在泉也产生自然胜气（统治元素压被统治元素）
    # 来自岁运的天然压制——这是稳定的，不算在每月变动里

    # ── 2. 复气计算 ──
    # 子复母仇：A胜B → B生C → C克A，C得到复气bonus
    fuqi = {wx: 0.0 for wx in WUXING_LIST}

    for wx_a in WUXING_LIST:
        wx_b = KE_CYCLE[wx_a]  # A所克
        wx_c = FUXI_CYCLE[wx_a]  # 复A之行（=子复母仇的C）

        a_victory = victory_qi.get(wx_a, 0.0)
        if a_victory > 0:
            # 复气强度 = 胜气强度 × 复气系数
            fuqi[wx_c] = fuqi.get(wx_c, 0.0) + a_victory * FUQI_COEF

    # ── 3. 郁气积累 ──
    # 郁气来源：被胜气压制 + 被复气压制 + 自身不及
    accumulation = {wx: prev_accumulation.get(wx, 0.0) for wx in WUXING_LIST}

    for wx in WUXING_LIST:
        # 被胜气压制（victory_qi负值部分）
        suppressed = -min(0, victory_qi.get(wx, 0.0))
        # 被复气压制（正值表示对某行的复气，负值是被复气压制）
        # 复气作用于"被复之行"——即fuqi中的行是对该行的反向压制
        # 实际上fuqi[wx_c]里负值表示被复气影响
        # 但复气本身就对被复行施加压制
        # 简化：复气正值 = 对FUXI_CYCLE中的行的压制
        for wx_a, wx_c in FUXI_CYCLE.items():
            if wx_c == wx:
                # wx是复仇者，那它不会压自己
                pass
            elif fuqi.get(wx_c, 0.0) > 0:
                # 复仇者wx_c正向，它不会压自己
                pass
        # 对于被复之行：A胜B → C复A，A是被复对象
        # fuqi[C] > 0 表示C在复仇，被复的是A
        for wx_a in WUXING_LIST:
            wx_c = FUXI_CYCLE[wx_a]
            if fuqi.get(wx_c, 0.0) > 0 and wx == wx_a:
                # wx_a是被复对象，被复气压制
                suppressed += fuqi[wx_c] * 0.5

        # 自身不及也产生郁气（运不及 = 自身虚弱，被外界压制）
        if wuyun_scores.get(wx, 0.0) < -0.1:
            suppressed += abs(wuyun_scores[wx]) * 0.3

        # 郁气月积累 = 上期残留 + 新增压制 - 自然衰减
        accumulation[wx] = accumulation.get(wx, 0.0) * (1 - YUQI_DECAY) + suppressed

    # ── 4. 郁发释放 ──
    layer5_scores = {wx: 0.0 for wx in WUXING_LIST}
    eruption_events = []

    for wx in WUXING_LIST:
        if accumulation[wx] > YUFA_THRESHOLD:
            # 郁发！该行正向爆发
            eruption_strength = accumulation[wx] * YUFA_COEF
            layer5_scores[wx] = eruption_strength
            eruption_events.append((wx, eruption_strength))
            # 郁发后：基本清零，留残值继续积累
            accumulation[wx] = YUFA_RESIDUAL

    # 郁发时，爆发行施加反向影响（胜复郁发综合）
    # 再加上复气正向评分
    for wx in WUXING_LIST:
        layer5_scores[wx] += fuqi.get(wx, 0.0)
        # 胜气对自身有正向作用
        victory_self = max(0, victory_qi.get(wx, 0.0))
        layer5_scores[wx] += victory_self * 0.5

    return layer5_scores, accumulation, eruption_events


# ═══════════════════════════════════════════════
# 核心评分函数
# ═══════════════════════════════════════════════

def compute_corrected_score(year, month, prev_accumulation=None,
                            eruption_history=None, options=None):
    """
    五层全链路评分
    ──────────────
    参数:
      year, month: 年份与月份（1=寅月）
      prev_accumulation: dict {行: 郁气积累值}，上月传回
      eruption_history: list 本月已发生的郁发事件（供后续参考）
      options: dict 可选项
        {
          "season_half": False,   # 🅲 季节阻逆全部减半
          "earth_bias": False,    # 🅱 土板块最终评分 -0.08
          "shengfu_enabled": True # 启用第5层胜复郁发（默认开）
        }

    返回:
      result: dict {
        "scores": {行: 综合评分},
        "accumulation": {行: 新版郁气积累},
        "eruption_events": [(行, 强度), ...],
        "layers": {层名: {行: 分项评分},
        "options_applied": [已生效的选项列表]
      }
    """
    opts = options or {}
    season_half = opts.get("season_half", False)
    earth_bias = opts.get("earth_bias", False)
    shengfu_enabled = opts.get("shengfu_enabled", True)

    if prev_accumulation is None:
        prev_accumulation = {wx: 0.0 for wx in WUXING_LIST}
    if eruption_history is None:
        eruption_history = []

    tiangan = "甲乙丙丁戊己庚辛壬癸"

    # ── 第1步：天干 → 岁运 ──
    gan_idx = (year - 4) % 10  # 甲=4
    gan = tiangan[gan_idx]
    wu_yun_el, tai_bu = TIANGAN_WUXING[gan]

    # ── 第1层：岁运太过/不及 ──
    layer1 = {wx: 0.0 for wx in WUXING_LIST}

    if tai_bu == "太过":
        layer1[wu_yun_el] = TAIGUO_BONUS
        # 太过对其所克的行有额外压制（岁运层面的直接压制）
        ke_el = KE_CYCLE[wu_yun_el]
        layer1[ke_el] = -TAIGUO_BONUS * 0.5
    else:
        layer1[wu_yun_el] = BUJI_MALUS

    # ── 第2层：司天在泉 ──
    layer2 = {wx: 0.0 for wx in WUXING_LIST}

    try:
        st_zq = get_sitian_zaiquan(year)
        if isinstance(st_zq, tuple) and len(st_zq) == 2:
            st_name, zq_name = st_zq
            st_wx = LIUQI_WUXING.get(st_name, "")
            zq_wx = LIUQI_WUXING.get(zq_name, "")
            if st_wx and st_wx in layer2:
                layer2[st_wx] = 0.08
            if zq_wx and zq_wx in layer2:
                layer2[zq_wx] = 0.06
    except Exception:
        pass

    # ── 第3层：季节阻逆 ──
    layer3 = {wx: 0.0 for wx in WUXING_LIST}
    season = MONTH_SEASON.get(month, "春")
    season_wx = SEASON_WUXING[season]

    for wx in WUXING_LIST:
        key = (season, wx)
        block_val = SEASON_BLOCK.get(key, 0.0)
        if season_half:
            block_val *= 0.5
        layer3[wx] = block_val

    # ── 第4层：客主加临（天刑→郁气积累） ──
    layer4 = {wx: 0.0 for wx in WUXING_LIST}
    yuqi_from_tianxing = {wx: 0.0 for wx in WUXING_LIST}

    # 用 analyze_year + judge_pattern 分析客主加临格局
    try:
        year_analysis = analyze_year(year)
        if year_analysis and isinstance(year_analysis, dict):
            # Keqi sequence starts from sitian for this year
            sitian_name = year_analysis.get("sitian_liuqi", "")
            keqi_seq = get_keqi_sequence(sitian_name) if sitian_name else []
            step = get_zhuqi_step(month, 15)
            if 1 <= step <= 6:
                zhuqi_name = get_zhuqi_at_step(step)
                keqi_name = get_keqi_at_step(keqi_seq, step) if keqi_seq else ""
                pattern = judge_pattern(zhuqi_name, keqi_name)
                if shengfu_enabled and keqi_name:
                    keqi_wx = LIUQI_WUXING.get(keqi_name, "")
                    if pattern in ["天刑", "不和"] and keqi_wx in yuqi_from_tianxing:
                        yuqi_from_tianxing[keqi_wx] += TIANXING_TO_YUQI
                    elif pattern in ["顺化", "同气"] and keqi_wx in layer4:
                        layer4[keqi_wx] += 0.04
    except Exception:
        pass

    # ── 第5层：胜复郁发 ──
    # 构建岁运强度字典（供第5层用）
    wuyun_strength = {}
    for wx in WUXING_LIST:
        wuyun_strength[wx] = layer1.get(wx, 0.0) + layer2.get(wx, 0.0)

    # 天刑郁气注入
    for wx in WUXING_LIST:
        if shengfu_enabled and yuqi_from_tianxing.get(wx, 0) > 0:
            prev_accumulation[wx] = prev_accumulation.get(wx, 0.0) + yuqi_from_tianxing[wx]

    if shengfu_enabled:
        layer5, new_accumulation, eruption_events = compute_shengfu_yufa(
            month, wuyun_strength, prev_accumulation
        )
    else:
        layer5 = {wx: 0.0 for wx in WUXING_LIST}
        new_accumulation = {wx: prev_accumulation.get(wx, 0.0) for wx in WUXING_LIST}
        eruption_events = []

    # ── 综合评分：5层加总 ──
    scores = {}
    for wx in WUXING_LIST:
        total = (layer1.get(wx, 0.0) + layer2.get(wx, 0.0) +
                 layer3.get(wx, 0.0) + layer4.get(wx, 0.0) +
                 layer5.get(wx, 0.0))

        # 均值回归（远离零点→向零收敛）
        if abs(total) > 0.2:
            total -= total * MEAN_REVERSION

        # 🅱 土板块偏置：仅土板块 final - 0.08
        if earth_bias and wx == "土":
            total -= 0.08

        scores[wx] = round(total, 4)

    # ── 记录已生效选项 ──
    options_applied = []
    if season_half:
        options_applied.append("🅲 季节阻逆减半")
    if earth_bias:
        options_applied.append("🅱 土板块偏置-0.08")
    if shengfu_enabled:
        options_applied.append("✅ 第5层·胜复郁发")
    else:
        options_applied.append("❌ 第5层·胜复郁发(关闭)")

    return {
        "scores": scores,
        "accumulation": new_accumulation,
        "eruption_events": eruption_events,
        "layers": {
            "layer1_岁运": layer1,
            "layer2_司天在泉": layer2,
            "layer3_季节阻逆": layer3,
            "layer4_客主加临": layer4,
            "layer5_胜复郁发": layer5,
        },
        "options_applied": options_applied,
    }


# ═══════════════════════════════════════════════
# 批量回测：支持持续积累
# ═══════════════════════════════════════════════

def run_full_backtest(years=None, options=None):
    """
    跑完整时间序列，积累持续跨月传递
    返回全部分数、郁发事件、淤积状态
    """
    if years is None:
        years = list(range(2011, 2026))
    opts = options or {}

    accumulation = {wx: 0.0 for wx in WUXING_LIST}
    eruption_history = []

    monthly_scores = []
    all_eruptions = []

    for year in years:
        for month in range(1, 13):
            result = compute_corrected_score(
                year, month,
                prev_accumulation=accumulation,
                eruption_history=eruption_history,
                options=opts,
            )

            # 传递积累到下一月
            accumulation = result["accumulation"]
            eruption_history = result["eruption_events"]

            monthly_scores.append({
                "year": year,
                "month": month,
                "scores": result["scores"],
                "accumulation": {k: round(v, 4) for k, v in result["accumulation"].items()},
                "eruption_events": result["eruption_events"],
                "layers": result["layers"],
                "options_applied": result["options_applied"],
            })

            for ev in result["eruption_events"]:
                all_eruptions.append({"year": year, "month": month,
                                      "element": ev[0], "strength": round(ev[1], 4)})

    return monthly_scores, all_eruptions


# ═══════════════════════════════════════════════
# 与v4版本对比测试
# ═══════════════════════════════════════════════

def compare_v4_v5():
    """对比 v4.1 和 v5 在相同年份的输出差异"""
    test_years = [2024]
    opts_v4 = {"shengfu_enabled": False}
    opts_v5 = {"shengfu_enabled": True, "season_half": False, "earth_bias": False}

    v4_result, _ = run_full_backtest(test_years, opts_v4)
    v5_result, v5_eruptions = run_full_backtest(test_years, opts_v5)

    print(f"{'Month':<8} {'v4_earth':<10} {'v5_earth':<10} {'diff':<10} {'eruptions':<20}")
    print("-" * 60)

    for m4, m5 in zip(v4_result, v5_result):
        v4_e = m4["scores"]["土"]
        v5_e = m5["scores"]["土"]
        diff = v5_e - v4_e
        ev_str = ",".join([f"{e[0]}+{round(e[1],3)}" for e in m5["eruption_events"]]) if m5["eruption_events"] else ""
        print(f"{m4['year']}-{m4['month']:<2} {v4_e:<+10.4f} {v5_e:<+10.4f} {diff:<+10.4f} {ev_str}")

    print(f"\n郁发事件数: {len(v5_eruptions)}")
    for ev in v5_eruptions:
        print(f"  {ev['year']}-{ev['month']:02d} {ev['element']} 爆发 +{ev['strength']:.4f}")

    return v4_result, v5_result


if __name__ == "__main__":
    print("═" * 60)
    print("  胜复校正评分引擎 v5  ·  五层全链路")
    print("═" * 60)

    # 快速单月测试
    result = compute_corrected_score(2024, 3, options={
        "season_half": False,
        "earth_bias": False,
        "shengfu_enabled": True,
    })
    print(f"\n2024年3月 评分: {result['scores']}")
    print(f"  郁发事件: {result['eruption_events']}")
    print(f"  郁气积累: {result['accumulation']}")
    print(f"  已生效: {result['options_applied']}")

    # 对比 v4 vs v5
    print("\n" + "═" * 60)
    print("  v4(v5关第5层) vs v5(开第5层) 对比")
    print("═" * 60)
    compare_v4_v5()
