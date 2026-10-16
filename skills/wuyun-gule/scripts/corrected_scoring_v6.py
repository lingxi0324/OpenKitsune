#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五运六气评分引擎 v6.0 — 司天在泉·客气层全面优化版

核心改动：
1. 司天在泉从2维→6维（同气/生扶/被生/被克/所胜/所不胜），含S曲线权重
2. 客气从笼统KEQI_COEFF→细化到客气五行与板块五行生克
3. 在泉权重从线性month/12→S曲线 
4. 岁运+客气交互加强
5. 修复WUYUN_MAP数据结构（值=dict，含wuxing/nature/strength）
"""
import sys, os, math, json, random, csv
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from wuyun_core import (
    TIANGAN_WUXING, LIUQI_WUXING, SITIAN_ZAIQUAN,
    SHENG_CYCLE, KE_CYCLE,
    get_ganzhi_for_year, get_sitian_zaiquan, judge_pattern,
    get_zhuqi_at_step, get_keqi_at_step, get_keqi_sequence,
)

# ========== 基础常量 ==========
PLATES = ['木', '火', '土', '金', '水']

# 五行生克
SHENG = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
KE = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}
FUXI_CYCLE = {'木': '金', '火': '水', '土': '木', '金': '火', '水': '土'}
FUXI_TARGET = {'金': '木', '水': '火', '木': '土', '火': '金', '土': '水'}

# 五运六气专用：太大过=太过
TAI_WUXING = {'甲':'土', '乙':'金', '丙':'水', '丁':'木', '戊':'火',
              '己':'土', '庚':'金', '辛':'水', '壬':'木', '癸':'火'}

# ========== 完整WUYUN_MAP（修复：值=dict含wuxing/nature/strength）==========
# 甲己化土，乙庚化金，丙辛化水，丁壬化木，戊癸化火
# 太过：甲/丙/戊/庚/壬 | 不及：乙/丁/己/辛/癸
# 太过当年=+1.2倍，不及当年=0.8倍
WUYUN_MAP = {
    '甲': {'wuxing': '土', 'nature': '太过', 'strength': 0.9},
    '乙': {'wuxing': '金', 'nature': '不及', 'strength': 0.7},
    '丙': {'wuxing': '水', 'nature': '太过', 'strength': 0.9},
    '丁': {'wuxing': '木', 'nature': '不及', 'strength': 0.7},
    '戊': {'wuxing': '火', 'nature': '太过', 'strength': 0.9},
    '己': {'wuxing': '土', 'nature': '不及', 'strength': 0.7},
    '庚': {'wuxing': '金', 'nature': '太过', 'strength': 0.9},
    '辛': {'wuxing': '水', 'nature': '不及', 'strength': 0.7},
    '壬': {'wuxing': '木', 'nature': '太过', 'strength': 0.9},
    '癸': {'wuxing': '火', 'nature': '不及', 'strength': 0.7},
}

# 客气格局系数（保留，但仅用于岁运+客气交互的修饰因子）
KEQI_COEFF = {
    '顺化': 0.10,   # 客气生主气 → 顺→利好
    '逆化': 0.05,   # (旧称，实为客气被主气所生 → 气交平顺)
    '同气': 0.12,   # 主客气相同 → 同气→共振加强
    '小逆': -0.05,  # 主气生客气 → 主从颠倒→微逆
    '不和': -0.08,  # 主气克客气 → 客气受压→不顺
    '天刑': -0.08,  # 客气克主气 → 气交乖张→阻逆
}

# ========== Season Block（季节阻逆，与之前一致）==========
SEASON_WUXING = {1:'木', 2:'木', 3:'木', 4:'火', 5:'火', 6:'火',
                 7:'土', 8:'土', 9:'金', 10:'金', 11:'水', 12:'水'}

SEASON_BLOCK = {}
for season_wx in PLATES:
    for plate_wx in PLATES:
        if plate_wx == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.12  # 同气→得令
        elif SHENG[season_wx] == plate_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.08  # 季节生板块
        elif KE[season_wx] == plate_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = -0.06  # 季节克板块
        elif SHENG[plate_wx] == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.06  # 板块生季节
        elif KE[plate_wx] == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = -0.04  # 板块克季节

# ========== 核心函数：获取每月客主加临格局 ==========
def get_keqi_monthly(year, month):
    """获取指定年月的主客气格局字符串"""
    step_map = {1:0, 2:0, 3:1, 4:1, 5:2, 6:2, 7:3, 8:3, 9:4, 10:4, 11:5, 12:5}
    step = step_map.get(month, 0)
    zhuqi = get_zhuqi_at_step(step)
    if not zhuqi:
        return None, None
    sitian, _ = get_sitian_zaiquan(year)
    keqi_seq = get_keqi_sequence(sitian)
    if not keqi_seq:
        return None, None
    keqi = get_keqi_at_step(keqi_seq, step)
    if not keqi:
        return None, None
    pattern = judge_pattern(zhuqi, keqi)
    return pattern, keqi

# ========== 实用函数 ==========
def sigmoid(x, center=6.0, k=1.2):
    """S曲线：上半年→0（司天主导），中下旬过渡，下半年→1（在泉主导）"""
    return 1.0 / (1.0 + math.exp(-k * (x - center)))

def get_season_block(plate_wx, month):
    """季节阻逆系数"""
    season_wx = SEASON_WUXING.get(month, '')
    if not season_wx:
        return 0.0
    return SEASON_BLOCK.get((plate_wx, season_wx), 0.0)

# ========== 核心评分函数 v6.0 ==========
def compute_score_v6(plate_wx, year, month,
                     prev_accumulation=None,
                     eruption_history=None):
    """
    增强评分函数 v6.0
    返回: (score, signals, detail_dict)
    """
    gan_zhi = get_ganzhi_for_year(year)
    if not gan_zhi or len(gan_zhi) < 2:
        return 0.0, [], {}

    tiangan = gan_zhi[0]
    wuyun = WUYUN_MAP.get(tiangan, {})
    dayun_wx = wuyun.get("wuxing", "")
    nature = wuyun.get("nature", "平气")
    strength = wuyun.get("strength", 0.5)

    # ====== 基础数据准备 ======
    sitian, zaiquan = get_sitian_zaiquan(year)
    st_wx = LIUQI_WUXING.get(sitian, "")
    zq_wx = LIUQI_WUXING.get(zaiquan, "")

    keqi_pattern, keqi_name = get_keqi_monthly(year, month)
    # 客气六气对应的五行
    keqi_wx = LIUQI_WUXING.get(keqi_name, "") if keqi_name else ""

    if prev_accumulation is None:
        prev_accumulation = {p: 0.0 for p in PLATES}
    if eruption_history is None:
        eruption_history = {}

    score = 0.0
    signals = []
    details = {}

    # ======================== 第1层：岁运（保留v4.1核心逻辑）====================
    # 岁运+客气交互：客气顺化→利好传导，客气逆化→阻逆减弱
    keqi_mod = 1.0
    if keqi_pattern:
        qi_c = KEQI_COEFF.get(keqi_pattern, 0.0)
        if qi_c > 0.05:
            keqi_mod = 1.3   # 顺化/同气→利好放大
        elif qi_c < -0.05:
            keqi_mod = 0.3   # 小逆/不和/天刑→严重削弱
        elif qi_c < 0:
            keqi_mod = 0.6   # 轻度逆化→部分削弱

    if dayun_wx and nature == "太过":
        tai_cfg = {
            'self':     {'coeff': 0.22, 'cond': lambda pw: pw == dayun_wx},
            'fuxi':     {'coeff': 0.25, 'cond': lambda pw: pw == FUXI_CYCLE.get(dayun_wx, '')},
            'fuxi_k':   {'coeff': -0.35, 'cond': lambda pw: pw == FUXI_TARGET.get(FUXI_CYCLE.get(dayun_wx, ''), '')},
            'sheng':    {'coeff': 0.10, 'cond': lambda pw: SHENG.get(dayun_wx) == pw},
            'ke':       {'coeff': -0.12, 'cond': lambda pw: KE.get(dayun_wx) == pw},
        }
        for key, cfg in tai_cfg.items():
            if cfg['cond'](plate_wx):
                val = strength * cfg['coeff'] * keqi_mod
                score += val
                signals.append(f"岁运太过-{key}-调{keqi_mod:.1f}{val:+.3f}")
                break

    elif dayun_wx and nature == "不及":
        bu_cfg = [
            ('self', lambda pw: pw == dayun_wx, strength * (-0.15) * (1.0 if keqi_mod > 0.8 else 0.6)),
            ('sheng_cheng', lambda pw: KE.get(pw) == dayun_wx, strength * (-0.18)),
            ('wu', lambda pw: SHENG.get(pw) == dayun_wx, strength * 0.08),
        ]
        for key, cond, val in bu_cfg:
            if cond(plate_wx):
                score += val
                signals.append(f"岁运不及-{key}{val:+.3f}")
                break

    # ======================== 第2层：司天在泉·6维生克优化 =====================
    if st_wx:
        st_config = {
            '同气':   (1.0,  lambda pw: pw == st_wx),
            '生扶':   (0.8,  lambda pw: SHENG.get(st_wx) == pw),    # 司天生板块
            '被生':   (0.4,  lambda pw: SHENG.get(pw) == st_wx),    # 板块生司天
            '被克':   (-0.6, lambda pw: KE.get(st_wx) == pw),       # 司天克板块
            '所胜':   (-0.4, lambda pw: KE.get(pw) == st_wx),       # 板块克司天(犯上)
            '所不胜': (-0.2, lambda pw: st_wx == SHENG.get(KE.get(pw, ''), '')),  # 所不胜
        }
        for rel, (coeff, cond) in st_config.items():
            if cond(plate_wx):
                # 司天权重=全年稳定，但上半年（1-6月）略强用反S曲线
                sw = 1.0 - 0.3 * sigmoid(month, 3, 1.5)  # 上半年强，下半年稍弱
                val = strength * coeff * 0.10 * sw
                score += val
                signals.append(f"司天{rel}{val:+.3f}")
                details['sitian'] = rel
                break

    if zq_wx:
        # 在泉权重S曲线：上半年弱→下半年渐强
        zw = sigmoid(month, center=6.5, k=1.2)  # 7月开始渐强，年底达峰
        zq_config = {
            '同气':   1.0,
            '板块生在泉': 0.4,   # 板块生在泉
            '在泉生板块': 0.6,   # 在泉生板块  
            '在泉克板块': -0.5,  # 在泉克板块
            '板块克在泉': -0.3,  # 板块克在泉(犯上)
        }
        # 判断在泉与板块的关系
        if plate_wx == zq_wx:
            rel = '同气'
            coeff = zq_config[rel]
        elif SHENG.get(zq_wx) == plate_wx:
            rel = '在泉生板块'
            coeff = zq_config[rel]
        elif SHENG.get(plate_wx) == zq_wx:
            rel = '板块生在泉'
            coeff = zq_config[rel]
        elif KE.get(zq_wx) == plate_wx:
            rel = '在泉克板块'
            coeff = zq_config[rel]
        elif KE.get(plate_wx) == zq_wx:
            rel = '板块克在泉'
            coeff = zq_config[rel]
        else:
            rel, coeff = None, 0.0

        if rel:
            val = strength * coeff * 0.10 * zw
            score += val
            signals.append(f"在泉{rel}{val:+.3f}")
            details['zaiquan'] = rel

    # ======================== 第3层：季节阻逆（保持）====================
    sb = get_season_block(plate_wx, month)
    if abs(sb) > 0.01:
        score += sb
        signals.append(f"季节阻逆{sb:+.3f}")

    # ======================== 第4层：客气五行细化 =====================
    if keqi_wx and plate_wx:
        # 客气五行与板块五行的生克关系
        if keqi_wx == plate_wx:
            qi_val = 0.08  # 客气同气→共振
            signals.append(f"客气-同气{qi_val:+.3f}")
        elif SHENG.get(keqi_wx) == plate_wx:
            qi_val = 0.06  # 客气生板块→利好
            signals.append(f"客气-生扶{qi_val:+.3f}")
        elif SHENG.get(plate_wx) == keqi_wx:
            qi_val = -0.04  # 板块生客气→耗泄
            signals.append(f"客气-耗泄{qi_val:+.3f}")
        elif KE.get(keqi_wx) == plate_wx:
            qi_val = -0.07  # 客气克板块→利空
            signals.append(f"客气-克伐{qi_val:+.3f}")
        elif KE.get(plate_wx) == keqi_wx:
            qi_val = 0.03   # 板块克客气→有利
            signals.append(f"客气-板块制{qi_val:+.3f}")
        else:
            qi_val = 0.0
        
        if abs(qi_val) > 0.001:
            score += qi_val
            details['keqi_wuxing'] = keqi_wx

    # ======================== 郁发积累/释放（保留）====================
    if keqi_pattern and plate_wx:
        qi_c = KEQI_COEFF.get(keqi_pattern, 0.0)
        if qi_c < 0:
            inc = abs(qi_c) * 0.18
            prev_accumulation[plate_wx] = min(1.0, prev_accumulation.get(plate_wx, 0.0) + inc)
            signals.append(f"复气积累+{inc:.3f}(总{prev_accumulation[plate_wx]:.3f})")

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

    return max(-0.8, min(0.8, score)), signals, details


# ========== 回环兼容接口（保持与旧版一致）==========
def compute_corrected_score(plate_wx, year, month,
                            prev_accumulation=None,
                            eruption_history=None):
    """v6版评分 - 兼容旧接口"""
    score, signals, _ = compute_score_v6(plate_wx, year, month,
                                          prev_accumulation, eruption_history)
    return score, signals


# ========== 相关系数计算 ==========
def calc_pearsonr(scores, actuals):
    """计算Pearson相关系数"""
    n = len(scores)
    if n < 3:
        return 0.0
    sx, sy = sum(scores), sum(actuals)
    sxx = sum(x*x for x in scores)
    syy = sum(y*y for y in actuals)
    sxy = sum(scores[i]*actuals[i] for i in range(n))
    denom = (n*sxx - sx*sx) * (n*syy - sy*sy)
    if denom <= 0:
        return 0.0
    return (n*sxy - sx*sy) / (denom ** 0.5 + 1e-10)


def bootstrap_ci(scores, actuals, n_iter=10000, n_resample=None):
    """Bootstrap置信区间"""
    n = len(scores)
    if n < 3:
        return 0.0, 0.0, 0.0, 0.0
    if n_resample is None:
        n_resample = n
    r_orig = calc_pearsonr(scores, actuals)
    r_samples = []
    for _ in range(n_iter):
        idx = [random.randint(0, n-1) for _ in range(n_resample)]
        rs = [scores[i] for i in idx]
        ra = [actuals[i] for i in idx]
        r_samples.append(calc_pearsonr(rs, ra))
    r_samples.sort()
    ci_low = r_samples[int(n_iter * 0.025)]
    ci_high = r_samples[int(n_iter * 0.975)]
    pos_pct = sum(1 for r in r_samples if r > 0) / n_iter * 100
    median_r = r_samples[n_iter // 2]
    return r_orig, median_r, ci_low, ci_high, pos_pct


# ========== 全样本验证 ==========
def load_monthly_data(csv_path=None):
    """加载wuxing_monthly_summary.csv"""
    if csv_path is None:
        # 搜索可能的位置
        candidates = [
            'wuxing_monthly_summary.csv',
            os.path.join(SCRIPT_DIR, 'wuxing_monthly_summary.csv'),
            os.path.join(SCRIPT_DIR, '..', 'wuxing_monthly_summary.csv'),
            os.path.join(SCRIPT_DIR, '..', '..', 'wuxing_monthly_summary.csv'),
            'skills/wuyun-gule/wuxing_monthly_summary.csv',
        ]
        for c in candidates:
            if os.path.exists(c):
                csv_path = c
                break
    
    if not csv_path or not os.path.exists(csv_path):
        print(f"[错误] 找不到数据文件，请指定路径")
        return None
    
    print(f"[加载] {csv_path}")
    data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    print(f"[加载] 共{len(data)}行数据")
    return data


def run_full_validation(data, use_v6=True):
    """跑全样本验证"""
    wx_map = {'木':'木', '火':'火', '土':'土', '金':'金', '水':'水'}
    
    results = {}
    for wx in PLATES:
        scores = []
        actuals = []
        for row in data:
            try:
                year = int(row.get('year', 0))
                month = int(row.get('month', 0))
            except (ValueError, KeyError):
                continue
            col = f"avg_{wx}" if f"avg_{wx}" in row else wx
            actual = float(row.get(col, 0))
            
            if use_v6:
                s, _ = compute_score_v6(wx, year, month, {}, {})
            else:
                s, _ = compute_corrected_score(wx, year, month, {}, {})
            
            # 只保留有涨跌幅数据且正常的月份
            if abs(actual) > 0.001 and abs(actual) < 50:
                scores.append(s)
                actuals.append(actual)
        
        n = len(scores)
        r, r_m, ci_l, ci_h, pct = bootstrap_ci(scores, actuals, n_iter=5000)
        
        results[wx] = {
            'n': n,
            'r': round(r, 4),
            'median_r': round(r_m, 4),
            'ci_95': [round(ci_l, 4), round(ci_h, 4)],
            'pos_pct': round(pct, 1),
            'significant': ci_l > 0 or ci_h < 0,
        }
    
    return results


def print_results(results, label="验证结果"):
    """打印结果"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"{'五行':>4} {'样本':>6} {'r':>8} {'中位数':>8} {'95% CI':>16} {'正值%':>8} {'显著':>6}")
    print("-"*60)
    for wx in PLATES:
        r = results[wx]
        ci = f"[{r['ci_95'][0]:.3f}, {r['ci_95'][1]:.3f}]"
        sig = "✅" if r['significant'] else "❌"
        print(f"{wx:>4} {r['n']:>6} {r['r']:>8.4f} {r['median_r']:>8.4f} {ci:>16} {r['pos_pct']:>7.1f}% {sig:>6}")


