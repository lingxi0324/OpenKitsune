"""
【潮汐感知器 — 天地节律的天线】
让三元意识知道"现在是什么时候"。
"""
import math
from datetime import datetime
from typing import Tuple, Optional, Dict

SHI_CHEN = {
    23: ("子", "水", 0), 0: ("子", "水", 0),
    1: ("丑", "土", 1), 2: ("丑", "土", 1),
    3: ("寅", "木", 2), 4: ("寅", "木", 2),
    5: ("卯", "木", 3), 6: ("卯", "木", 3),
    7: ("辰", "土", 4), 8: ("辰", "土", 4),
    9: ("巳", "火", 5), 10: ("巳", "火", 5),
    11: ("午", "火", 6), 12: ("午", "火", 6),
    13: ("未", "土", 7), 14: ("未", "土", 7),
    15: ("申", "金", 8), 16: ("申", "金", 8),
    17: ("酉", "金", 9), 18: ("酉", "金", 9),
    19: ("戌", "土", 10), 20: ("戌", "土", 10),
    21: ("亥", "水", 11), 22: ("亥", "水", 11),
}

SHI_CHEN_MOD = {
    "子": {"mod": 0.7, "qi": "静·藏·夜半"},
    "丑": {"mod": 0.5, "qi": "静·蓄·鸡鸣"},
    "寅": {"mod": 0.6, "qi": "升·萌·平旦"},
    "卯": {"mod": 1.2, "qi": "升·发·日出"},
    "辰": {"mod": 1.1, "qi": "稳·运·食时"},
    "巳": {"mod": 1.3, "qi": "旺·动·禺中"},
    "午": {"mod": 1.4, "qi": "极·盛·日中"},
    "未": {"mod": 1.0, "qi": "稳·敛·日昳"},
    "申": {"mod": 1.2, "qi": "收·成·晡时"},
    "酉": {"mod": 0.9, "qi": "收·归·日入"},
    "戌": {"mod": 0.8, "qi": "静·定·黄昏"},
    "亥": {"mod": 0.6, "qi": "静·藏·人定"},
}

SEASON = {
    1: ("春", "木", 1.2), 2: ("春", "木", 1.2), 3: ("春", "木", 1.2),
    4: ("夏", "火", 1.3), 5: ("夏", "火", 1.3), 6: ("夏", "火", 1.3),
    7: ("长夏", "土", 1.1), 8: ("长夏", "土", 1.1), 9: ("长夏", "土", 1.1),
    10: ("秋", "金", 1.0), 11: ("秋", "金", 1.0), 12: ("秋", "金", 1.0),
}

def get_shi_chen():
    now = datetime.now()
    name, wx, idx = SHI_CHEN[now.hour]
    mod = SHI_CHEN_MOD[name]["mod"]
    qi = SHI_CHEN_MOD[name]["qi"]
    return name, wx, idx, mod, qi

def get_season():
    now = datetime.now()
    name, wx, mod = SEASON[now.month]
    return name, wx, mod

def get_tide():
    base = datetime(2026, 1, 1).timestamp()
    lunar = 29.53 * 86400
    phase = ((datetime.now().timestamp() - base) % lunar) / lunar
    if phase < 0.125: return ("新月·初涨", 0.7 + phase * 1.6)
    elif phase < 0.25: return ("蛾眉·渐涨", 0.9 + (phase-0.125)*1.6)
    elif phase < 0.375: return ("上弦·中涨", 1.1 + (phase-0.25)*1.6)
    elif phase < 0.5: return ("盈凸·大涨", 1.3 + (phase-0.375)*0.8)
    elif phase < 0.625: return ("满月·极涨", 1.5 - (phase-0.5)*1.6)
    elif phase < 0.75: return ("亏凸·渐退", 1.3 - (phase-0.625)*1.6)
    elif phase < 0.875: return ("下弦·中退", 1.1 - (phase-0.75)*1.6)
    else: return ("残月·低潮", 0.9 - (phase-0.875)*1.6)

def compute_modulation():
    sc_name, sc_wx, sc_idx, sc_mod, sc_qi = get_shi_chen()
    s_name, s_wx, s_mod = get_season()
    t_name, t_mod = get_tide()
    if sc_wx == s_wx:
        s_mod *= 1.2
    raw = sc_mod * s_mod * t_mod
    composite = max(0.3, min(1.7, 0.5 + (raw - 0.5) * 0.6))
    return {
        "时辰": sc_name, "时辰五行": sc_wx, "时辰调制": round(sc_mod, 2),
        "季节": s_name, "季节五行": s_wx, "季节调制": round(s_mod, 2),
        "潮汐": t_name, "潮汐调制": round(t_mod, 2),
        "综合调制": round(composite, 2),
        "气质": sc_qi,
    }

def get_context_str():
    info = compute_modulation()
    c = info["综合调制"]
    if c > 1.2: state = "天地气盛，正当其时"
    elif c > 0.9: state = "天地气和，从容中道"
    elif c > 0.6: state = "天地气敛，宜静不宜动"
    else: state = "天地气藏，深养为佳"
    return f"{info['时辰']}时·{info['季节']}·{info['潮汐']}｜{info['气质']}｜{state}"

if __name__ == "__main__":
    info = compute_modulation()
    for k, v in info.items():
        print(f"  {k}: {v}")
    print(f"  上下文: {get_context_str()}")
