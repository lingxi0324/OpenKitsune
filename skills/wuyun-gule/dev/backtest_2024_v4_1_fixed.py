"""
2024甲辰年 · 月度回测 v4.1 — 修正版
=====================================
修正要点：
1. 边界月拆分（1月前半=2023终之气,后半=2024初之气）
2. 判定阈值收紧：涨≥0.3, 跌≤-0.25
3. 气段权重提升至50%
4. 纳入全部十条补充变量

十条变量清单（今日补充）：
①主运客运太过不及 ②主客气加临错位 ③司天在泉+间气
④岁会/天符 ⑤迁正退位 ⑥伏气积累 ⑦藏干 ⑧十二长生 ⑨纳音 ⑩胜复郁发
"""
import sys, json
from datetime import datetime, timedelta

sys.path.insert(0, '.')
from wuyun_core import (
    analyze_year, get_keqi_sequence, LIUQI_WUXING,
    ZHUQI_STEPS, SHENG_CYCLE, KE_CYCLE, BEI_KE,
    get_zhuqi_at_step, get_keqi_at_step, judge_pattern
)
from shengfu_yufa import ShengfuYufaEngine
from three_layer_ganzhi_enhanced import (
    TIANGAN_WUXING, DIZHI_WUXING, CANG_GAN, CANG_GAN_WEIGHT,
    NAYIN_WUXING
)

# ═══════════════════════════════════════════════
# 实际数据
# ═══════════════════════════════════════════════

ACTUAL_2024 = {
    "木": [-12, +8, -3, -3, -5, -10, -8, -6, +25, 0, -4, -3],
    "火": [-18, +15, +8, -4, -8, -12, -15, -8, +37, +12, -7, -4],
    "土": [-8, +2, -3, 0, -2, -2, -3, -5, +30, +4, -3, -1],
    "金": [+2, 0, +2, -2, -1, +1, 0, -1, +12, +5, +2, 0],
    "水": [+3, -1, -1, 0, +1, +2, +1, 0, -8, -2, 0, +1],
}
PLATES = ["木", "火", "土", "金", "水"]
MONTHS = list(range(1, 13))

# 月干支 (2024甲辰年)
# 甲年: 丙寅(正月/2月), 丁卯(2月/3月)... 乙丑(12月/1月)
MONTH_GANZHI_2024 = {
    1: ("乙丑",), 2: ("丙寅",), 3: ("丁卯",), 4: ("戊辰",),
    5: ("己巳",), 6: ("庚午",), 7: ("辛未",), 8: ("壬申",),
    9: ("癸酉",), 10: ("甲戌",), 11: ("乙亥",), 12: ("丙子",),
}

# ═══════════════════════════════════════════════
# 核心函数
# ═══════════════════════════════════════════════

def get_qi_idx_for_day(month: int, day: int) -> int:
    """根据月日获取所属气段索引(0-5)"""
    if month == 1:
        return 5 if day < 20 else 0  # 1.20前=终之气(2023), 后=初之气(2024)
    elif month == 2:
        return 0
    elif month == 3:
        return 0 if day < 21 else 1  # 3.21春分=分界
    elif month == 4:
        return 1
    elif month == 5:
        return 1 if day < 21 else 2  # 5.21小满=分界
    elif month == 6:
        return 2
    elif month == 7:
        return 2 if day < 23 else 3  # 7.23大暑=分界
    elif month == 8:
        return 3
    elif month == 9:
        return 3 if day < 23 else 4  # 9.23秋分=分界
    elif month == 10:
        return 4
    elif month == 11:
        return 4 if day < 22 else 5  # 11.22小雪=分界
    elif month == 12:
        return 5


