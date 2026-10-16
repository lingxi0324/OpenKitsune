#!/usr/bin/env python3
"""
奇门遁甲病机诊断工具 v1.0

基于游兄（用户）独创的「奇门遁甲病机诊断法」体系，融合六步推演法、
多科室辨证、九重辩证法、五运六气加权，实现临床快速诊断。

功能：
1. 奇门排盘（lunar-python 节气精准定局）
2. 六步推演法（起盘→天芮定位→病位定性→病性定量→五运六气→出方案）
3. 多科室自动检测（内科/妇科/儿科/外科/精神科）
4. 内伤外感双规判断
5. 九重辩证法 LLM 深度分析
6. 结构化 JSON 输出

用法：
    python qimen_diagnosis.py --year 2026 --month 5 --day 7 --hour 19 "头痛两侧口苦"
    python qimen_diagnosis.py "头痛两侧口苦，胃胀，失眠"
    python qimen_diagnosis.py --year 2026 --month 5 --day 7 --hour 8 --interactive

环境变量：
    LLM_API_URL    — LLM API 地址（默认 http://127.0.0.1:11434/v1/chat/completions）
    LLM_MODEL      — 模型名称（默认 huihui_ai/qwen2.5-1m-abliterated:7b）
    KNOWLEDGE_BASE — 知识库根目录（必须显式设置；不提供默认机器路径）
"""

import json
import sys
import os
import re
from datetime import datetime, date
from pathlib import Path

# =============================================================
# 基础常量
# =============================================================

TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 奇门节气顺序（冬至→大雪，完整一年）
_QIMEN_TERM_ORDER = [
    "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰",
    "春分", "清明", "谷雨", "立夏", "小满", "芒种",
    "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
    "秋分", "寒露", "霜降", "立冬", "小雪", "大雪"
]

# 阳遁局数表（冬至→夏至前）
_QIMEN_YANG_JU = {
    "冬至": [1, 7, 4], "小寒": [2, 8, 5], "大寒": [3, 9, 6],
    "立春": [8, 5, 2], "雨水": [9, 6, 3], "惊蛰": [1, 7, 4],
    "春分": [3, 9, 6], "清明": [4, 1, 7], "谷雨": [5, 2, 8],
    "立夏": [4, 1, 7], "小满": [5, 2, 8], "芒种": [6, 3, 9],
}
# 阴遁局数表（夏至→冬至前）
_QIMEN_YIN_JU = {
    "夏至": [9, 3, 6], "小暑": [8, 2, 5], "大暑": [7, 1, 4],
    "立秋": [2, 5, 8], "处暑": [1, 4, 7], "白露": [9, 3, 6],
    "秋分": [7, 1, 4], "寒露": [6, 9, 3], "霜降": [5, 8, 2],
    "立冬": [6, 9, 3], "小雪": [5, 8, 2], "大雪": [4, 7, 1],
}

# 天干序号
GAN_INDEX = {g: i for i, g in enumerate(TIAN_GAN)}

# 九星
JIU_XING = ["天蓬", "天芮", "天冲", "天辅", "天禽", "天心", "天柱", "天任", "天英"]
JIU_XING_LEVEL = {
    "天蓬": "大凶", "天芮": "凶", "天冲": "小吉", "天辅": "大吉",
    "天禽": "大吉", "天心": "大吉", "天柱": "小凶", "天任": "小吉", "天英": "小凶"
}

# 八门
BA_MEN = ["休", "死", "伤", "杜", "中", "开", "惊", "生", "景"]
BA_MEN_LEVEL = {
    "休": "大吉", "生": "大吉", "伤": "凶", "杜": "平",
    "景": "小吉", "死": "凶", "惊": "凶", "开": "大吉"
}

# 八神顺序（阳遁顺/阴遁逆排列）
BA_SHEN_YANG = ["值符", "腾蛇", "太阴", "六合", "白虎", "玄武", "九地", "九天"]
BA_SHEN_YIN = ["值符", "九天", "九地", "玄武", "白虎", "六合", "太阴", "腾蛇"]

# 九宫→八卦映射
GONG_TO_GUA = {
    1: "坎", 2: "坤", 3: "震", 4: "巽",
    5: "中", 6: "乾", 7: "兑", 8: "艮", 9: "离"
}

# 九宫→方位映射
GONG_TO_DIRECTION = {
    1: "北", 2: "西南", 3: "东", 4: "东南",
    5: "中", 6: "西北", 7: "西", 8: "东北", 9: "南"
}

# 九宫→脏腑映射（游兄体系）
GONG_TO_ZANGFU = {
    1: "肾（水）", 2: "心（火）",
    3: "肝（木）", 4: "肺（金）",
    5: "脾（土·中宫枢纽）",
    6: "脾肾（水土复合）", 7: "心脾（火土复合）",
    8: "肝脾（木土复合）", 9: "肺脾（金土复合）"
}

# 八门→病势映射
MEN_TO_SHI = {
    "休": "虚证·慢性·宜补", "生": "新病·急性·预后好",
    "伤": "炎症·损伤·血证", "杜": "慢性阻塞·痰瘀",
    "景": "热证·炎症·肿疡", "死": "器质病变·肿瘤·预后差",
    "惊": "功能紊乱·情志·恐惧", "开": "表证·初起·正气尚存"
}

