"""
胜复校正评分引擎 v4.1+  ·  四层全链路评分校正
============================================
核心重构：
  ✅ 移除所有年份硬编码
  ✅ 新增「太过反制」：正向信号堆叠超阈值→自动触发反向修正
  ✅ 新增「均值回归」：评分远离零点→向零收敛力
  ✅ 动态郁发：基于客气压制累积而非固定月份
  ✅ 季节阻逆补全五行（原仅木/火/水，缺土/金）

八项修复要点：
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

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import (
    WUYUN_MAP, TIANGAN_WUXING, LIUQI_WUXING, SITIAN_ZAIQUAN,
    SHENG_CYCLE, KE_CYCLE,
    get_ganzhi_for_year, get_sitian_zaiquan, judge_pattern,
    get_zhuqi_at_step, get_keqi_at_step, get_keqi_sequence,
)

# ================================================================
# 客主加临系数 + 格局判断
# ================================================================
KEQI_COEFF = {
    "顺化": 0.10, "逆化": 0.05, "同气": 0.12,
    "小逆": -0.05, "不和": -0.08, "天刑": -0.08,
}

def get_keqi_monthly(year, month):
    """获取指定年月的主客气格局字符串"""
    step_map = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2, 6: 2,
                7: 3, 8: 3, 9: 4, 10: 4, 11: 5, 12: 5}
    step = step_map.get(month, 0)
    zhuqi = get_zhuqi_at_step(step)
    if not zhuqi:
        return "未知"
    sitian, _ = get_sitian_zaiquan(year)
    keqi_seq = get_keqi_sequence(sitian)
    if not keqi_seq:
        return "未知"
    keqi = get_keqi_at_step(keqi_seq, step)
    if not keqi:
        return "未知"
    return judge_pattern(zhuqi, keqi)

PLATES = ["木", "火", "土", "金", "水"]

# 生克链
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}

# 复气链
FUXI_CYCLE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}
FUXI_TARGET = {v: k for k, v in FUXI_CYCLE.items()}

# 季节五行
SEASON_WUXING = {
    1:"木",2:"木",3:"木", 4:"火",5:"火",6:"火",
    7:"土",8:"土", 9:"金",10:"金", 11:"水",12:"水",
}

# 季节阻逆预计算
SEASON_BLOCK = {}
for s_wx in PLATES:
    for p_wx in PLATES:
        if s_wx == p_wx:
            v = 0.12
        elif SHENG.get(s_wx) == p_wx:
            v = 0.08
        elif KE.get(s_wx) == p_wx:
            v = -0.06
        elif SHENG.get(p_wx) == s_wx:
            v = 0.06
        elif KE.get(p_wx) == s_wx:
            v = -0.04
        else:
            v = 0.0
        SEASON_BLOCK[(s_wx, p_wx)] = v

def get_season_block(plate_wx, month):
    return SEASON_BLOCK.get((SEASON_WUXING.get(month, "土"), plate_wx), 0.0)


def compute_corrected_score(plate_wx, year, month,
                            prev_accumulation=None,
                            eruption_history=None):
    """
    核心评分函数 v4.1+
    返回: (score, signals)
    """
    gan_zhi = get_ganzhi_for_year(year)
    if not gan_zhi or len(gan_zhi) < 2:
        return 0.0, []

    tiangan = gan_zhi[0]  # 天干
    wuyun = WUYUN_MAP.get(tiangan, {})
    dayun_wx = wuyun.get("wuxing", "")
    nature = wuyun.get("nature", "平气")
    strength = wuyun.get("strength", 0.5)

    sitian, zaiquan = get_sitian_zaiquan(year)
    st_wx = LIUQI_WUXING.get(sitian, "")
    zq_wx = LIUQI_WUXING.get(zaiquan, "")

    keqi = get_keqi_monthly(year, month)
    qi_factor = KEQI_COEFF.get(keqi, 0.0)

    if prev_accumulation is None:
        prev_accumulation = {p: 0.0 for p in PLATES}
    if eruption_history is None:
        eruption_history = {}

    score = 0.0
    signals = []

    # ======================== 第1层：岁运 ========================
    if dayun_wx and nature == "太过":
        if qi_factor > 0:
            keqi_mod = 1.0
        elif qi_factor < -0.25:
            keqi_mod = 0.0
        elif qi_factor < -0.15:
            keqi_mod = 0.2
        else:
            keqi_mod = 0.5

        if plate_wx == dayun_wx:
            score += strength * 0.22 * keqi_mod
            signals.append(f"岁运太过-调{keqi_mod:.1f}+{strength*0.22*keqi_mod:.3f}")
        elif plate_wx == FUXI_CYCLE.get(dayun_wx, ""):
            score += strength * 0.25
            signals.append(f"复气-{FUXI_CYCLE[dayun_wx]}+{strength*0.25:.3f}")
        elif plate_wx == FUXI_TARGET.get(FUXI_CYCLE.get(dayun_wx, ""), ""):
            score -= strength * 0.35
            signals.append(f"复气克{plate_wx}-{strength*0.35:.3f}")
        elif SHENG.get(dayun_wx) == plate_wx:
            score += strength * 0.10
            signals.append(f"岁运生{plate_wx}+{strength*0.10:.3f}")
        elif KE.get(dayun_wx) == plate_wx:
            score -= strength * 0.12
            signals.append(f"岁运克{plate_wx}-{strength*0.12:.3f}")

    elif dayun_wx and nature == "不及":
        if plate_wx == dayun_wx:
            score -= strength * 0.15
            signals.append(f"岁运不及-{strength*0.15:.3f}")
        elif KE.get(plate_wx) == dayun_wx:
            score -= strength * 0.18
            signals.append(f"所不胜乘{plate_wx}-{strength*0.18:.3f}")
        elif SHENG.get(plate_wx) == dayun_wx:
            score += strength * 0.08
            signals.append(f"所胜侮{plate_wx}+{strength*0.08:.3f}")

    # ======================== 第2层：司天在泉 ========================
    if st_wx:
        if plate_wx == st_wx:
            score += strength * 0.10
            signals.append(f"司天同气+{strength*0.10:.3f}")
        elif KE.get(plate_wx) == st_wx:
            score -= strength * 0.08
            signals.append(f"司天克{plate_wx}-{strength*0.08:.3f}")

    if zq_wx:
        mp = month / 12.0
        if plate_wx == zq_wx:
            score += strength * 0.12 * mp
            signals.append(f"在泉同气({month}/12)+{strength*0.12*mp:.3f}")
        elif KE.get(plate_wx) == zq_wx:
            score -= strength * 0.08 * mp
            signals.append(f"在泉克-{strength*0.08*mp:.3f}")

    # ======================== 第3层：季节阻逆 ========================
    sb = get_season_block(plate_wx, month)
    if abs(sb) > 0.01:
        score += sb
        signals.append(f"季节阻逆{sb:+.3f}")

    # ======================== 第4层：客主加临 ========================
    if qi_factor > 0:
        score += qi_factor * 0.20
        signals.append(f"顺化+{qi_factor*0.20:.3f}")
    elif qi_factor < 0:
        inc = abs(qi_factor) * 0.18
        prev_accumulation[plate_wx] = min(1.0, prev_accumulation.get(plate_wx, 0.0) + inc)
        signals.append(f"复气积累+{inc:.3f}(总{prev_accumulation[plate_wx]:.3f})")

    # ======================== 郁发释放 ========================
    accum = prev_accumulation.get(plate_wx, 0.0)
    last_eruption = eruption_history.get(plate_wx, 0)

    if accum > 0.06 and (month - last_eruption) >= 2:
        release = accum * 0.55
        score += release
        signals.append(f"郁发释放+{release:.3f}(积累{accum:.3f})")
        prev_accumulation[plate_wx] = accum * 0.60
        eruption_history[plate_wx] = month
    elif accum > 0.001:
        mp = month / 12.0
        pen = accum * 0.08 * mp
        score -= pen
        signals.append(f"积累抑制-{pen:.3f}")

    # ======================== 均值回归 ========================
    mr = score * 0.015
    score -= mr
    if abs(mr) > 0.001:
        signals.append(f"均值回归-{mr:.3f}")

    # ======================== 太过反制 ========================
    if score > 0.30:
        anti = (score - 0.30) * 0.25
        score -= anti
        signals.append(f"太过反制-{anti:.3f}")
    elif score < -0.30:
        anti = (score + 0.30) * 0.25
        score -= anti
        signals.append(f"不及反制+{abs(anti):.3f}")

    return max(-0.8, min(0.8, score)), signals


# ======================== 工具函数 ========================
def load_test_suite(path=None):
    if path is None:
        path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_corrected(test_data):
    """严格方向评估"""
    correct = total = 0
    for year_str, year_data in test_data.items():
        year = int(year_str)
        for m_entry in year_data.get("months", []):
            m = m_entry.get("m", 0)
            for p in PLATES:
                if p not in m_entry:
                    continue
                act = m_entry[p]
                ad = 1 if act >= 4 else (-1 if act <= -4 else 0)
                score, _ = compute_corrected_score(p, year, m, {}, {})
                pd = 1 if score >= 0.03 else (-1 if score <= -0.03 else 0)
                if ad != 0 and pd != 0:
                    total += 1
                    if pd == ad:
                        correct += 1
    return correct, total, correct / total if total > 0 else 0


def correlation_analysis(test_data):
    """评分与实际涨跌幅的相关系数"""
    corrs = {}
    for p in PLATES:
        scores = []
        actuals = []
        for year_str, year_data in test_data.items():
            year = int(year_str)
            for m_entry in year_data.get("months", []):
                m = m_entry.get("m", 0)
                if p not in m_entry:
                    continue
                actuals.append(m_entry[p])
                score, _ = compute_corrected_score(p, year, m, {}, {})
                scores.append(score)
        if len(scores) < 3:
            corrs[p] = 0.0
            continue
        n = len(scores)
        sx, sy = sum(scores), sum(actuals)
        sxx = sum(x * x for x in scores)
        syy = sum(y * y for y in actuals)
        sxy = sum(scores[i] * actuals[i] for i in range(n))
        denom = (n * sxx - sx * sx) * (n * syy - sy * sy)
        corrs[p] = round((n * sxy - sx * sy) / (denom ** 0.5 + 1e-10), 4)
    return corrs


if __name__ == "__main__":
    print("=" * 60)
    print("胜复校正评分引擎 v4.1+ · 诊断")
    print("=" * 60)
    td = load_test_suite()

    print("\n=== 方向准确率 ===")
    for y in [2024, 2025]:
        f = {str(y): td[str(y)]}
        c, t, r = evaluate_corrected(f)
        print(f"  {y}年: {c}/{t} = {r:.1%}")
    c, t, r = evaluate_corrected(td)
    print(f"  联合: {c}/{t} = {r:.1%}")

    corrs = correlation_analysis(td)
    print("\n=== 相关系数 r ===")
    for p in PLATES:
        c = corrs[p]
        mk = "🟢" if c > 0.1 else ("🔴" if c < -0.1 else "⚪")
        print(f"  {mk} {p}: r = {c:.4f}")

    # 土板块逐月明细
    print("\n=== 土板块逐月 ===")
    print(f'{"月":>6} {"评分":>8} {"实际%":>6}  →')
    print("-" * 35)
    for y in [2024, 2025]:
        for me in td[str(y)]["months"]:
            m = me["m"]
            act = me.get("土", 0)
            score, signals = compute_corrected_score("土", y, m, {}, {})
            pd = "涨" if score > 0.04 else ("跌" if score < -0.04 else "震")
            ad = "涨" if act >= 4 else ("跌" if act <= -4 else "震")
            ok = pd == ad
            print(f"{'✅' if ok else '❌'} {y}-{m:02d}  {score:+8.4f}  {act:+6.1f}%  {pd}->{ad}")
            if signals:
                print(f"      {', '.join(signals[:4])}")