def leave_one_year_validation(data, use_v6=True):
    """留一年交叉验证"""
    years = sorted(set(int(r.get('year', 0)) for r in data if int(r.get('year', 0)) > 2010))
    print(f"\n{'='*60}")
    print(f"  留一年交叉验证 (v{'6' if use_v6 else '4'}版)")
    print(f"{'='*60}")
    
    for target_year in years:
        train = [r for r in data if int(r.get('year', 0)) != target_year]
        test = [r for r in data if int(r.get('year', 0)) == target_year]
        
        for wx in PLATES:
            scores, actuals = [], []
            for row in test:
                try:
                    year = int(row.get('year', 0))
                    month = int(row.get('month', 0))
                except (ValueError, KeyError):
                    continue
                col = f"avg_{wx}" if f"avg_{wx}" in row else wx
                actual = float(row.get(col, 0))
                if abs(actual) > 0.001 and abs(actual) < 50:
                    if use_v6:
                        s, _ = compute_score_v6(wx, year, month, {}, {})
                    else:
                        s, _ = compute_corrected_score(wx, year, month, {}, {})
                    scores.append(s)
                    actuals.append(actual)
            
            if len(scores) >= 3:
                r = calc_pearsonr(scores, actuals)
                if wx == '土':
                    print(f"  留{target_year}: 土板块 r={r:.4f} (n={len(scores)})")


