"""Temporal awareness for conversational prompts.

Builds a compact, human-readable snapshot of *when* the agent is speaking:
calendar date/time, day period, Chinese double-hour (时辰), season phase,
solar term (节气), and — when ``lunar_python`` is installed — lunar date and
traditional festivals.

The solar-term calculation is pure stdlib (Meeus low-precision apparent solar
longitude + Newton iteration), so prompt assembly never depends on an optional
third-party package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from functools import lru_cache

SOLAR_TERM_NAMES: tuple[str, ...] = (
    "小寒",
    "大寒",
    "立春",
    "雨水",
    "惊蛰",
    "春分",
    "清明",
    "谷雨",
    "立夏",
    "小满",
    "芒种",
    "夏至",
    "小暑",
    "大暑",
    "立秋",
    "处暑",
    "白露",
    "秋分",
    "寒露",
    "霜降",
    "立冬",
    "小雪",
    "大雪",
    "冬至",
)

# Apparent solar longitude (degrees) at each term, starting with 小寒 at 285°.
_TERM_LONGITUDES: tuple[float, ...] = tuple((285 + 15 * i) % 360 for i in range(24))

_CHINESE_HOURS: tuple[str, ...] = (
    "子",
    "丑",
    "寅",
    "卯",
    "辰",
    "巳",
    "午",
    "未",
    "申",
    "酉",
    "戌",
    "亥",
)

_WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_SEASON_NAMES: tuple[str, ...] = ("春", "夏", "秋", "冬")
_SEASON_PHASES: tuple[str, ...] = ("初", "仲", "季")


@dataclass(frozen=True)
class SolarTermSpan:
    """A solar-term window: ``start`` inclusive, ``end`` exclusive."""

    name: str
    index: int
    start: datetime
    end: datetime
    next_name: str


def resolve_timezone(timezone_name: str | None = None) -> tzinfo:
    """Resolve an IANA timezone name, falling back to UTC+8."""
    name = timezone_name or "Asia/Shanghai"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=8))


def _julian_day(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5


def _solar_apparent_longitude(jde: float) -> float:
    """Apparent geocentric longitude of the Sun (degrees), Meeus low precision."""
    t = (jde - 2451545.0) / 36525.0
    mean_longitude = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    mean_anomaly = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    equation_of_center = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(mean_anomaly)
        + (0.019993 - 0.000101 * t) * math.sin(2 * mean_anomaly)
        + 0.000289 * math.sin(3 * mean_anomaly)
    )
    true_longitude = mean_longitude + equation_of_center
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = true_longitude - 0.00569 - 0.00478 * math.sin(omega)
    return apparent % 360.0


def _find_term_datetime(year: int, index: int, tz: tzinfo) -> datetime:
    """Return the instant the ``index``-th solar term starts, in ``tz``."""
    angle = _TERM_LONGITUDES[index]
    month = index // 2 + 1
    seed_day = 6 if index % 2 == 0 else 21
    jde = _julian_day(datetime(year, month, seed_day, tzinfo=UTC))
    for _ in range(24):
        diff = (angle - _solar_apparent_longitude(jde) + 180.0) % 360.0 - 180.0
        if abs(diff) < 1e-7:
            break
        jde += diff / 0.98564736
    return datetime.fromtimestamp((jde - 2440587.5) * 86400.0, tz=UTC).astimezone(tz)


@lru_cache(maxsize=32)
def _terms_for_year(year: int, timezone_name: str) -> tuple[datetime, ...]:
    tz = resolve_timezone(timezone_name)
    return tuple(_find_term_datetime(year, i, tz) for i in range(24))


def current_solar_term(
    now: datetime,
    timezone_name: str | None = None,
) -> SolarTermSpan:
    """Locate the solar-term window containing ``now``."""
    tz = resolve_timezone(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    timezone_key = timezone_name or "Asia/Shanghai"
    # Terms span calendar years only at the January/December edges.
    if now.month == 1:
        years = (now.year - 1, now.year)
    elif now.month == 12:
        years = (now.year, now.year + 1)
    else:
        years = (now.year,)

    candidates: list[tuple[datetime, str, int]] = []
    for year in years:
        starts = _terms_for_year(year, timezone_key)
        candidates.extend((starts[i], SOLAR_TERM_NAMES[i], i) for i in range(24))
    candidates.sort(key=lambda item: item[0])

    current_pos = 0
    for pos, (start, _name, _index) in enumerate(candidates):
        if start <= now:
            current_pos = pos
        else:
            break

    start, name, index = candidates[current_pos]
    end, next_name, _next_index = candidates[(current_pos + 1) % len(candidates)]
    return SolarTermSpan(
        name=name,
        index=index,
        start=start,
        end=end,
        next_name=next_name,
    )


def season_for(term_index: int) -> tuple[str, str]:
    """Return (season, phase) where phase is 初/仲/季."""
    offset = (term_index - 2) % 24
    return _SEASON_NAMES[offset // 6], _SEASON_PHASES[(offset % 6) // 2]


def chinese_hour(hour: int) -> tuple[str, int]:
    """Return (时辰名, 起始小时) for ``hour`` (0-23)."""
    branch = ((hour + 1) % 24) // 2
    start_hour = (branch * 2 - 1) % 24
    return _CHINESE_HOURS[branch], start_hour


def day_period(hour: int) -> tuple[str, str]:
    """Return (day-period label, conversational guidance) for ``hour``."""
    if hour < 5:
        return "深夜", "夜深人静，回复宜轻短，可关心一句休息，不主动铺开长任务"
    if hour < 8:
        return "清晨", "清晨刚醒，语气清爽，可自然问候新的一天"
    if hour < 11:
        return "上午", "上午精力充沛，适合推进正事"
    if hour < 13:
        return "中午", "午间节奏放缓，适合简短闲聊或提醒吃饭"
    if hour < 17:
        return "下午", "下午适合持续推进，也可留意用户的疲惫感"
    if hour < 19:
        return "傍晚", "傍晚是收工过渡，适合聊聊今天、放松一下"
    if hour < 23:
        return "夜晚", "晚间语气舒缓，适合复盘、闲聊或安排明天"
    return "深夜", "夜深人静，回复宜轻短，可关心一句休息，不主动铺开长任务"


def _lunar_details(now: datetime) -> str | None:
    """Return lunar date / zodiac / festival text when ``lunar_python`` exists."""
    try:
        from lunar_python import Solar

        solar = Solar.fromYmdHms(now.year, now.month, now.day, now.hour, now.minute, now.second)
        lunar = solar.getLunar()
        parts = [f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"]
        ganzhi_year = lunar.getYearInGanZhi()
        zodiac = lunar.getYearShengXiao()
        if ganzhi_year and zodiac:
            parts.append(f"{ganzhi_year}年（{zodiac}）")
        festivals = list(lunar.getFestivals() or []) + list(solar.getFestivals() or [])
        if festivals:
            parts.append("·".join(dict.fromkeys(festivals)))
        return " · ".join(parts)
    except Exception:
        return None


def build_temporal_context(
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> str:
    """Build the markdown ``## 时间感知`` block injected into prompts."""
    tz = resolve_timezone(timezone_name)
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    span = current_solar_term(now, timezone_name)
    season, phase = season_for(span.index)
    period, guidance = day_period(now.hour)
    branch, branch_start = chinese_hour(now.hour)
    branch_end = (branch_start + 1) % 24

    days_in_term = max(0, (now.date() - span.start.date()).days)
    days_to_next = max(0, (span.end.date() - now.date()).days)
    pentad = ("初候", "二候", "三候")[min(days_in_term // 5, 2)]

    weekend = "周末" if now.weekday() >= 5 else "工作日"
    term_start = f"{span.start.month}月{span.start.day}日"
    if days_in_term == 0:
        term_progress = f"{term_start}交节，今日交节 · {pentad}"
    else:
        term_progress = f"{term_start}交节，第 {days_in_term + 1} 天 · {pentad}"

    next_term = f"下一节气 {span.next_name} {span.end.month}月{span.end.day}日"
    if days_to_next == 0:
        next_term += "（今日交节）"
    else:
        next_term += f"，还有 {days_to_next} 天"

    lines = [
        "## 时间感知",
        "",
        f"- 此刻：{now.year}年{now.month}月{now.day}日 {_WEEKDAY_NAMES[now.weekday()]} "
        f"{now:%H:%M}（{timezone_name or 'Asia/Shanghai'}）",
        f"- 时段：{period}（{branch}时 {branch_start:02d}:00–{branch_end:02d}:59）· {weekend}",
        f"- 季节：{phase}{season}（以节气划分）",
        f"- 节气：{span.name}（{term_progress}）；{next_term}",
    ]

    lunar = _lunar_details(now)
    if lunar:
        lines.append(f"- 农历：{lunar}")

    lines.append(
        f"- 语境：{guidance}。可把季节、节气与时段自然地融入问候和关心，"
        "但不要机械报时，也不要每轮都重复；用户未问及时间时点到为止。"
        "涉及具体日期或时效时，以此处「此刻」为准。"
    )
    return "\n".join(lines)