# 八神→情志映射
SHEN_TO_QINGZHI = {
    "值符": "神明·清净", "腾蛇": "惊恐·怪异",
    "太阴": "抑郁·思虑", "六合": "纠结·多虑",
    "白虎": "狂躁·暴力·血证", "玄武": "幻觉·恐惧·妄想",
    "九地": "忧郁·悲伤·绝望", "九天": "亢奋·躁动"
}

# 九宫洛书数字
LO_SHU_NUMS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}

# 八维路径（洛书核心——每行/列/对角线之和=15）
BA_WEI_PATHS = [
    # 三行
    [4, 9, 2],  # 上排：巽4 + 离9 + 坤2 = 15
    [3, 5, 7],  # 中排：震3 + 中5 + 兑7 = 15
    [8, 1, 6],  # 下排：艮8 + 坎1 + 乾6 = 15
    # 三列
    [4, 3, 8],  # 左列：巽4 + 震3 + 艮8 = 15
    [9, 5, 1],  # 中列：离9 + 中5 + 坎1 = 15
    [2, 7, 6],  # 右列：坤2 + 兑7 + 乾6 = 15
    # 两条对角线
    [4, 5, 6],  # 主对角线：巽4 + 中5 + 乾6 = 15
    [2, 5, 8],  # 副对角线：坤2 + 中5 + 艮8 = 15
]

# 内伤外感 keywords
WAI_GAN_KEYWORDS = [
    "恶寒", "发热", "怕冷", "怕风", "鼻塞", "流涕", "喷嚏",
    "咳嗽", "咽痛", "头痛身痛", "酸痛", "感冒", "受凉",
    "风寒", "风热", "外感", "时气", "疫气", "温病"
]
NEI_SHANG_KEYWORDS = [
    "乏力", "气短", "纳差", "腹胀", "便溏", "便秘",
    "失眠", "多梦", "腰酸", "腿软", "头晕", "耳鸣",
    "口苦", "口干", "心烦", "易怒", "抑郁", "焦虑",
    "月经", "带下", "遗精", "阳痿", "畏寒", "怕冷",
    "食欲", "饭后", "劳累", "休息", "久病", "体虚"
]

# 科室关键字
DEPARTMENT_KEYWORDS = {
    "妇科": ["月经", "带下", "经前", "经期", "产后", "崩漏", "痛经",
             "闭经", "不孕", "乳腺", "更年期", "盆腔", "妊娠",
             "赤白带", "经行", "乳胀", "阴痒", "子宫"],
    "儿科": ["小儿", "婴儿", "幼儿", "儿童", "发育", "厌食", "积食",
             "夜啼", "遗尿", "惊风", "麻疹", "水痘", "疳积",
             "扁桃体", "腺样体"],
    "外科/皮肤科": ["疮疡", "痈肿", "疔毒", "湿疹", "皮疹", "荨麻疹",
                    "痤疮", "毛囊炎", "带状疱疹", "丹毒", "牛皮癣",
                    "神经性皮炎", "银屑病", "硬皮病", "斑秃",
                    "外伤", "骨折", "扭伤", "关节"],
    "精神科": ["抑郁", "焦虑", "恐惧", "惊恐", "幻觉", "妄想",
               "双相", "狂躁", "强迫", "失眠严重", "痴呆",
               "精神分裂", "人格障碍", "躯体化",
               "心悸", "心慌", "胆小", "易惊", "梦多", "噩梦",
               "烦躁易怒", "情绪低落", "悲伤欲哭", "多疑",
               "自闭", "社交恐惧", "紧张", "神经衰弱"],
}

# 多科室奇门辨证要点——九宫脏腑对应
DEPT_GONG_MAP = {
    "内科": {
        "坎1(肾)": "腰痛/水肿/耳聋/骨病",
        "坤2(心)": "烦热/失眠/口疮",
        "震3(肝)": "眩晕/胁痛/头痛/抽搐",
        "巽4(胆)": "中风/口苦/摇摆/眩晕",
        "中5(脾)": "痞满/纳差/乏力",
        "乾6(脾肾)": "泄泻/水肿/腰膝酸软",
        "兑7(肺)": "咳喘/咽痛/发热/汗出",
        "艮8(肝脾)": "腹胀/胁满/纳呆",
        "离9(心/肺)": "心烦/不寐/咳血"
    },
    "妇科": {
        "坎1(肾)": "腰酸/不孕/胎动不安",
        "坤2(脾土·带脉)": "带下/崩漏/经水不调",
        "震3(肝)": "经前烦躁/乳胀/胁痛",
        "艮8(肝脾·少腹)": "癥瘕/痛经/少腹痛",
        "离9(心神)": "经前烦乱/产后抑郁",
        "巽4(胆/风)": "更年期潮热/眩晕"
    },
    "儿科": {
        "坎1(肾)": "遗尿/发育迟缓",
        "艮8(胃)": "食积/疳积/呕吐",
        "巽4(风木)": "惊风/麻疹/风疹",
        "中5(中气)": "厌食/腹胀/腹泻",
        "兑7(肺)": "咳嗽/哮喘/发烧",
        "离9(心)": "夜啼/烦躁/多动"
    },
    "外科/皮肤科": {
        "兑7(金·皮毛)": "疮疡/湿疹/皮肤顽疾",
        "离9(火·血热)": "痤疮/丹毒/痈肿",
        "巽4(风·疮毒)": "风疹/荨麻疹/游走性疮毒",
        "坎1(肾水)": "慢性溃疡/阴疽"
    },
    "精神科": {
        "离9(心神)·八神": "失眠/癫狂/神志不清",
        "震3(肝)·伤门": "惊狂/躁动/易怒",
        "坤2(心)·死门": "抑郁/绝望/木僵",
        "天芮+腾蛇": "惊恐/怪异/幻觉",
        "天芮+白虎": "狂躁/暴力/血证",
        "天芮+玄武": "幻觉/恐惧/妄想",
        "天芮+九地": "忧郁/悲伤/绝望",
        "天芮+九天": "亢奋/躁动"
    }
}

