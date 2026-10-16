#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五运六气评分引擎 v7.0 — 主客运分步精确匹配版

核心改动（方法一：主客运分步）：
1. 新增 zhuyun_step() 将每月精确匹配到主运五步（初运→终运，73天/步）
2. 新增 keyun_step() 将每月匹配到客运五步（依岁运天干定初运→相生序）
3. 新增主客运生克评分：主同客、客生主、主生客、客克主、主克客
4. 新增主运-板块生克 + 客运-板块生克
5. 保留v6全部层（岁运/司天在泉/客气/季节阻逆/郁发），新增运层作为第0层前置

评分总分 = 运层(0.15权重) + 岁运 + 司天在泉 + 客气 + 季节阻逆 + 郁发
"""
import sys, os, math, json, random, csv
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ========== 核心函数引自wuyun_core（直接内联，避免跨skill路径依赖）==========
TIANGAN = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
DIZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

TIANGAN_HUAYUN_WUXING = {
    '甲':'土', '己':'土', '乙':'金', '庚':'金',
    '丙':'水', '辛':'水', '丁':'木', '壬':'木', '戊':'火', '癸':'火'
}

DIZHI_HUAQI_WUXING = {
    '少阴君火':'火', '少阳相火':'火', '太阴湿土':'土',
    '阳明燥金':'金', '太阳寒水':'水', '厥阴风木':'木'
}

# 天干化运·五行（岁运/中运）
WUYUN_MAP = {
    '甲': {'wuxing': '土', 'nature': '太过', 'strength': 0.9},
    '乙': {'wuxing': '金', 'nature': '不及', 'strength': 0.7},
    '丙': {'wuxing': '水', 'nature': '太过', 'strength': 0.9},
    '丁': {'wuxing': '木', 'nature': '不及', 'strength': 0.7},
    '戊': {'wuxing': '火', 'nature': '太过', 'strength': 0.9},
    '己': {'wuxing': '土', 'nature': '不及', 'strength': 0.7},
    '庚': {'wuxing': '金', 'nature': '太过', 'strength': 0.9},
    '辛': {'wuxing': '水', 'nature': '不及', 'strength': 0.7},
    '壬': {'wuxing': '木', 'nature': '太过', 'strength': 0.9},
    '癸': {'wuxing': '火', 'nature': '不及', 'strength': 0.7},
}

# 年柱
def get_year_ganzhi(year):
    tg = TIANGAN[(year - 4) % 10]
    dz = DIZHI[(year - 4) % 12]
    return tg, dz

# 地支化气（司天在泉）
DIZHI_HUAQI = {
    '子':'少阴君火', '午':'少阴君火', '丑':'太阴湿土', '未':'太阴湿土',
    '寅':'少阳相火', '申':'少阳相火', '卯':'阳明燥金', '酉':'阳明燥金',
    '辰':'太阳寒水', '戌':'太阳寒水', '巳':'厥阴风木', '亥':'厥阴风木',
}

# 客气顺排
KEQI_ORDER = {
    '少阴君火': ['少阴君火','太阴湿土','少阳相火','阳明燥金','太阳寒水','厥阴风木'],
    '太阴湿土': ['太阴湿土','少阳相火','阳明燥金','太阳寒水','厥阴风木','少阴君火'],
    '少阳相火': ['少阳相火','阳明燥金','太阳寒水','厥阴风木','少阴君火','太阴湿土'],
    '阳明燥金': ['阳明燥金','太阳寒水','厥阴风木','少阴君火','太阴湿土','少阳相火'],
    '太阳寒水': ['太阳寒水','厥阴风木','少阴君火','太阴湿土','少阳相火','阳明燥金'],
    '厥阴风木': ['厥阴风木','少阴君火','太阴湿土','少阳相火','阳明燥金','太阳寒水'],
}

# 主气（六步）
ZHUQI = ['厥阴风木', '少阴君火', '少阳相火', '太阴湿土', '阳明燥金', '太阳寒水']

# 客运五步（随天干变化）
KEYUN_WUBU = {
    '甲':'太宫→少商→太羽→少角→太徵',
    '乙':'少商→太羽→少角→太徵→少宫',
    '丙':'太羽→少角→太徵→少宫→太商',
    '丁':'少角→太徵→少宫→太商→少羽',
    '戊':'太徵→少宫→太商→少羽→少角',
    '己':'少宫→太商→少羽→少角→太徵',
    '庚':'太商→少羽→少角→太徵→少宫',
    '辛':'少羽→少角→太徵→少宫→太商',
    '壬':'太角→少徵→太宫→少商→太羽',
    '癸':'少徵→太宫→少商→太羽→少角',
}

# 太少→五行
TAISHAO_WUXING = {
    '太角':'木', '少角':'木', '太徵':'火', '少徵':'火',
    '太宫':'土', '少宫':'土', '太商':'金', '少商':'金', '太羽':'水', '少羽':'水'
}

# 主运五步（太少交替，甲己年太角起/乙庚年少角起...）
ZHUYUN_START = {
    '甲':'太角', '己':'太角', '乙':'少角', '庚':'少角',
    '丙':'太角', '辛':'太角', '丁':'少角', '壬':'少角',
    '戊':'太角', '癸':'太角'
}

ZHUYUN_WUBU = {
    '太角': ['太角','少徵','太宫','少商','太羽'],
    '少角': ['少角','太徵','少宫','太商','少羽'],
}

# 五步主运对应五行（固定序：木→火→土→金→水）
ZHUYUN_WUXING_FIXED = ['木', '火', '土', '金', '水']

# 主运时段（月日）
ZHUYUN_PERIOD = [
    (1, 20, 4, 3),    # 初运 1.20~4.3
    (4, 3, 6, 16),    # 二运 4.3~6.16
    (6, 16, 8, 30),   # 三运 6.16~8.30
    (8, 30, 11, 11),  # 四运 8.30~11.11
    (11, 11, 1, 20),  # 终运 11.11~1.20
]

SHENG = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
KE = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}
PLATES = ['木', '火', '土', '金', '水']

# 客气格局系数
KEQI_COEFF = {
    '顺化': 0.10, '逆化': 0.05, '同气': 0.12,
    '小逆': -0.05, '不和': -0.08, '天刑': -0.08,
}

# 季节阻逆（与v6一致）
SEASON_WUXING = {1:'木', 2:'木', 3:'木', 4:'火', 5:'火', 6:'火',
                 7:'土', 8:'土', 9:'金', 10:'金', 11:'水', 12:'水'}

SEASON_BLOCK = {}
for season_wx in PLATES:
    for plate_wx in PLATES:
        if plate_wx == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.12
        elif SHENG[season_wx] == plate_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.08
        elif KE[season_wx] == plate_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = -0.06
        elif SHENG[plate_wx] == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = 0.06
        elif KE[plate_wx] == season_wx:
            SEASON_BLOCK[(plate_wx, season_wx)] = -0.04

FUXI_CYCLE = {'木': '金', '火': '水', '土': '木', '金': '火', '水': '土'}
FUXI_TARGET = {'金': '木', '水': '火', '木': '土', '火': '金', '土': '水'}

# ========== 方法一：主客运分步 核心函数 ==========

def get_zhuyun_step(month, day=15):
    """
    获取每月（取15号为代表）所属的主运步（0-4）
    0=初运木, 1=二运火, 2=三运土, 3=四运金, 4=终运水
    """
    # 用每月的15日作为代表日期
    if month == 1:
        return 4 if day <= 19 else 0  # 1/20前属上年终运
    if month == 2: return 0
    if month == 3: return 0
    if month == 4: return 0 if day <= 2 else 1  # 4/3前仍属初运
    if month == 5: return 1
    if month == 6: return 1 if day <= 15 else 2  # 6/16前二运，后三运
    if month == 7: return 2
    if month == 8: return 2
    if month == 9: return 3  # 8/30后入四运
    if month == 10: return 3
    if month == 11: return 3 if day <= 10 else 4  # 11/11前四运，后终运
    if month == 12: return 4
    return 2

def get_keyun_wuxing(tiangan, step):
    """
    获取指定年份（天干）的客运五行
    step: 0-4 对应初运→终运
    """
    keyun_str = KEYUN_WUBU.get(tiangan, '')
    if not keyun_str:
        return ''
    keyun_list = [k.strip() for k in keyun_str.split('→')]
    if step < 0 or step >= len(keyun_list):
        return ''
    return TAISHAO_WUXING.get(keyun_list[step], '')

def get_zhuyun_wuxing(tiangan, step):
    """
    获取主运五行（固定序：木火土金水，但太少有年际变化）
    step: 0-4
    注意：主运的五行顺序是固定的（木→火→土→金→水）
    但太少（太过/不及）随年天干变化
    主运对板块的影响只看五行，不关注太少
    """
    if 0 <= step <= 4:
        return ZHUYUN_WUXING_FIXED[step]
    return ''

def compute_zhuyun_keyun_score(plate_wx, year, month):
    """
    主客运分步评分（方法一核心）
    
    三层生克叠加：
    1. 主运 vs 客运（客主加临在运层）
    2. 主运 vs 板块
    3. 客运 vs 板块
    
    Returns: (score, signals)
    """
    tiangan, dizhi = get_year_ganzhi(year)
    
    # 获取主运步和客运步
    step = get_zhuyun_step(month)
    
    # 如果是1月且step=4（在1/20前，属于上一年的终运），取上一年的天干
    if month == 1 and step == 4:
        prev_tiangan, _ = get_year_ganzhi(year - 1)
        zhuyun_wx = get_zhuyun_wuxing(prev_tiangan, step)
        keyun_wx = get_keyun_wuxing(prev_tiangan, step)
    else:
        zhuyun_wx = get_zhuyun_wuxing(tiangan, step)
        keyun_wx = get_keyun_wuxing(tiangan, step)
    
    if not zhuyun_wx or not keyun_wx:
        return 0.0, []
    
    signals = []
    score = 0.0
    
    # ===== 第1层：主运 vs 客运（运层客主加临）= 0.10权重  =====
    if zhuyun_wx == keyun_wx:
        yun_r = 0.06  # 同气：主客合一
        sig = f"运层·同气({zhuyun_wx}={keyun_wx})"
    elif SHENG.get(keyun_wx) == zhuyun_wx:
        yun_r = 0.08  # 客运生主运：客来扶主→顺
        sig = f"运层·客生主({keyun_wx}→{zhuyun_wx})"
    elif SHENG.get(zhuyun_wx) == keyun_wx:
        yun_r = -0.04  # 主运生客运：主泄于客→耗
        sig = f"运层·主生客({zhuyun_wx}→{keyun_wx})"
    elif KE.get(keyun_wx) == zhuyun_wx:
        yun_r = -0.08  # 客运克主运：客来克主→逆
        sig = f"运层·客克主({keyun_wx}克{zhuyun_wx})"
    elif KE.get(zhuyun_wx) == keyun_wx:
        yun_r = -0.02  # 主运克客运：主制客但稍逆
        sig = f"运层·主克客({zhuyun_wx}克{keyun_wx})"
    else:
        yun_r = 0.0
        sig = ""
    
    score += yun_r
    if sig:
        signals.append(sig)
    
    # ===== 第2层：主运 vs 板块 = 0.10权重 =====
    if zhuyun_wx == plate_wx:
        z_p = 0.08  # 同气→板块得分运助
        sig2 = f"主运·同气({zhuyun_wx}同{plate_wx})"
    elif SHENG.get(zhuyun_wx) == plate_wx:
        z_p = 0.06  # 主运生板块→得令
        sig2 = f"主运·生扶({zhuyun_wx}→{plate_wx})"
    elif SHENG.get(plate_wx) == zhuyun_wx:
        z_p = -0.03  # 板块生主运→耗泄
        sig2 = f"主运·耗泄({plate_wx}→{zhuyun_wx})"
    elif KE.get(zhuyun_wx) == plate_wx:
        z_p = -0.06  # 主运克板块→压制
        sig2 = f"主运·克伐({zhuyun_wx}克{plate_wx})"
    elif KE.get(plate_wx) == zhuyun_wx:
        z_p = 0.03  # 板块克主运→板块反制
        sig2 = f"主运·反制({plate_wx}克{zhuyun_wx})"
    else:
        z_p = 0.0
        sig2 = ""
    
    score += z_p
    if sig2:
        signals.append(sig2)
    
    # ===== 第3层：客运 vs 板块 = 0.06权重 =====
    if keyun_wx == plate_wx:
        k_p = 0.06  # 同气→板块得客运助
        sig3 = f"客运·同气({keyun_wx}同{plate_wx})"
    elif SHENG.get(keyun_wx) == plate_wx:
        k_p = 0.05  # 客运生板块→客助
        sig3 = f"客运·生扶({keyun_wx}→{plate_wx})"
    elif SHENG.get(plate_wx) == keyun_wx:
        k_p = -0.03  # 板块生客运→耗散
        sig3 = f"客运·耗散({plate_wx}→{keyun_wx})"
    elif KE.get(keyun_wx) == plate_wx:
        k_p = -0.06  # 客运克板块→客压
        sig3 = f"客运·克伐({keyun_wx}克{plate_wx})"
    elif KE.get(plate_wx) == keyun_wx:
        k_p = 0.03  # 板块克客运→制客
        sig3 = f"客运·制客({plate_wx}克{keyun_wx})"
    else:
        k_p = 0.0
        sig3 = ""
    
    score += k_p
    if sig3:
        signals.append(sig3)
    
    return score, signals


# ========== 从v6沿用的辅助函数 ==========

def sigmoid(x, center=6.0, k=1.2):
    return 1.0 / (1.0 + math.exp(-k * (x - center)))

def get_season_block(plate_wx, month):
    season_wx = SEASON_WUXING.get(month, '')
    if not season_wx:
        return 0.0
    return SEASON_BLOCK.get((plate_wx, season_wx), 0.0)

def get_sitian_zaiquan(year):
    """获取司天在泉"""
    _, dz = get_year_ganzhi(year)
    sitian = DIZHI_HUAQI.get(dz, '')
    zaiquan = ''
    if sitian:
        keqi_seq = KEQI_ORDER.get(sitian, [])
        if len(keqi_seq) > 5:
            zaiquan = keqi_seq[5]
    return sitian, zaiquan

def get_zhuqi_at_step(step):
    """主气六步"""
    if 0 <= step <= 5:
        return ZHUQI[step]
    return ''

def get_keqi_at_step(keqi_seq, step):
    if keqi_seq and 0 <= step <= 5:
        return keqi_seq[step]
    return ''

def get_keqi_sequence(sitian):
    return KEQI_ORDER.get(sitian, [])

def judge_pattern(zhuqi, keqi):
    """判读客主加临格局"""
    zhu_wx = DIZHI_HUAQI_WUXING.get(zhuqi, '')
    ke_wx = DIZHI_HUAQI_WUXING.get(keqi, '')
    if not zhu_wx or not ke_wx:
        return ''
    if zhu_wx == ke_wx:
        return '同气'
    if SHENG.get(ke_wx) == zhu_wx:
        return '顺化'
    if SHENG.get(zhu_wx) == ke_wx:
        return '逆化'
    if KE.get(ke_wx) == zhu_wx:
        return '天刑'
    if KE.get(zhu_wx) == ke_wx:
        return '不和'
    return ''

def get_keqi_monthly(year, month):
    """获取指定年月的主客气格局"""
    step_map = {1:0, 2:0, 3:1, 4:1, 5:2, 6:2, 7:3, 8:3, 9:4, 10:4, 11:5, 12:5}
    step = step_map.get(month, 0)
    zhuqi = get_zhuqi_at_step(step)
    if not zhuqi:
        return None, None
    sitian, _ = get_sitian_zaiquan(year)
    keqi_seq = get_keqi_sequence(sitian)
    if not keqi_seq:
        return None, None
    keqi = get_keqi_at_step(keqi_seq, step)
    if not keqi:
        return None, None
    pattern = judge_pattern(zhuqi, keqi)
    return pattern, keqi


# ========== 核心评分函数 v7.0 ==========

def compute_score_v7(plate_wx, year, month,
                     prev_accumulation=None,
                     eruption_history=None,
                     enable_zhuyun_keyun=True):
    """
    增强评分函数 v7.0 — 主客运分步层
    
    新增 enable_zhuyun_keyun 参数，可开关主客运分步（用于ab对比测试）
    """
    tiangan, dizhi = get_year_ganzhi(year)
    if not tiangan:
        return 0.0, [], {}
    
    wuyun = WUYUN_MAP.get(tiangan, {})
    dayun_wx = wuyun.get("wuxing", "")
    nature = wuyun.get("nature", "平气")
    strength = wuyun.get("strength", 0.5)
    
    # ====== 基础数据 ======
    sitian, zaiquan = get_sitian_zaiquan(year)
    st_wx = DIZHI_HUAQI_WUXING.get(sitian, "")
    zq_wx = DIZHI_HUAQI_WUXING.get(zaiquan, "")
    
    keqi_pattern, keqi_name = get_keqi_monthly(year, month)
    keqi_wx = DIZHI_HUAQI_WUXING.get(keqi_name, "") if keqi_name else ""
    
    if prev_accumulation is None:
        prev_accumulation = {p: 0.0 for p in PLATES}
    if eruption_history is None:
        eruption_history = {}
    
    score = 0.0
    signals = []
    details = {}
    
    # ======================== 第0层（新增）：主客运分步评分 =====================
    if enable_zhuyun_keyun:
        zk_score, zk_signals = compute_zhuyun_keyun_score(plate_wx, year, month)
        # 以0.15权重融入总分（防止运层信号过度主导）
        zk_contrib = zk_score * 0.15
        score += zk_contrib
        details['zhuyun_keyun_raw'] = round(zk_score, 4)
        details['zhuyun_step'] = get_zhuyun_step(month)
        # 获取主运客运五行信息，加入details
        step = get_zhuyun_step(month)
        tiangan_y, _ = get_year_ganzhi(year)
        if month == 1 and step == 4:
            tiangan_y, _ = get_year_ganzhi(year - 1)
        details['zhuyun_wx'] = get_zhuyun_wuxing(tiangan_y, step)
        details['keyun_wx'] = get_keyun_wuxing(tiangan_y, step)
        signals.extend([f"运层·{s}" for s in zk_signals])
        signals.append(f"运层合计{zk_contrib:+.4f}")
    
    # ======================== 第1层：岁运（与v6一致）====================
    keqi_mod = 1.0
    if keqi_pattern:
        qi_c = KEQI_COEFF.get(keqi_pattern, 0.0)
        if qi_c > 0.05:
            keqi_mod = 1.3
        elif qi_c < -0.05:
            keqi_mod = 0.3
        elif qi_c < 0:
            keqi_mod = 0.6
    
    if dayun_wx and nature == "太过":
        tai_cfg = {
            'self':     {'coeff': 0.22, 'cond': lambda pw: pw == dayun_wx},
            'fuxi':     {'coeff': 0.25, 'cond': lambda pw: pw == FUXI_CYCLE.get(dayun_wx, '')},
            'fuxi_k':   {'coeff': -0.35, 'cond': lambda pw: pw == FUXI_TARGET.get(FUXI_CYCLE.get(dayun_wx, ''), '')},
            'sheng':    {'coeff': 0.10, 'cond': lambda pw: SHENG.get(dayun_wx) == pw},
            'ke':       {'coeff': -0.12, 'cond': lambda pw: KE.get(dayun_wx) == pw},
        }
        for key, cfg in tai_cfg.items():
            if cfg['cond'](plate_wx):
                val = strength * cfg['coeff'] * keqi_mod
                score += val
                signals.append(f"岁运太过-{key}-调{keqi_mod:.1f}{val:+.3f}")
                break
    
    elif dayun_wx and nature == "不及":
        bu_cfg = [
            ('self', lambda pw: pw == dayun_wx, strength * (-0.15) * (1.0 if keqi_mod > 0.8 else 0.6)),
            ('sheng_cheng', lambda pw: KE.get(pw) == dayun_wx, strength * (-0.18)),
            ('wu', lambda pw: SHENG.get(pw) == dayun_wx, strength * 0.08),
        ]
        for key, cond, val in bu_cfg:
            if cond(plate_wx):
                score += val
                signals.append(f"岁运不及-{key}{val:+.3f}")
                break
    
    # ======================== 第2层：司天在泉 =====================
    if st_wx:
        st_config = {
            '同气':   (1.0,  lambda pw: pw == st_wx),
            '生扶':   (0.8,  lambda pw: SHENG.get(st_wx) == pw),
            '被生':   (0.4,  lambda pw: SHENG.get(pw) == st_wx),
            '被克':   (-0.6, lambda pw: KE.get(st_wx) == pw),
            '所胜':   (-0.4, lambda pw: KE.get(pw) == st_wx),
            '所不胜': (-0.2, lambda pw: st_wx == SHENG.get(KE.get(pw, ''), '')),
        }
        for rel, (coeff, cond) in st_config.items():
            if cond(plate_wx):
                sw = 1.0 - 0.3 * sigmoid(month, 3, 1.5)
                val = strength * coeff * 0.10 * sw
                score += val
                signals.append(f"司天{rel}{val:+.3f}")
                details['sitian'] = rel
                break
    
    if zq_wx:
        zw = sigmoid(month, center=6.5, k=1.2)
        if plate_wx == zq_wx:
            rel, coeff = '同气', 1.0
        elif SHENG.get(zq_wx) == plate_wx:
            rel, coeff = '在泉生板块', 0.6
        elif SHENG.get(plate_wx) == zq_wx:
            rel, coeff = '板块生在泉', 0.4
        elif KE.get(zq_wx) == plate_wx:
            rel, coeff = '在泉克板块', -0.5
        elif KE.get(plate_wx) == zq_wx:
            rel, coeff = '板块克在泉', -0.3
        else:
            rel, coeff = None, 0.0
        if rel:
            val = strength * coeff * 0.10 * zw
            score += val
            signals.append(f"在泉{rel}{val:+.3f}")
            details['zaiquan'] = rel
    
    # ======================== 第3层：季节阻逆 =====================
    sb = get_season_block(plate_wx, month)
    if abs(sb) > 0.01:
        score += sb
        signals.append(f"季节阻逆{sb:+.3f}")
    
    # ======================== 第4层：客气五行细化 =====================
    if keqi_wx and plate_wx:
        if keqi_wx == plate_wx:
            qi_val = 0.08
            signals.append(f"客气-同气{qi_val:+.3f}")
        elif SHENG.get(keqi_wx) == plate_wx:
            qi_val = 0.06
            signals.append(f"客气-生扶{qi_val:+.3f}")
        elif SHENG.get(plate_wx) == keqi_wx:
            qi_val = -0.04
            signals.append(f"客气-耗泄{qi_val:+.3f}")
        elif KE.get(keqi_wx) == plate_wx:
            qi_val = -0.07
            signals.append(f"客气-克伐{qi_val:+.3f}")
        elif KE.get(plate_wx) == keqi_wx:
            qi_val = 0.03
            signals.append(f"客气-板块制{qi_val:+.3f}")
        else:
            qi_val = 0.0
        if abs(qi_val) > 0.001:
            score += qi_val
            details['keqi_wuxing'] = keqi_wx
    
    # ======================== 郁发积累/释放 =====================
    if keqi_pattern and plate_wx:
        qi_c = KEQI_COEFF.get(keqi_pattern, 0.0)
        if qi_c < 0:
            inc = abs(qi_c) * 0.18
            prev_accumulation[plate_wx] = min(1.0, prev_accumulation.get(plate_wx, 0.0) + inc)
            signals.append(f"复气积累+{inc:.3f}(总{prev_accumulation[plate_wx]:.3f})")
    
    accum = prev_accumulation.get(plate_wx, 0.0)
    last_eruption = eruption_history.get(plate_wx, 0)
    
    if accum > 0.06 and (month - last_eruption) >= 2:
        release = accum * 0.55
        score += release
        signals.append(f"郁发释放+{release:.3f}(积累{accum:.3f})")
        prev_accumulation[plate_wx] = accum * 0.60
        eruption_history[plate_wx] = month
    elif accum > 0.001:
        mp = month / 12.0
        pen = accum * 0.08 * mp
        score -= pen
        signals.append(f"积累抑制-{pen:.3f}")
    
    # ======================== 均值回归 + 太过反制 =====================
    mr = score * 0.015
    score -= mr
    if abs(mr) > 0.001:
        signals.append(f"均值回归-{mr:.3f}")
    
    if score > 0.30:
        anti = (score - 0.30) * 0.25
        score -= anti
        signals.append(f"太过反制-{anti:.3f}")
    elif score < -0.30:
        anti = (score + 0.30) * 0.25
        score -= anti
        signals.append(f"不及反制+{abs(anti):.3f}")
    
    return max(-0.8, min(0.8, score)), signals, details


# ========== 兼容接口 ==========
def compute_corrected_score(plate_wx, year, month,
                            prev_accumulation=None,
                            eruption_history=None,
                            enable_zhuyun_keyun=True):
    score, signals, _ = compute_score_v7(plate_wx, year, month,
                                          prev_accumulation, eruption_history,
                                          enable_zhuyun_keyun)
    return score, signals


# ========== 相关系数计算 ==========
def calc_pearsonr(scores, actuals):
    n = len(scores)
    if n < 3:
        return 0.0
    sx, sy = sum(scores), sum(actuals)
    sxx = sum(x*x for x in scores)
    syy = sum(y*y for y in actuals)
    sxy = sum(scores[i]*actuals[i] for i in range(n))
    denom = (n*sxx - sx*sx) * (n*syy - sy*sy)
    if denom <= 0:
        return 0.0
    return (n*sxy - sx*sy) / (denom ** 0.5 + 1e-10)

def bootstrap_ci(scores, actuals, n_iter=5000, n_resample=None):
    n = len(scores)
    if n < 3:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    if n_resample is None:
        n_resample = n
    r_orig = calc_pearsonr(scores, actuals)
    r_samples = []
    for _ in range(n_iter):
        idx = [random.randint(0, n-1) for _ in range(n_resample)]
        rs = [scores[i] for i in idx]
        ra = [actuals[i] for i in idx]
        r_samples.append(calc_pearsonr(rs, ra))
    r_samples.sort()
    ci_low = r_samples[int(n_iter * 0.025)]
    ci_high = r_samples[int(n_iter * 0.975)]
    pos_pct = sum(1 for r in r_samples if r > 0) / n_iter * 100
    median_r = r_samples[n_iter // 2]
    return r_orig, median_r, ci_low, ci_high, pos_pct


# ========== 数据加载与验证 ==========
def find_data_file():
    """自动搜索wuxing_monthly_summary.csv"""
    candidates = [
        'wuxing_monthly_summary.csv',
        os.path.join(SCRIPT_DIR, 'wuxing_monthly_summary.csv'),
        os.path.join(SCRIPT_DIR, '..', '..', '..', '..', '我的文件夹', '灵汐档案', '五行-板块', 'wuxing_monthly_summary.csv'),
        os.path.join(SCRIPT_DIR, '..', 'wuxing_monthly_summary.csv'),
        '我的文件夹/灵汐档案/五行-板块/wuxing_monthly_summary.csv',
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def load_monthly_data(csv_path=None):
    if csv_path is None:
        csv_path = find_data_file()
    if not csv_path or not os.path.exists(csv_path):
        print(f"[错误] 找不到数据文件: {csv_path}")
        return None
    print(f"[加载] {csv_path}")
    data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    print(f"[加载] 共{len(data)}行数据")
    return data

def run_validation(data, label="v7验证", enable_zk=True):
    """跑全样本验证"""
    results = {}
    for wx in PLATES:
        scores = []
        actuals = []
        for row in data:
            try:
                year = int(row.get('year', 0))
                month = int(row.get('month', 0))
            except (ValueError, KeyError):
                continue
            col = f"avg_{wx}" if f"avg_{wx}" in row else wx
            actual = float(row.get(col, 0))
            s, _ = compute_corrected_score(wx, year, month, {}, {}, enable_zhuyun_keyun=enable_zk)
            if abs(actual) > 0.001 and abs(actual) < 50:
                scores.append(s)
                actuals.append(actual)
        n = len(scores)
        r, r_m, ci_l, ci_h, pct = bootstrap_ci(scores, actuals, n_iter=5000)
        results[wx] = {
            'n': n, 'r': round(r, 4), 'median_r': round(r_m, 4),
            'ci_95': [round(ci_l, 4), round(ci_h, 4)],
            'pos_pct': round(pct, 1),
            'significant': ci_l > 0 or ci_h < 0,
        }
    return results

def print_results(results, label="验证结果"):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"{'五行':>4} {'样本':>6} {'r':>8} {'中位数':>8} {'95% CI':>16} {'正值%':>8} {'显著':>6}")
    print("-"*60)
    for wx in PLATES:
        r = results[wx]
        ci = f"[{r['ci_95'][0]:.3f}, {r['ci_95'][1]:.3f}]"
        sig = "✅" if r['significant'] else "❌"
        print(f"{wx:>4} {r['n']:>6} {r['r']:>8.4f} {r['median_r']:>8.4f} {ci:>16} {r['pos_pct']:>7.1f}% {sig:>6}")


# ========== 主入口 ==========
if __name__ == '__main__':
    # 参数解析
    enable_zk = True
    csv_path = None
    for arg in sys.argv[1:]:
        if arg == '--no-zk':
            enable_zk = False
        elif not arg.startswith('--'):
            csv_path = arg
    
    data = load_monthly_data(csv_path)
    if not data:
        print("用法: python corrected_scoring_v7.py [--no-zk] [csv_path]")
        sys.exit(1)
    
    # v7 启用主客运分步
    v7_on = run_validation(data, "v7.0 主客运分步 ON", enable_zk=True)
    print_results(v7_on, "v7.0 主客运分步 ON")
    
    # v7 关闭主客运分步（相当于v6基线）
    v7_off = run_validation(data, "v7.0 主客运分步 OFF (v6基线)", enable_zk=False)
    print_results(v7_off, "v7.0 主客运分步 OFF (v6基线)")
    
    # 对比
    print(f"\n{'='*60}")
    print(f"  版本对比: v6基线 vs v7主客运分步")
    print(f"{'='*60}")
    print(f"{'五行':>4} {'v6 r':>8} {'v7 r':>8} {'v6中位数':>10} {'v7中位数':>10} {'v6正值%':>8} {'v7正值%':>8} {'变化':>8}")
    print("-"*60)
    for wx in PLATES:
        r6 = v7_off[wx]['r']
        r7 = v7_on[wx]['r']
        m6 = v7_off[wx]['median_r']
        m7 = v7_on[wx]['median_r']
        p6 = v7_off[wx]['pos_pct']
        p7 = v7_on[wx]['pos_pct']
        delta = r7 - r6
        print(f"{wx:>4} {r6:>8.4f} {r7:>8.4f} {m6:>10.4f} {m7:>10.4f} {p6:>7.1f}% {p7:>7.1f}% {delta:>+8.4f}")
    
    # 土板块留一年验证（仅v7）
    print(f"\n{'='*60}")
    print(f"  土板块·留一年交叉验证 (v7主客运分步)")
    print(f"{'='*60}")
    years = sorted(set(int(r.get('year', 0)) for r in data if int(r.get('year', 0)) > 2010))
    for target_year in years:
        train = [r for r in data if int(r.get('year', 0)) != target_year]
        test = [r for r in data if int(r.get('year', 0)) == target_year]
        scores, actuals = [], []
        for row in test:
            try:
                year = int(row.get('year', 0))
                month = int(row.get('month', 0))
            except (ValueError, KeyError):
                continue
            col = f"avg_土" if "avg_土" in row else "土"
            actual = float(row.get(col, 0))
            if abs(actual) > 0.001 and abs(actual) < 50:
                s, _ = compute_corrected_score('土', year, month, {}, {}, enable_zhuyun_keyun=True)
                scores.append(s)
                actuals.append(actual)
        if len(scores) >= 3:
            r = calc_pearsonr(scores, actuals)
            print(f"  留{target_year}: 土板块 r={r:.4f} (n={len(scores)})")
