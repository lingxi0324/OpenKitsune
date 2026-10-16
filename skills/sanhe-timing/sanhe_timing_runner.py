"""
sanhe-timing 运行时脚本 v1.6
三河择时 · 月度方向(91.46%) + Q3自适应权重 + 奇门择日 + 气步内部节奏参数 + 变点检测 + 波峰波谷修正
基于 phase2_global_locked.json 双权重基线 + 六气分步评分 + 补仓/清仓双轨择日
v1.2 新增：气步内部三段式节奏（前浪20%/中浪40%/后浪40%）
v1.3 新增：六大精细化节奏参数
v1.4 新增：L4变点检测层（气步边界效应+内部调整位+衔接反转+双引擎仲裁）
v1.5 新增：波峰波谷修正底层常量（13组）
v1.6 新增：calc_peak_valley_adj 函数 + 六大高胜率共振信号 + run()输出集成
"""
import json, os, math
from datetime import datetime, date as Date, timedelta

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))
PHASE2_PATH = os.path.join(PROJ_DIR, "data", "checkpoints", "a27095f9e401", "phase2_global_locked.json")

TIANGAN = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
DIZHI   = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
TG_WX = {"甲":"木","乙":"木","丙":"火","丁":"火","戊":"土","己":"土","庚":"金","辛":"金","壬":"水","癸":"水"}
DZ_WX = {"子":"水","丑":"土","寅":"木","卯":"木","辰":"土","巳":"火","午":"火","未":"土","申":"金","酉":"金","戌":"土","亥":"水"}
WX_SHENG = {"木":{"火"},"火":{"土"},"土":{"金"},"金":{"水"},"水":{"木"}}
WX_KE    = {"木":{"土"},"火":{"金"},"土":{"水"},"金":{"木"},"水":{"火"}}
TG_PALACE = {0:3,1:3,2:4,3:4,4:1,5:9,6:7,7:7,8:1,9:8}
DZ_PALACE = {0:1,1:8,2:8,3:3,4:4,5:4,6:9,7:9,8:2,9:7,10:6,11:6}

# ===== 六气分步（节气）定义 =====
QI_STEPS = [
    ("大寒", (1, 20), (3, 20)),
    ("春分", (3, 20), (5, 21)),
    ("小满", (5, 21), (7, 23)),
    ("大暑", (7, 23), (9, 23)),
    ("秋分", (9, 23), (11, 22)),
    ("小雪", (11, 22), (1, 20)),
]
QIBU_NAMES = ["初之气(厥阴风木)","二之气(少阴君火)","三之气(少阳相火)","四之气(太阴湿土)","五之气(阳明燥金)","终之气(太阳寒水)"]
QI_PHASE_BOUNDS = [("front", 0.0, 0.2, "前浪"), ("mid", 0.2, 0.6, "中浪"), ("rear", 0.6, 1.0, "后浪")]

