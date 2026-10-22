#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙神数岁计推演引擎.

算法主线取自《太乙金镜式经》（唐·王希明）与《太乙统宗宝鉴》常用格局。
所有锚点与公式均在代码中显式写出，便于按不同师承替换参数。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 上元甲子至唐开元十二年甲子（724）积年
EPOCH_YEAR = 724
EPOCH_JINIAN = 1_937_281

# 太乙顺行八宫，不游中五
TAIYI_PALACE_RING = [1, 2, 3, 4, 6, 7, 8, 9]

# 十六神（顺行）
SHISHEN = [
    ("地主", "子"), ("阳德", "丑"), ("和德", "艮"), ("吕申", "寅"),
    ("高丛", "卯"), ("太阳", "辰"), ("大炅", "巽"), ("大神", "巳"),
    ("大威", "午"), ("天道", "未"), ("大武", "坤"), ("武德", "申"),
    ("太簇", "酉"), ("阴主", "戌"), ("阴德", "乾"), ("大义", "亥"),
]
SHISHEN_INDEX = {name: i for i, (name, _) in enumerate(SHISHEN)}
SHISHEN_BRANCH = {name: branch for name, branch in SHISHEN}
BRANCH_TO_PALACE = {
    "子": 1, "丑": 8, "寅": 8, "卯": 3, "辰": 4, "巳": 4,
    "午": 9, "未": 2, "申": 2, "酉": 7, "戌": 6, "亥": 6,
}
PALACE_TO_BRANCH = {
    1: "子", 2: "未", 3: "卯", 4: "辰", 6: "戌", 7: "酉", 8: "丑", 9: "午",
}
PALACE_NAME = {
    1: "坎一宫", 2: "坤二宫", 3: "震三宫", 4: "巽四宫",
    6: "乾六宫", 7: "兑七宫", 8: "艮八宫", 9: "离九宫",
}

# 岁计八门：开、休、生、伤、杜、景、死、惊
EIGHT_DOORS = ["开", "休", "生", "伤", "杜", "景", "死", "惊"]

PATTERN_MEANING = {
    "掩": "始击临太乙，主纲纪失序、上压下、宜修德禳解。",
    "迫": "始击邻太乙，主逼迫、事势紧、宜先解外压。",
    "囚": "文昌临太乙，主谋而受制、才不得伸。",
    "击": "始击临文昌，主客犯主谋、竞争与冲突加剧。",
    "格": "始击对太乙，主上下相格、政令不通。",
    "对": "文昌对太乙，主臣怀二心、信息不对称。",
}


def _jinian(year: int) -> int:
    return EPOCH_JINIAN + (int(year) - EPOCH_YEAR)


def _ganzhi(index: int) -> str:
    return GAN[index % 10] + ZHI[index % 12]


def _palace_index(palace: int) -> int:
    return TAIYI_PALACE_RING.index(palace)


def _is_opposite(a: int, b: int) -> bool:
    return (a, b) in {(1, 9), (9, 1), (2, 8), (8, 2),
                      (3, 7), (7, 3), (4, 6), (6, 4)}


def _is_adjacent(a: int, b: int) -> bool:
    ia, ib = _palace_index(a), _palace_index(b)
    diff = abs(ia - ib)
    return diff == 1 or diff == len(TAIYI_PALACE_RING) - 1


def _count_between(start_branch: str, end_branch: str) -> int:
    """顺行数宫：含起点与终点。"""
    start = ZHI.index(start_branch)
    end = ZHI.index(end_branch)
    return (end - start) % 12 + 1


def _general(count: int) -> int:
    """主/客大将：取个位，0 作 9。"""
    value = count % 10
    return 9 if value == 0 else value


def _assistant(general: int) -> int:
    """参将 = 大将 + 3；超过 9 减 9。"""
    value = general + 3
    return value - 9 if value > 9 else value


def _tianmu_index(jinian: int) -> int:
    """天目（文昌）：积年去 360、72、18，命起武德，遇武德、大武重留一算。"""
    n = (jinian - 1) % 360
    n %= 72
    n %= 18
    index = SHISHEN_INDEX["武德"]
    remaining = n
    while remaining > 0:
        index = (index + 1) % 16
        remaining -= 1
        if SHISHEN[index][0] in ("武德", "大武"):
            remaining -= 1
    return index


