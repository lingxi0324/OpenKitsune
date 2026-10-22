#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奇门遁甲格局、旺相、门迫、反吟伏吟与四柱角色分析.

被 qimen_diagnosis.py 调用，也可独立作为轻量分析库使用。
"""
from __future__ import annotations

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

GAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
PALACE_WUXING = {
    1: "水", 2: "土", 3: "木", 4: "木", 5: "土",
    6: "金", 7: "金", 8: "土", 9: "火",
}
PALACE_GUA = {1: "坎", 2: "坤", 3: "震", 4: "巽", 5: "中", 6: "乾", 7: "兑", 8: "艮", 9: "离"}
GATE_WUXING = {"休": "水", "生": "土", "伤": "木", "杜": "木",
               "景": "火", "死": "土", "惊": "金", "开": "金"}
STAR_WUXING = {"天蓬": "水", "天芮": "土", "天冲": "木", "天辅": "木",
               "天禽": "土", "天心": "金", "天柱": "金", "天任": "土", "天英": "火"}
STAR_ORIGINAL_PALACE = {"天蓬": 1, "天芮": 2, "天冲": 3, "天辅": 4,
                        "天禽": 5, "天心": 6, "天柱": 7, "天任": 8, "天英": 9}
GATE_ORIGINAL_PALACE = {"休": 1, "死": 2, "伤": 3, "杜": 4,
                        "中": 5, "开": 6, "惊": 7, "生": 8, "景": 9}

SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def _relation(a: str, b: str) -> str:
    """a 对 b 的五行关系。"""
    if a == b:
        return "比和"
    if SHENG.get(a) == b:
        return "生"
    if SHENG.get(b) == a:
        return "被生"
    if KE.get(a) == b:
        return "克"
    if KE.get(b) == a:
        return "被克"
    return "未知"


# 十干克应（天盘干 + 地盘干）
TIAN_DI_PATTERNS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("戊", "丙"): ("青龙返首", "大吉", "贵人相助，事可成，病得良医"),
    ("丙", "戊"): ("飞鸟跌穴", "大吉", "不谋而合，不治而愈"),
    ("乙", "辛"): ("青龙逃走", "凶", "合作离心，病势走窜"),
    ("辛", "乙"): ("白虎猖狂", "凶", "冲突加剧，血光肿痛"),
    ("癸", "丁"): ("腾蛇夭矫", "凶", "虚惊怪异，小儿惊风"),
    ("丁", "癸"): ("朱雀投江", "凶", "文书信息受阻，病势沉伏"),
    ("庚", "丙"): ("太白入荧", "凶", "外邪入侵，盗贼入室"),
    ("丙", "庚"): ("荧入太白", "吉", "病退事缓，贼退"),
    ("庚", "癸"): ("大格", "凶", "事业受困，诉讼不利"),
    ("庚", "己"): ("刑格", "凶", "刑罚手术，外伤血证"),
    ("庚", "戊"): ("天乙伏宫", "凶", "被人压制，求职被拒"),
    ("庚", "庚"): ("太白同宫", "凶", "同类相争，竞争激烈"),
    ("庚", "辛"): ("白虎干格", "凶", "刚烈冲突，金刃伤"),
    ("辛", "庚"): ("白虎出力", "凶", "争斗出力，事倍功半"),
    ("辛", "癸"): ("天牢华盖", "凶", "牢狱束缚，事难伸展"),
    ("辛", "壬"): ("凶蛇入狱", "凶", "纠缠入困，暗耗"),
    ("壬", "癸"): ("幼女奸淫", "凶", "阴私暗昧，情志纠纷"),
    ("癸", "癸"): ("天网四张", "凶", "处处受制，不可妄动"),
    ("戊", "己"): ("贵人入狱", "凶", "贵人受困，助力不显"),
    ("戊", "庚"): ("值符飞宫", "凶", "格局变动，计划被打断"),
    ("戊", "辛"): ("青龙折足", "凶", "根基受损，行动受阻"),
    ("戊", "壬"): ("青龙入天牢", "凶", "受制于外，屈而不伸"),
    ("戊", "癸"): ("青龙华盖", "吉", "有贵人亦有遮掩，宜守"),
    ("己", "戊"): ("犬遇青龙", "吉", "得贵人提携，事有转机"),
    ("己", "己"): ("地户逢鬼", "凶", "阴浊内停，病势缠绵"),
    ("己", "庚"): ("利格反名", "凶", "名利反复，口舌是非"),
    ("己", "辛"): ("游魂入墓", "凶", "神志恍惚，病位不定"),
    ("己", "壬"): ("地网高张", "凶", "网络纠缠，难以脱身"),
    ("己", "癸"): ("地刑玄武", "凶", "阴私刑伤，暗耗"),
    ("乙", "丙"): ("奇仪顺遂", "吉", "事顺人和，病势向愈"),
    ("乙", "丁"): ("奇仪相佐", "吉", "有辅佐，文书顺利"),
    ("乙", "戊"): ("阴害阳门", "平", "利阴人阴事，不利公开"),
    ("乙", "己"): ("日奇入墓", "凶", "才华受困，事难显达"),
    ("乙", "庚"): ("日奇被刑", "凶", "受制受刑，病势加重"),
    ("乙", "壬"): ("日奇入地", "凶", "下沉受困，精神不振"),
    ("乙", "癸"): ("华盖逢星", "吉", "有遮掩但有生机，宜静"),
    ("丙", "乙"): ("日月并行", "吉", "光明并行，事有双助"),
    ("丙", "丙"): ("月奇悖师", "凶", "过刚易折，冲突升级"),
    ("丙", "丁"): ("星随月转", "吉", "顺势而转，事有转机"),
    ("丙", "己"): ("火悖入刑", "凶", "火郁成毒，炎症加重"),
    ("丙", "辛"): ("相佐", "吉", "有辅佐，事可成"),
    ("丙", "壬"): ("火入天罗", "凶", "火被水制，欲进不能"),
    ("丙", "癸"): ("华盖悖师", "凶", "阴盖阳火，事多阻"),
    ("丁", "乙"): ("玉女奇生", "吉", "阴中生阳，事有暗助"),
    ("丁", "丙"): ("星随月转", "吉", "顺势而转，病有转机"),
    ("丁", "丁"): ("奇入太阴", "吉", "阴中得奇，宜静中求"),
    ("丁", "戊"): ("青龙转光", "吉", "贵人转机，事有光明"),
    ("丁", "己"): ("火入勾陈", "凶", "火被土晦，事多迟滞"),
    ("丁", "庚"): ("文书阻隔", "凶", "信息不通，文书受阻"),
    ("丁", "辛"): ("朱雀入狱", "凶", "口舌官非，信息被压"),
    ("丁", "壬"): ("五神互合", "吉", "多方合和，事可成"),
    ("庚", "乙"): ("太白逢星", "吉", "刚中有柔，事可缓和"),
    ("庚", "丁"): ("亭亭之格", "凶", "孤立无援，事难成"),
    ("辛", "丙"): ("干合悖师", "凶", "合而相悖，表面和内部争"),
    ("辛", "丁"): ("狱神得奇", "吉", "困中得奇，事有转机"),
    ("辛", "戊"): ("困龙被伤", "凶", "受困受伤，根基受损"),
    ("辛", "己"): ("入狱自刑", "凶", "自招困扰，内耗"),
    ("辛", "辛"): ("伏吟", "平", "停滞反复，事缓"),
    ("壬", "乙"): ("小蛇日奇", "吉", "柔中得助，事可缓成"),
    ("壬", "丙"): ("水蛇入火", "凶", "水火相战，冲突激烈"),
    ("壬", "丁"): ("干合蛇刑", "吉", "合中带刑，先难后成"),
    ("壬", "戊"): ("小蛇化龙", "吉", "由小变大，事有跃升"),
    ("壬", "己"): ("反吟蛇刑", "凶", "反复纠缠，事多反复"),
    ("壬", "庚"): ("太白擒蛇", "吉", "以刚制柔，事可制"),
    ("壬", "辛"): ("腾蛇相缠", "凶", "缠绕不清，难以脱身"),
    ("壬", "壬"): ("蛇入地罗", "凶", "深陷困局，难以自拔"),
    ("癸", "乙"): ("华盖逢星", "吉", "有盖有星，宜静守"),
    ("癸", "丙"): ("华盖悖师", "凶", "阴盖阳火，事多阻"),
    ("癸", "戊"): ("天乙合会", "吉", "贵人合会，事可成"),
    ("癸", "己"): ("华盖地户", "凶", "阴浊闭塞，病势沉"),
    ("癸", "庚"): ("太白入网", "凶", "受制于网，事难脱"),
    ("癸", "辛"): ("网盖天牢", "凶", "双重束缚，事难行"),
    ("癸", "壬"): ("复见腾蛇", "凶", "旧事重来，纠缠反复"),
}

# 八节旺门
WANG_GATE_BY_TERM = {
    "冬至": "休", "立春": "生", "春分": "伤", "立夏": "杜",
    "夏至": "景", "立秋": "死", "秋分": "惊", "立冬": "开",
}
# 节气 → 季节
TERM_SEASON = {
    "立春": "春", "雨水": "春", "惊蛰": "春", "春分": "春", "清明": "春", "谷雨": "春",
    "立夏": "夏", "小满": "夏", "芒种": "夏", "夏至": "夏", "小暑": "夏", "大暑": "夏",
    "立秋": "秋", "处暑": "秋", "白露": "秋", "秋分": "秋", "寒露": "秋", "霜降": "秋",
    "立冬": "冬", "小雪": "冬", "大雪": "冬", "冬至": "冬", "小寒": "冬", "大寒": "冬",
}
SEASON_WUXING = {"春": "木", "夏": "火", "秋": "金", "冬": "水", "四季": "土"}


def detect_geju(tianpan_gan: dict, dipan_gan: dict) -> list[dict]:
    """检测十干克应格局。"""
    results = []
    for palace, tian in (tianpan_gan or {}).items():
        di = (dipan_gan or {}).get(palace)
        if not tian or not di:
            continue
        info = TIAN_DI_PATTERNS.get((tian, di))
        if info:
            name, nature, meaning = info
            results.append({
                "palace": palace,
                "palace_gua": PALACE_GUA.get(palace, ""),
                "tian": tian,
                "di": di,
                "name": name,
                "nature": nature,
                "meaning": meaning,
            })
    order = {"大凶": 0, "凶": 1, "平": 2, "吉": 3, "大吉": 4}
    results.sort(key=lambda item: order.get(item["nature"], 9))
    return results


def detect_fuyin_fanyin(star_layout: dict, gate_layout: dict) -> dict:
    """伏吟/反吟检测：星门大面积归本宫或对宫。"""
    star_fuyin = sum(1 for palace, star in (star_layout or {}).items()
                     if palace == STAR_ORIGINAL_PALACE.get(star))
    gate_fuyin = sum(1 for palace, gate in (gate_layout or {}).items()
                     if palace == GATE_ORIGINAL_PALACE.get(gate))
    star_fanyin = sum(1 for palace, star in (star_layout or {}).items()
                      if _is_opposite(palace, STAR_ORIGINAL_PALACE.get(star, 0)))
    gate_fanyin = sum(1 for palace, gate in (gate_layout or {}).items()
                      if _is_opposite(palace, GATE_ORIGINAL_PALACE.get(gate, 0)))

    if star_fuyin + gate_fuyin >= 5:
        kind = "伏吟"
        meaning = "星门多归本宫，病势缠绵、事多停滞，宜守不宜攻。"
    elif star_fanyin + gate_fanyin >= 5:
        kind = "反吟"
        meaning = "星门多临对宫，病势反复、来势急，宜先治标。"
    else:
        kind = "无"
        meaning = "未见全局伏吟/反吟。"
    return {
        "type": kind,
        "meaning": meaning,
        "star_fuyin": star_fuyin,
        "gate_fuyin": gate_fuyin,
        "star_fanyin": star_fanyin,
        "gate_fanyin": gate_fanyin,
    }


def _is_opposite(a: int, b: int) -> bool:
    if not a or not b:
        return False
    return (a + b) == 10 or (a, b) in {(1, 9), (9, 1), (2, 8), (8, 2),
                                       (3, 7), (7, 3), (4, 6), (6, 4)}


def gate_wangshuai(term: str, gate_layout: dict) -> dict:
    """按八节判断八门旺相休囚死。"""
    season_wx = SEASON_WUXING.get(TERM_SEASON.get(term, "四季"), "土")
    result = {}
    for palace, gate in (gate_layout or {}).items():
        gate_wx = GATE_WUXING.get(gate)
        if not gate_wx:
            continue
        rel = _relation(season_wx, gate_wx)
        status = {
            "比和": "旺", "生": "休", "被生": "相", "克": "死", "被克": "囚",
        }.get(rel, "平")
        result[gate] = {"status": status, "relation": rel, "palace": palace}
    return result


def star_wangshuai(month_branch: str, star_layout: dict) -> dict:
    """按月令判断九星旺相休囚死（简化五行口径）。"""
    month_wx = {
        "寅": "木", "卯": "木", "辰": "土", "巳": "火", "午": "火", "未": "土",
        "申": "金", "酉": "金", "戌": "土", "亥": "水", "子": "水", "丑": "土",
    }.get(month_branch, "土")
    result = {}
    for palace, star in (star_layout or {}).items():
        star_wx = STAR_WUXING.get(star)
        if not star_wx:
            continue
        rel = _relation(month_wx, star_wx)
        status = {
            "比和": "旺", "生": "休", "被生": "相", "克": "死", "被克": "囚",
        }.get(rel, "平")
        result[star] = {"status": status, "relation": rel, "palace": palace}
    return result


def men_po(gate_layout: dict) -> list[dict]:
    """门迫/门制：门克宫为门迫，宫克门为门制。"""
    results = []
    for palace, gate in (gate_layout or {}).items():
        gate_wx = GATE_WUXING.get(gate)
        palace_wx = PALACE_WUXING.get(palace)
        if not gate_wx or not palace_wx:
            continue
        if KE.get(gate_wx) == palace_wx:
            results.append({
                "gate": gate, "palace": palace, "type": "门迫",
                "impact": "凶",
                "meaning": f"{gate}门（{gate_wx}）克{PALACE_GUA.get(palace, '')}宫（{palace_wx}），病进、事倍功半",
            })
        elif KE.get(palace_wx) == gate_wx:
            results.append({
                "gate": gate, "palace": palace, "type": "门制",
                "impact": "次凶",
                "meaning": f"{PALACE_GUA.get(palace, '')}宫（{palace_wx}）克{gate}门（{gate_wx}），病退、阻力可控",
            })
    return results


def tianrui_shen_combo(shen: str) -> str:
    """天芮 + 八神的情志/病因组合。"""
    mapping = {
        "值符": "正气尚存，病虽重可治；压力过大、长期透支。",
        "腾蛇": "痰扰心神、思虑过度，易焦虑、疑病、噩梦。",
        "太阴": "肝气郁结、情志压抑，易抑郁、胸闷叹息。",
        "六合": "人际关系失调、依赖心理，易社交焦虑、胃痛。",
        "白虎": "肝火旺盛、气血上冲，易高血压、暴怒、血证。",
        "玄武": "肾气不固、恐惧伤肾，易恐惧症、遗精遗尿、成瘾。",
        "九地": "湿困脾阳、气机呆滞，易慢性疲劳、肥胖、湿温。",
        "九天": "心火上炎、浮阳外越，易失眠、躁狂、心悸。",
    }
    return mapping.get(shen, "情志病因待辨。")


def ganzhi_role_analysis(four_pillars: str, tianpan_gan: dict,
                         dipan_gan: dict) -> dict:
    """年/月/日/时干落宫与角色分析。"""
    parts = four_pillars.split()
    if len(parts) != 4:
        return {}
    year_gan, month_gan = parts[0][0], parts[1][0]
    day_gan, time_gan = parts[2][0], parts[3][0]

    def locate(gan: str) -> list[int]:
        palaces = [p for p, g in (tianpan_gan or {}).items() if g == gan]
        if not palaces:
            palaces = [p for p, g in (dipan_gan or {}).items() if g == gan]
        return palaces

    roles = {
        "年干": {"gan": year_gan, "role": "大环境/上司/长辈", "palaces": locate(year_gan)},
        "月干": {"gan": month_gan, "role": "平辈/同事/合伙", "palaces": locate(month_gan)},
        "日干": {"gan": day_gan, "role": "患者本人/问事人", "palaces": locate(day_gan)},
        "时干": {"gan": time_gan, "role": "病气/结果/下属", "palaces": locate(time_gan)},
    }

    relations = {}
    day_palaces = roles["日干"]["palaces"]
    for key in ("年干", "月干", "时干"):
        other = roles[key]["palaces"]
        if not day_palaces or not other:
            continue
        day_wx = PALACE_WUXING.get(day_palaces[0], "")
        other_wx = PALACE_WUXING.get(other[0], "")
        relations[key] = _relation(other_wx, day_wx)
    roles["relations"] = relations
    return roles