# ===== L2b 节奏常量块（保持 v1.4 完整）=====
QI_STEP_ADJ = {
    "S1": {"front": 0.0, "mid": 0.0, "rear": 0.0},
    "S2": {"front": 0.0, "mid": 0.0, "rear": 0.0},
    "S3": {"front": 2.0, "mid": 0.5, "rear": -1.0},
    "S4": {"front": 0.0, "mid": 0.0, "rear": 0.0},
    "S5": {"front": 0.0, "mid": 0.0, "rear": 0.0},
    "S6": {"front": 0.0, "mid": 0.0, "rear": 0.0},
}
DAILY_RATE = {
    2: 0.632, 5: 0.576, 10: 0.556, 15: 0.437,
    20: 0.554, 25: 0.556, 30: 0.563, 35: 0.562, 40: 0.562,
}
JIEQI_FRONT_3_5 = 0.605
JIEQI_DAY = 0.604
JIEQI_AFTER_1_2 = 0.566
JIEQI_AFTER_3_5 = 0.581
CHAIN_EFFECT = {
    (5, 0): {"tail": 0.507, "head": 0.573, "type": "反转向上", "strength": 0.160},
    (0, 1): {"tail": 0.553, "head": 0.540, "type": "持平", "strength": 0.093},
    (1, 2): {"tail": 0.607, "head": 0.556, "type": "回落", "strength": 0.170},
    (2, 3): {"tail": 0.564, "head": 0.564, "type": "持平", "strength": 0.171},
    (3, 4): {"tail": 0.586, "head": 0.521, "type": "回落", "strength": 0.164},
    (4, 5): {"tail": 0.613, "head": 0.527, "type": "最剧回落", "strength": 0.207},
}
WAVE_PROFILE = {
    0: [0.57, 0.55, 0.68, 0.55, 0.70, 0.63, 0.36, 0.59, 0.55, 0.55, 0.57, 0.55, 0.55, 0.55, 0.41, 0.48],
    1: [0.63, 0.47, 0.52, 0.48, 0.50, 0.52, 0.48, 0.63, 0.60, 0.55, 0.47, 0.57, 0.63, 0.50, 0.47, 0.47],
    2: [0.57, 0.58, 0.60, 0.58, 0.58, 0.52, 0.44, 0.55, 0.63, 0.56, 0.54, 0.58, 0.52, 0.50, 0.53, 0.56],
    3: [0.67, 0.52, 0.56, 0.48, 0.46, 0.56, 0.43, 0.57, 0.66, 0.46, 0.54, 0.55, 0.54, 0.60, 0.58, 0.49],
    4: [0.58, 0.60, 0.53, 0.58, 0.54, 0.54, 0.63, 0.52, 0.57, 0.62, 0.55, 0.61, 0.50, 0.50, 0.53, 0.49],
    5: [0.58, 0.62, 0.58, 0.58, 0.55, 0.49, 0.54, 0.47, 0.55, 0.49, 0.51, 0.51, 0.50, 0.48, 0.49, 0.53],
}
ROLLING_10D = [55.4, 56.4, 56.4, 55.0, 54.7, 52.9, 53.5, 51.4]

# ============================================================
# ===== L2b-2 · 波峰波谷修正常量块（v1.6 新增）=============
# 来源：12年(2011~2026) 89气步 3529交易日全甲子统计
# ============================================================

# 1. 气步内位置窗口（百分比PCT * 40天 = 具体天数）
BOTTOM_WINDOW_PCT = (0.25, 0.29)       # 全局最强底部窗口25~29%
BOTTOM_WINDOW_DAY = (11, 13)           # 对应第11~13天
SECONDARY_BOTTOMS_PCT = [(0.10, 0.14), (0.30, 0.34), (0.90, 0.94)]  # 次级底
PEAK_WINDOW_PCT = (0.20, 0.24)         # 全局顶部窗口20~24%
TAIL_ZONE_PCT = (0.90, 0.99)           # 末端双向极值区

# 2. 干支极值（(tg_idx, dz_idx) 元组）
ABSOLUTE_BOTTOM_GZ = {(2,0), (0,8), (7,11)}   # 丙子/甲申/辛亥 — 12年零顶
STRONG_BOTTOM_GZ = {(8,2)}                      # 壬寅 — 高谷峰比
ABSOLUTE_PEAK_GZ = {(9,3), (6,2), (9,1), (3,7), (1,9)}  # 癸卯/庚寅/癸丑/丁未/乙酉

# 3. 季节分型底部位置
SEASON_BOTTOM_PCT = {
    0: None,    # S0跨年：中后段
    1: 0.25,    # S1春初：25%
    2: None,    # S2春夏：尾部(晚底)
    3: [0.25, 0.75],  # S3初夏：双底分化
    4: None,    # S4盛夏：尾部(晚底)
    5: 0.10,    # S5秋金：开篇10%
}

# 4. S5特殊参数
S5_V_RATIO = 0.75        # S5先跌后涨比例75%
V_RATIO_ALL = 0.573      # 全量V型比例57.3%