# 时干→五门十变化合
SHI_GAN_TO_HEHUA = {
    "甲": ("甲己化土", "临泣(足胆)+公孙(脾络)", "运中焦、调升降"),
    "己": ("甲己化土", "临泣(足胆)+公孙(脾络)", "运中焦、调升降"),
    "乙": ("乙庚化金", "商阳(手大)+少商(手肺)", "理气肃肺"),
    "庚": ("乙庚化金", "商阳(手大)+少商(手肺)", "理气肃肺"),
    "丙": ("丙辛化水", "阳谷(手小)+太渊(手肺)", "滋阴引火归元"),
    "辛": ("丙辛化水", "阳谷(手小)+太渊(手肺)", "滋阴引火归元"),
    "丁": ("丁壬化木", "少冲(手心)+至阴(足膀)", "疏肝调神"),
    "壬": ("丁壬化木", "少冲(手心)+至阴(足膀)", "疏肝调神"),
    "戊": ("戊癸化火", "阴谷(足肾)+三里(足胃)", "温阳补火生土"),
    "癸": ("戊癸化火", "阴谷(足肾)+三里(足胃)", "温阳补火生土"),
}

# 环境变量
LLM_API_URL = os.environ.get("LLM_API_URL", "http://127.0.0.1:11434/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "huihui_ai/qwen2.5-1m-abliterated:7b")
KNOWLEDGE_BASE = os.environ.get("KNOWLEDGE_BASE", "") or None


# =============================================================
# 工具函数
# =============================================================

def _hour_to_dizhi(hour: int) -> str:
    return DI_ZHI[(hour + 1) // 2 % 12]

def _hour_to_dizhi_index(hour: int) -> int:
    return (hour + 1) // 2 % 12

def _get_shi_gan(ri_gan: str, hour: int) -> str:
    """五鼠遁：根据日干和时辰推算时干"""
    shi_idx = _hour_to_dizhi_index(hour)
    start_map = {"甲": 0, "己": 0, "乙": 2, "庚": 2, "丙": 4, "辛": 4,
                 "丁": 6, "壬": 6, "戊": 8, "癸": 8}
    start = start_map.get(ri_gan, 0)
    return TIAN_GAN[(start + shi_idx) % 10]


def _qimen_get_term_and_ju(year: int, month: int, day: int, hour: int):
    """节气定局：获取当前节气+阴阳遁+局数（使用 lunar-python API）

    修复说明：lunar_python 的 getPrevJieQi()/getNextJieQi() 返回单个 JieQi 对象，
    不可迭代/切片。改用 getJieQiTable() 获取字典 {名称: Solar} 来构建节气列表。
    """
    from lunar_python import Solar
    from datetime import datetime as dt

    year, month, day, hour = int(year), int(month), int(day), int(hour)
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    lunar_obj = solar.getLunar()
    curr_dt = dt(year, month, day, hour)

    # 用 getJieQiTable() 获取全年节气字典 {名称: Solar}
    jieqi_table = lunar_obj.getJieQiTable()
    jieqi_list = lunar_obj.getJieQiList()  # 有序名称列表

    # 构建设当前时间前后的节气序列
    terms = []
    for name in jieqi_list:
        if name in jieqi_table:
            solar_dt = jieqi_table[name]
            t_dt = dt(solar_dt.getYear(), solar_dt.getMonth(), solar_dt.getDay(), 0, 0)
            terms.append((name, t_dt))

    terms.sort(key=lambda x: x[1])

    # 找到最后一个不晚于当前时间的节气
    if not terms:
        # fallback: 从当前节气计算
        from lunar_python import JieQi, Solar as _Solar
        prev = lunar_obj.getPrevJieQi()
        s = prev.getSolar()
        current_term = prev.getName()
        current_term_dt = dt(s.getYear(), s.getMonth(), s.getDay(), 0, 0)
    else:
        current_term = terms[0][0]
        current_term_dt = terms[0][1]
        for name, t_dt in terms:
            if t_dt <= curr_dt:
                current_term = name
                current_term_dt = t_dt

    days_in_term = (curr_dt - current_term_dt).days

    # 阴阳遁：冬至→夏至前阳遁，夏至→冬至前阴遁
    if current_term not in _QIMEN_TERM_ORDER:
        # fallback: 根据月份粗略判断
        is_yang = 5 <= month <= 11
        ju = 3  # 默认3局
        yuan = '下元'
        return is_yang, ju, current_term, days_in_term, yuan

    curr_idx = _QIMEN_TERM_ORDER.index(current_term)
    xia_zhi_idx = _QIMEN_TERM_ORDER.index('夏至')
    is_yang = curr_idx < xia_zhi_idx

    # 上中下元：每5天一换
    yuan_idx = (days_in_term) // 5
    if yuan_idx > 2:
        yuan_idx = yuan_idx % 3

    ju_table = _QIMEN_YANG_JU if is_yang else _QIMEN_YIN_JU
    ju = ju_table.get(current_term, [3, 3, 3])[yuan_idx]

    yuan_names = ['上元', '中元', '下元']
    return is_yang, ju, current_term, days_in_term, yuan_names[yuan_idx]


def _full_ju(year: int, month: int, day: int, hour: int, use_lunar_time: bool = False) -> dict:
    """
    完整奇门排盘（独立实现，不依赖系统qimen_pail工具）

    返回结构化九宫数据：
    - four_pillars: 四柱
    - yin_yang: 阳遁/阴遁
    - ju: 局数
    - yuan: 上/中/下元
    - term: 当前节气
    - palaces: 九宫列表（含星/门/神/吉凶）
    - zhi_fu_gong: 值符落宫
    - yong_shen_gong: 用神落宫
    """
    from lunar_python import Solar

    year, month, day, hour = int(year), int(month), int(day), int(hour)
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    lunar_obj = solar.getLunar()
    bazi = lunar_obj.getEightChar()

    nian_gan, nian_zhi = bazi.getYearGan(), bazi.getYearZhi()
    yue_gan, yue_zhi = bazi.getMonthGan(), bazi.getMonthZhi()
    ri_gan, ri_zhi = bazi.getDayGan(), bazi.getDayZhi()
    shi_zhi = _hour_to_dizhi(hour)
    shi_gan = _get_shi_gan(ri_gan, hour)

    four_pillars = f"{nian_gan}{nian_zhi} {yue_gan}{yue_zhi} {ri_gan}{ri_zhi} {shi_gan}{shi_zhi}"

    # 节气定局
    is_yang_dun, ju, term, days_in_term, yuan = _qimen_get_term_and_ju(year, month, day, hour)
    yin_yang = "阳遁" if is_yang_dun else "阴遁"

    # 用神落宫 = 时干落宫
    shi_gan_idx = GAN_INDEX.get(shi_gan, 0)
    yong_shen_gong = (shi_gan_idx % 9) + 1
    if yong_shen_gong == 5:
        yong_shen_gong = 2  # 中宫寄坤

    LO_SHU_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9]

    # 八神定位：值符从用神宫起，阳顺阴逆
    zhi_fu_start = yong_shen_gong
    shen_position = {}
    index_of_zf = LO_SHU_ORDER.index(zhi_fu_start)
    for i, gong_num in enumerate(LO_SHU_ORDER):
        if is_yang_dun:
            offset = (i - index_of_zf) % 8
        else:
            offset = (index_of_zf - i) % 8
        shen_name = BA_SHEN_YANG[offset]
        shen_position[gong_num] = shen_name

    # 排九星（洛书顺序+中宫寄坤2）
    star_mapping = {}
    # 阳遁顺排，阴遁逆排
    star_indices = list(range(9))
    star_order_1 = (ju - 1) % 9  # 坎1（值符星）
    for i, gong_num in enumerate(LO_SHU_ORDER):
        if gong_num == 5:
            continue  # 中宫天禽寄坤2
        if is_yang_dun:
            idx = (star_order_1 + i) % 9
        else:
            idx = (star_order_1 - i - 1) % 9
        star_mapping[gong_num] = JIU_XING[idx]

    # 寄宫
    star_mapping[5] = "天禽"
    star_mapping[2] = star_mapping.get(2, "天芮")  # 天芮+天禽同宫

    # 排八门
    men_mapping = {}
    # 休门从坎1起
    men_order_1 = (ju - 1) % 9
    for i, gong_num in enumerate(LO_SHU_ORDER):
        if gong_num == 5:
            continue
        if is_yang_dun:
            idx = (men_order_1 + i) % 9
        else:
            idx = (men_order_1 - i - 1) % 9
        men_mapping[gong_num] = BA_MEN[idx]

    # 值符定位
    zhi_fu_star = star_mapping.get(1, "天蓬")  # 坎1为值符

    # 构建九宫数据
    palaces = []
    for gong in LO_SHU_ORDER:
        palace = {
            "gong": gong,
            "name": GONG_TO_GUA.get(gong, ""),
            "direction": GONG_TO_DIRECTION.get(gong, ""),
            "star": star_mapping.get(gong, "天禽"),
            "men": men_mapping.get(gong, "中"),
            "shen": shen_position.get(gong, "值符"),
            "level": ""
        }
        star_level = JIU_XING_LEVEL.get(palace["star"], "平")
        men_level = BA_MEN_LEVEL.get(palace["men"], "平")
        if star_level == "大凶" or men_level == "凶":
            palace["level"] = "凶"
        elif star_level == "大吉" and men_level == "大吉":
            palace["level"] = "大吉"
        elif "吉" in star_level or "吉" in men_level:
            palace["level"] = "小吉"
        else:
            palace["level"] = "平"
        palaces.append(palace)

    return {
        "four_pillars": four_pillars,
        "yin_yang": yin_yang,
        "ju": ju,
        "yuan": yuan,
        "term": term,
        "days_in_term": days_in_term,
        "palaces": palaces,
        "zhi_fu_star": zhi_fu_star,
        "yong_shen_gong": yong_shen_gong
    }


# =============================================================
# 科室检测
# =============================================================

def _detect_department(symptoms: str) -> str:
    """根据症状关键词自动检测科室"""
    symptoms_lower = symptoms
    dept_scores = {}
    for dept, keywords in DEPARTMENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in symptoms_lower)
        if score > 0:
            dept_scores[dept] = score
    if dept_scores:
        return max(dept_scores, key=dept_scores.get)
    return "内科"