def _jishen_branch(jinian: int) -> str:
    """计神：积年去 60，命起寅宫，逆行十二辰。"""
    n = (jinian - 1) % 60
    return ZHI[(2 - n) % 12]


def _shiji_index(tianmu_index: int, jishen_branch: str) -> int:
    """始击（客目）：计神加和德，顺行十六神，视天目所临。"""
    jishen_index = next(
        (i for i, (_, branch) in enumerate(SHISHEN)
         if branch == jishen_branch),
        0,
    )
    hede_index = SHISHEN_INDEX["和德"]
    shift = (jishen_index - hede_index) % 16
    return (tianmu_index + shift) % 16


class TaiyiEngine:
    """太乙神数岁计引擎。"""

    def year_pan(self, year: int | None = None) -> dict:
        year = int(year or datetime.now().year)
        jinian = _jinian(year)

        # 太岁 / 六纪
        suishu_index = (jinian - 1) % 60
        taishui = _ganzhi(suishu_index)
        ji = (jinian - 1) % 360 // 60
        ru_ji = (jinian - 1) % 60

        # 太乙宫
        n24 = (jinian - 1) % 24
        palace_index = n24 // 3
        ru_gong = n24 % 3
        taiyi_palace = TAIYI_PALACE_RING[palace_index]
        taiyi_branch = PALACE_TO_BRANCH[taiyi_palace]

        # 天目 / 计神 / 始击
        tianmu_index = _tianmu_index(jinian)
        tianmu_name, tianmu_branch = SHISHEN[tianmu_index]
        tianmu_palace = BRANCH_TO_PALACE[tianmu_branch]

        jishen_branch = _jishen_branch(jinian)
        jishen_name = next(
            (name for name, branch in SHISHEN if branch == jishen_branch),
            "计神",
        )
        he_shen_branch = ZHI[(ZHI.index(taishui[1]) + 1) % 12]

        shiji_index = _shiji_index(tianmu_index, jishen_branch)
        shiji_name, shiji_branch = SHISHEN[shiji_index]
        shiji_palace = BRANCH_TO_PALACE[shiji_branch]

        # 主客算
        host_count = _count_between(tianmu_branch, taiyi_branch)
        guest_count = _count_between(shiji_branch, taiyi_branch)
        host_general = _general(host_count)
        guest_general = _general(guest_count)
        host_assistant = _assistant(host_general)
        guest_assistant = _assistant(guest_general)

        # 八门
        n720 = (jinian - 1) % 720
        door_index = (n720 % 240) // 30 % 8
        door = EIGHT_DOORS[door_index]

        # 格局
        patterns = self._patterns(taiyi_palace, tianmu_palace, shiji_palace)
        pattern_names = {p["name"] for p in patterns}

        # 主客胜负
        host_score = host_count + (2 if door in ("开", "休", "生") else 0)
        guest_score = guest_count
        host_score -= sum(2 for name in pattern_names
                          if name in ("掩", "迫", "囚", "击", "格"))
        winner = "主胜" if host_score > guest_score else (
            "客胜" if guest_score > host_score else "主客相当")
        if pattern_names & {"掩", "格", "对"}:
            advice = "先守后动，先解外压再图进取；不宜强行开局。"
        elif "囚" in pattern_names:
            advice = "谋事受制，宜借力、缓进，先修补内部缺口。"
        elif winner == "主胜":
            advice = "主势可用，宜主动布局，但须留后手。"
        elif winner == "客胜":
            advice = "客势在外，宜借势、合作、后发制人。"
        else:
            advice = "主客相当，宜守中待时，不做单边重注。"

        return {
            "year": year,
            "jinian": {
                "value": jinian,
                "epoch": f"唐开元十二年甲子（{EPOCH_YEAR}）= {EPOCH_JINIAN}",
                "ji": ji + 1,
                "ru_ji_year": ru_ji,
                "taishui": taishui,
                "suishu_index": suishu_index + 1,
            },
            "taiyi": {
                "palace": taiyi_palace,
                "palace_name": PALACE_NAME[taiyi_palace],
                "branch": taiyi_branch,
                "ru_gong_year": ru_gong,
                "yin_yang": "阳宫" if taiyi_palace % 2 == 1 else "阴宫",
            },
            "tianmu": {
                "name": tianmu_name,
                "branch": tianmu_branch,
                "palace": tianmu_palace,
                "palace_name": PALACE_NAME[tianmu_palace],
                "role": "文昌/下目/主",
            },
            "jishen": {
                "branch": jishen_branch,
                "name": jishen_name,
                "he_shen": he_shen_branch,
                "note": "计神起寅逆行；合神随太岁顺行一位",
            },
            "shiji": {
                "name": shiji_name,
                "branch": shiji_branch,
                "palace": shiji_palace,
                "palace_name": PALACE_NAME[shiji_palace],
                "role": "始击/上目/客",
            },
            "calculations": {
                "host": {
                    "count": host_count,
                    "general": host_general,
                    "assistant": host_assistant,
                    "path": f"{tianmu_branch}→{taiyi_branch}",
                },
                "guest": {
                    "count": guest_count,
                    "general": guest_general,
                    "assistant": guest_assistant,
                    "path": f"{shiji_branch}→{taiyi_branch}",
                },
            },
            "eight_doors": {
                "door": door,
                "position": door_index + 1,
            },
            "patterns": patterns,
            "judgement": {
                "host_score": host_score,
                "guest_score": guest_score,
                "winner": winner,
                "advice": advice,
            },
        }

    @staticmethod
    def _patterns(taiyi: int, tianmu: int, shiji: int) -> list[dict]:
        patterns: list[dict] = []

        def add(name: str) -> None:
            patterns.append({
                "name": name,
                "meaning": PATTERN_MEANING[name],
            })

        if shiji == taiyi:
            add("掩")
        elif _is_adjacent(shiji, taiyi):
            add("迫")
        if tianmu == taiyi:
            add("囚")
        if shiji == tianmu:
            add("击")
        if _is_opposite(shiji, taiyi):
            add("格")
        if _is_opposite(tianmu, taiyi):
            add("对")
        return patterns

    @staticmethod
    def format_text(pan: dict) -> str:
        taiyi = pan["taiyi"]
        tianmu = pan["tianmu"]
        shiji = pan["shiji"]
        calc = pan["calculations"]
        judge = pan["judgement"]
        lines = [
            "=" * 56,
            "              太乙神数 · 岁计推演",
            "=" * 56,
            f"公元：{pan['year']} 年",
            f"积年：{pan['jinian']['value']}（{pan['jinian']['epoch']}）",
            f"六纪：第 {pan['jinian']['ji']} 纪，入纪 {pan['jinian']['ru_ji_year']} 年"
            f"｜太岁 {pan['jinian']['taishui']}",
            "-" * 56,
            f"太乙：{taiyi['palace_name']}（{taiyi['branch']}）"
            f"｜{taiyi['yin_yang']}｜入宫 {taiyi['ru_gong_year']} 年",
            f"文昌：{tianmu['name']}·{tianmu['palace_name']}（{tianmu['branch']}）",
            f"计神：{pan['jishen']['name']}（{pan['jishen']['branch']}）"
            f"｜合神 {pan['jishen']['he_shen']}",
            f"始击：{shiji['name']}·{shiji['palace_name']}（{shiji['branch']}）",
            "-" * 56,
            f"主算：{calc['host']['count']}｜主大将 {calc['host']['general']}"
            f"｜主参将 {calc['host']['assistant']}",
            f"客算：{calc['guest']['count']}｜客大将 {calc['guest']['general']}"
            f"｜客参将 {calc['guest']['assistant']}",
            f"岁计直门：{pan['eight_doors']['door']}门"
            f"（第 {pan['eight_doors']['position']} 门）",
            "-" * 56,
            "格局：",
        ]
        if pan["patterns"]:
            for pattern in pan["patterns"]:
                lines.append(f"  · {pattern['name']}：{pattern['meaning']}")
        else:
            lines.append("  · 无显著格局（掩/迫/囚/击/格/对）")
        lines.extend([
            "-" * 56,
            f"主客：主 {judge['host_score']} vs 客 {judge['guest_score']}"
            f" → {judge['winner']}",
            f"建议：{judge['advice']}",
            "=" * 56,
        ])
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="太乙神数岁计推演引擎")
    parser.add_argument("--year", type=int, default=None, help="公元年份")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    engine = TaiyiEngine()
    pan = engine.year_pan(args.year)
    if args.json:
        print(json.dumps(pan, ensure_ascii=False, indent=2))
    else:
        print(engine.format_text(pan))


if __name__ == "__main__":
    main()
