#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""紫微斗数排盘引擎.

实现：命宫/身宫、寅首、五行局、紫微/天府安星、十四主星、主要辅星煞星、
十天干四化、十二宫、大限、常用格局与庙旺等级。

算法口径见 SKILL.md；核心步骤与《紫微斗数全书》及 dart_iztro 的
起紫微星诀一致，可用 2021-03-19 亥时女命（命宫辰、水二局、紫微辰）自检。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

try:
    from lunar_python import Solar
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "ziwei-doushu 需要 lunar_python。请先执行: pip install lunar-python"
    ) from exc

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
PALACE_NAMES = ["命宫", "兄弟宫", "夫妻宫", "子女宫", "财帛宫", "疾厄宫",
                "迁移宫", "交友宫", "官禄宫", "田宅宫", "福德宫", "父母宫"]

# 60 甲子纳音五行（每两组一个五行）
NAYIN_ELEMENTS = [
    "金", "火", "木", "土", "金", "火", "水", "土", "金", "木",
    "水", "土", "火", "木", "水", "金", "火", "木", "土", "金",
    "火", "水", "土", "金", "木", "水", "土", "火", "木", "水",
]
JU_BY_ELEMENT = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}
JU_NAME = {2: "水二局", 3: "木三局", 4: "金四局", 5: "土五局", 6: "火六局"}

MAIN_STARS = ["紫微", "天机", "太阳", "武曲", "天同", "廉贞",
              "天府", "太阴", "贪狼", "巨门", "天相", "天梁", "七杀", "破军"]

FOUR_TRANSFORMS = {
    "甲": {"化禄": "廉贞", "化权": "破军", "化科": "武曲", "化忌": "太阳"},
    "乙": {"化禄": "天机", "化权": "天梁", "化科": "紫微", "化忌": "太阴"},
    "丙": {"化禄": "天同", "化权": "天机", "化科": "文昌", "化忌": "廉贞"},
    "丁": {"化禄": "太阴", "化权": "天同", "化科": "天机", "化忌": "巨门"},
    "戊": {"化禄": "贪狼", "化权": "太阴", "化科": "右弼", "化忌": "天机"},
    "己": {"化禄": "武曲", "化权": "贪狼", "化科": "天梁", "化忌": "文曲"},
    "庚": {"化禄": "太阳", "化权": "武曲", "化科": "太阴", "化忌": "天同"},
    "辛": {"化禄": "巨门", "化权": "太阳", "化科": "文曲", "化忌": "文昌"},
    "壬": {"化禄": "天梁", "化权": "紫微", "化科": "左辅", "化忌": "武曲"},
    "癸": {"化禄": "破军", "化权": "巨门", "化科": "太阴", "化忌": "贪狼"},
}

# 年干 → 天魁/天钺
KUI_YUE = {
    "甲": ("丑", "未"), "戊": ("丑", "未"), "庚": ("丑", "未"),
    "乙": ("子", "申"), "己": ("子", "申"),
    "丙": ("亥", "酉"), "丁": ("亥", "酉"),
    "辛": ("午", "寅"),
    "壬": ("卯", "巳"), "癸": ("卯", "巳"),
}
# 年干 → 禄存
LU_CUN = {
    "甲": "寅", "乙": "卯", "丙": "巳", "戊": "巳", "丁": "午",
    "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子",
}
# 年支组 → 火星/铃星起点
HUO_LING_START = {
    "申": ("寅", "戌"), "子": ("寅", "戌"), "辰": ("寅", "戌"),
    "寅": ("丑", "卯"), "午": ("丑", "卯"), "戌": ("丑", "卯"),
    "巳": ("卯", "戌"), "酉": ("卯", "戌"), "丑": ("卯", "戌"),
    "亥": ("酉", "戌"), "卯": ("酉", "戌"), "未": ("酉", "戌"),
}
# 年支 → 天马
TIAN_MA = {
    "寅": "申", "午": "申", "戌": "申",
    "申": "寅", "子": "寅", "辰": "寅",
    "巳": "亥", "酉": "亥", "丑": "亥",
    "亥": "巳", "卯": "巳", "未": "巳",
}