# =============================================================
# 内伤外感判断
# =============================================================

def _detect_type(symptoms: str) -> str:
    """判断外感/内伤/合病"""
    wai = sum(1 for kw in WAI_GAN_KEYWORDS if kw in symptoms)
    nei = sum(1 for kw in NEI_SHANG_KEYWORDS if kw in symptoms)
    if wai >= 2 and nei >= 2:
        return "外感内伤合病"
    elif wai >= 2:
        return "外感为主"
    elif nei >= 2:
        return "内伤为主"
    return "待辨"


# =============================================================
# 天芮定位
# =============================================================

def _tianrui_analysis(pan: dict, symptoms: str) -> dict:
    """分析天芮病星落宫+八门八神的临床意义"""
    palaces = pan["palaces"]
    tianrui = None
    for p in palaces:
        if p["star"] == "天芮":
            tianrui = p
            break
    if not tianrui:
        tianrui = palaces[1]  # 默认坤2

    gong = tianrui["gong"]
    men = tianrui["men"]
    shen = tianrui["shen"]

    meaning_parts = [f"天芮落{GONG_TO_GUA.get(gong, '')}{gong}宫"]
    if gong in GONG_TO_ZANGFU:
        meaning_parts.append(f"→{GONG_TO_ZANGFU[gong]}")
    if men in MEN_TO_SHI:
        meaning_parts.append(f"·{MEN_TO_SHI[men]}")
    if shen in SHEN_TO_QINGZHI:
        meaning_parts.append(f"·{SHEN_TO_QINGZHI[shen]}")

    return {
        "gong": gong,
        "name": GONG_TO_GUA.get(gong, ""),
        "star": "天芮",
        "men": men,
        "shen": shen,
        "level": "凶",
        "meaning": "".join(meaning_parts)
    }