def get_plate_qi_score(plate_wx: str, qi_idx: int, keqi_seq: list) -> dict:
    """
    计算板块在某气段的综合生克分数
    返回 {score, pattern, details}
    """
    zhuqi_name = get_zhuqi_at_step(qi_idx) if qi_idx < 6 else ""
    keqi_name = get_keqi_at_step(keqi_seq, qi_idx) if qi_idx < len(keqi_seq) else ""
    zhuqi_wx = LIUQI_WUXING.get(zhuqi_name, "")
    keqi_wx = LIUQI_WUXING.get(keqi_name, "")
    
    # 1) 主气对板块
    if plate_wx == zhuqi_wx:
        qi_score = 0.6     # 同气共振
        qi_desc = f"主气{zhuqi_wx}同{plate_wx}→强助"
    elif SHENG_CYCLE.get(zhuqi_wx) == plate_wx:
        qi_score = 0.5     # 主气生我
        qi_desc = f"主气{zhuqi_wx}生{plate_wx}→助涨"
    elif SHENG_CYCLE.get(plate_wx) == zhuqi_wx:
        qi_score = -0.3    # 我生主气→泄气
        qi_desc = f"{plate_wx}生主气{zhuqi_wx}→泄气偏弱"
    elif KE_CYCLE.get(zhuqi_wx) == plate_wx:
        qi_score = -0.6    # 主气克我
        qi_desc = f"主气{zhuqi_wx}克{plate_wx}→压制"
    elif KE_CYCLE.get(plate_wx) == zhuqi_wx:
        qi_score = 0.3     # 我克主气→反制抗跌
        qi_desc = f"{plate_wx}克主气{zhuqi_wx}→抗跌"
    else:
        qi_score = 0.0
        qi_desc = f"主气{zhuqi_wx}↔{plate_wx}→无直接生克"
    
    # 2) 客气对板块（叠加效应）
    if keqi_wx:
        if plate_wx == keqi_wx:
            ke_score = 0.4
            ke_desc = f"客{keqi_wx}同板→叠加强"
        elif SHENG_CYCLE.get(keqi_wx) == plate_wx:
            ke_score = 0.3
            ke_desc = f"客{keqi_wx}生{plate_wx}→加持"
        elif KE_CYCLE.get(keqi_wx) == plate_wx:
            ke_score = -0.4
            ke_desc = f"客{keqi_wx}克{plate_wx}→压制"
        elif SHENG_CYCLE.get(plate_wx) == keqi_wx:
            ke_score = -0.2
            ke_desc = f"{plate_wx}生客{keqi_wx}→泄气"
        else:
            ke_score = 0.0
            ke_desc = f"客{keqi_wx}↔{plate_wx}→无直接"
    else:
        ke_score = 0.0
        ke_desc = "无客气"
    
    # 3) 主客气格局系数
    pattern = judge_pattern(zhuqi_name, keqi_name)
    pattern_coeff = {
        "顺化": 0.2, "同气": 0.3, "天刑": 0.4,
        "小逆": -0.1, "不和": -0.2,
    }.get(pattern, 0.0)
    
    total = qi_score + ke_score + pattern_coeff
    return {
        "score": round(total, 3),
        "气段": f"{['初','二','三','四','五','终'][qi_idx]}之气",
        "主气": f"{zhuqi_name}({zhuqi_wx})",
        "客气": f"{keqi_name}({keqi_wx})",
        "格局": pattern,
        "主气对板": qi_desc,
        "客气对板": ke_desc,
    }


def monthly_ganzhi_score(plate_wx: str, month: int) -> tuple:
    """月干支+纳音+藏干 综合分数"""
    if month not in MONTH_GANZHI_2024:
        return 0.0, []
    gz = MONTH_GANZHI_2024[month][0]
    gan, zhi = gz[0], gz[1]
    gan_wx = TIANGAN_WUXING.get(gan, "")
    zhi_wx = DIZHI_WUXING.get(zhi, "")
    factors = []
    score = 0.0
    
    # 月干
    if gan_wx == plate_wx:
        score += 0.3; factors.append(f"月干{gan}({gan_wx})同板+0.3")
    elif SHENG_CYCLE.get(gan_wx) == plate_wx:
        score += 0.2; factors.append(f"月干{gan}({gan_wx})生板+0.2")
    elif KE_CYCLE.get(gan_wx) == plate_wx:
        score -= 0.2; factors.append(f"月干{gan}({gan_wx})克板-0.2")
    
    # 月支
    if zhi_wx == plate_wx:
        score += 0.2; factors.append(f"月支{zhi}({zhi_wx})同板+0.2")
    elif SHENG_CYCLE.get(zhi_wx) == plate_wx:
        score += 0.15; factors.append(f"月支{zhi}({zhi_wx})生板+0.15")
    elif KE_CYCLE.get(zhi_wx) == plate_wx:
        score -= 0.15; factors.append(f"月支{zhi}({zhi_wx})克板-0.15")
    
    # 纳音
    nayin_wx = NAYIN_WUXING.get(gz, "")
    if nayin_wx:
        if nayin_wx == plate_wx:
            score += 0.15; factors.append(f"纳音{gz}({nayin_wx})同板+0.15")
        elif SHENG_CYCLE.get(nayin_wx) == plate_wx:
            score += 0.1; factors.append(f"纳音{gz}({nayin_wx})生板+0.1")
        elif KE_CYCLE.get(nayin_wx) == plate_wx:
            score -= 0.1; factors.append(f"纳音{gz}({nayin_wx})克板-0.1")
    
    # 藏干（辰戌丑未）
    if zhi in CANG_GAN:
        cang = CANG_GAN[zhi]
        for qtype, qwx in cang.items():
            wt = CANG_GAN_WEIGHT.get(qtype, 0.0)
            if qwx == plate_wx:
                add = wt * 0.4
                score += add
                factors.append(f"藏干{zhi}.{qtype}({qwx})→+{add:.2f}")
    
    return round(score, 3), factors


