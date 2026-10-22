#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时家奇门真实排盘（拆补转盘）.

移植自 hermes-agent `divination/mingli/qimen.py`，改为直接使用 lunar_python
计算四柱与节气，去掉对外部 `_common` 包的依赖。

输出：定局、地盘三奇六仪、天盘九星/天盘干、八门、八神、值符值使、空亡驿马。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    from lunar_python import Solar
except ImportError as exc:  # pragma: no cover
    raise ImportError("qimen-paipan 需要 lunar_python。请先执行: pip install lunar-python") from exc

TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
JIAZI = [TIAN_GAN[i % 10] + DI_ZHI[i % 12] for i in range(60)]

# 阳遁局数表：节气 → (上, 中, 下) 元局数
QIMEN_YANG_JU = {
    "冬至": (1, 7, 4), "小寒": (2, 8, 5), "大寒": (3, 9, 6),
    "立春": (8, 5, 2), "雨水": (9, 6, 3), "惊蛰": (1, 7, 4),
    "春分": (3, 9, 6), "清明": (4, 1, 7), "谷雨": (5, 2, 8),
    "立夏": (4, 1, 7), "小满": (5, 2, 8), "芒种": (6, 3, 9),
}
QIMEN_YIN_JU = {
    "夏至": (9, 3, 6), "小暑": (8, 2, 5), "大暑": (7, 1, 4),
    "立秋": (2, 5, 8), "处暑": (1, 4, 7), "白露": (9, 3, 6),
    "秋分": (7, 1, 4), "寒露": (6, 9, 3), "霜降": (5, 8, 2),
    "立冬": (6, 9, 3), "小雪": (5, 8, 2), "大雪": (4, 7, 1),
}

QIMEN_YI_QI = ["戊", "己", "庚", "辛", "壬", "癸", "丁", "丙", "乙"]
LUO_SHU_RING = [1, 8, 3, 4, 9, 2, 7, 6]
LUO_SHU_RING_CCW = [1, 6, 7, 2, 9, 4, 3, 8]
QIMEN_BASIC_XING = ["天蓬", "天芮", "天冲", "天辅", "天禽", "天心", "天柱", "天任", "天英"]
QIMEN_BASIC_MEN = ["休", "死", "伤", "杜", "", "开", "惊", "生", "景"]
QIMEN_SHEN = ["值符", "腾蛇", "太阴", "六合", "白虎", "玄武", "九地", "九天"]
QIMEN_GONG_WEI = [
    ("坎", "北"), ("坤", "西南"), ("震", "东"), ("巽", "东南"), ("中", "中"),
    ("乾", "西北"), ("兑", "西"), ("艮", "东北"), ("离", "南"),
]
YIMA = {"寅": "申", "午": "申", "戌": "申", "巳": "亥", "酉": "亥", "丑": "亥",
        "申": "寅", "子": "寅", "辰": "寅", "亥": "巳", "卯": "巳", "未": "巳"}
XUN_SHOU_LIUYI = {"子": "戊", "戌": "己", "申": "庚", "午": "辛", "辰": "壬", "寅": "癸"}

MEN_LEVEL = {"休": "大吉", "生": "大吉", "伤": "凶", "杜": "平", "景": "平",
             "死": "大凶", "惊": "凶", "开": "大吉"}
XING_LEVEL = {"天蓬": "大凶", "天芮": "凶", "天冲": "小吉", "天辅": "大吉",
              "天禽": "大吉", "天心": "大吉", "天柱": "小凶", "天任": "小吉",
              "天英": "小凶"}


@dataclass
class Gong:
    gong: int
    name: str
    direction: str
    star: str
    men: str
    shen: str
    di_gan: str
    an_gan: str
    tian_pan_gan: str
    level: str = ""


@dataclass
class QimenReport:
    four_pillars: str
    yin_yang: str
    ju: int
    yuan: str
    term: str
    days_in_term: int
    xun_shou: str
    xun_shou_liu_yi: str
    zhi_fu_gong: int
    zhi_fu_xing: str
    zhi_fu_luo_gong: int
    zhi_shi_men: str
    zhi_shi_gong: int
    yong_shen_gong: int
    kong_wang: str
    yi_ma: str
    palaces: list = field(default_factory=list)

    def palace(self, gong: int) -> Optional[Gong]:
        return next((p for p in self.palaces if p.gong == gong), None)

    def to_dict(self) -> dict:
        return {
            "four_pillars": self.four_pillars,
            "yin_yang": self.yin_yang,
            "ju": self.ju,
            "yuan": self.yuan,
            "term": self.term,
            "days_in_term": self.days_in_term,
            "xun_shou": self.xun_shou,
            "xun_shou_liu_yi": self.xun_shou_liu_yi,
            "zhi_fu_gong": self.zhi_fu_gong,
            "zhi_fu_star": self.zhi_fu_xing,
            "zhi_fu_luo_gong": self.zhi_fu_luo_gong,
            "zhi_shi_men": self.zhi_shi_men,
            "zhi_shi_gong": self.zhi_shi_gong,
            "yong_shen_gong": self.yong_shen_gong,
            "kong_wang": self.kong_wang,
            "yi_ma": self.yi_ma,
            "palaces": [
                {
                    "gong": p.gong, "name": p.name, "direction": p.direction,
                    "star": p.star, "men": p.men or "中", "shen": p.shen or "值符",
                    "level": p.level, "tianpan_gan": p.tian_pan_gan,
                    "dipan_gan": p.di_gan, "an_gan": p.an_gan,
                }
                for p in self.palaces
            ],
            "tianpan_gan": {p.gong: p.tian_pan_gan for p in self.palaces},
            "dipan_gan": {p.gong: p.di_gan for p in self.palaces},
        }