# =============================================================
# 六步推演
# =============================================================

def _six_step_analysis(pan: dict, symptoms: str, department: str,
                       diag_type: str, tianrui: dict) -> dict:
    """六步推演法完整分析"""
    palaces = pan["palaces"]
    
    # Step 1: 起盘定局
    step1 = f"起盘：{pan['yin_yang']}{pan['ju']}局，{pan['term']}{pan['yuan']}，四柱{pan['four_pillars']}"

    # Step 2: 天芮定位
    step2 = f"天芮落{tianrui['name']}{tianrui['gong']}宫+{tianrui['men']}门+{tianrui['shen']}神"
    if tianrui["gong"] in GONG_TO_ZANGFU:
        step2 += f"·{GONG_TO_ZANGFU[tianrui['gong']]}"

    # Step 3: 病位定性
    gong = tianrui["gong"]
    if gong in GONG_TO_ZANGFU:
        zangfu = GONG_TO_ZANGFU[gong]
    else:
        zangfu = f"{GONG_TO_GUA.get(gong, '')}宫"
    step3 = f"病位：{zangfu}（{pan['yin_yang']}{pan['ju']}局天芮落{GONG_TO_GUA.get(gong, '')}{gong}宫→{GONG_TO_DIRECTION.get(gong, '')}方）"

    # Step 4: 病性定量
    men = tianrui["men"]
    shen = tianrui["shen"]
    men_shi = MEN_TO_SHI.get(men, "待辨")
    shen_qing = SHEN_TO_QINGZHI.get(shen, "待辨")
    step4 = f"病势：{men_shi}·情志：{shen_qing}"

    # Step 5: 五运六气
    year_gan = pan["four_pillars"].split()[0][0]
    # 简单五运六气加权
    yun_analysis = {
        "丙": "丙午年·少阳相火司天·郁火偏重",
        "丁": "丁未年·太阴湿土司天·寒湿偏重",
        "戊": "戊申年·少阳相火司天·火热偏重",
        "己": "己酉年·少阴君火司天·燥热偏重"
    }
    yun_desc = yun_analysis.get(year_gan, "五运六气：当前年份")
    step5 = f"五运：{yun_desc}·当前节气{pan['term']}"

    # Step 6: 出方案
    # 时干化合针法
    shi_gan = pan["four_pillars"].split()[-1][0]
    hehua = SHI_GAN_TO_HEHUA.get(shi_gan, ("时干化合", "公孙+足三里", "运中焦"))
    
    # 九宫配穴（病宫的对应穴位）
    gong_acupoints = {
        1: "太溪、照海、复溜", 2: "神门、少府、阴郄",
        3: "太冲、行间、曲泉", 4: "太渊、经渠、尺泽",
        5: "公孙、中脘、足三里", 6: "太白、三阴交、地机",
        7: "神门、大陵、内关", 8: "太冲、足三里、阴陵泉",
        9: "中府、太渊、鱼际"
    }

    step6_acupuncture_parts = [f"主穴：{gong_acupoints.get(gong, '足三里、公孙')}"]
    step6_acupuncture_parts.append(f"时干{hehua[0]}：{hehua[1]}（{hehua[2]}）")
    step6_timing = f"当前{pan['term']}·{pan['yuan']}·{pan['yin_yang']}{pan['ju']}局"

    step6 = f"针法：{'；'.join(step6_acupuncture_parts)}；时机：{step6_timing}"
    if diag_type == "内伤为主":
        step6 += "（内伤为主·丸散缓图·五脏填补在后）"
    elif diag_type == "外感为主":
        step6 += "（外感为主·针药并施·以开表为先）"

    return {
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "step4": step4,
        "step5": step5,
        "step6": step6
    }