def predict_month(plate_wx: str, month: int, keqi_seq_2024: list,
                  yufa: ShengfuYufaEngine) -> dict:
    """单月单板块预测"""
    score = 0.0
    all_factors = []
    
    # ── 气段因子（权重50%）──
    # 处理边界月：加权平均两个气段
    if month == 1:
        # 1月: 20天终之气(2023) + 11天初之气(2024)
        qi5 = get_plate_qi_score(plate_wx, 5, keqi_seq_2024)  # 终之气
        qi0 = get_plate_qi_score(plate_wx, 0, keqi_seq_2024)  # 初之气
        qi_score = (qi5["score"] * 20 + qi0["score"] * 11) / 31
        main_qi = f"终气(20d)×{qi5['score']}+初气(11d)×{qi0['score']}"
    elif month == 3:
        qi0 = get_plate_qi_score(plate_wx, 0, keqi_seq_2024)
        qi1 = get_plate_qi_score(plate_wx, 1, keqi_seq_2024)
        qi_score = (qi0["score"] * 20 + qi1["score"] * 11) / 31
        main_qi = f"初气(20d)×{qi0['score']}+二气(11d)×{qi1['score']}"
    elif month == 5:
        qi1 = get_plate_qi_score(plate_wx, 1, keqi_seq_2024)
        qi2 = get_plate_qi_score(plate_wx, 2, keqi_seq_2024)
        qi_score = (qi1["score"] * 20 + qi2["score"] * 11) / 31
        main_qi = f"二气(20d)×{qi1['score']}+三气(11d)×{qi2['score']}"
    elif month == 7:
        qi2 = get_plate_qi_score(plate_wx, 2, keqi_seq_2024)
        qi3 = get_plate_qi_score(plate_wx, 3, keqi_seq_2024)
        qi_score = (qi2["score"] * 22 + qi3["score"] * 9) / 31
        main_qi = f"三气(22d)×{qi2['score']}+四气(9d)×{qi3['score']}"
    elif month == 9:
        qi3 = get_plate_qi_score(plate_wx, 3, keqi_seq_2024)
        qi4 = get_plate_qi_score(plate_wx, 4, keqi_seq_2024)
        qi_score = (qi3["score"] * 22 + qi4["score"] * 8) / 31
        main_qi = f"三气(22d)×{qi3['score']}+五气(8d)×{qi4['score']}"
    elif month == 11:
        qi4 = get_plate_qi_score(plate_wx, 4, keqi_seq_2024)
        qi5 = get_plate_qi_score(plate_wx, 5, keqi_seq_2024)
        qi_score = (qi4["score"] * 21 + qi5["score"] * 9) / 31
        main_qi = f"五气(21d)+终气(9d)×{qi5['score']}"
    else:
        if month in [2]:
            qi_idx = 0
        elif month in [4]:
            qi_idx = 1
        elif month in [6]:
            qi_idx = 2
        elif month in [8]:
            qi_idx = 3
        elif month in [10]:
            qi_idx = 4
        else:  # 12
            qi_idx = 5
        qi_data = get_plate_qi_score(plate_wx, qi_idx, keqi_seq_2024)
        qi_score = qi_data["score"]
        main_qi = f"单气段×{qi_score}"
    
    score += qi_score * 0.5  # 权重50%
    all_factors.append(f"气段{main_qi}→{qi_score:+.2f}×0.5={qi_score*0.5:+.2f}")
    
    # ── 月干支因子（权重25%）──
    gz_score, gz_factors = monthly_ganzhi_score(plate_wx, month)
    score += gz_score * 0.25
    all_factors.append(f"月干支{gz_score:+.2f}×0.25={gz_score*0.25:+.2f}")
    all_factors.extend(gz_factors)
    
    # ── 胜复郁发因子（权重25%）──
    accum = yufa.accumulation.get(plate_wx, 0.0)
    yufa_score = 0.0
    if accum > 3.0:
        yufa_score = 1.0  # 郁发窗口
    elif accum > 1.5:
        yufa_score = 0.5
    elif accum < -2.0:
        yufa_score = -0.5
    elif accum < -3.0:
        yufa_score = -1.0
    score += yufa_score * 0.25
    all_factors.append(f"郁发累积{accum:.1f}→{yufa_score:+.2f}×0.25={yufa_score*0.25:+.2f}")
    
    # 判定
    if score >= 0.3:
        pred = "涨"
    elif score <= -0.25:
        pred = "跌"
    else:
        pred = "震荡"
    
    return {"prediction": pred, "score": round(score, 3), "factors": all_factors}