# 庙旺利陷（常用主星，缺省为“平”）
BRIGHTNESS = {
    "紫微": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "天机": {"卯": "庙", "酉": "庙", "寅": "得地", "申": "得地", "巳": "旺", "亥": "旺", "子": "陷", "午": "陷"},
    "太阳": {"卯": "庙", "辰": "庙", "午": "庙", "寅": "旺", "巳": "旺", "未": "得地", "申": "得地", "酉": "陷", "戌": "陷", "子": "陷", "亥": "陷"},
    "武曲": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "天同": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "巳": "利", "亥": "利", "丑": "陷", "未": "陷"},
    "廉贞": {"寅": "庙", "申": "庙", "卯": "旺", "酉": "旺", "子": "平", "午": "平", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "天府": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "太阴": {"亥": "庙", "子": "庙", "丑": "庙", "申": "旺", "酉": "旺", "寅": "得地", "卯": "得地", "巳": "陷", "午": "陷"},
    "贪狼": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "巨门": {"子": "旺", "午": "旺", "卯": "庙", "酉": "庙", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "天相": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "天梁": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "七杀": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
    "破军": {"子": "庙", "午": "庙", "卯": "旺", "酉": "旺", "寅": "得地", "申": "得地", "辰": "利", "戌": "利", "丑": "陷", "未": "陷"},
}


def _branch_index(branch: str) -> int:
    return ZHI.index(branch)


def _ganzhi_index(stem: str, branch: str) -> int:
    for i in range(60):
        if GAN[i % 10] == stem and ZHI[i % 12] == branch:
            return i
    raise ValueError(f"无效干支: {stem}{branch}")


def _nayin_element(stem: str, branch: str) -> str:
    return NAYIN_ELEMENTS[_ganzhi_index(stem, branch) // 2]


def _year_stem_base(year_stem: str) -> int:
    """五虎遁：寅宫宫干（1-based）。"""
    stem_1based = GAN.index(year_stem) + 1
    value = (stem_1based * 2 + 1) % 10
    return 10 if value == 0 else value


def _palace_stem(year_stem: str, branch: str) -> str:
    base = _year_stem_base(year_stem)
    offset = (_branch_index(branch) - 2) % 12
    value = (base - 1 + offset) % 10 + 1
    return GAN[value - 1]


def _ziwei_index(day: int, ju: int) -> int:
    """起紫微星：返回寅=0 的宫索引。"""
    offset = 0
    while (day + offset) % ju != 0:
        offset += 1
    quotient = (day + offset) // ju
    index = quotient - 1
    index += offset if offset % 2 == 0 else -offset
    return index % 12


class ZiweiChart:
    """紫微斗数命盘。"""

    def __init__(self, year: int, month: int, day: int, hour: int,
                 gender: str = "male", minute: int = 0):
        solar = Solar.fromYmdHms(int(year), int(month), int(day),
                                 int(hour), int(minute), 0)
        lunar = solar.getLunar()
        self.solar = solar
        self.lunar = lunar
        self.gender = self._normalize_gender(gender)
        self.year_gz = lunar.getYearInGanZhiExact()
        self.month_gz = lunar.getMonthInGanZhiExact()
        self.day_gz = lunar.getDayInGanZhiExact()
        self.time_gz = lunar.getTimeInGanZhi()
        self.year_stem = self.year_gz[0]
        self.year_branch = self.year_gz[1]
        self.lunar_month = abs(lunar.getMonth())
        self.lunar_day = lunar.getDay()
        self.hour_branch = lunar.getTimeZhi()
        self.hour_index = _branch_index(self.hour_branch)

        self.life_branch = ZHI[(2 + (self.lunar_month - 1) - self.hour_index) % 12]
        self.body_branch = ZHI[(2 + (self.lunar_month - 1) + self.hour_index) % 12]

        self.life_stem = _palace_stem(self.year_stem, self.life_branch)
        self.life_gz = self.life_stem + self.life_branch
        self.nayin_element = _nayin_element(self.life_stem, self.life_branch)
        self.ju = JU_BY_ELEMENT[self.nayin_element]
        self.ju_name = JU_NAME[self.ju]

        self.palaces: list[dict] = []
        self._build_palaces()
        self._arrange_stars()
        self._apply_transforms()
        self._build_limits()
        self.patterns = self._detect_patterns()

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_gender(gender: str) -> str:
        text = str(gender).strip().lower()
        if text in ("male", "m", "男", "乾"):
            return "male"
        if text in ("female", "f", "女", "坤"):
            return "female"
        return "male"

    def _build_palaces(self) -> None:
        life_idx = _branch_index(self.life_branch)
        for i, name in enumerate(PALACE_NAMES):
            branch = ZHI[(life_idx - i) % 12]
            self.palaces.append({
                "name": name,
                "branch": branch,
                "stem": _palace_stem(self.year_stem, branch),
                "main_stars": [],
                "minor_stars": [],
                "stars": [],
                "is_body": branch == self.body_branch,
                "is_empty": True,
                "transforms": {},
                "brightness": {},
            })

    def _palace_by_branch(self, branch: str) -> dict:
        for palace in self.palaces:
            if palace["branch"] == branch:
                return palace
        raise KeyError(branch)

    def _add_star(self, name: str, branch: str, kind: str = "main") -> None:
        palace = self._palace_by_branch(branch)
        palace["stars"].append(name)
        if kind == "main":
            palace["main_stars"].append(name)
            palace["is_empty"] = False
            palace["brightness"][name] = BRIGHTNESS.get(name, {}).get(branch, "平")
        else:
            palace["minor_stars"].append(name)

    def _arrange_stars(self) -> None:
        ziwei_idx = _ziwei_index(self.lunar_day, self.ju)
        ziwei_branch = ZHI[(ziwei_idx + 2) % 12]
        # 天府与紫微关于寅申轴对称：branch(天府) = 4 - branch(紫微) (mod 12)
        tianfu_branch = ZHI[(4 - _branch_index(ziwei_branch)) % 12]

        self.ziwei_branch = ziwei_branch
        self.tianfu_branch = tianfu_branch

        zi = _branch_index(ziwei_branch)
        for name, offset in [
            ("紫微", 0), ("天机", -1), ("太阳", -3), ("武曲", -4),
            ("天同", -5), ("廉贞", -8),
        ]:
            self._add_star(name, ZHI[(zi + offset) % 12])

        tf = _branch_index(tianfu_branch)
        for name, offset in [
            ("天府", 0), ("太阴", 1), ("贪狼", 2), ("巨门", 3),
            ("天相", 4), ("天梁", 5), ("七杀", 6), ("破军", 10),
        ]:
            self._add_star(name, ZHI[(tf + offset) % 12])

        # 辅弼昌曲空劫
        month_offset = self.lunar_month - 1
        self._add_star("左辅", ZHI[(4 + month_offset) % 12], "minor")
        self._add_star("右弼", ZHI[(10 - month_offset) % 12], "minor")
        self._add_star("文曲", ZHI[(4 + self.hour_index) % 12], "minor")
        self._add_star("文昌", ZHI[(10 - self.hour_index) % 12], "minor")
        self._add_star("地劫", ZHI[(11 + self.hour_index) % 12], "minor")
        self._add_star("地空", ZHI[(11 - self.hour_index) % 12], "minor")

        # 魁钺
        kui, yue = KUI_YUE[self.year_stem]
        self._add_star("天魁", kui, "minor")
        self._add_star("天钺", yue, "minor")

        # 禄存、擎羊、陀罗
        lu = LU_CUN[self.year_stem]
        lu_idx = _branch_index(lu)
        self._add_star("禄存", lu, "minor")
        self._add_star("擎羊", ZHI[(lu_idx + 1) % 12], "minor")
        self._add_star("陀罗", ZHI[(lu_idx - 1) % 12], "minor")

        # 火铃
        huo_start, ling_start = HUO_LING_START[self.year_branch]
        self._add_star("火星", ZHI[(_branch_index(huo_start) + self.hour_index) % 12], "minor")
        self._add_star("铃星", ZHI[(_branch_index(ling_start) + self.hour_index) % 12], "minor")

        # 天马、红鸾、天喜
        self._add_star("天马", TIAN_MA[self.year_branch], "minor")
        hongluan = ZHI[(3 - _branch_index(self.year_branch)) % 12]
        self._add_star("红鸾", hongluan, "minor")
        self._add_star("天喜", ZHI[(_branch_index(hongluan) + 6) % 12], "minor")

    def _apply_transforms(self) -> None:
        mapping = FOUR_TRANSFORMS[self.year_stem]
        self.transforms = {}
        for transform, star in mapping.items():
            self.transforms[star] = transform
            for palace in self.palaces:
                if star in palace["stars"]:
                    palace["transforms"][star] = transform

    def _build_limits(self) -> None:
        is_yang = GAN.index(self.year_stem) % 2 == 0
        forward = (is_yang and self.gender == "male") or (
            not is_yang and self.gender == "female")
        life_idx = _branch_index(self.life_branch)
        start_age = self.ju
        limits = []
        for i in range(12):
            branch = ZHI[(life_idx + i if forward else life_idx - i) % 12]
            palace = self._palace_by_branch(branch)
            limits.append({
                "palace": palace["name"],
                "branch": branch,
                "start_age": start_age + i * 10,
                "end_age": start_age + i * 10 + 9,
            })
        self.limits = limits
        self.limit_direction = "顺行" if forward else "逆行"

    # ------------------------------------------------------------------
    def _detect_patterns(self) -> list[dict]:
        life = self._palace_by_branch(self.life_branch)
        life_stars = set(life["main_stars"] + life["minor_stars"])
        patterns: list[dict] = []

        def add(name: str, weight: float, desc: str) -> None:
            patterns.append({"name": name, "weight": weight, "description": desc})

        if {"紫微", "天府"} <= set(life["main_stars"]):
            add("紫府同宫", 1.3, "紫微天府同坐命宫，帝王格局，主贵。")
        if {"紫微", "天府", "天相"} <= set(life["main_stars"]):
            add("君臣庆会", 1.5, "紫微、天府、天相同宫，君臣相得，主大富大贵。")
        if {"火星", "贪狼"} <= life_stars:
            add("火贪格", 1.4, "火星贪狼同宫，暴发格局，主横财与突变。")
        if {"铃星", "贪狼"} <= life_stars:
            add("铃贪格", 1.3, "铃星贪狼同宫，突发机遇，来得快去得也快。")
        if {"天相", "擎羊", "廉贞"} <= life_stars:
            add("刑囚夹印", 0.8, "天相被擎羊廉贞夹，主刑讼是非。")
        if not life["main_stars"]:
            add("命无正曜", 0.9, "命宫无十四主星，借对宫安星，人生方向多借外力。")

        sun = self._star_palace("太阳")
        moon = self._star_palace("太阴")
        if sun and moon:
            if sun["branch"] in ("戌", "亥", "子") and moon["branch"] in ("辰", "巳", "午"):
                add("日月反背", 1.2, "太阳太阴俱落陷地，主劳碌奔波，终有所成。")
        if sun and sun["branch"] == "卯":
            add("日照雷门", 1.3, "太阳在卯宫坐守，光明磊落，贵人相助。")
        if moon and moon["branch"] == "亥":
            add("月朗天门", 1.3, "太阴在亥宫坐守，才华出众，富贵双全。")

        life_triad = self._triad_branches(self.life_branch)
        triad_stars = set()
        for branch in life_triad:
            palace = self._palace_by_branch(branch)
            triad_stars.update(palace["main_stars"])
        if {"七杀", "破军", "贪狼"} <= triad_stars:
            add("杀破狼", 1.2, "七杀破军贪狼会照，主变革创新、动荡中求发展。")
        if {"天机", "太阴", "天同", "天梁"} <= triad_stars:
            add("机月同梁", 1.1, "机月同梁会照，主文职清贵、策划管理之才。")
        if {"天府", "天相"} <= triad_stars:
            add("府相朝垣", 1.1, "天府天相会照命宫，主稳健、有辅佐之力。")
        return patterns

    def _star_palace(self, star: str) -> dict | None:
        for palace in self.palaces:
            if star in palace["stars"]:
                return palace
        return None

    def _triad_branches(self, branch: str) -> list[str]:
        idx = _branch_index(branch)
        return [ZHI[idx], ZHI[(idx + 4) % 12], ZHI[(idx + 8) % 12], ZHI[(idx + 6) % 12]]

    # ------------------------------------------------------------------
    def liunian(self, year: int) -> dict:
        """流年盘：流年命宫、流年十二宫、流年四化、所属大限。"""
        stem = GAN[(int(year) - 4) % 10]
        branch = ZHI[(int(year) - 4) % 12]
        idx = _branch_index(branch)
        palaces = []
        for i, name in enumerate(PALACE_NAMES):
            palaces.append({
                "name": name,
                "branch": ZHI[(idx - i) % 12],
            })
        transforms = FOUR_TRANSFORMS[stem]
        age = int(year) - int(self.lunar.getYear()) + 1
        limit = next((item for item in self.limits
                      if item["start_age"] <= age <= item["end_age"]), None)
        return {
            "year": int(year),
            "ganzhi": stem + branch,
            "age": age,
            "life_palace_branch": branch,
            "palaces": palaces,
            "transforms": transforms,
            "limit": limit,
        }

    def to_dict(self) -> dict:
        return {
            "solar": self.solar.toYmdHms(),
            "lunar": {
                "year": self.lunar.getYear(),
                "month": self.lunar_month,
                "day": self.lunar_day,
                "is_leap": self.lunar.getMonth() < 0,
                "text": f"{self.lunar.getYearInChinese()}年"
                        f"{self.lunar.getMonthInChinese()}月"
                        f"{self.lunar.getDayInChinese()}",
            },
            "four_pillars": " ".join([self.year_gz, self.month_gz,
                                      self.day_gz, self.time_gz]),
            "gender": self.gender,
            "life_palace": {
                "branch": self.life_branch,
                "stem": self.life_stem,
                "ganzhi": self.life_gz,
                "nayin_element": self.nayin_element,
                "ju": self.ju,
                "ju_name": self.ju_name,
            },
            "body_palace": {"branch": self.body_branch},
            "ziwei_branch": self.ziwei_branch,
            "tianfu_branch": self.tianfu_branch,
            "palaces": self.palaces,
            "transforms": self.transforms,
            "limits": self.limits,
            "limit_direction": self.limit_direction,
            "patterns": self.patterns,
            "liunian": self.liunian(datetime.now().year),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def format_text(chart: dict) -> str:
        life = chart["life_palace"]
        lines = [
            "=" * 58,
            "                紫微斗数命盘",
            "=" * 58,
            f"公历：{chart['solar']}｜性别：{'男' if chart['gender'] == 'male' else '女'}",
            f"农历：{chart['lunar']['text']}",
            f"四柱：{chart['four_pillars']}",
            f"命宫：{life['ganzhi']}（{life['branch']}）｜{life['ju_name']}"
            f"（纳音{life['nayin_element']}）",
            f"身宫：{chart['body_palace']['branch']}",
            f"紫微：{chart['ziwei_branch']}｜天府：{chart['tianfu_branch']}",
            "-" * 58,
            "十二宫：",
        ]
        for palace in chart["palaces"]:
            stars = []
            for star in palace["stars"]:
                bright = palace["brightness"].get(star)
                transform = palace["transforms"].get(star)
                tag = f"{star}"
                if bright:
                    tag += f"({bright})"
                if transform:
                    tag += f"[{transform}]"
                stars.append(tag)
            body = "·身宫" if palace["is_body"] else ""
            lines.append(
                f"  {palace['name']:<4}{palace['stem']}{palace['branch']}"
                f"{body}：{'、'.join(stars) or '空宫'}"
            )
        lines.append("-" * 58)
        lines.append("大限（{}）：".format(chart["limit_direction"]))
        for limit in chart["limits"]:
            lines.append(
                f"  {limit['start_age']:>2}-{limit['end_age']:<2}岁 "
                f"{limit['palace']}（{limit['branch']}）"
            )
        lines.append("-" * 58)
        ln = chart.get("liunian")
        if ln:
            lines.append(
                f"流年：{ln['year']} {ln['ganzhi']}｜虚岁 {ln['age']}｜"
                f"流年命宫 {ln['life_palace_branch']}"
            )
            if ln.get("limit"):
                lines.append(
                    f"  所属大限：{ln['limit']['start_age']}-{ln['limit']['end_age']}岁 "
                    f"{ln['limit']['palace']}（{ln['limit']['branch']}）"
                )
            lines.append("  流年四化：" + "、".join(
                f"{star}{hua}" for hua, star in ln["transforms"].items()))
        lines.append("-" * 58)
        if chart["patterns"]:
            lines.append("格局：")
            for pattern in chart["patterns"]:
                lines.append(
                    f"  · {pattern['name']}（权重{pattern['weight']}）："
                    f"{pattern['description']}"
                )
        else:
            lines.append("格局：未见显著特殊格局。")
        lines.append("=" * 58)
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="紫微斗数排盘引擎")
    parser.add_argument("--date", default=None, help="公历日期 YYYY-MM-DD")
    parser.add_argument("--hour", type=int, default=None, help="出生小时 0-23")
    parser.add_argument("--minute", type=int, default=0, help="分钟")
    parser.add_argument("--gender", default="male", help="male/female 或 男/女")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    now = datetime.now()
    if args.date:
        year, month, day = [int(part) for part in args.date.split("-")]
    else:
        year, month, day = now.year, now.month, now.day
    hour = args.hour if args.hour is not None else now.hour

    chart = ZiweiChart(year, month, day, hour, args.gender, args.minute)
    data = chart.to_dict()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(ZiweiChart.format_text(data))


if __name__ == "__main__":
    main()