# =============================================================
# 九重辩证法 LLM 深度分析
# =============================================================

def _load_knowledge_files() -> dict:
    """加载知识库参考文件"""
    if not KNOWLEDGE_BASE:
        return {}
    knowledge_path = Path(KNOWLEDGE_BASE)
    if not knowledge_path.exists():
        return {}

    result = {}
    related_files = [
        "01-理论基础/六经三才论·先天八卦化生推演.md",
        "01-理论基础/五脏九宫矩阵·洛书数理与脏腑升降体系.md",
        "01-理论基础/辅行诀五味体用辨·河图用药底层逻辑.md",
        "02-临床辨证/内伤外感双轨辩证.md",
        "02-临床辨证/五脏双轨辩证.md",
        "02-临床辨证/五脏藏神辩证.md",
        "02-临床辨证/奇门遁甲病机诊断法.md",
        "02-临床辨证/九宫对角脉应律.md",
        "02-临床辨证/六经精神病辨证指南.md",
        "02-临床辨证/六经妇科辨证指南.md",
        "02-临床辨证/六经儿科辨证指南.md",
        "02-临床辨证/六经外科辨证指南.md",
        "02-临床辨证/九重辩证法.md"
    ]

    for rel_path in related_files:
        full_path = knowledge_path / rel_path
        if full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8")
                result[rel_path] = content[:5000]
            except Exception:
                pass
    return result