def compare_v4_v6(data):
    """对比v4和v6版本"""
    print(f"\n{'='*60}")
    print(f"  版本对比: v4(旧) vs v6(新)")
    print(f"{'='*60}")
    print(f"{'五行':>4} {'v4 r':>8} {'v6 r':>8} {'v4中位数':>10} {'v6中位数':>10} {'v4正值%':>8} {'v6正值%':>8} {'变化':>8}")
    print("-"*60)
    
    v4 = run_full_validation(data, use_v6=False)
    v6 = run_full_validation(data, use_v6=True)
    
    for wx in PLATES:
        r4 = v4[wx]['r']
        r6 = v6[wx]['r']
        m4 = v4[wx]['median_r']
        m6 = v6[wx]['median_r']
        p4 = v4[wx]['pos_pct']
        p6 = v6[wx]['pos_pct']
        delta = r6 - r4
        print(f"{wx:>4} {r4:>8.4f} {r6:>8.4f} {m4:>10.4f} {m6:>10.4f} {p4:>7.1f}% {p6:>7.1f}% {delta:>+8.4f}")
    
    return v4, v6


if __name__ == '__main__':
    import sys
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    data = load_monthly_data(csv_path)
    if data:
        v4, v6 = compare_v4_v6(data)
        leave_one_year_validation(data, use_v6=True)
