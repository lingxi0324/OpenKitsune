# -*- coding: utf-8 -*-
"""
TCM 潮汐上下文引擎 — 时辰体用
Python 原生翻译自 tide.rs

根据当前时间: 时辰 → 节气 → 季节 → 岁运 → 司天 → 时辰体用

输出: TideContext(时间, 时辰, 节气, 季节, 岁运, 司天, 季节调候, 时辰体用)
"""

from datetime import datetime
from typing import List, Optional, Tuple

from .clinical_types import TideContext
from .wuyun import year_to_ganzhi, tian_gan_hua_qi, sitian_zaiyuan


# ════════════════════════════════════════════════════════════════════════════
# 时辰表 (子,丑,寅,卯,辰,巳,午,未,申,酉,戌,亥)
# ════════════════════════════════════════════════════════════════════════════

# (时辰名, 起始小时, 脏腑, 体用描述)
SHICHEN: List[Tuple[str, int, str, str]] = [
    ("子时", 23, "胆", "一阳初生, 体生用微"),
    ("丑时", 1,  "肝", "阴尽阳生, 体藏用疏"),
    ("寅时", 3,  "肺", "肺气朝百脉, 用始布"),
    ("卯时", 5,  "大肠", "阳升于表, 用通降"),
    ("辰时", 7,  "胃", "水谷腐熟, 体化用"),
    ("巳时", 9,  "脾", "运化精微, 体充用"),
    ("午时", 11, "心", "阳盛于外, 用亢"),
    ("未时", 13, "小肠", "分清泌浊, 体清用"),
    ("申时", 15, "膀胱", "太阳气化, 用行"),
    ("酉时", 17, "肾", "肾精封藏, 体用俱静"),
    ("戌时", 19, "心包", "心包代心受邪, 用御"),
    ("亥时", 21, "三焦", "三焦通调, 体用和"),
]


def get_shichen(hour: int) -> Tuple[str, str]:
    """根据小时(0-23)返回 (时辰名, 时辰体用描述)"""
    for i, (name, start, _zangfu, desc) in enumerate(SHICHEN):
        next_start = SHICHEN[(i + 1) % 12][1]
        # 子时跨午夜: 23:00~00:59
        if name == "子时":
            if hour >= 23 or hour < 1:
                return (name, desc)
        elif start <= hour < next_start:
            return (name, desc)
    return ("未知", "未知")


# ════════════════════════════════════════════════════════════════════════════
# 节气表 (2026 年)
# ════════════════════════════════════════════════════════════════════════════

SOLAR_TERMS_2026: List[Tuple[str, int, int]] = [
    ("小寒", 1, 5), ("大寒", 1, 20),
    ("立春", 2, 4), ("雨水", 2, 19),
    ("惊蛰", 3, 6), ("春分", 3, 21),
    ("清明", 4, 5), ("谷雨", 4, 20),
    ("立夏", 5, 6), ("小满", 5, 21),
    ("芒种", 6, 6), ("夏至", 6, 21),
    ("小暑", 7, 7), ("大暑", 7, 23),
    ("立秋", 8, 8), ("处暑", 8, 23),
    ("白露", 9, 8), ("秋分", 9, 23),
    ("寒露", 10, 8), ("霜降", 10, 23),
    ("立冬", 11, 7), ("小雪", 11, 22),
    ("大雪", 12, 7), ("冬至", 12, 22),
]


def get_solar_term(month: int, day: int) -> str:
    """根据月日返回最近的节气名（同月内取日差最小者）"""
    closest = ("未知", 31)
    for name, m, d in SOLAR_TERMS_2026:
        if m == month:
            diff = day - d if day >= d else 31 - d + day
            if diff < closest[1]:
                closest = (name, diff)
    return closest[0]


def get_season(month: int, solar_term: str) -> str:
    """根据月与节气返回季节"""
    if solar_term in ("立春", "雨水", "惊蛰", "春分", "清明", "谷雨"):
        return "春"
    if solar_term in ("立夏", "小满", "芒种", "夏至", "小暑", "大暑"):
        return "夏"
    if solar_term in ("立秋", "处暑", "白露", "秋分", "寒露", "霜降"):
        return "秋"
    if solar_term in ("立冬", "小雪", "大雪", "冬至", "小寒", "大寒"):
        return "冬"
    # fallback by month
    if 3 <= month <= 5:
        return "春"
    if 6 <= month <= 8:
        return "夏"
    if 9 <= month <= 11:
        return "秋"
    return "冬"


# ════════════════════════════════════════════════════════════════════════════
# 季节调候
# ════════════════════════════════════════════════════════════════════════════

SEASON_TIAOHOU: dict = {
    "春": "木旺升发, 宜疏肝达郁, 忌升散太过",
    "夏": "火旺外散, 宜清心养阴, 忌苦寒伤阳",
    "秋": "金旺收敛, 宜润肺生津, 忌耗散伤津",
    "冬": "水旺封藏, 宜温阳填精, 忌开泄伤肾",
}


def tide_context(now: Optional[datetime] = None) -> TideContext:
    """
    获取当前潮汐上下文。

    返回 TideContext: 时间 / 时辰 / 节气 / 季节 / 岁运 / 司天 / 季节调候 / 时辰体用
    """
    if now is None:
        now = datetime.now()

    # 时间
    time_str = now.strftime("%Y-%m-%d %H:%M")

    # 时辰
    shichen_name, shichen_desc = get_shichen(now.hour)

    # 节气
    solar_term = get_solar_term(now.month, now.day)

    # 季节
    season = get_season(now.month, solar_term)

    # 岁运
    ganzhi = year_to_ganzhi(now.year)
    huaqi = tian_gan_hua_qi(ganzhi)
    sui_yun = huaqi.化气 + ("太过" if huaqi.阴阳 == "阳" else "不及")

    # 司天
    sitian_info = sitian_zaiyuan(ganzhi)

    # 季节调候
    tiaohou = SEASON_TIAOHOU.get(season, "未知")

    return TideContext(
        时间=time_str,
        时辰=shichen_name,
        节气=solar_term,
        季节=season,
        岁运=sui_yun,
        司天=sitian_info.司天,
        季节调候=tiaohou,
        时辰体用=shichen_desc,
    )