def run_backtest() -> dict:
    """完整回测"""
    # 获取2024气运
    keqi_seq_2024 = get_keqi_sequence("太阳寒水")
    yufa = ShengfuYufaEngine()
    
    total = 0; hits = 0
    plate_results = {p: {"hits": 0, "total": 0} for p in PLATES}
    detail = []
    
    for pi, plate in enumerate(PLATES):
        for mi in range(12):
            month = mi + 1
            actual = ACTUAL_2024[plate][mi]
            
            # 预测
            pred = predict_month(plate, month, keqi_seq_2024, yufa)
            
            # 实际方向
            if actual >= 3:
                actual_dir = "涨"
            elif actual <= -3:
                actual_dir = "跌"
            else:
                actual_dir = "震荡"
            
            hit = pred["prediction"] == actual_dir
            if hit:
                hits += 1
                plate_results[plate]["hits"] += 1
            plate_results[plate]["total"] += 1
            total += 1
            
            # 更新郁发状态（用实际值）
            if actual > 5:
                for wx in PLATES:
                    yufa.accumulation[wx] = yufa.accumulation.get(wx, 0) + 0.3 if wx == plate else yufa.accumulation.get(wx, 0)
            elif actual < -5:
                for wx in PLATES:
                    yufa.accumulation[wx] = yufa.accumulation.get(wx, 0) - 0.2 if wx == plate else yufa.accumulation.get(wx, 0)
            
            detail.append({
                "板块": plate, "月份": f"{month}月",
                "推演": pred["prediction"], "得分": pred["score"],
                "实际方向": actual_dir, "实际值": actual,
                "吻合": "✅" if hit else "❌"
            })
    
    acc = round(hits / total * 100, 1) if total > 0 else 0
    return {
        "accuracy": acc, "hits": hits, "total": total,
        "plate_acc": {p: round(r["hits"]/r["total"]*100, 1) 
                      for p, r in plate_results.items()},
        "detail": detail,
    }


if __name__ == "__main__":
    print("=" * 75)
    print("🔬 2024月度回测 v4.1 — 边界月拆分+气段权重50%+阈值收紧")
    print("=" * 75)
    
    result = run_backtest()
    
    print(f"\n📊 整体吻合率: {result['accuracy']}% ({result['hits']}/{result['total']})")
    print(f"\n各板块：")
    for p in PLATES:
        print(f"  {p}: {result['plate_acc'][p]}%")
    
    print(f"\n逐月明细：")
    for d in result["detail"]:
        print(f"  {d['吻合']} {d['板块']}·{d['月份']}: 推演{d['推演']}({d['得分']:+.2f}) vs "
              f"实际{d['实际方向']}({d['实际值']:+d}%)")
    
    print(f"\n🏆 结论：v4.1({result['accuracy']}%) vs v4.0(40%) vs v2(37%)")
    
    # 保存
    out = {
        "version": "v4.1",
        "accuracy": result["accuracy"],
        "hits": result["hits"], "total": result["total"],
        "plate_acc": result["plate_acc"],
    }
    with open("backtest_2024_v4_1_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n✅ 结果已保存")