def hour_zhi_idx(hour: int) -> int:
    if hour in (23, 0):
        return 0
    return (hour + 1) // 2


def ganzhi_index(ganzhi: str) -> int:
    return JIAZI.index(ganzhi)


def _solar_term(dt: datetime) -> tuple[str, datetime, int]:
    solar = Solar.fromYmdHms(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
    lunar = solar.getLunar()
    prev = lunar.getPrevJieQi()
    next_jq = lunar.getNextJieQi()
    current = lunar.getCurrentJieQi() or prev
    term = current.getName() if current else (prev.getName() if prev else "冬至")
    term_solar = (current or prev).getSolar()
    term_dt = datetime(term_solar.getYear(), term_solar.getMonth(),
                       term_solar.getDay(), term_solar.getHour(),
                       term_solar.getMinute())
    days = (dt.date() - term_dt.date()).days
    if days < 0 and next_jq:
        term = next_jq.getName()
        s = next_jq.getSolar()
        term_dt = datetime(s.getYear(), s.getMonth(), s.getDay(),
                           s.getHour(), s.getMinute())
        days = 0
    return term, term_dt, max(0, days)


def _ring_idx(gong: int) -> int:
    return LUO_SHU_RING.index(gong)


def compute_qimen(year: int, month: int, day: int, hour: int,
                  minute: int = 0) -> QimenReport:
    dt = datetime(year, month, day, hour, minute)
    solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
    lunar = solar.getLunar()

    year_gz = lunar.getYearInGanZhiExact()
    month_gz = lunar.getMonthInGanZhiExact()
    day_gz = lunar.getDayInGanZhiExact()
    shi_zhi = lunar.getTimeZhi()
    shi_gan = lunar.getTimeGan()
    four = f"{year_gz} {month_gz} {day_gz} {shi_gan}{shi_zhi}"

    # 定局
    term, _, days_in_term = _solar_term(dt)
    day_idx = ganzhi_index(day_gz)
    fu_tou_idx = day_idx - (day_idx % 5)
    yuan_idx = (fu_tou_idx // 5) % 3
    yuan_name = ["上元", "中元", "下元"][yuan_idx]
    if term in QIMEN_YANG_JU:
        is_yang = True
        ju = QIMEN_YANG_JU[term][yuan_idx]
    elif term in QIMEN_YIN_JU:
        is_yang = False
        ju = QIMEN_YIN_JU[term][yuan_idx]
    else:
        is_yang = 5 <= month <= 11
        ju = 3

    # 旬首
    shi_idx = ganzhi_index(f"{shi_gan}{shi_zhi}")
    xun_shou_idx = shi_idx - (shi_idx % 10)
    xun_shou_zhi = DI_ZHI[xun_shou_idx % 12]
    xun_shou = f"甲{xun_shou_zhi}"
    liu_yi = XUN_SHOU_LIUYI.get(xun_shou_zhi, "戊")

    # 地盘
    di_pan = [""] * 10
    for i, gan in enumerate(QIMEN_YI_QI):
        gong_num = (ju - 1 + i) % 9 + 1 if is_yang else ((ju + 8 - i) % 9) + 1
        di_pan[gong_num] = gan

    def find_gan_gong(gan: str) -> int:
        for g in LUO_SHU_RING:
            if di_pan[g] == gan:
                return g
        return 2 if di_pan[5] == gan else 2

    zhi_fu_gong = find_gan_gong(liu_yi)
    zhi_fu_xing = QIMEN_BASIC_XING[zhi_fu_gong - 1]
    zhi_shi_men = QIMEN_BASIC_MEN[zhi_fu_gong - 1]
    shi_gan_gong = zhi_fu_gong if shi_gan == "甲" else find_gan_gong(shi_gan)

    # 天盘九星
    steps = (_ring_idx(shi_gan_gong) + 8 - _ring_idx(zhi_fu_gong)) % 8
    star_mapping = [""] * 10
    tian_pan_gan = [""] * 10
    for i in range(8):
        orig = LUO_SHU_RING[i]
        new = LUO_SHU_RING[(i + steps) % 8]
        star_mapping[new] = QIMEN_BASIC_XING[orig - 1]
        tian_pan_gan[new] = di_pan[orig]
    star_mapping[5] = "天禽"
    tian_pan_gan[5] = tian_pan_gan[2]

    # 人盘八门
    hour_diff = shi_idx - xun_shou_idx
    if is_yang:
        zs_num = ((zhi_fu_gong - 1 + hour_diff) % 9) + 1
    else:
        zs_num = ((zhi_fu_gong - 1 - (hour_diff % 9) + 9) % 9) + 1
    zhi_shi_gong = 2 if zs_num == 5 else zs_num
    ring_steps = (_ring_idx(zhi_shi_gong) + 8 - _ring_idx(zhi_fu_gong)) % 8
    men_mapping = [""] * 10
    an_gan = [""] * 10
    for i in range(8):
        orig = LUO_SHU_RING[i]
        new = LUO_SHU_RING[(i + ring_steps) % 8]
        men_mapping[new] = QIMEN_BASIC_MEN[orig - 1]
        an_gan[new] = di_pan[orig]
    men_mapping[5] = ""
    an_gan[5] = di_pan[5]

    # 神盘八神
    shen_position = [""] * 10
    order = LUO_SHU_RING if is_yang else LUO_SHU_RING_CCW
    zf_ring = order.index(shi_gan_gong)
    for i in range(8):
        g = order[(zf_ring + i) % 8]
        shen_position[g] = QIMEN_SHEN[i]
    shen_position[5] = ""

    kong_wang = DI_ZHI[(xun_shou_idx + 10) % 12] + DI_ZHI[(xun_shou_idx + 11) % 12]
    yi_ma = YIMA.get(shi_zhi, "")

    palaces = []
    for gno in range(1, 10):
        name, direction = QIMEN_GONG_WEI[gno - 1]
        star = star_mapping[gno]
        men = men_mapping[gno]
        shen = shen_position[gno]
        sl = XING_LEVEL.get(star, "平")
        ml = MEN_LEVEL.get(men, "平")
        if sl in ("大凶", "凶") or ml in ("凶", "大凶"):
            level = "凶"
        elif sl == "大吉" and ml == "大吉":
            level = "大吉"
        elif "吉" in sl or "吉" in ml:
            level = "小吉"
        else:
            level = "平"
        palaces.append(Gong(gno, name, direction, star, men, shen,
                            di_pan[gno], an_gan[gno], tian_pan_gan[gno], level))

    return QimenReport(
        four_pillars=four, yin_yang="阳遁" if is_yang else "阴遁", ju=ju,
        yuan=yuan_name, term=term, days_in_term=days_in_term,
        xun_shou=xun_shou, xun_shou_liu_yi=liu_yi,
        zhi_fu_gong=zhi_fu_gong, zhi_fu_xing=zhi_fu_xing,
        zhi_fu_luo_gong=shi_gan_gong, zhi_shi_men=zhi_shi_men,
        zhi_shi_gong=zhi_shi_gong, yong_shen_gong=shi_gan_gong,
        kong_wang=kong_wang, yi_ma=yi_ma, palaces=palaces,
    )


def format_qimen(report: QimenReport) -> str:
    lines = [
        f"四柱：{report.four_pillars}",
        f"{report.yin_yang} {report.ju}局 {report.yuan}"
        f"（{report.term}后{report.days_in_term}日）",
        f"旬首：{report.xun_shou}（{report.xun_shou_liu_yi}）"
        f"  值符{report.zhi_fu_xing}落{report.zhi_fu_luo_gong}宫"
        f"  值使{report.zhi_shi_men}落{report.zhi_shi_gong}宫",
        f"空亡：{report.kong_wang}  驿马：{report.yi_ma}",
        "",
    ]
    label = {g.gong: g for g in report.palaces}
    for row in ([4, 9, 2], [3, 5, 7], [8, 1, 6]):
        cells = []
        for gno in row:
            g = label[gno]
            cells.append(f"{g.name}{g.gong}:{g.star}/{g.men}/{g.shen}/"
                         f"{g.tian_pan_gan}|{g.di_gan}")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="时家奇门排盘")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--month", type=int, default=datetime.now().month)
    parser.add_argument("--day", type=int, default=datetime.now().day)
    parser.add_argument("--hour", type=int, default=datetime.now().hour)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = compute_qimen(args.year, args.month, args.day, args.hour)
    if args.json:
        import json
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_qimen(report))


if __name__ == "__main__":
    main()
