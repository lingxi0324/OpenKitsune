#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北斗七星与九宫飞星针法推演引擎.

数据来源：丹道玄医录
- 《北斗七星与奇门遁甲针法·针灸大成合参定稿》
- 《天罡北斗针阵·十二时辰命宫配穴全诀》
- 《北斗七星三才针阵体系总诀》
- 《九宫飞星三合阵（洛书九宫乘北斗九星）》
"""
from __future__ import annotations

import argparse
import json
from typing import Any

ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
ZHI_HOUR = {
    "子": "23:00-00:59", "丑": "01:00-02:59", "寅": "03:00-04:59",
    "卯": "05:00-06:59", "辰": "07:00-08:59", "巳": "09:00-10:59",
    "午": "11:00-12:59", "未": "13:00-14:59", "申": "15:00-16:59",
    "酉": "17:00-18:59", "戌": "19:00-20:59", "亥": "21:00-22:59",
}
STAR_LORD = {
    "子": "贪狼", "丑": "巨门", "寅": "禄存", "卯": "文曲",
    "辰": "廉贞", "巳": "武曲", "午": "破军", "未": "左辅",
    "申": "右弼", "酉": "天魁", "戌": "天钺", "亥": "天府",
}
CHANNEL = {
    "子": "胆经", "丑": "肝经", "寅": "肺经", "卯": "大肠经",
    "辰": "胃经", "巳": "脾经", "午": "心经", "未": "小肠经",
    "申": "膀胱经", "酉": "肾经", "戌": "心包经", "亥": "三焦经",
}

# 十二命宫 × 十二时辰三才针阵
# 字段：命宫|施针时辰|天|地|人|四辅|手法
_TREAT_TABLE = """
子|子|膻中|日月|风池|太溪、照海、天枢、百会|青龙摆尾
子|丑|关元|期门|太冲|肝俞、阳陵泉、三阴交、行间|白虎摇头
子|寅|中脘|中府|尺泽|肺俞、孔最、列缺、膻中|苍龟探穴
子|卯|气海|合谷|曲池|天枢、手三里、太渊、足三里|凤凰展翅
子|辰|大椎|足三里|内庭|中脘、梁门、公孙、丰隆|赤凤迎源
子|巳|神阙|三阴交|血海|太白、阴陵泉、章门、地机|饿马摇铃
子|午|命门|少海|通里|心俞、神门、劳宫、至阳|子午捣臼
子|未|百会|后溪|腕骨|支正、小海、关元、下巨虚|龙虎交战
子|申|涌泉|委中|昆仑|肾俞、申脉、太溪、飞扬|进气
子|酉|劳宫|太溪|复溜|照海、水泉、命门、气海|烧山火
子|戌|三阴交|内关|郄门|大陵、间使、膻中、巨阙|抽添
子|亥|太渊|阳池|外关|支沟、会宗、石门、水分|透天凉
丑|子|关元|太冲|阳陵泉|日月、丘墟、侠溪、带脉|青龙摆尾
丑|丑|期门|行间|曲泉|章门、中都、蠡沟、肝俞|苍龟探穴
丑|寅|中府|经渠|鱼际|孔最、列缺、尺泽、太渊|白虎摇头
丑|卯|合谷|温溜|偏历|曲池、手三里、上巨虚、天枢|赤凤迎源
丑|辰|足三里|梁丘|冲阳|内庭、丰隆、公孙、解溪|凤凰展翅
丑|巳|三阴交|地机|大都|阴陵泉、太白、公孙、血海|饿马摇铃
丑|午|少海|灵道|阴郄|通里、神门、巨阙、至阳|子午捣臼
丑|未|后溪|腕骨|养老|支正、小海、关元、下巨虚|龙虎交战
丑|申|委中|金门|束骨|昆仑、申脉、肾俞、太溪|进气
丑|酉|太溪|水泉|大钟|复溜、照海、命门、气海|烧山火
丑|戌|内关|劳宫|大陵|郄门、间使、膻中、巨阙|抽添
丑|亥|阳池|四渎|会宗|外关、支沟、石门、水分|透天凉
寅|子|中脘|风池|带脉|日月、太溪、丘墟、阳陵泉|苍龟探穴
寅|丑|期门|章门|中都|太冲、行间、蠡沟、肝俞|白虎摇头
寅|寅|中府|云门|孔最|尺泽、列缺、膻中、太渊|赤凤迎源
寅|卯|合谷|阳溪|温溜|曲池、手三里、天枢、上巨虚|凤凰展翅
寅|辰|足三里|梁门|解溪|内庭、丰隆、公孙、冲阳|子午捣臼
寅|巳|三阴交|地机|阴陵泉|血海、太白、公孙、章门|龙虎交战
寅|午|巨阙|灵台|通里|少海、神门、至阳、劳宫|进气
寅|未|关元|下巨虚|支正|后溪、腕骨、小海、足临泣|烧山火
寅|申|肾俞|飞扬|昆仑|委中、申脉、太溪、金门|抽添
寅|酉|太溪|照海|复溜|水泉、大钟、命门、气海|透天凉
寅|戌|膻中|天池|间使|内关、大陵、郄门、巨阙|青龙摆尾
寅|亥|石门|四渎|会宗|阳池、外关、支沟、水分|白虎摇头
卯|子|气海|日月|丘墟|风池、带脉、阳陵泉、太冲|苍龟探穴
卯|丑|章门|中都|期门|行间、太冲、蠡沟、肝俞|赤凤迎源
卯|寅|云门|天府|列缺|中府、尺泽、孔最、太渊|凤凰展翅
卯|卯|阳溪|偏历|手三里|合谷、曲池、天枢、上巨虚|子午捣臼
卯|辰|梁门|伏兔|内庭|足三里、丰隆、公孙、解溪|龙虎交战
卯|巳|地机|血海|公孙|三阴交、太白、阴陵泉、章门|进气
卯|午|灵台|至阳|少冲|巨阙、通里、神门、劳宫|烧山火
卯|未|下巨虚|小海|养老|关元、支正、腕骨、足临泣|透天凉
卯|申|飞扬|承山|申脉|肾俞、昆仑、太溪、金门|抽添
卯|酉|照海|水泉|大钟|太溪、复溜、命门、气海|青龙摆尾
卯|戌|天池|郄门|劳宫|膻中、内关、大陵、巨阙|白虎摇头
卯|亥|四渎|清冷渊|支沟|石门、阳池、外关、水分|苍龟探穴
辰|子|大椎|梁门|解溪|足三里、内庭、公孙、丰隆|赤凤迎源
辰|丑|中脘|足三里|冲阳|梁丘、内庭、丰隆、公孙|凤凰展翅
辰|寅|膻中|肺俞|孔最|中府、尺泽、列缺、太渊|苍龟探穴
辰|卯|合谷|曲池|偏历|温溜、手三里、天枢、上巨虚|赤凤迎源
辰|辰|足三里|内庭|丰隆|梁门、解溪、公孙、中脘|凤凰展翅
辰|巳|三阴交|阴陵泉|血海|太白、公孙、章门、地机|饿马摇铃
辰|午|巨阙|少府|通里|神门、灵道、至阳、涌泉|子午捣臼
辰|未|关元|后溪|支正|腕骨、小海、下巨虚、足临泣|龙虎交战
辰|申|肾俞|委中|昆仑|申脉、金门、太溪、飞扬|进气
辰|酉|气海|太溪|照海|复溜、水泉、命门、涌泉|烧山火
辰|戌|膻中|内关|劳宫|大陵、郄门、间使、巨阙|抽添
辰|亥|石门|阳池|支沟|外关、四渎、会宗、水分|透天凉
巳|子|神阙|公孙|太白|三阴交、血海、章门、地机|饿马摇铃
巳|丑|章门|三阴交|阴陵泉|太白、公孙、血海、地机|凤凰展翅
巳|寅|中府|尺泽|列缺|孔最、经渠、太渊、膻中|白虎摇头
巳|卯|天枢|上巨虚|下巨虚|合谷、曲池、手三里、温溜|赤凤迎源
巳|辰|足三里|丰隆|梁丘|内庭、解溪、公孙、中脘|赤凤迎源
巳|巳|三阴交|血海|地机|太白、阴陵泉、公孙、章门|饿马摇铃
巳|午|至阳|神门|少冲|通里、灵道、巨阙、涌泉|子午捣臼
巳|未|关元|腕骨|养老|后溪、支正、小海、下巨虚|龙虎交战
巳|申|肾俞|飞扬|申脉|委中、昆仑、太溪、金门|进气
巳|酉|太溪|照海|复溜|水泉、大钟、命门、气海|烧山火
巳|戌|内关|郄门|间使|大陵、劳宫、膻中、巨阙|抽添
巳|亥|外关|支沟|四渎|阳池、会宗、石门、水分|透天凉
午|子|命门|至阳|胆俞|日月、风池、太溪、涌泉|子午捣臼
午|丑|少海|期门|曲泉|太冲、行间、阳陵泉、三阴交|龙虎交战
午|寅|神门|中府|孔最|尺泽、列缺、膻中、太渊|赤凤迎源
午|卯|通里|合谷|温溜|曲池、偏历、天枢、足三里|凤凰展翅
午|辰|巨阙|足三里|梁门|中脘、内庭、公孙、丰隆|饿马摇铃
午|巳|灵道|三阴交|血海|阴陵泉、太白、章门、地机|进气
午|午|至阳|少府|通里|神门、灵台、劳宫、涌泉|子午捣臼
午|未|腕骨|关元|支正|后溪、小海、下巨虚、足临泣|龙虎交战
午|申|肾俞|委中|飞扬|昆仑、申脉、太溪、金门|赤凤迎源
午|酉|气海|太溪|复溜|照海、水泉、命门、涌泉|烧山火
午|戌|膻中|内关|劳宫|大陵、郄门、间使、巨阙|抽添
午|亥|石门|外关|支沟|阳池、四渎、会宗、水分|透天凉
未|子|百会|风池|日月|丘墟、侠溪、太溪、照海|青龙摆尾
未|丑|后溪|章门|中都|太冲、行间、阳陵泉、三阴交|白虎摇头
未|寅|支正|中府|经渠|孔最、列缺、尺泽、鱼际|苍龟探穴
未|卯|小海|合谷|手三里|曲池、偏历、天枢、上巨虚|凤凰展翅
未|辰|养老|足三里|解溪|梁丘、内庭、公孙、丰隆|饿马摇铃
未|巳|下巨虚|三阴交|地机|阴陵泉、太白、血海、公孙|进气
未|午|关元|少海|灵道|神门、通里、至阳、涌泉|子午捣臼
未|未|腕骨|后溪|支正|小海、养老、下巨虚、足临泣|龙虎交战
未|申|委中|昆仑|申脉|肾俞、飞扬、金门、太溪|赤凤迎源
未|酉|太溪|复溜|照海|水泉、大钟、命门、气海|烧山火
未|戌|内关|大陵|郄门|劳宫、间使、膻中、巨阙|抽添
未|亥|阳池|支沟|会宗|外关、四渎、石门、水分|透天凉
申|子|涌泉|委中|昆仑|肾俞、申脉、太溪、飞扬|进气
申|丑|太冲|曲泉|中都|期门、章门、阳陵泉、三阴交|苍龟探穴
申|寅|尺泽|孔最|列缺|中府、云门、膻中、太渊|白虎摇头
申|卯|曲池|偏历|温溜|合谷、手三里、天枢、上巨虚|凤凰展翅
申|辰|丰隆|解溪|冲阳|足三里、内庭、公孙、梁丘|赤凤迎源
申|巳|阴陵泉|地机|公孙|三阴交、血海、太白、章门|饿马摇铃
申|午|通里|灵道|少府|神门、少海、至阳、涌泉|子午捣臼
申|未|小海|养老|支正|后溪、腕骨、关元、下巨虚|龙虎交战
申|申|肾俞|飞扬|金门|委中、昆仑、申脉、太溪|进气
申|酉|照海|水泉|大钟|太溪、复溜、命门、气海|烧山火
申|戌|郄门|间使|劳宫|内关、大陵、膻中、巨阙|抽添
申|亥|支沟|会宗|四渎|阳池、外关、石门、水分|透天凉
酉|子|劳宫|太溪|复溜|涌泉、照海、日月、风池|烧山火
酉|丑|行间|蠡沟|章门|太冲、期门、阳陵泉、三阴交|苍龟探穴
酉|寅|经渠|鱼际|云门|中府、尺泽、列缺、孔最|白虎摇头
酉|卯|手三里|上巨虚|下廉|合谷、曲池、天枢、温溜|凤凰展翅
酉|辰|梁门|下巨虚|陷谷|足三里、内庭、丰隆、公孙|赤凤迎源
酉|巳|血海|腹结|府舍|三阴交、阴陵泉、太白、地机|饿马摇铃
酉|午|灵台|少冲|青灵|神门、通里、至阳、涌泉|子午捣臼
酉|未|腕骨|阳谷|前谷|后溪、支正、关元、下巨虚|龙虎交战
酉|申|申脉|仆参|跗阳|委中、昆仑、肾俞、飞扬|进气
酉|酉|气海|横骨|大赫|太溪、复溜、命门、涌泉|烧山火
酉|戌|天泉|曲泽|中冲|内关、郄门、膻中、巨阙|抽添
酉|亥|清冷渊|消泺|臑会|外关、支沟、石门、水分|透天凉
戌|子|三阴交|丘墟|日月|风池、带脉、阳陵泉、太溪|青龙摆尾
戌|丑|内关|蠡沟|中都|行间、章门、曲泉、肝俞|白虎摇头
戌|寅|郄门|孔最|经渠|鱼际、尺泽、太渊、列缺|苍龟探穴
戌|卯|大陵|偏历|温溜|手三里、天枢、上巨虚、曲池|凤凰展翅
戌|辰|劳宫|梁丘|冲阳|足三里、丰隆、公孙、内庭|赤凤迎源
戌|巳|间使|地机|大都|阴陵泉、太白、公孙、血海|饿马摇铃
戌|午|膻中|灵道|少府|神门、通里、巨阙、至阳|子午捣臼
戌|未|巨阙|养老|支正|小海、下巨虚、关元、腕骨|龙虎交战
戌|申|天池|金门|飞扬|委中、昆仑、肾俞、太溪|进气
戌|酉|气海|水泉|复溜|照海、大钟、命门、涌泉|烧山火
戌|戌|三阴交|郄门|间使|内关、大陵、劳宫、膻中|抽添
戌|亥|石门|支沟|会宗|阳池、外关、四渎、水分|透天凉
亥|子|太渊|阳辅|悬钟|丘墟、足临泣、风市、日月|青龙摆尾
亥|丑|阳池|中封|膝关|太冲、行间、曲泉、期门|白虎摇头
亥|寅|外关|列缺|天府|孔最、尺泽、鱼际、太渊|苍龟探穴
亥|卯|支沟|下廉|臂臑|合谷、曲池、手三里、天枢|凤凰展翅
亥|辰|会宗|伏兔|髀关|足三里、梁丘、丰隆、内庭|赤凤迎源
亥|巳|四渎|地机|腹结|三阴交、阴陵泉、公孙、血海|饿马摇铃
亥|午|水分|少冲|青灵|神门、通里、至阳、巨阙|子午捣臼
亥|未|石门|肩贞|臑俞|后溪、腕骨、小海、关元|龙虎交战
亥|申|阴交|承扶|秩边|委中、昆仑、肾俞、太溪|进气
亥|酉|气海|横骨|大赫|太溪、复溜、照海、命门|烧山火
亥|戌|三阴交|郄门|间使|内关、大陵、劳宫、膻中|抽添
亥|亥|太渊|翳风|颅息|阳池、外关、支沟、石门|透天凉
"""


def _build_table() -> dict[str, dict[str, dict]]:
    table: dict[str, dict[str, dict]] = {}
    for line in _TREAT_TABLE.strip().splitlines():
        natal, treat, tian, di, ren, assist, technique = line.split("|")
        table.setdefault(natal, {})[treat] = {
            "tian": tian,
            "di": di,
            "ren": ren,
            "assist": [item for item in assist.split("、") if item],
            "technique": technique,
        }
    return table


TREAT_TABLE = _build_table()

# 九宫配穴（《北斗七星与奇门遁甲针法》第三部分）
JIU_GONG = {
    "坎": {
        "num": 1, "wuxing": "水", "star": "天蓬", "men": "休门", "channel": "足少阴肾经",
        "points": ["太溪", "涌泉", "阴谷"],
        "rule": "补则太溪，泻则涌泉",
        "indication": "水亏火亢、失眠盗汗、腰膝酸软、虚阳上浮",
        "triangle": ["涌泉", "神门", "关元"],
        "formation": "坎离交泰阵",
        "time": "子时、午时交替",
        "tech": "涌泉为基（6阴数），神门为顶（9阳数），关元居中（15太乙数）",
        "caution": "孕妇禁用关元",
    },
    "坤": {
        "num": 2, "wuxing": "土", "star": "天芮", "men": "死门", "channel": "足太阴脾经",
        "points": ["隐白", "太白", "阴陵泉"],
        "rule": "实则泻阴陵泉，虚则补太白",
        "indication": "脾虚湿困、崩漏、泄泻、带下、中气下陷",
        "triangle": ["三阴交", "足三里", "公孙"],
        "formation": "坤舆载物阵",
        "time": "丑时、未时、辰时",
        "tech": "黄玉针，针尖指向坤方（西南），配合黄土灸",
        "caution": "湿热带下者不宜温补太过",
    },
    "震": {
        "num": 3, "wuxing": "木", "star": "天冲", "men": "伤门", "channel": "足厥阴肝经",
        "points": ["太冲", "行间", "曲泉"],
        "rule": "郁则疏太冲，火则泻行间",
        "indication": "肝气郁结、肝火上炎、胁痛、眩晕、筋挛",
        "triangle": ["太冲", "合谷", "阳陵泉"],
        "formation": "金木制化阵",
        "time": "寅时、卯时",
        "tech": "寅刺太冲行青龙法，卯配合谷行白虎法",
        "caution": "孕妇慎用合谷、太冲",
    },
    "巽": {
        "num": 4, "wuxing": "木", "star": "天辅", "men": "杜门", "channel": "手厥阴心包经",
        "points": ["内关", "大陵", "劳宫"],
        "rule": "内关配大陵，主心胸胃中痛",
        "indication": "心胸憋闷、焦虑烦躁、风邪入络、偏正头痛",
        "triangle": ["风池", "太冲", "阳陵泉"],
        "formation": "风雷相薄阵",
        "time": "辰时、巳时",
        "tech": "风池斜刺透风府，太冲直刺泻肝阳",
        "caution": "风池深刺需严格掌握方向与深度",
    },
    "中": {
        "num": 5, "wuxing": "土", "star": "天禽", "men": "无门", "channel": "足阳明胃经",
        "points": ["足三里", "中脘", "公孙"],
        "rule": "中宫为九宫之轴，任何针法必保中宫通畅",
        "indication": "中气虚衰、诸虚百损、脘腹胀满、呕逆",
        "triangle": ["中脘", "膻中", "神阙"],
        "formation": "混沌归元阵",
        "time": "四立前各一日",
        "tech": "先刺膻中调胸中大气，中脘和胃，神阙灸三壮",
        "caution": "神阙禁针，只灸",
    },
    "乾": {
        "num": 6, "wuxing": "金", "star": "天心", "men": "开门", "channel": "手少阳三焦经",
        "points": ["外关", "支沟", "曲池"],
        "rule": "开门配外关，启上焦之门透邪外出",
        "indication": "表证、热病、耳鸣、三焦不通、便秘",
        "triangle": ["百会", "大椎", "命门"],
        "formation": "乾天刚健阵",
        "time": "戌时、亥时",
        "tech": "百会浅刺引天阳，大椎通督，命门温灸",
        "caution": "百会针深以 3 分为准，不可深刺",
    },
    "兑": {
        "num": 7, "wuxing": "金", "star": "天柱", "men": "惊门", "channel": "手太阴肺经",
        "points": ["尺泽", "列缺", "太渊"],
        "rule": "兑为口舌，配太渊调血脉，以金制木",
        "indication": "咳嗽、盗汗、潮热、咽痛、肺气不降",
        "triangle": ["尺泽", "曲池", "太渊"],
        "formation": "白虎肃杀阵",
        "time": "申时、酉时",
        "tech": "尺泽深刺透天凉，曲池泻阳明，太渊补肺气",
        "caution": "肺虚寒者慎用透天凉",
    },
    "艮": {
        "num": 8, "wuxing": "土", "star": "天任", "men": "生门", "channel": "足阳明胃经",
        "points": ["丰隆", "天枢", "脾俞"],
        "rule": "艮为山主止，生门主生，以降为用",
        "indication": "痰湿阻络、肥胖水肿、食积、关节痛",
        "triangle": ["公孙", "太白", "丰隆"],
        "formation": "艮山止渊阵",
        "time": "辰时、巳时、丑时",
        "tech": "公孙先泻后补化湿，太白补脾，丰隆化痰",
        "caution": "孕妇慎用天枢",
    },
    "离": {
        "num": 9, "wuxing": "火", "star": "天英", "men": "景门", "channel": "手少阴心经",
        "points": ["神门", "少海", "极泉"],
        "rule": "实则泻神门，虚则补少海",
        "indication": "心火亢盛、失眠心烦、口舌生疮、血热",
        "triangle": ["劳宫", "少府", "涌泉"],
        "formation": "离火明耀阵",
        "time": "午时（先刺涌泉再刺劳宫）",
        "tech": "先刺涌泉引火归元，再刺少府清心火，最后劳宫调水火",
        "caution": "虚火上浮者不可一味清泻",
    },
}

# 症状 → 九宫
SYMPTOM_PALACE = {
    "坎": ["腰酸", "腰痛", "耳鸣", "耳聋", "水肿", "小便不利", "盗汗", "骨痛",
           "畏寒", "夜尿", "遗精", "阳痿", "足冷", "健忘"],
    "坤": ["腹胀", "纳差", "便溏", "腹泻", "带下", "崩漏", "乏力", "水肿",
           "身重", "苔腻", "中气下陷", "脱肛", "内脏下垂"],
    "震": ["胁痛", "眩晕", "头痛", "抽搐", "易怒", "口苦", "筋挛", "目赤",
           "高血压", "肝郁", "抑郁", "月经不调"],
    "巽": ["胸闷", "心悸", "焦虑", "心烦", "口疮", "风疹", "面瘫", "偏头痛",
           "游走性疼痛", "癫痫"],
    "中": ["脘腹胀满", "呕逆", "胃痛", "食欲不振", "气虚", "疲劳", "消瘦",
           "慢性胃病", "中焦不利"],
    "乾": ["便秘", "咳逆", "项强", "头疾", "寒战", "三焦不通", "耳鸣",
           "肩颈痛", "督脉瘀阻"],
    "兑": ["咳嗽", "咽痛", "口干", "盗汗", "潮热", "哮喘", "皮肤干燥",
           "鼻塞", "悲泣", "肺热"],
    "艮": ["痰多", "肥胖", "食积", "关节痛", "痞块", "硬肿", "面黄",
           "鼻病", "眩晕", "水肿"],
    "离": ["失眠", "心烦", "心悸", "口舌生疮", "躁狂", "发热", "疮疡",
           "血热", "目赤", "多梦"],
}

# 四时变阵：按《针灸大成·四时刺逆从论》
SEASON_ADJUST = {
    "春": {
        "replace": {"膻中": "大杼", "关元": "太溪", "太冲": "阳陵泉"},
        "note": "春分斗柄指东，木气升发，肝气当疏；不泻肾阳。",
    },
    "夏": {
        "replace": {"神门": "大陵", "太溪": "然谷", "三阴交": "阴陵泉"},
        "note": "夏至斗柄指南，火气炎上，心火当清；兼清暑湿。",
    },
    "秋": {
        "replace": {"期门": "中府", "太冲": "尺泽", "三阴交": "太渊"},
        "note": "秋分斗柄指西，金气收敛，肺气当降；收敛浮火。",
    },
    "冬": {
        "replace": {"膻中": "命门", "神门": "通里"},
        "add": {"关元": "气海"},
        "note": "冬至斗柄指北，水气闭藏，肾阳当温；可加气海双穴温肾。",
    },
}

# 针深校核（《针灸大成》临床记载）
NEEDLE_DEPTH = {
    "百会": "3分（巅顶颅骨薄，不可深刺）",
    "外关": "3~5分（前臂肉薄）",
    "照海": "4分（踝下血管丰富）",
    "关元": "8分（腹部肉厚）",
    "带脉": "6分（胁下肉厚）",
    "风池": "针尖向鼻尖方向，0.8~1.2寸，不可向上深刺",
    "神阙": "禁针，只灸",
}

# 十二时辰星君/经络
TREAT_HOUR_INFO = {
    zhi: {"star": STAR_LORD[zhi], "channel": CHANNEL[zhi], "range": ZHI_HOUR[zhi]}
    for zhi in ZHI
}

# 经典北斗七星主穴（对齐 hermes divination/acupuncture/planner.py）
CLASSIC_STARS = {
    "天枢": {"point": "膻中", "meridian": "任脉", "technique": "补法", "depth": 7,
             "function": "开上焦气门", "indication": "胸闷打嗝"},
    "天璇": {"point": "神门", "meridian": "心经", "technique": "补法", "depth": 9,
             "function": "敛心安神", "indication": "焦虑失眠"},
    "天玑": {"point": "期门", "meridian": "肝经", "technique": "泄法", "depth": 2,
             "function": "疏肝定惊", "indication": "胁痛烦躁"},
    "天权": {"point": "关元", "meridian": "任脉", "technique": "灸法", "depth": 4,
             "function": "引火归元温阳", "indication": "虚寒"},
    "玉衡": {"point": "太溪", "meridian": "肾经", "technique": "补法", "depth": 6,
             "function": "滋肾纳气", "indication": "肾虚脾虚"},
    "开阳": {"point": "太冲", "meridian": "肝经", "technique": "平补平泄", "depth": 7,
             "function": "调肝舒筋", "indication": "肝郁胃胀"},
    "摇光": {"point": "三阴交", "meridian": "脾经", "technique": "补法", "depth": 9,
             "function": "收三阴固本", "indication": "五脏皆虚"},
}
STAR_ALTERNATIVES = {
    "玉衡": [("太白", "脾经", "补法", "健脾益气", "脾虚"),
             ("太溪", "肾经", "补法", "滋肾阴", "肾虚")],
    "开阳": [("足三里", "胃经", "补法", "健胃和胃", "胃胀打嗝"),
             ("太冲", "肝经", "平补平泄", "疏肝解郁", "肝郁焦虑")],
}
SYNDROME_MAP = {
    "太阴病": ("太白", "足三里", "太阴脾虚—玉衡太白健脾，天权灸关元温阳"),
    "少阴病": ("太溪", "太冲", "少阴肾虚—玉衡太溪滋肾，天权灸关元，天璇安神"),
    "厥阴病": ("太溪", "太冲", "厥阴肝郁—天玑期门泻肝，开阳太冲舒筋"),
}
DEFAULT_SYNDROME = ("太白", "足三里", "合病—先灸关元固本，摇光收三阴")
ADDITION_RULES = {
    "焦虑": ["印堂(补)", "大陵(泻)"],
    "打嗝": ["内关(补)", "公孙(补)"],
    "失眠": ["印堂(补)"],
    "纳差": ["中脘(补)", "足三里(补)"],
    "腹胀": ["天枢(泻)", "气海(补)"],
    "完谷不化": ["脾俞(灸)", "胃俞(灸)"],
    "胸闷": ["内关(泻)"],
    "咳嗽": ["肺俞(补)", "列缺(补)"],
}

# 九宫飞星
FLY_ORDER = [5, 6, 7, 8, 9, 1, 2, 3, 4]  # 中→乾→兑→艮→离→坎→坤→震→巽
FLY_PALACE_NAME = {5: "中", 6: "乾", 7: "兑", 8: "艮", 9: "离",
                   1: "坎", 2: "坤", 3: "震", 4: "巽"}
FLY_STARS = {
    1: {"name": "一白贪狼", "wuxing": "水", "luck": "吉", "score": 0.8},
    2: {"name": "二黑巨门", "wuxing": "土", "luck": "凶", "score": -0.6},
    3: {"name": "三碧禄存", "wuxing": "木", "luck": "凶", "score": -0.3},
    4: {"name": "四绿文曲", "wuxing": "木", "luck": "吉", "score": 0.5},
    5: {"name": "五黄廉贞", "wuxing": "土", "luck": "大凶", "score": -1.0},
    6: {"name": "六白武曲", "wuxing": "金", "luck": "吉", "score": 0.7},
    7: {"name": "七赤破军", "wuxing": "金", "luck": "凶", "score": -0.4},
    8: {"name": "八白左辅", "wuxing": "土", "luck": "大吉", "score": 1.0},
    9: {"name": "九紫右弼", "wuxing": "火", "luck": "吉", "score": 0.9},
}


def _fly_layout(center_star: int) -> dict:
    """以入中星顺飞九宫。"""
    layout = {}
    for i, gong in enumerate(FLY_ORDER):
        star = (center_star - 1 + i) % 9 + 1
        layout[FLY_PALACE_NAME[gong]] = {
            "gong": gong,
            **FLY_STARS[star],
            "star_num": star,
        }
    return layout


def feixing(year: int, month: int) -> dict:
    """年飞星 + 月飞星。

    年入中星 = (2022 - year) % 9，0 作 9。
    月序 = (month - 2) % 12 + 1（寅月=1）；月入中 = (年入中 - 月序) % 9，0 作 9。
    """
    year_star = (2022 - int(year)) % 9 or 9
    month_seq = (int(month) - 2) % 12 + 1
    month_star = (year_star - month_seq) % 9 or 9
    return {
        "year": int(year),
        "month": int(month),
        "year_center": year_star,
        "year_star": FLY_STARS[year_star],
        "month_seq": month_seq,
        "month_center": month_star,
        "month_star": FLY_STARS[month_star],
        "year_layout": _fly_layout(year_star),
        "month_layout": _fly_layout(month_star),
    }


def normalize_hour(value: Any) -> str:
    """把 0-23 小时或地支名统一为地支。"""
    if isinstance(value, str):
        value = value.strip()
        if value in ZHI:
            return value
        try:
            value = int(value)
        except ValueError as exc:
            raise ValueError(f"无法识别时辰: {value}") from exc
    hour = int(value) % 24
    return ZHI[((hour + 1) // 2) % 12]


def _replace_points(points: list[str], mapping: dict[str, str]) -> tuple[list[str], list[str]]:
    replaced: list[str] = []
    changes: list[str] = []
    for point in points:
        if point in mapping:
            replaced.append(mapping[point])
            changes.append(f"{point}→{mapping[point]}")
        else:
            replaced.append(point)
    return replaced, changes


class ZhenfaEngine:
    """北斗七星 + 九宫飞星针法引擎。"""

    def beidou(self, birth_hour: Any, treat_hour: Any,
               season: str | None = None) -> dict:
        natal = normalize_hour(birth_hour)
        treat = normalize_hour(treat_hour)
        row = TREAT_TABLE.get(natal, {}).get(treat)
        if not row:
            raise ValueError(f"未找到命宫{natal}·{treat}时针阵")

        points = {
            "天": row["tian"], "地": row["di"], "人": row["ren"],
            "辅": list(row["assist"]),
        }
        changes: list[str] = []
        note = ""
        if season:
            season = season[0] if season else ""
            adjust = SEASON_ADJUST.get(season)
            if adjust:
                new_points: dict[str, Any] = {}
                for layer in ("天", "地", "人"):
                    replaced, changed = _replace_points(
                        [points[layer]], adjust.get("replace", {}))
                    new_points[layer] = replaced[0]
                    changes.extend(changed)
                new_points["辅"], changed = _replace_points(
                    points["辅"], adjust.get("replace", {}))
                changes.extend(changed)
                for base, extra in adjust.get("add", {}).items():
                    if base in new_points.values() and extra not in new_points["辅"]:
                        new_points["辅"].append(extra)
                        changes.append(f"加{extra}")
                points = new_points
                note = adjust["note"]

        return {
            "natal_palace": {
                "branch": natal,
                "hour_range": ZHI_HOUR[natal],
                "star": STAR_LORD[natal],
                "channel": CHANNEL[natal],
            },
            "treat_hour": TREAT_HOUR_INFO[treat],
            "main_points": {"天": points["天"], "地": points["地"], "人": points["人"]},
            "assist_points": points["辅"],
            "technique": row["technique"],
            "order": ["天", "地", "人", "四辅"],
            "season_adjust": {"season": season or "", "changes": changes, "note": note},
            "needle_depth": {
                point: NEEDLE_DEPTH[point]
                for point in [points["天"], points["地"], points["人"]] + points["辅"]
                if point in NEEDLE_DEPTH
            },
        }

    def jiugong(self, palace: str | None = None,
                symptoms: str = "") -> dict:
        matched = self.match_palace(symptoms) if symptoms else None
        if palace is None:
            palace = matched["palace"] if matched else "中"
        if palace not in JIU_GONG:
            raise ValueError(f"未知九宫: {palace}")
        info = dict(JIU_GONG[palace])
        info["palace"] = palace
        info["matched_symptoms"] = matched["matched"] if matched else []
        return info

    def match_palace(self, symptoms: str) -> dict:
        scores: dict[str, list[str]] = {}
        for palace, keywords in SYMPTOM_PALACE.items():
            hit = [kw for kw in keywords if kw in symptoms]
            if hit:
                scores[palace] = hit
        if not scores:
            return {"palace": "中", "matched": [], "scores": {}}
        best = max(scores, key=lambda p: (len(scores[p]), -list(JIU_GONG).index(p)))
        return {"palace": best, "matched": scores[best], "scores": scores}

    def classic_beidou(self, syndrome: str = "", symptoms: str = "") -> dict:
        """经典北斗七星针法：天枢→天璇→天玑→天权→玉衡→开阳→摇光。"""
        yuheng, kaiyang, rationale = SYNDROME_MAP.get(syndrome, DEFAULT_SYNDROME)
        stars = []
        for star, info in CLASSIC_STARS.items():
            point = info["point"]
            meridian = info["meridian"]
            technique = info["technique"]
            function = info["function"]
            indication = info["indication"]
            if star == "玉衡":
                point, meridian, technique = yuheng, self._meridian_of(yuheng), "补法"
                for alt in STAR_ALTERNATIVES["玉衡"]:
                    if alt[0] == point:
                        _, meridian, technique, function, indication = alt
                        break
            elif star == "开阳":
                point, meridian, technique = kaiyang, self._meridian_of(kaiyang), "平补平泄"
                for alt in STAR_ALTERNATIVES["开阳"]:
                    if alt[0] == point:
                        _, meridian, technique, function, indication = alt
                        break
            stars.append({
                "star": star,
                "point": point,
                "meridian": meridian,
                "technique": technique,
                "depth": info["depth"],
                "function": function,
                "indication": indication,
            })
        additions = []
        for keyword, points in ADDITION_RULES.items():
            if keyword in symptoms:
                additions.extend(points)
        return {
            "syndrome": syndrome or "合病/未定",
            "rationale": rationale,
            "stars": stars,
            "order": [s["star"] for s in stars],
            "additions": additions,
            "moxibustion": [
                "关元灸 3~5 壮（虚寒者）",
                "脾俞、胃俞灸（纳差、完谷不化者）",
                "神阙禁针，只灸",
            ],
            "course": "急性前 3 日每日 1 次，后隔日 1 次，10 次一疗程",
        }

    @staticmethod
    def _meridian_of(point: str) -> str:
        mapping = {
            "太白": "脾经", "太溪": "肾经", "足三里": "胃经", "太冲": "肝经",
            "膻中": "任脉", "神门": "心经", "期门": "肝经", "关元": "任脉",
            "三阴交": "脾经",
        }
        return mapping.get(point, "")

    def prescribe(self, birth_hour: Any, treat_hour: Any,
                  symptoms: str = "", season: str | None = None,
                  pregnant: bool = False, syndrome: str = "",
                  year: int | None = None, month: int | None = None) -> dict:
        from datetime import datetime
        beidou = self.beidou(birth_hour, treat_hour, season)
        palace = self.match_palace(symptoms)
        jiugong = self.jiugong(palace["palace"], symptoms)
        cautions = self._cautions(pregnant, symptoms, beidou, jiugong)
        now = datetime.now()
        fly = feixing(year or now.year, month or now.month)
        return {
            "symptoms": symptoms,
            **beidou,
            "symptom_palace": palace,
            "jiugong": jiugong,
            "classic": self.classic_beidou(syndrome, symptoms),
            "feixing": fly,
            "cautions": cautions,
            "course": {
                "acute": "前 3 日每日 1 次，后隔日 1 次",
                "standard": "10 次为一疗程",
                "chronic": "九宫轮刺：每宫 2 天，18 天一轮；3 轮 81 天",
            },
        }

    @staticmethod
    def _cautions(pregnant: bool, symptoms: str,
                  beidou: dict, jiugong: dict) -> list[str]:
        cautions = [
            "孕妇禁针天枢星位；关元、合谷、三阴交、太冲须由执业医师评估。",
            "日月食、九星连珠、雷暴天气停用四方针阵；雷暴禁用火性针法。",
            "垂危、大出血、严重心肺功能不全者不以针法为主。",
            "针深以《针灸大成》临床记载为准，数理推演不可替代临床手感。",
        ]
        if pregnant:
            cautions.insert(0, "已标记妊娠：禁用关元、天枢、合谷、三阴交深刺。")
        if "血" in symptoms or "出血" in symptoms:
            cautions.append("见血证：慎用破军、白虎类攻伐手法，先止血固脱。")
        if "肿瘤" in symptoms or "痞块" in symptoms:
            cautions.append("见癥瘕痞块：先明确诊断，针法只作辅助，不可替代影像与病理检查。")
        point_text = "".join(str(v) for v in beidou["main_points"].values())
        if "神阙" in point_text:
            cautions.append("神阙禁针，只灸。")
        if jiugong["caution"] not in cautions:
            cautions.append(jiugong["caution"])
        return cautions

    @staticmethod
    def format_text(plan: dict) -> str:
        natal = plan["natal_palace"]
        treat = plan["treat_hour"]
        main = plan["main_points"]
        jg = plan["jiugong"]
        lines = [
            "=" * 56,
            "          北斗七星 · 九宫飞星针法推演",
            "=" * 56,
            f"命宫：{natal['branch']}时（{natal['hour_range']}）"
            f"｜星君 {natal['star']}｜本经 {natal['channel']}",
            f"施针：{treat['channel']}当令（{treat['range']}）｜星君 {treat['star']}",
            "-" * 56,
            f"三才主穴：天[{main['天']}] → 地[{main['地']}] → 人[{main['人']}]",
            f"四象辅穴：{'、'.join(plan['assist_points'])}",
            f"手法：{plan['technique']}",
            f"顺序：{' → '.join(plan['order'])}",
            "-" * 56,
            f"症状落宫：{jg['palace']}宫（{jg['wuxing']}·{jg['star']}·{jg['men']}）",
            f"九宫主穴：{'、'.join(jg['points'])}",
            f"三角阵：{'、'.join(jg['triangle'])}｜{jg['formation']}",
            f"九宫主治：{jg['indication']}",
            f"九宫针法：{jg['tech']}",
        ]
        if plan["season_adjust"]["changes"]:
            lines.append(
                f"四时变阵：{'、'.join(plan['season_adjust']['changes'])}"
                f"（{plan['season_adjust']['note']}）"
            )
        if plan["needle_depth"]:
            lines.append("针深校核：" + "；".join(
                f"{k} {v}" for k, v in plan["needle_depth"].items()))
        lines.append("-" * 56)
        classic = plan.get("classic", {})
        if classic:
            lines.append(f"经典七星阵（{classic['syndrome']}）：")
            for item in classic["stars"]:
                lines.append(
                    f"  {item['star']}→{item['point']}（{item['meridian']}，"
                    f"{item['technique']}，{item['depth']}分）：{item['function']}"
                )
            lines.append(f"  依据：{classic['rationale']}")
            if classic["additions"]:
                lines.append(f"  配穴加减：{'、'.join(classic['additions'])}")
            if classic["moxibustion"]:
                lines.append(f"  艾灸：{'；'.join(classic['moxibustion'])}")
        fly = plan.get("feixing", {})
        if fly:
            lines.append("-" * 56)
            lines.append(
                f"九宫飞星：{fly['year']}年{fly['year_star']['name']}入中｜"
                f"{fly['month']}月{fly['month_star']['name']}入中"
            )
            lines.append("  月飞星九宫：" + "；".join(
                f"{palace}:{item['name']}"
                for palace, item in fly["month_layout"].items()
            ))
        lines.append("-" * 56)
        lines.append("禁忌：")
        for item in plan["cautions"]:
            lines.append(f"  · {item}")
        lines.append("=" * 56)
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="北斗七星与九宫飞星针法引擎")
    parser.add_argument("--birth-hour", default="子", help="出生时辰（0-23 或 子..亥）")
    parser.add_argument("--treat-hour", default=None, help="施针时辰（0-23 或 子..亥）")
    parser.add_argument("--symptoms", default="", help="症状描述")
    parser.add_argument("--season", default=None, help="季节：春/夏/秋/冬")
    parser.add_argument("--syndrome", default="", help="六经病证：太阴病/少阴病/厥阴病")
    parser.add_argument("--year", type=int, default=None, help="飞星年份（默认当前）")
    parser.add_argument("--month", type=int, default=None, help="飞星月份（默认当前）")
    parser.add_argument("--pregnant", action="store_true", help="标记妊娠")
    parser.add_argument("--jiugong", default=None, help="只查九宫：坎/坤/震/巽/中/乾/兑/艮/离")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    engine = ZhenfaEngine()

    if args.jiugong:
        info = engine.jiugong(args.jiugong, args.symptoms)
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(f"{args.jiugong}宫（{info['wuxing']}）")
            print(f"星门：{info['star']}·{info['men']}｜经络：{info['channel']}")
            print(f"主穴：{'、'.join(info['points'])}｜{info['rule']}")
            print(f"三角阵：{'、'.join(info['triangle'])}｜{info['formation']}")
            print(f"主治：{info['indication']}")
            print(f"针法：{info['tech']}")
            print(f"禁忌：{info['caution']}")
        return

    treat_hour = args.treat_hour if args.treat_hour is not None else args.birth_hour
    plan = engine.prescribe(args.birth_hour, treat_hour, args.symptoms,
                            args.season, args.pregnant, args.syndrome,
                            args.year, args.month)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(engine.format_text(plan))


if __name__ == "__main__":
    main()
