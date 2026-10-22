#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
六十甲子综合数据库与核心计算模块
"""
from datetime import date, timedelta
import json

# ========== 基础数据 ==========
TIANGAN = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
DIZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

TIANGAN_WUXING = {'甲': '木', '乙': '木', '丙': '火', '丁': '火',
                  '戊': '土', '己': '土', '庚': '金', '辛': '金', '壬': '水', '癸': '水'}
DIZHI_WUXING = {'子': '水', '丑': '土', '寅': '木', '卯': '木',
                '辰': '土', '巳': '火', '午': '火', '未': '土',
                '申': '金', '酉': '金', '戌': '土', '亥': '水'}

# 六十甲子表 (序号从1开始, 甲子=1)
LIUSHIHJIAZI = []
for i in range(60):
    tg = TIANGAN[i % 10]
    dz = DIZHI[i % 12]
    LIUSHIHJIAZI.append((i + 1, tg, dz))

# 六十甲子纳音五行表（30组，每甲子对应1组）
NAYIN = {
    (1, 2): '海中金', (3, 4): '炉中火', (5, 6): '大林木',
    (7, 8): '路旁土', (9, 10): '剑锋金', (11, 12): '山头火',
    (13, 14): '涧下水', (15, 16): '城头土', (17, 18): '白蜡金',
    (19, 20): '杨柳木', (21, 22): '泉中水', (23, 24): '屋上土',
    (25, 26): '霹雳火', (27, 28): '松柏木', (29, 30): '长流水',
    (31, 32): '砂中金', (33, 34): '山下火', (35, 36): '平地木',
    (37, 38): '壁上土', (39, 40): '金箔金', (41, 42): '覆灯火',
    (43, 44): '天河水', (45, 46): '大驿土', (47, 48): '钗钏金',
    (49, 50): '桑柘木', (51, 52): '大溪水', (53, 54): '沙中土',
    (55, 56): '天上火', (57, 58): '石榴木', (59, 60): '大海水'
}

# 时辰对应（现代24小时制）
SHICHEN_MAP = [
    (23, 0, '子'), (1, 2, '丑'), (3, 4, '寅'), (5, 6, '卯'),
    (7, 8, '辰'), (9, 10, '巳'), (11, 12, '午'), (13, 14, '未'),
    (15, 16, '申'), (17, 18, '酉'), (19, 20, '戌'), (21, 22, '亥')
]

DIZHI_ORDER = {d: i + 1 for i, d in enumerate(DIZHI)}  # 子=1...亥=12
TIANGAN_ORDER = {t: i + 1 for i, t in enumerate(TIANGAN)}  # 甲=1...癸=10

# 地支相冲
LIUCHONG = {'子': '午', '丑': '未', '寅': '申', '卯': '酉', '辰': '戌', '巳': '亥',
             '午': '子', '未': '丑', '申': '寅', '酉': '卯', '戌': '辰', '亥': '巳'}

# 地支六合
LIUHE = {'子': '丑', '丑': '子', '寅': '亥', '卯': '戌', '辰': '酉', '巳': '申',
          '午': '未', '未': '午', '申': '巳', '酉': '辰', '戌': '卯', '亥': '寅'}

# 地支三合
SANHE = {'申': ['申', '子', '辰'], '子': ['申', '子', '辰'], '辰': ['申', '子', '辰'],
         '亥': ['亥', '卯', '未'], '卯': ['亥', '卯', '未'], '未': ['亥', '卯', '未'],
         '寅': ['寅', '午', '戌'], '午': ['寅', '午', '戌'], '戌': ['寅', '午', '戌'],
         '巳': ['巳', '酉', '丑'], '酉': ['巳', '酉', '丑'], '丑': ['巳', '酉', '丑']}

# 建除十二星 (从立春后第一个寅日起建)
JIANCHU_NAMES = ['建', '除', '满', '平', '定', '执', '破', '危', '成', '收', '开', '闭']
JIANCHU_JIXIONG = {'建': '平', '除': '吉', '满': '凶', '平': '平', '定': '吉', '执': '凶',
                   '破': '大凶', '危': '吉', '成': '吉', '收': '凶', '开': '吉', '闭': '凶'}

# 黄道黑道
HUANGDAO = {'子': '青龙', '丑': '明堂', '寅': '天刑', '卯': '朱雀',
            '辰': '金匮', '巳': '天德', '午': '白虎', '未': '玉堂',
            '申': '天牢', '酉': '玄武', '戌': '司命', '亥': '勾陈'}
HUANGDAO_JIXIONG = {'青龙': '吉', '明堂': '吉', '天刑': '凶', '朱雀': '凶',
                    '金匮': '吉', '天德': '吉', '白虎': '凶', '玉堂': '吉',
                    '天牢': '凶', '玄武': '凶', '司命': '吉', '勾陈': '凶'}

# 神煞（简化版常用神煞）
SHENSHA_FUNC = {}


def get_hour_gz(day_gan, hour):
    """五鼠遁：根据日干和时辰地支，推算时辰天干"""
    # 日干序号（甲=1...癸=10）
    dg_idx = TIANGAN_ORDER[day_gan] - 1
    # 甲己日 -> 甲子时起
    # 乙庚日 -> 丙子时起
    # 丙辛日 -> 戊子时起
    # 丁壬日 -> 庚子时起
    # 戊癸日 -> 壬子时起
    start_gz_cycle = [0, 2, 4, 6, 8]  # 甲=0, 乙=2, 丙=4, 丁=6, 戊=8
    start_idx = start_gz_cycle[dg_idx % 5]
    
    # 地支序号（子=1...亥=12）
    dz_name = None
    for start_h, end_h, name in SHICHEN_MAP:
        if start_h == hour or (start_h == 23 and hour >= 23):
            dz_name = name
            break
        if start_h <= hour <= end_h:
            dz_name = name
            break
        if start_h == 23 and hour == 23:
            dz_name = '子'
            break
    
    if dz_name is None:
        dz_name = '子'
    
    dz_idx = DIZHI_ORDER[dz_name] - 1  # 0-based
    
    hour_tg_idx = (start_idx + dz_idx) % 10
    hour_tg = TIANGAN[hour_tg_idx]
    
    return (hour_tg, dz_name)


def get_ganzhi_by_offset(gan, zhi, offset):
    """从指定干支偏移N位"""
    seq = get_ganzhi_seq(gan, zhi)
    if seq is None:
        return None
    new_seq = ((seq - 1 + offset) % 60) + 1
    if new_seq < 1:
        new_seq += 60
    return LIUSHIHJIAZI[new_seq - 1][1:]


def get_nayin(gan, zhi):
    """获取纳音五行"""
    seq = get_ganzhi_seq(gan, zhi)
    if seq is None:
        return None
    for (a, b), val in NAYIN.items():
        if a <= seq <= b:
            return val
    return None


def get_ganzhi_seq(gan, zhi):
    """获取干支在六十甲子中的序号"""
    for seq, g, z in LIUSHIHJIAZI:
        if g == gan and z == zhi:
            return seq
    return None


# ========== 公历推算模块 ==========
# 基准日：2000年1月1日 = 戊午日（注意：此日用真太阳时万年历校核，非旧版己卯）
BASE_DATE = date(2000, 1, 1)
BASE_GAN = '戊'
BASE_ZHI = '午'
BASE_SEQ = get_ganzhi_seq('戊', '午')

# 立春日期表（2020-2030年，因每年立春时刻不同，取大约日期）
# 立春一般在公历2月3日-5日之间，精确日期据天文计算
LISHUN_DATE = {
    2020: date(2020, 2, 4), 2021: date(2021, 2, 3), 2022: date(2022, 2, 4),
    2023: date(2023, 2, 4), 2024: date(2024, 2, 4), 2025: date(2025, 2, 3),
    2026: date(2026, 2, 4), 2027: date(2027, 2, 4), 2028: date(2028, 2, 4),
    2029: date(2029, 2, 3), 2030: date(2030, 2, 4),
}
# 未录入年份默认2月4日
DEFAULT_LISHUN = date(2000, 2, 4)

def get_lishun(year):
    """获取某年立春日期"""
    return LISHUN_DATE.get(year, date(year, DEFAULT_LISHUN.month, DEFAULT_LISHUN.day))

# 年干支基准（2000年=庚辰年）
YEAR_GAN_BASE = {2000: '庚'}
YEAR_ZHI_BASE = {2000: '辰'}

# 月干支基准（2000年1月=丁丑月）—— 注意：农历月干支以节气分界
# 立春(2月4日)前为上一年的十二月，立春后为新年的正月


def get_year_ganzhi(year, target_date=None):
    """获取年干支（以立春为界；优先使用 lunar_python 精确节气）。"""
    if target_date is None:
        target_date = date(year, 6, 1)  # 默认年中，肯定在立春后
    try:
        from lunar_python import Solar
        solar = Solar.fromYmd(target_date.year, target_date.month, target_date.day)
        gz = solar.getLunar().getYearInGanZhiExact()
        return (gz[0], gz[1])
    except Exception:
        pass
    # 2000年（庚辰年）立春后为庚辰年——但注意2000年立春前是己卯年
    # 年干支基准：2000年立春后=庚辰
    lichun = get_lishun(year)
    if target_date < lichun:
        # 立春前，用上一年的干支
        real_year = year - 1
    else:
        real_year = year
    diff = real_year - 2000
    tg_idx = (TIANGAN_ORDER['庚'] - 1 + diff) % 10
    dz_idx = (DIZHI_ORDER['辰'] - 1 + diff) % 12
    return (TIANGAN[tg_idx], DIZHI[dz_idx])


# 月干支表（正月=寅，以节气分界）
# 甲己之年丙作首，乙庚之岁戊为头，丙辛之年寻庚上，丁壬壬寅顺水流，若问戊癸何处起，甲寅之上好追求
MONTH_START = {
    '甲': '丙', '己': '丙',
    '乙': '戊', '庚': '戊',
    '丙': '庚', '辛': '庚',
    '丁': '壬', '壬': '壬',
    '戊': '甲', '癸': '甲'
}
MONTH_DIZHI = ['寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥', '子', '丑']

# 节气月分界（简化版：每月气为准）
# 约为：寅月(2月4日立春), 卯月(3月6日惊蛰), 辰月(4月5日清明), 
#       巳月(5月6日立夏), 午月(6月6日芒种), 未月(7月7日小暑),
#       申月(8月7日立秋), 酉月(9月8日白露), 戌月(10月8日寒露),
#       亥月(11月7日立冬), 子月(12月7日大雪), 丑月(1月6日小寒)
JIEQI_MONTH_BOUNDARY = {
    1: 6,   # 小寒（约1月6日）后进入丑月
    2: 4,   # 立春（约2月4日）后进入寅月
    3: 6,   # 惊蛰（约3月6日）后进入卯月
    4: 5,   # 清明（约4月5日）后进入辰月
    5: 6,   # 立夏（约5月6日）后进入巳月
    6: 6,   # 芒种（约6月6日）后进入午月
    7: 7,   # 小暑（约7月7日）后进入未月
    8: 7,   # 立秋（约8月7日）后进入申月
    9: 8,   # 白露（约9月8日）后进入酉月
    10: 8,  # 寒露（约10月8日）后进入戌月
    11: 7,  # 立冬（约11月7日）后进入亥月
    12: 7,  # 大雪（约12月7日）后进入子月
}


def get_month_ganzhi(year, month, day):
    """根据年月日获取月柱（以节气分界；优先精确节气）。"""
    try:
        from lunar_python import Solar
        gz = Solar.fromYmd(year, month, day).getLunar().getMonthInGanZhiExact()
        return (gz[0], gz[1])
    except Exception:
        pass
    # 先确定月的地支
    boundary = JIEQI_MONTH_BOUNDARY.get(month, 1)
    if day < boundary:
        # 还在上个月
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        return get_month_ganzhi(prev_year, prev_month, 28)

    # 确定月地支序号
    month_to_dz = {2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9, 12: 10, 1: 11}
    month_dz_idx = month_to_dz.get(month, 0) % 12
    dz_name = MONTH_DIZHI[month_dz_idx]

    # 确定月天干（五虎遁）
    year_gan = get_year_ganzhi(year, date(year, month, day))[0]
    start_gan = MONTH_START.get(year_gan, '丙')
    start_idx = TIANGAN_ORDER[start_gan] - 1
    tg_idx = (start_idx + month_dz_idx) % 10

    return (TIANGAN[tg_idx], dz_name)


def get_day_ganzhi(target_date):
    """根据基准日推算目标日干支（优先 lunar_python）。"""
    try:
        from lunar_python import Solar
        gz = Solar.fromYmd(target_date.year, target_date.month,
                           target_date.day).getLunar().getDayInGanZhi()
        return (gz[0], gz[1])
    except Exception:
        pass
    delta = (target_date - BASE_DATE).days
    seq_idx = (BASE_SEQ - 1 + delta) % 60
    return LIUSHIHJIAZI[seq_idx][1:]


# ========== 神煞推算 ==========
def get_shensha(gan, zhi):
    """获取主要神煞"""
    shensha_list = []
    
    # 天德贵人
    tian_de = {'寅': '丁', '卯': '申', '辰': '壬', '巳': '辛',
               '午': '亥', '未': '甲', '申': '癸', '酉': '寅',
               '戌': '丙', '亥': '乙', '子': '巳', '丑': '庚'}
    if zhi in tian_de and tian_de[zhi] == gan:
        shensha_list.append('天德贵人')
    
    # 月德贵人
    month_de = {'寅': '丙', '卯': '甲', '辰': '壬', '巳': '庚',
                '午': '丙', '未': '甲', '申': '壬', '酉': '庚',
                '戌': '丙', '亥': '甲', '子': '壬', '丑': '庚'}
    if zhi in month_de and month_de[zhi] == gan:
        shensha_list.append('月德贵人')
    
    # 天赦日
    tianshe_days = [
        (('甲', '子'), ('甲', '寅')),
        (('戊', '寅'), ('戊', '申')),
        (('戊', '申'), ('戊', '寅')),
    ]
    if (gan, zhi) == ('甲', '子') or (gan, zhi) == ('戊', '寅') or (gan, zhi) == ('戊', '申'):
        shensha_list.append('天赦日')
    
    # 桃花
    tao_hua = {'寅': '午', '午': '卯', '戌': '卯',
               '巳': '酉', '酉': '午', '丑': '午',
               '申': '子', '子': '酉', '辰': '酉',
               '亥': '卯', '卯': '子', '未': '子'}
    for k, v in tao_hua.items():
        if zhi == v:
            shensha_list.append('桃花')
            break
    
    # 驿马
    yi_ma = {'寅': '申', '午': '申', '戌': '申',
             '巳': '亥', '酉': '亥', '丑': '亥',
             '申': '寅', '子': '寅', '辰': '寅',
             '亥': '巳', '卯': '巳', '未': '巳'}
    for k, v in yi_ma.items():
        if zhi == v:
            shensha_list.append('驿马')
            break
    
    # 天喜
    tian_xi = {'寅': '戌', '卯': '亥', '辰': '子', '巳': '丑',
               '午': '寅', '未': '卯', '申': '辰', '酉': '巳',
               '戌': '午', '亥': '未', '子': '申', '丑': '酉'}
    for k, v in tian_xi.items():
        if zhi == v:
            shensha_list.append('天喜星')
            break
    
    return shensha_list


# ========== 综合查询函数 ==========
def query_date(target_date, hour=None):
    """综合查询某一天的干支、纳音、神煞等全信息"""
    y, m, d = target_date.year, target_date.month, target_date.day
    
    # 年柱
    year_gz = get_year_ganzhi(y, target_date)
    # 月柱
    month_gz = get_month_ganzhi(y, m, d)
    # 日柱
    day_gz = get_day_ganzhi(target_date)
    
    result = {
        '公历': f"{y}年{m}月{d}日",
        '年柱': {'干': year_gz[0], '支': year_gz[1], '纳音': get_nayin(year_gz[0], year_gz[1])},
        '月柱': {'干': month_gz[0], '支': month_gz[1], '纳音': get_nayin(month_gz[0], month_gz[1])},
        '日柱': {'干': day_gz[0], '支': day_gz[1], '纳音': get_nayin(day_gz[0], day_gz[1])},
        '日神煞': get_shensha(day_gz[0], day_gz[1]),
        '黄道黑道': HUANGDAO.get(day_gz[1], ''),
        '黄道吉凶': HUANGDAO_JIXIONG.get(HUANGDAO.get(day_gz[1], ''), ''),
        '地支六冲': LIUCHONG.get(day_gz[1], ''),
        '地支六合': LIUHE.get(day_gz[1], ''),
        '地支三合': SANHE.get(day_gz[1], []),
    }
    
    if hour is not None:
        hour_gz = get_hour_gz(day_gz[0], hour)
        result['时辰'] = {'时': f"{hour}时", '干': hour_gz[0], '支': hour_gz[1],
                        '纳音': get_nayin(hour_gz[0], hour_gz[1])}
        result['时柱'] = hour_gz
    
    return result


def query_hours_by_date(target_date):
    """查询某一天所有时辰的干支"""
    y, m, d = target_date.year, target_date.month, target_date.day
    day_gz = get_day_ganzhi(target_date)
    results = []
    for start_h, end_h, dz_name in SHICHEN_MAP:
        hour_tg, _ = get_hour_gz(day_gz[0], start_h)
        nayin = get_nayin(hour_tg, dz_name)
        results.append({
            '时辰': f"{dz_name}时({start_h:02d}-{end_h:02d}时)",
            '干支': f"{hour_tg}{dz_name}",
            '纳音': nayin
        })
    return results


def format_query_result(result):
    """格式化查询结果为可读文本"""
    lines = []
    lines.append(f"📅 {result['公历']}")
    lines.append("")
    lines.append(f"【四柱】")
    lines.append(f"  年柱：{result['年柱']['干']}{result['年柱']['支']} ({result['年柱']['纳音']})")
    lines.append(f"  月柱：{result['月柱']['干']}{result['月柱']['支']} ({result['月柱']['纳音']})")
    lines.append(f"  日柱：{result['日柱']['干']}{result['日柱']['支']} ({result['日柱']['纳音']})")
    
    if '时辰' in result:
        lines.append(f"  时柱：{result['时辰']['干']}{result['时辰']['支']} ({result['时辰']['纳音']})")
    
    lines.append("")
    lines.append(f"【日神煞】")
    if result['日神煞']:
        lines.append(f"  {'、'.join(result['日神煞'])}")
    else:
        lines.append(f"  无主要吉神")
    
    lines.append("")
    lines.append(f"【黄道吉日】")
    lines.append(f"  黄道：{result['黄道黑道']}（{result['黄道吉凶']}）")
    
    lines.append("")
    lines.append(f"【地支关系】")
    lines.append(f"  六冲：{result['日柱']['支']}冲{result['地支六冲']}")
    lines.append(f"  六合：{result['日柱']['支']}合{result['地支六合']}")
    lines.append(f"  三合：{'、'.join(result['地支三合'])}")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == '--test':
            # 测试
            d = date(2026, 5, 15)
            r = query_date(d, hour=10)
            print(format_query_result(r))