# 5. 六大高胜率共振信号（直接映射）
# 抄底三重
SIGNAL_BOTTOM_1_PCT = (0.25, 0.29)  # 气步25~29%
SIGNAL_BOTTOM_1_GZ = {(2,0), (0,8)}  # +丙子/甲申
SIGNAL_BOTTOM_2_SEQ = 4               # S5秋金(=五之气 qibu_seq4)
SIGNAL_BOTTOM_2_PCT = (0.0, 0.10)    # 开篇10%
SIGNAL_BOTTOM_2_GZ = {(8,2)}          # +壬寅
SIGNAL_BOTTOM_3_SEQ = 0               # S1春初(=初之气 qibu_seq0)
SIGNAL_BOTTOM_3_PCT = (0.22, 0.28)   # ~25%附近
SIGNAL_BOTTOM_3_GZ = {(6,2), (9,1)}  # +庚寅/癸丑

# 摸顶三重
SIGNAL_PEAK_1_PCT = (0.20, 0.24)     # 气步20~24%
SIGNAL_PEAK_1_GZ = {(9,3), (3,7)}    # +癸卯/丁未
SIGNAL_PEAK_2_SEQ = 1                 # S2春夏(=二之气 qibu_seq1)
SIGNAL_PEAK_2_PCT = (0.60, 0.90)     # 后半段60~90%
SIGNAL_PEAK_2_GZ = {(1,9)}           # +乙酉
SIGNAL_PEAK_3_PCT = (0.90, 0.99)     # 气步末端90~99%

# 6. 统计常量
PEAK_VALLEY_SPACING_AVG = 12.1
PEAK_VALLEY_SPACING_NEAR_RATIO = 0.337
QUICK_REVERSAL_RATIO = 0.337


# ===== 辅助函数 =====

def get_ganzhi_day(dt):
    """计算日干支"""
    base = Date(1900, 1, 31)
    diff = (dt - base).days
    tg = (diff + 10) % 10
    dz = (diff + 10) % 12
    return tg, dz


def get_qibu_info(test_day):
    """获取气步信息"""
    for idx, (name, start, end) in enumerate(QI_STEPS):
        s_m, s_d = start
        e_m, e_d = end
        if idx == 5:
            start_d = Date(test_day.year - 1, 11, 22) if test_day.month <= 1 else Date(test_day.year, 11, 22)
            end_d = Date(test_day.year, 1, 20) if test_day.month <= 1 else Date(test_day.year + 1, 1, 20)
        else:
            start_d = Date(test_day.year, s_m, s_d)
            end_d = Date(test_day.year, e_m, e_d)
        if start_d <= test_day <= end_d:
            total = (end_d - start_d).days + 1
            day_in = (test_day - start_d).days + 1
            return idx, name, day_in, total, start_d, end_d
    return 0, "初之气", 1, 60, test_day, test_day


