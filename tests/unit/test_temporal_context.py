from datetime import datetime
from zoneinfo import ZoneInfo

from openkitsune.core.temporal_context import (
    build_temporal_context,
    chinese_hour,
    current_solar_term,
    day_period,
    season_for,
)

TZ = ZoneInfo("Asia/Shanghai")


def _at(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_solar_term_boundaries_2026():
    assert current_solar_term(_at(2026, 2, 3), "Asia/Shanghai").name == "大寒"
    assert current_solar_term(_at(2026, 2, 4), "Asia/Shanghai").name == "立春"
    assert current_solar_term(_at(2026, 10, 7), "Asia/Shanghai").name == "秋分"
    assert current_solar_term(_at(2026, 10, 8, 20), "Asia/Shanghai").name == "寒露"
    assert current_solar_term(_at(2026, 12, 21), "Asia/Shanghai").name == "大雪"
    assert current_solar_term(_at(2026, 12, 22), "Asia/Shanghai").name == "冬至"


def test_solar_term_span_links_to_next_term():
    span = current_solar_term(_at(2026, 10, 18, 20, 10), "Asia/Shanghai")
    assert span.name == "寒露"
    assert span.next_name == "霜降"
    assert span.start.date().isoformat() == "2026-10-08"
    assert span.end.date().isoformat() == "2026-10-23"


def test_season_and_phase_follow_solar_terms():
    assert season_for(2) == ("春", "初")
    assert season_for(5) == ("春", "仲")
    assert season_for(8) == ("夏", "初")
    assert season_for(18) == ("秋", "季")
    assert season_for(23) == ("冬", "仲")
    assert season_for(0) == ("冬", "季")


def test_chinese_hour_maps_across_midnight():
    assert chinese_hour(23) == ("子", 23)
    assert chinese_hour(0) == ("子", 23)
    assert chinese_hour(1) == ("丑", 1)
    assert chinese_hour(12) == ("午", 11)
    assert chinese_hour(20) == ("戌", 19)


def test_day_period_labels():
    assert day_period(3)[0] == "深夜"
    assert day_period(6)[0] == "清晨"
    assert day_period(9)[0] == "上午"
    assert day_period(12)[0] == "中午"
    assert day_period(15)[0] == "下午"
    assert day_period(18)[0] == "傍晚"
    assert day_period(20)[0] == "夜晚"
    assert day_period(23)[0] == "深夜"


def test_build_temporal_context_snapshot():
    context = build_temporal_context(_at(2026, 10, 18, 20, 10), "Asia/Shanghai")

    assert "## 时间感知" in context
    assert "2026年10月18日 周日 20:10" in context
    assert "戌时" in context
    assert "夜晚" in context
    assert "周末" in context
    assert "季秋" in context
    assert "寒露" in context
    assert "霜降" in context
    assert "不要机械报时" in context
