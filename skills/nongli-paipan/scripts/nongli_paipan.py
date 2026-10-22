#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""农历查询与排盘引擎.

统一提供「公历/农历 -> 四柱、节气、建除、二十八宿、神煞、宜忌」的结构化结果，
供奇门、紫微、四柱、针法等技能复用。

依赖 lunar_python（与 bazi-analysis / qimen-diagnosis 保持一致）。
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Any

try:
    from lunar_python import Lunar, Solar
except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
    raise ImportError(
        "nongli-paipan 需要 lunar_python。请先执行: pip install lunar-python"
    ) from exc

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
ZODIAC = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]


def _solar_text(jieqi: Any) -> str:
    """把 lunar_python 的 JieQi 对象转成可读日期时间。"""
    if jieqi is None:
        return ""
    try:
        solar = jieqi.getSolar()
        return (
            f"{solar.getYear():04d}-{solar.getMonth():02d}-{solar.getDay():02d} "
            f"{solar.getHour():02d}:{solar.getMinute():02d}"
        )
    except Exception:
        return ""


def _safe(getter, default=None):
    try:
        value = getter()
        return value if value is not None else default
    except Exception:
        return default


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


class NongliPaipan:
    """农历查询与排盘引擎。"""

    def solar(self, year: int, month: int, day: int, hour: int = 0,
              minute: int = 0, second: int = 0) -> dict:
        """按公历时间排盘。hour 使用 0-23。"""
        solar = Solar.fromYmdHms(int(year), int(month), int(day),
                                 int(hour), int(minute), int(second))
        return self._build(solar)

    def lunar(self, year: int, month: int, day: int, hour: int = 0,
              minute: int = 0, is_leap: bool = False) -> dict:
        """按农历时间排盘。month 为 1-12；闰月用 is_leap=True。"""
        lunar_month = -abs(int(month)) if is_leap else abs(int(month))
        lunar = Lunar.fromYmdHms(int(year), lunar_month, int(day),
                                 int(hour), int(minute), 0)
        return self._build(lunar.getSolar())

    def today(self, hour: int | None = None) -> dict:
        now = datetime.now()
        return self.solar(now.year, now.month, now.day,
                          now.hour if hour is None else hour, now.minute)

    def date_range(self, start: date, days: int, hour: int = 0) -> list[dict]:
        """连续多日日课；days 含起始日。"""
        days = max(1, int(days))
        return [
            self.solar((start + timedelta(days=i)).year,
                       (start + timedelta(days=i)).month,
                       (start + timedelta(days=i)).day, hour)
            for i in range(days)
        ]

    # ------------------------------------------------------------------
    def _build(self, solar: Solar) -> dict:
        lunar = solar.getLunar()

        year_gz = lunar.getYearInGanZhiExact()
        month_gz = lunar.getMonthInGanZhiExact()
        day_gz = lunar.getDayInGanZhiExact()
        time_gz = lunar.getTimeInGanZhi()

        current_jieqi = _safe(lunar.getCurrentJieQi)
        prev_jieqi = _safe(lunar.getPrevJieQi)
        next_jieqi = _safe(lunar.getNextJieQi)
        # getCurrentJieQi 只在节气当天返回对象；平日以“上一节气”作为当前节气。
        if current_jieqi is None:
            current_jieqi = prev_jieqi

        festivals = _as_list(_safe(lunar.getFestivals))
        other_festivals = _as_list(_safe(lunar.getOtherFestivals))

        weekday = WEEKDAYS[solar.getWeek() - 1] if 1 <= solar.getWeek() <= 7 else ""

        return {
            "solar": {
                "date": solar.toYmd(),
                "datetime": solar.toYmdHms(),
                "weekday": weekday,
                "year": solar.getYear(),
                "month": solar.getMonth(),
                "day": solar.getDay(),
                "hour": solar.getHour(),
                "minute": solar.getMinute(),
            },
            "lunar": {
                "year": lunar.getYear(),
                "month": abs(lunar.getMonth()),
                "day": lunar.getDay(),
                "is_leap": lunar.getMonth() < 0,
                "text": f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月"
                        f"{lunar.getDayInChinese()}",
                "year_ganzhi": year_gz,
                "month_ganzhi": month_gz,
                "day_ganzhi": day_gz,
                "time_ganzhi": time_gz,
                "zodiac": ZODIAC[(lunar.getYear() - 4) % 12],
                "festivals": festivals,
                "other_festivals": other_festivals,
            },
            "four_pillars": " ".join([year_gz, month_gz, day_gz, time_gz]),
            "nayin": {
                "year": _safe(lunar.getYearNaYin, ""),
                "month": _safe(lunar.getMonthNaYin, ""),
                "day": _safe(lunar.getDayNaYin, ""),
                "time": _safe(lunar.getTimeNaYin, ""),
            },
            "xunkong": {
                "year": _safe(lunar.getYearXunKongExact, ""),
                "month": _safe(lunar.getMonthXunKongExact, ""),
                "day": _safe(lunar.getDayXunKongExact, ""),
                "time": _safe(lunar.getTimeXunKong, ""),
            },
            "jieqi": {
                "current": _safe(current_jieqi.getName, "") if current_jieqi else "",
                "current_time": _solar_text(current_jieqi),
                "prev": _safe(prev_jieqi.getName, "") if prev_jieqi else "",
                "prev_time": _solar_text(prev_jieqi),
                "next": _safe(next_jieqi.getName, "") if next_jieqi else "",
                "next_time": _solar_text(next_jieqi),
            },
            "jianchu": {
                "zhi_xing": _safe(lunar.getZhiXing, ""),
                "tian_shen": _safe(lunar.getDayTianShen, ""),
                "tian_shen_type": _safe(lunar.getDayTianShenType, ""),
                "tian_shen_luck": _safe(lunar.getDayTianShenLuck, ""),
            },
            "xiu": {
                "xiu": _safe(lunar.getXiu, ""),
                "zheng": _safe(lunar.getZheng, ""),
                "animal": _safe(lunar.getAnimal, ""),
                "luck": _safe(lunar.getXiuLuck, ""),
                "song": _safe(lunar.getXiuSong, ""),
                "gong": _safe(lunar.getGong, ""),
                "shou": _safe(lunar.getShou, ""),
            },
            "shensha": {
                "ji_shen": _as_list(_safe(lunar.getDayJiShen)),
                "xiong_sha": _as_list(_safe(lunar.getDayXiongSha)),
            },
            "yi": _as_list(_safe(lunar.getDayYi)),
            "ji": _as_list(_safe(lunar.getDayJi)),
            "chong": {
                "desc": _safe(lunar.getDayChongDesc, ""),
                "sha": _safe(lunar.getDaySha, ""),
                "shengxiao": _safe(lunar.getDayChongShengXiao, ""),
            },
            "pengzu": {
                "gan": _safe(lunar.getPengZuGan, ""),
                "zhi": _safe(lunar.getPengZuZhi, ""),
            },
            "taishen": {
                "day": _safe(lunar.getDayPositionTai, ""),
                "month": _safe(lunar.getMonthPositionTai, ""),
                "year": _safe(lunar.getYearPositionTaiSuiDesc, ""),
            },
            "shichen": {
                "zhi": _safe(lunar.getTimeZhi, ""),
                "ganzhi": time_gz,
                "tian_shen": _safe(lunar.getTimeTianShen, ""),
                "tian_shen_luck": _safe(lunar.getTimeTianShenLuck, ""),
                "yi": _as_list(_safe(lunar.getTimeYi)),
                "ji": _as_list(_safe(lunar.getTimeJi)),
                "chong": _safe(lunar.getTimeChongDesc, ""),
                "sha": _safe(lunar.getTimeSha, ""),
            },
        }

    # ------------------------------------------------------------------
    @staticmethod
    def format_text(info: dict) -> str:
        """把结构化结果格式化为可读文本。"""
        solar = info["solar"]
        lunar = info["lunar"]
        jq = info["jieqi"]
        jc = info["jianchu"]
        xiu = info["xiu"]
        ss = info["shensha"]

        lines = [
            "=" * 52,
            "              农历查询 · 日课排盘",
            "=" * 52,
            f"公历：{solar['date']} {solar['weekday']} {solar['hour']:02d}:{solar['minute']:02d}",
            f"农历：{lunar['text']}（{lunar['year_ganzhi']}年 · 属{lunar['zodiac']}）",
            f"四柱：{info['four_pillars']}",
            f"纳音：年{info['nayin']['year']}｜月{info['nayin']['month']}｜"
            f"日{info['nayin']['day']}｜时{info['nayin']['time']}",
            f"旬空：年{info['xunkong']['year']}｜月{info['xunkong']['month']}｜"
            f"日{info['xunkong']['day']}｜时{info['xunkong']['time']}",
            "-" * 52,
            f"节气：当前【{jq['current']}】{jq['current_time']}",
            f"      上一【{jq['prev']}】{jq['prev_time']}",
            f"      下一【{jq['next']}】{jq['next_time']}",
            f"建除：{jc['zhi_xing']}日｜值神：{jc['tian_shen']}（{jc['tian_shen_luck']}）",
            f"二十八宿：{xiu['xiu']}宿（{xiu['zheng']}{xiu['animal']}，{xiu['luck']}）"
            f"｜{xiu['gong']}宫{xiu['shou']}",
            f"冲煞：{info['chong']['desc']} 煞{info['chong']['sha']}",
            f"胎神：{info['taishen']['day']}",
            "-" * 52,
            f"吉神：{'、'.join(ss['ji_shen']) or '无'}",
            f"凶煞：{'、'.join(ss['xiong_sha']) or '无'}",
            f"宜：{'、'.join(info['yi']) or '无'}",
            f"忌：{'、'.join(info['ji']) or '无'}",
            f"时辰：{info['shichen']['ganzhi']}时（{info['shichen']['tian_shen']}，"
            f"{info['shichen']['tian_shen_luck']}）"
            f"｜时冲{info['shichen']['chong']} 煞{info['shichen']['sha']}",
        ]
        if lunar["festivals"] or lunar["other_festivals"]:
            lines.append(
                f"节日：{'、'.join(lunar['festivals'] + lunar['other_festivals'])}"
            )
        lines.append("=" * 52)
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="农历查询与排盘引擎")
    parser.add_argument("date", nargs="?", help="公历日期 YYYY-MM-DD；缺省为今天")
    parser.add_argument("--lunar", nargs=3, metavar=("YEAR", "MONTH", "DAY"),
                        type=int, help="农历年月日")
    parser.add_argument("--leap", action="store_true", help="农历闰月")
    parser.add_argument("--hour", type=int, default=None, help="小时 0-23")
    parser.add_argument("--minute", type=int, default=0, help="分钟 0-59")
    parser.add_argument("--range", nargs=2, metavar=("START", "DAYS"),
                        help="连续日课：起始日期 天数")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    engine = NongliPaipan()
    hour = args.hour if args.hour is not None else datetime.now().hour

    if args.range:
        start_text, days_text = args.range
        start = date.fromisoformat(start_text)
        results = engine.date_range(start, int(days_text), hour)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for item in results:
                print(engine.format_text(item))
        return

    if args.lunar:
        year, month, day = args.lunar
        info = engine.lunar(year, month, day, hour, args.minute, args.leap)
    elif args.date:
        parsed = date.fromisoformat(args.date)
        info = engine.solar(parsed.year, parsed.month, parsed.day, hour, args.minute)
    else:
        info = engine.today(hour)

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(engine.format_text(info))


if __name__ == "__main__":
    main()