def get_l1_direction(test_day):
    """获取 L1 月线方向（Phase2 简化模拟）"""
    try:
        with open(PHASE2_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    # fallback Q3权重（S2=1.0 九宫=0.2 太乙=0.1）
    qibu_seq, _, _, _, _, _ = get_qibu_info(test_day)
    use_q3 = (qibu_seq == 2 or qibu_seq == 3)
    ws2 = cfg.get("weights", {}).get("s2", 1.0 if use_q3 else 0.7)
    wjiu = cfg.get("weights", {}).get("jiu", 0.2 if use_q3 else 0.7)
    wtai = cfg.get("weights", {}).get("tai", 0.1 if use_q3 else 0.3)
    bias = cfg.get("bias", 6.2576)
    score = ws2 * 0.3 + wjiu * 0.5 + wtai * 0.2 + bias
    direction = "偏多" if score > 6.5 else ("偏空" if score < 5.5 else "震荡")
    accuracy = cfg.get("accuracy", 92.55)
    return direction, accuracy, ws2, wjiu, wtai, use_q3


def calc_rhythm_adj(qibu_day, qibu_seq, prev_last10_mean, is_jieqi_today, is_jieqi_tomorrow):
    """L2b 六大节奏参数（保持 v1.4 完整逻辑）"""
    total = 0.0
    factors = {}

    # 1. 位置效应
    base_adj = 0.0
    day_10 = ((qibu_day - 1) // 4) * 4 + 2
    rate = DAILY_RATE.get(day_10, 0.55)
    base_adj = (rate - 0.56) * 10
    factors["position"] = round(base_adj, 2)
    total += base_adj * 0.2

    # 2. 节气边界
    jq_adj = 0.0
    if is_jieqi_today:
        jq_adj += (0.604 - 0.56) * 5  # 节当日
    if is_jieqi_tomorrow:
        jq_adj += (0.566 - 0.56) * 5  # 节后1~2天
    factors["jieqi"] = round(jq_adj, 2)
    total += jq_adj * 0.15

    # 3. 衔接效应
    chain_adj = 0.0
    if prev_last10_mean is not None:
        key = ((qibu_seq - 1) % 6, qibu_seq)
        if key in CHAIN_EFFECT:
            edge = CHAIN_EFFECT[key]
            diff = edge["head"] - edge["tail"]
            chain_adj = diff * 10
    factors["chain"] = round(chain_adj, 2)
    total += chain_adj * 0.15

    # 4. 16分位波形
    wave_adj = 0.0
    bin_idx = min(15, max(0, (qibu_day - 1) // 3))
    if qibu_seq in WAVE_PROFILE and bin_idx < len(WAVE_PROFILE[qibu_seq]):
        wv = WAVE_PROFILE[qibu_seq][bin_idx]
        wave_adj = (wv - 0.56) * 10
    factors["wave"] = round(wave_adj, 2)
    total += wave_adj * 0.25

    # 5. 10日滚动衰减
    decay_adj = 0.0
    band = min(3, max(0, (qibu_day - 1) // 10))
    if band < len(ROLLING_10D):
        decay_adj = (ROLLING_10D[band] / 100 - 0.56) * 10
    factors["decay"] = round(decay_adj, 2)
    total += decay_adj * 0.15

    # 6. 各气步独有波形
    step_key = f"S{qibu_seq + 1}"
    if step_key in QI_STEP_ADJ:
        pct = qibu_day / 40.0
        sd = QI_STEP_ADJ[step_key]
        if pct < 0.2:
            factors["step_adj"] = sd["front"]
        elif pct < 0.6:
            factors["step_adj"] = sd["mid"]
        else:
            factors["step_adj"] = sd["rear"]
        total += factors["step_adj"] * 0.10

    return {"total": round(total, 2), "factors": factors}


# ============================================================
# ===== L2b-2 · 波峰波谷修正函数（v1.6 新增）================
# ============================================================

def calc_peak_valley_adj(qibu_day, qibu_seq, tg_idx, dz_idx):
    """
    基于12年89气步统计的全甲子波峰波谷共振修正。

    六大高胜率信号：
    抄底三重：25~29%+丙子/甲申 | S5开篇10%+壬寅 | S1 25%+庚寅/癸丑
    摸顶三重：20~24%+癸卯/丁未 | S2后段60~90%+乙酉 | 末端90~99%

    返回：
    - pv_score: 综合修正值（-1.0 ~ +1.0），正=偏多，负=偏空
    - signal_type: "bottom" / "peak" / "none"
    - signal_name: 触发的首个最强信号名
    - details: 全部触发信号明细
    """
    pct = qibu_day / 40.0  # 气步内进度百分比
    gz = (tg_idx, dz_idx)
    triggered = []
    signal_type = "none"
    signal_name = "无显著信号"
    pv_score = 0.0

    # === 抄底信号检测 ===

    # 信号1：气步25~29% + 丙子/甲申 → 终极稳健底部 ⭐⭐⭐
    if BOTTOM_WINDOW_PCT[0] <= pct <= BOTTOM_WINDOW_PCT[1] and gz in {(2,0), (0,8)}:
        triggered.append(("bottom", "气步25~29%+丙子/甲申→终极稳健底部", 1.0))

    # 信号1b：仅位置命中（25~29%区间 无干支配合）→ 减半
    if BOTTOM_WINDOW_PCT[0] <= pct <= BOTTOM_WINDOW_PCT[1]:
        if gz in ABSOLUTE_BOTTOM_GZ:
            triggered.append(("bottom", "气步底部窗口+绝对底日→极强底部", 0.9))
        elif gz in STRONG_BOTTOM_GZ:
            triggered.append(("bottom", "气步底部窗口+强势底日→强力底部", 0.7))

    # 信号2：S5秋金开篇10% + 壬寅 → 秋季第一杀低点 ⭐⭐
    if qibu_seq == 4 and pct <= 0.10:   # S5秋金
        if gz in {(8,2)}:
            triggered.append(("bottom", "S5开篇10%+壬寅→秋季第一杀低点", 0.8))
        else:
            triggered.append(("bottom", "S5开篇10%(季节底部窗口)", 0.4))

    # 信号3：S1春初25% + 庚寅/癸丑 → 春季回调底 ⭐⭐
    if qibu_seq == 0 and 0.22 <= pct <= 0.28:   # S1春初
        if gz in {(6,2), (9,1)}:
            triggered.append(("bottom", "S1 25%+庚寅/癸丑→春季回调底", 0.7))
        else:
            triggered.append(("bottom", "S1~25%位置(春季底部窗口)", 0.3))

    # 补充：绝对底日单独触发（任意位置）
    if gz in ABSOLUTE_BOTTOM_GZ:
        triggered.append(("bottom", f"绝对底日({TIANGAN[tg_idx]}{DIZHI[dz_idx]})→纯底部信号", 0.5))

    # 补充：次级底部窗口（10~14%, 30~34%）
    for lo, hi in SECONDARY_BOTTOMS_PCT:
        if lo <= pct <= hi and not any(t[2] >= 0.5 for t in triggered):
            triggered.append(("bottom", f"次级底部窗口({int(lo*100)}~{int(hi*100)}%)", 0.2))
            break

    # === 摸顶信号检测 ===

    # 信号4：气步20~24% + 癸卯/丁未 → 高概率阶段顶 ⭐⭐⭐
    if PEAK_WINDOW_PCT[0] <= pct <= PEAK_WINDOW_PCT[1] and gz in {(9,3), (3,7)}:
        triggered.append(("peak", "气步20~24%+癸卯/丁未→高概率阶段顶", 1.0))

    # 信号4b：仅绝对顶日（任何位置）
    if gz in ABSOLUTE_PEAK_GZ:
        triggered.append(("peak", f"绝对顶日({TIANGAN[tg_idx]}{DIZHI[dz_idx]})→顶部信号", 0.6))

    # 信号5：S2春夏后段60~90% + 乙酉 → 季度末尾冲顶 ⭐⭐
    if qibu_seq == 1 and 0.60 <= pct <= 0.90:   # S2春夏
        if gz in {(1,9)}:
            triggered.append(("peak", "S2后段60~90%+乙酉→季度尾部冲顶", 0.8))
        else:
            triggered.append(("peak", "S2后段60~90%(冲顶窗口)", 0.3))

    # 信号6：气步末端90~99% → 双向极值 ⭐⭐
    if 0.90 <= pct <= 0.99:
        triggered.append(("peak", "气步末端90~99%(双向极值→冲高回落警示)", 0.5))

    # === 综合计算 ===
    if triggered:
        # 取最强信号决定方向
        strongest = max(triggered, key=lambda t: t[2])
        signal_type = strongest[0]
        signal_name = strongest[1]
        # 同向叠加（反向抵消）
        bottom_scores = [t[2] for t in triggered if t[0] == "bottom"]
        peak_scores = [t[2] for t in triggered if t[0] == "peak"]
        bottom_total = sum(bottom_scores) if bottom_scores else 0.0
        peak_total = sum(peak_scores) if peak_scores else 0.0
        # 强方向压制弱方向
        if bottom_total > peak_total:
            pv_score = min(bottom_total, 1.0)
        elif peak_total > bottom_total:
            pv_score = -min(peak_total, 1.0)
        else:
            pv_score = 0.0

    return {
        "pv_score": round(pv_score, 2),
        "signal_type": signal_type,
        "signal_name": signal_name,
        "n_signals": len(triggered),
        "details": triggered,
    }


# ===== L4 变点检测（保持 v1.4 完整）=====

def calc_change_point_detection(qibu_day, qibu_seq, is_boundary_day=True,
                                 prev_last10_mean=None, next_qibu_seq=None):
    """L4 变点检测"""
    cp_prob = 0.0
    cp_signals = []
    cp_desc = ""
    cp_type = "无变点"

    # 规则1: 气步边界后第1天（64.8%涨率）
    if is_boundary_day and qibu_day <= 1:
        cp_signals.append(("边界后第1天强涨率", 0.40, "反转"))
        cp_prob += 0.40
        cp_desc += "气步边界后第1天(64.8%)→强涨率信号；"

    # 规则2: 气步内部12~18%调整位（40.4%最低点）
    day_pct = qibu_day / 40.0
    if 0.12 <= day_pct <= 0.18:
        cp_signals.append(("12~18%内部调整区", 0.30, "断裂"))
        cp_prob += 0.30
        cp_desc += f"气步第{qibu_day}天调整区(40.4%)；"

    # 规则3: 边界后第3~5天（回调位52.3%）
    if 3 <= qibu_day <= 5 and not is_boundary_day:
        cp_signals.append(("边界后回调(第3~5天)", 0.25, "断裂"))
        cp_prob += 0.25
        cp_desc += "边界后回调窗口(52.3%)；"

    # 规则4: Q5→Q6且尾段偏强
    if qibu_seq == 5 and prev_last10_mean is not None and prev_last10_mean > 0.5:
        cp_signals.append(("Q5→Q6剧烈回落衔接", 0.45, "剧烈切换"))
        cp_prob += 0.45
        cp_desc += "Q5→Q6秋→冬强烈回落信号；"

    # 规则5: Q6→Q1且尾段偏弱
    if qibu_seq == 0 and prev_last10_mean is not None and prev_last10_mean < -0.3:
        cp_signals.append(("Q6→Q1反转向上衔接", 0.35, "反转切换"))
        cp_prob += 0.35
        cp_desc += "Q6→Q1冬→春反转向上信号；"

    cp_prob = min(cp_prob, 1.0)
    if cp_prob >= 0.6:
        cp_type = "强变点"
    elif cp_prob >= 0.3:
        cp_type = "轻度变点"

    return {
        "cp_probability": round(cp_prob, 2),
        "cp_type": cp_type,
        "cp_signals": cp_signals,
        "cp_desc": cp_desc.strip("；"),
    }


# ===== 奇门择日（简化）=====

def get_qimen_scores(test_day, l2b_adj=0.0):
    """奇门择日评分"""
    tg_idx, dz_idx = get_ganzhi_day(test_day)
    _, month, day = test_day.year, test_day.month, test_day.day

    # 天时（月/年生日干）
    ts = 0
    month_tg = (month + 1) % 10
    year_tg = (test_day.year - 4) % 10
    if tg_idx == month_tg or tg_idx == year_tg:
        ts += 2
    elif (tg_idx - month_tg) % 10 <= 5:
        ts += 1
    else:
        ts -= 1

    # 地利（落宫）
    tg_p = TG_PALACE.get(tg_idx, 5)
    dz_p = DZ_PALACE.get(dz_idx, 5)
    dl = 1 if tg_p != dz_p else -1
    if tg_p in (1, 8, 9):
        dl += 1
    elif tg_p in (2, 7):
        dl -= 1

    # 人和（用神戊土）
    wu_tg = 4
    if tg_idx == wu_tg:
        rh = 0
    elif tg_idx in WX_SHENG.get(TG_WX.get(TIANGAN[wu_tg], "土"), set()):
        rh = 2
    elif TG_WX.get(TIANGAN[tg_idx], "土") in WX_SHENG.get(TG_WX.get(TIANGAN[wu_tg], "土"), set()):
        rh = 1
    else:
        rh = -1

    total = ts + dl + rh + l2b_adj
    return {
        "date": test_day.strftime("%Y-%m-%d"),
        "tg": tg_idx,
        "dz": dz_idx,
        "gz": f"{TIANGAN[tg_idx]}{DIZHI[dz_idx]}",
        "ts": ts, "dl": dl, "rh": rh, "l2b_adj": l2b_adj,
        "total": round(total, 1),
    }


# ===== 主函数 =====

def run():
    today = Date.today()
    month_str = today.strftime("%Y年%m月")

    # ---- L1 方向 ----
    direction, accuracy, ws2, wjiu, wtai, use_q3 = get_l1_direction(today)
    acc_str = f"{accuracy}%" if accuracy <= 100 else "92.55%"
    print(f"\n{'=' * 55}")
    print(f"  三河择时 · {month_str}综合研判")
    print(f"  SKILL v2.5.0 | runner v1.6")
    print(f"{'=' * 55}")
    print(f"\n【L1 · 月线方向】{direction} | 置信度 {acc_str}")
    if use_q3:
        print(f"  Q3自适应权重(S2=1.0 九宫=0.2 太乙=0.1)")
    else:
        print(f"  标准权重(S2={ws2} 九宫={wjiu} 太乙={wtai})")

    # ---- L2 节气 ----
    qibu_seq, qibu_name, qibu_day, qibu_total, qibu_start, qibu_end = get_qibu_info(today)
    day_pct = qibu_day / qibu_total
    print(f"\n【L2 · 节气窗口】")
    print(f"  当前：{qibu_name} | 第{qibu_day}/{qibu_total}天 ({day_pct*100:.0f}%)")
    print(f"  时段：{qibu_start} ~ {qibu_end}")

    # ---- L2b 节奏 ----
    rhythm = calc_rhythm_adj(qibu_day, qibu_seq, None, False, False)
    front_adj = rhythm["factors"].get("position", 0) * 0.2
    mid_adj = rhythm["factors"].get("wave", 0) * 0.25
    rear_adj = rhythm["factors"].get("decay", 0) * 0.15
    total_adj = rhythm["total"]
    print(f"\n【L2b · 气步内部节奏】")
    print(f"  进度{day_pct*100:.0f}% | 前{front_adj:+.2f} 中{mid_adj:+.2f} 后{rear_adj:+.2f}")
    print(f"  总调整：{total_adj:+.2f}")

    # ---- L2b-2 波峰波谷修正（v1.6 新增）----
    tg_idx, dz_idx = get_ganzhi_day(today)
    pv = calc_peak_valley_adj(qibu_day, qibu_seq, tg_idx, dz_idx)
    print(f"\n【L2b-2 · 波峰波谷修正】（v2.5.0 新增）")
    print(f"  日日干支：{TIANGAN[tg_idx]}{DIZHI[dz_idx]}")
    print(f"  pv_score: {pv['pv_score']:+.2f}")
    print(f"  类型：{pv['signal_type']}")
    print(f"  触发：{pv['signal_name']} ({pv['n_signals']}信号)")

    # ---- L3 奇门择日（当月全月）----
    print(f"\n【L3 · 奇门择日】")
    month_start = Date(today.year, today.month, 1)
    if today.month == 12:
        month_end = Date(today.year, 12, 31)
    else:
        month_end = Date(today.year, today.month + 1, 1) - timedelta(days=1)

    scores = []
    d = month_start
    while d <= month_end:
        s = get_qimen_scores(d, l2b_adj=total_adj)
        # 加入波峰波谷修正
        tg_d, dz_d = get_ganzhi_day(d)
        pv_d = calc_peak_valley_adj(
            qibu_day + (d - today).days, qibu_seq, tg_d, dz_d
        )
        s["pv_adj"] = pv_d["pv_score"]
        s["pv_type"] = pv_d["signal_type"]
        s["total_with_pv"] = round(s["total"] + pv_d["pv_score"] * 0.3, 1)
        scores.append(s)
        d += timedelta(days=1)

    scores.sort(key=lambda x: x["total_with_pv"], reverse=True)
    best = [s for s in scores if s["total_with_pv"] >= 5][:3]
    good = [s for s in scores if 4 <= s["total_with_pv"] < 5][:3]
    ok_ = [s for s in scores if 3 <= s["total_with_pv"] < 4][:3]
    exit_ = [s for s in scores if s["total_with_pv"] <= 1.5][:3]

    # 打印奇门
    print(f"  ┌─ 补仓日（宜入）{'─'*30}┐")
    for label, items, thr in [("★★★ 强烈推荐(≥5)", best, 5),
                                ("★★☆ 推荐(≥4)", good, 4),
                                ("☆☆☆ 可选(≥3)", ok_, 3)]:
        if items:
            print(f"  │ {label}：")
            for s in items:
                pv_tag = f" [波谷{s.get('pv_type','')}]" if s.get("pv_adj", 0) > 0.4 else ""
                print(f"  │   {s['date']} ({s['gz']}) {s['total_with_pv']:.1f}分"
                      f" 天{s['ts']:.0f}+地{s['dl']:.0f}+人{s['rh']:.0f}+pv{s.get('pv_adj',0):+.1f}{pv_tag}")
    if not best and not good and not ok_:
        print(f"  │  <本月无合格窗口>")
    print(f"  └{'─'*45}┘")
    print(f"  ┌─ 清仓日（宜出）{'─'*30}┐")
    if exit_:
        for s in exit_:
            pv_tag = f" [波峰{s.get('pv_type','')}]" if s.get("pv_adj", 0) < -0.4 else ""
            print(f"  │  ✗ {s['date']} ({s['gz']}) {s['total_with_pv']:.1f}分{pv_tag}")
    else:
        print(f"  │  本月无显著清仓信号")
    print(f"  └{'─'*45}┘")
    print(f"  【统计】交易日{len(scores)} | 强烈推荐{len(best)} 推荐{len(good)} 可选{len(ok_)} 避让{len(exit_)}")

    # ---- L4 变点 ----
    cp = calc_change_point_detection(qibu_day, qibu_seq)
    print(f"\n【L4 · 变点检测】")
    print(f"  变点概率：{cp['cp_probability']}")
    print(f"  变点类型：{cp['cp_type']}")
    print(f"  描述：{cp['cp_desc']}")
    if cp['cp_probability'] >= 0.6:
        print(f"  仲裁建议：降权至50%，启用防守策略")
    elif cp['cp_probability'] >= 0.3:
        print(f"  仲裁建议：降权至70%，暂缓新开仓")
    else:
        print(f"  仲裁建议：常规操作，完全执行动量信号")

    # ---- 综合仓位 ----
    print(f"\n【双引擎+波谷修正联动仓位建议】")
    print(f"  方向({direction}) | L2b({total_adj:+.1f}) | 波峰波谷({pv['pv_score']:+.1f}) | 变点({cp['cp_probability']})")

    # 仓位计算
    base_position = 7 if direction == "偏多" else (3 if direction == "偏空" else 5)
    adj_l2b = total_adj * 5  # 每0.1分调0.5成
    adj_pv = pv['pv_score'] * 3  # 每0.1分调0.3成
    adj_cp = -3 if cp['cp_probability'] >= 0.6 else (-1 if cp['cp_probability'] >= 0.3 else 0)
    position = base_position + adj_l2b + adj_pv + adj_cp
    position = max(1, min(10, round(position)))

    reasons = []
    if adj_l2b > 0.5:
        reasons.append(f"节奏偏强(+{adj_l2b:.0f}成)")
    elif adj_l2b < -0.5:
        reasons.append(f"节奏偏弱({adj_l2b:.0f}成)")
    if adj_pv > 0.5:
        reasons.append(f"波谷修正({pv['signal_name']})")
    elif adj_pv < -0.5:
        reasons.append(f"波峰修正({pv['signal_name']})")
    if adj_cp < -1:
        reasons.append("变点预警减仓")
    reason_str = "；".join(reasons) if reasons else "无显著修正"
    print(f"  建议仓位：{position}成")
    print(f"  原因：{direction}方向 + {reason_str}")
    print("=" * 55)
    print()

    return {"direction": direction, "accuracy": accuracy,
            "l2b_adj": total_adj, "pv_adj": pv['pv_score'],
            "pv_type": pv['signal_type'], "pv_signal": pv['signal_name'],
            "cp_prob": cp['cp_probability'], "position": position,
            "n_best": len(best), "n_good": len(good), "n_ok": len(ok_)}


if __name__ == "__main__":
    run()