def _llm_deep_analysis(symptoms: str, pan: dict, tianrui: dict,
                       six_steps: dict, department: str, diag_type: str) -> dict:
    """调用本地 LLM 进行九重辩证法深度分析"""
    import urllib.request

    # 加载知识库
    knowledge = _load_knowledge_files()
    knowledge_sections = []
    for path, content in knowledge.items():
        knowledge_sections.append(f"=== {path} ===\n{content[:3000]}")

    pan_json = json.dumps({
        "four_pillars": pan["four_pillars"],
        "yin_yang": pan["yin_yang"],
        "ju": pan["ju"],
        "term": pan["term"],
        "palaces": [{k: v for k, v in p.items() if k in ("gong","name","direction","star","men","shen","level")}
                     for p in pan["palaces"]]
    }, ensure_ascii=False, indent=2)

    prompt = f"""你是一位精通奇门遁甲病机诊断的中医临床专家，请基于游兄（用户）独创的「九重辩证法」体系，对以下病例进行完整的深层病机分析。

## 患者信息
- 就诊时间：{pan['four_pillars']}（{pan['yin_yang']}{pan['ju']}局，{pan['term']}{pan['yuan']}）
- 主诉：{symptoms}
- 科室：{department}
- 辨证类型：{diag_type}

## 奇门盘面
{pan_json}

## 天芮分析
- 落宫：{tianrui['name']}{tianrui['gong']}宫
- 八门：{tianrui['men']}
- 八神：{tianrui['shen']}
- 意义：{tianrui['meaning']}

## 六步推演
{json.dumps(six_steps, ensure_ascii=False, indent=2)}

## 知识库参考
{chr(10).join(knowledge_sections[:3])}

## 要求——按九重辩证法层层推进

### 第1重：奇门三才定性
天盘（天芮+九星+天时）→ 外感因素
人盘（八门+八神）→ 病势/情志
地盘（九宫+脏腑）→ 脏腑定位
→ 病在天地人哪一部？

### 第2重：奇门五步推演
审盘求证→辨证求机→审因论治→随证施治→验效求理

### 第3重：内伤外感双规
{diag_type}→ 先开六经还是先补五脏？

### 第4重：穿宫传变预测
病势向哪些宫位传变？（纵/横/斜向）

### 第5重：八维平衡辨证
九宫八维和15是否被打破？相关宫位关系？

### 第6重：五脏藏神辨证
八神对应七情，哪一神异常？

### 第7重：河图四象五味
病宫之气是体不足还是用不畅？

### 第8重：辅行诀体用辨
宫位本气 vs 星门神外来影响，体用是否合一？

### 第9重：化合配穴
时干{pan['four_pillars'].split()[-1][0]}应哪组五门十变？水火交媾阵适用？

请以 JSON 格式输出：
{{
  "qimen_sancai": "天/人/地 ...分析...",
  "xujiadong": "证→机→因→治→效 分析",
  "shuang_gui": "外感/内伤/合病 分析",
  "chuangong": "传变预测",
  "bawei": "八维平衡分析",
  "cangshen": "五脏藏神异常分析",
  "hetu_tiyong": "河图体用分析",
  "fuxingjue": "辅行诀分析",
  "wumen": "五门十变化合配穴",
  "overall_analysis": "综合病机分析（300字以内，临床可读）"
}}
"""

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": False
    }

    try:
        req = urllib.request.Request(
            LLM_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]

        # 尝试从回复中提取 JSON
        json_match = re.search(r'\{[^{}]*"qimen_sancai"[^{}]*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        # 更宽松的匹配
        json_match2 = re.search(r'\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}', content, re.DOTALL)
        if json_match2:
            return json.loads(json_match2.group())

        return {"error": "LLM 未返回有效 JSON", "raw": content[:500]}
    except Exception as e:
        return {"error": str(e), "note": "LLM深度分析失败，使用基础分析"}


# =============================================================
# 紧急度判断
# =============================================================

def _urgency_analysis(pan: dict, tianrui: dict) -> str:
    """基于盘面特征判断病情紧急度"""
    urgency = []
    four_pillars = pan["four_pillars"]
    
    # 反吟/伏吟判断（简化：日干时干相冲为反吟）
    day_gan = four_pillars.split()[2][0]
    hour_gan = four_pillars.split()[3][0]
    if day_gan and hour_gan:
        d_idx = GAN_INDEX.get(day_gan, 0)
        h_idx = GAN_INDEX.get(hour_gan, 0)
        if abs(d_idx - h_idx) == 5 or abs(d_idx - h_idx) == 7:
            urgency.append("反吟盘→急性发作，传变迅速，针法以开为主")
    
    # 天芮+死门
    if tianrui["men"] == "死":
        urgency.append("天芮+死门→器质病变可能性大，建议进一步检查")
    
    # 天芮+空亡（简化）
    if tianrui["shen"] in ("九地", "太阴"):
        urgency.append("天芮+九地/太阴→病隐伏不显或慢性缠绵")
    
    # 中宫吉凶（简化）
    for p in pan["palaces"]:
        if p["gong"] == 5 and p["level"] == "凶":
            urgency.append("中宫凶→胃气已衰，预后差，以扶正为主")
            break
    else:
        urgency.append("中宫吉→正气尚存，可攻补兼施")
    
    return "；".join(urgency) if urgency else "无明显紧急特征"


# =============================================================
# 治疗方案生成
# =============================================================

def _generate_plan(pan: dict, tianrui: dict, department: str, diag_type: str,
                   deep_analysis: dict) -> dict:
    """综合生成治疗方案"""
    gong = tianrui["gong"]
    shi_gan = pan["four_pillars"].split()[-1][0]
    hehua = SHI_GAN_TO_HEHUA.get(shi_gan, ("时干化合", "公孙+足三里", "运中焦"))

    # 病宫配穴
    gong_acupoints = {
        1: "太溪、照海、复溜", 2: "神门、少府、阴郄",
        3: "太冲、行间、曲泉", 4: "太渊、经渠、尺泽",
        5: "中脘、公孙、足三里", 6: "太白、三阴交、地机",
        7: "神门、大陵、内关", 8: "太冲、足三里、阴陵泉",
        9: "中府、太渊、鱼际"
    }
    
    # 对宫配穴（八维平衡——选对宫/相关宫位）
    dui_gong_acupoints = {
        1: "中府、太渊（离9·肺脾—坎1的对宫）",
        2: "太冲、阴陵泉（艮8·肝脾—坤2的对宫）",
        3: "神门、内关（兑7·心脾—震3的对宫）",
        4: "太白、三阴交（乾6·脾肾—巽4的对宫）",
        5: "全宫皆调",
        6: "太渊、经渠（巽4·肺—乾6的对宫）",
        7: "太冲、行间（震3·肝—兑7的对宫）",
        8: "神门、少府（坤2·心—艮8的对宫）",
        9: "太溪、复溜（坎1·肾—离9的对宫）"
    }

    # 紧急度
    urgency = _urgency_analysis(pan, tianrui)

    acupuncture_parts = []
    acupuncture_parts.append(f"本宫：{gong_acupoints.get(gong, '足三里、公孙')}")
    acupuncture_parts.append(f"对宫：{dui_gong_acupoints.get(gong, '足三里、中脘')}")
    acupuncture_parts.append(f"时干{hehua[0]}：{hehua[1]}（{hehua[2]}）")

    # 水火交媾阵（丙午年背景）
    acupuncture_parts.append("水火交媾阵：阳谷+太渊（丙辛化水）+足三里+阴谷（戊癸化火）")

    return {
        "acupuncture": "；".join(acupuncture_parts),
        "timing": f"当前{pan['term']}·{pan['yin_yang']}{pan['ju']}局·{pan['yuan']}·避五不遇时",
        "urgency": urgency
    }


# =============================================================
# 主诊断函数
# =============================================================

def diagnose(symptoms: str, year: int = None, month: int = None,
             day: int = None, hour: int = None) -> dict:
    """
    奇门遁甲病机诊断主函数

    参数：
        symptoms: 症状描述
        year/month/day/hour: 就诊时间（默认当前时间）

    返回结构化诊断报告
    """
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    day = day or now.day
    hour = hour if hour is not None else now.hour
    # 23点后按子时处理
    if hour == 23:
        hour = 0

    # 科室检测
    department = _detect_department(symptoms)
    
    # 内伤外感判断
    diag_type = _detect_type(symptoms)

    # 奇门排盘
    pan = _full_ju(year, month, day, hour)

    # 天芮定位
    tianrui = _tianrui_analysis(pan, symptoms)

    # 六步推演
    six_steps = _six_step_analysis(pan, symptoms, department, diag_type, tianrui)

    # LLM 九重辩证法深度分析
    deep_analysis = _llm_deep_analysis(symptoms, pan, tianrui, six_steps, department, diag_type)

    # 治疗方案
    plan = _generate_plan(pan, tianrui, department, diag_type, deep_analysis)

    return {
        "success": True,
        "input": {
            "symptoms": symptoms,
            "year": year, "month": month, "day": day, "hour": hour
        },
        "qimen_pan": pan,
        "department": department,
        "type": diag_type,
        "tianrui": tianrui,
        "step_by_step": six_steps,
        "nine_layers": deep_analysis if "error" not in deep_analysis else {"note": "LLM不可用，使用基础分析", **deep_analysis},
        "plan": plan
    }


# =============================================================
# CLI 入口
# =============================================================

def _pretty_print(result: dict):
    """人性化输出"""
    print("=" * 55)
    print("        奇门遁甲病机诊断报告")
    print("=" * 55)
    print(f"  就诊时间：{result['input']['year']}年{result['input']['month']}月{result['input']['day']}日{result['input']['hour']}时")
    print(f"  四柱八字：{result['qimen_pan']['four_pillars']}")
    print(f"  节气定局：{result['qimen_pan']['term']}{result['qimen_pan']['yuan']}·{result['qimen_pan']['yin_yang']}{result['qimen_pan']['ju']}局")
    print(f"  科    室：{result['department']}")
    print(f"  辨证类型：{result['type']}")
    print(f"  主    诉：{result['input']['symptoms']}")
    print("-" * 55)
    print(f"【天芮定位】{result['tianrui']['meaning']}")
    print("-" * 55)
    print("【六步推演】")
    for k, v in result['step_by_step'].items():
        print(f"  {k}: {v}")
    print("-" * 55)
    print("【九重辩证法深度分析】")
    nl = result.get("nine_layers", {})
    if "overall_analysis" in nl:
        print(f"  {nl['overall_analysis']}")
    elif "error" in nl:
        print(f"  ⚠️ {nl['error']}")
    else:
        for k, v in nl.items():
            if isinstance(v, str) and len(v) > 10:
                print(f"  {k}: {v[:100]}...")
    print("-" * 55)
    print("【治疗方案】")
    print(f"  针法：{result['plan']['acupuncture']}")
    print(f"  时机：{result['plan']['timing']}")
    print(f"  紧急度：{result['plan']['urgency']}")
    print("=" * 55)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="奇门遁甲病机诊断工具")
    parser.add_argument("symptoms", nargs="?", help="症状描述")
    parser.add_argument("--year", type=int, default=None, help="就诊年（默认当前）")
    parser.add_argument("--month", type=int, default=None, help="就诊月（默认当前）")
    parser.add_argument("--day", type=int, default=None, help="就诊日（默认当前）")
    parser.add_argument("--hour", type=int, default=None, help="就诊时（0-23，默认当前）")
    parser.add_argument("--pretty", action="store_true", help="可读输出（非JSON）")
    parser.add_argument("--json-input", type=str, help="JSON格式输入文件")
    parser.add_argument("--interactive", action="store_true", help="交互模式")
    parser.add_argument("-o", "--output", type=str, help="输出到文件")

    args = parser.parse_args()

    # 交互模式
    if args.interactive:
        print("奇门遁甲病机诊断工具 v1.0 — 交互模式")
        print("输入'quit'退出，'json'切换JSON输出")
        json_mode = False
        while True:
            symptoms = input("\n请输入症状：").strip()
            if not symptoms or symptoms.lower() in ("quit", "exit", "q"):
                break
            if symptoms.lower() == "json":
                json_mode = not json_mode
                print(f"JSON模式={'开启' if json_mode else '关闭'}")
                continue
            result = diagnose(symptoms)
            if json_mode:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _pretty_print(result)
        return

    # 症状输入
    symptoms = args.symptoms
    if args.json_input:
        with open(args.json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
            symptoms = data.get("symptoms", symptoms or "")
    
    if not symptoms:
        parser.print_help()
        sys.exit(1)

    # 执行诊断
    result = diagnose(symptoms, args.year, args.month, args.day, args.hour)

    # 输出
    output_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.pretty:
        _pretty_print(result)
    else:
        print(output_str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)


if __name__ == "__main__":
    main()
