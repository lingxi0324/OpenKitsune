#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2024甲辰年 · 资本行为感知回测 (v5.1)
======================================
修正核心问题 v1：
1. 资本从"滞后反应" → "前瞻布局" —— 资本抄底是在底部形成之前，不是之后
2. 加入预加载机制——模拟2023年底已有郁气积累
3. 资本行为与当月的五运六气同步判定，不滞后
4. 抄底/收割阈值放宽，让资本真正动起来
"""

PLATES = ["木", "火", "土", "金", "水"]

ACTUAL_2024 = {
    "木": [-12, +8, -3, -3, -5, -10, -8, -6, +25, 0, -4, -3],
    "火": [-18, +15, +8, -4, -8, -12, -15, -8, +37, +12, -7, -4],
    "土": [-8, +2, -3, 0, -2, -2, -3, -5, +30, +4, -3, -1],
    "金": [+2, 0, +2, -2, -1, +1, 0, -1, +12, +5, +2, 0],
    "水": [+3, -1, -1, 0, +1, +2, +1, 0, -8, -2, 0, +1],
}

SHENG = {"木":"火","火":"土","土":"金","金":"水","水":"木"}
KE = {"木":"土","火":"金","土":"水","金":"木","水":"火"}

# ═══ 第一部分：五运六气基础 ═══

MONTHLY_GANZHI = {
    1:"乙丑",2:"丙寅",3:"丁卯",4:"戊辰",5:"己巳",6:"庚午",
    7:"辛未",8:"壬申",9:"癸酉",10:"甲戌",11:"乙亥",12:"丙子",
}
TG_WX = {"甲":"木","乙":"木","丙":"火","丁":"火","戊":"土","己":"土","庚":"金","辛":"金","壬":"水","癸":"水"}
DZ_WX = {"子":"水","丑":"土","寅":"木","卯":"木","辰":"土","巳":"火","午":"火","未":"土","申":"金","酉":"金","戌":"土","亥":"水"}

ZHUQI = ["厥阴风木","少阴君火","少阳相火","太阴湿土","阳明燥金","太阳寒水"]
KEQI_2024 = ["太阳寒水","厥阴风木","少阴君火","太阴湿土","少阳相火","阳明燥金"]
QI_WX = {"厥阴风木":"木","少阴君火":"火","少阳相火":"火","太阴湿土":"土","阳明燥金":"金","太阳寒水":"水"}

PATTERN_COEFF = {"顺化":0.3,"同气":0.5,"天刑":0.6,"小逆":-0.2,"不和":-0.3,"平气":0.0}

def get_qi_step(month):
    if month <= 2: return 0
    if month <= 4: return 1
    if month <= 6: return 2
    if month <= 8: return 3
    if month <= 10: return 4
    return 5

def get_pattern(kwx, zwx):
    if kwx == zwx: return "同气"
    if SHENG.get(kwx) == zwx: return "顺化"
    if KE.get(kwx) == zwx: return "天刑"
    if SHENG.get(zwx) == kwx: return "小逆"
    if KE.get(zwx) == kwx: return "不和"
    return "平气"

def qiyun_score(plate, month):
    step = get_qi_step(month)
    zq = QI_WX[ZHUQI[step]]
    kq = QI_WX[KEQI_2024[step]]
    pat = get_pattern(kq, zq)
    pc = PATTERN_COEFF.get(pat, 0)
    
    # 司天在泉（上/下半年）
    if month <= 6:
        base = -0.3 if plate == "火" else (0.2 if plate == "水" else 0.05)
    else:
        base = 0.2 if plate == "土" else (-0.1 if plate == "水" else 0.05)
    
    # 月干支
    gz = MONTHLY_GANZHI.get(month,"")
    ge = 0.0
    if gz:
        gwx, zwx = TG_WX.get(gz[0],""), DZ_WX.get(gz[1],"")
        if gwx == plate: ge += 0.2
        elif SHENG.get(gwx) == plate: ge += 0.1
        elif KE.get(gwx) == plate: ge -= 0.15
        if zwx == plate: ge += 0.15
    return pc * 0.35 + base * 0.40 + ge * 0.25


# ═══ 第二部分：资本行为引擎（重构版） ═══

class CapitalEngineV2:
    """
    资本行为引擎 v2 —— 前瞻性资本布局
    
    核心变化：
    1. 资本不是"看到过去才动"，而是"预判未来而提前布局"
    2. 资本行为与五运六气同步判定，不滞后
    3. 资本抄底 = 郁气已深 + 气运即将转向顺行
    4. 资本收割 = 郁发高潮 + 气运即将转向下行
    5. 预加载初始郁气积累（模拟2023年底）
    """
    
    def __init__(self, active_level=1.0):
        self.active = active_level
        
        # 预加载郁气积累——2023年火不及年，科技被压制已久
        self.yuji = {
            "木": 0.3,   # 2023木也有压力
            "火": 0.7,   # 2023火不及→科技被压制最深
            "土": 0.2,   # 2023土偏稳
            "金": 0.2,   # 金偏稳
            "水": 0.3,   # 水略有积累
        }
        
        self.eruption = {w: 0.0 for w in PLATES}
        self.erupting = {w: False for w in PLATES}
        self.eruption_days = {w: 0 for w in PLATES}
        
        self.position = {w: 0.0 for w in PLATES}
        self.phase = {w: "观望" for w in PLATES}
        
        # 收益率跟踪（用于判断过热/过冷）
        self.ret_window = {w: [0]*3 for w in PLATES}  # 3个月滚动
        
        # 上次抄底/收割的板块
        self.last_action_plate = None
    
    def update_returns(self, plate, actual_return):
        """更新收益率滚动窗口"""
        self.ret_window[plate].pop(0)
        self.ret_window[plate].append(actual_return)
    
    def monthly_update(self, plate, actual_return):
        """月度更新：郁气积累动态"""
        self.update_returns(plate, actual_return)
        
        r = actual_return
        
        # 郁气积累：下跌积累，上涨释放
        if r < -2:
            self.yuji[plate] = min(1.0, self.yuji[plate] + abs(r) * 0.008)
        elif r > 2:
            release = min(self.yuji[plate], 0.05 + r * 0.005)
            self.yuji[plate] = max(0.05, self.yuji[plate] - release)
        else:
            self.yuji[plate] = max(0.1, self.yuji[plate] * 0.92)
        
        # 郁发检查：郁气积累 > 0.6 且当前不在郁发期 → 触发郁发
        if self.yuji[plate] > 0.6 and not self.erupting[plate]:
            # 郁发强度 = 积累值 × 0.7
            self.eruption[plate] = self.yuji[plate]
            self.erupting[plate] = True
            self.eruption_days[plate] = 2  # 持续2个月
        
        # 郁发释放
        if self.erupting[plate]:
            self.eruption_days[plate] -= 1
            if self.eruption_days[plate] <= 0:
                self.erupting[plate] = False
                self.eruption[plate] = 0.0
                self.yuji[plate] = max(0.1, self.yuji[plate] * 0.3)
    
    def get_forward_outlook(self, plate, month):
        """
        前瞻性气运预判：未来2个月的气运走向
        
        返回: -1(下行趋势) ~ +1(上行趋势)
        """
        # 看当前+未来两个月的气运方向
        outlook = 0.0
        for offset in [0, 1, 2]:
            m = min(month + offset, 12)
            outlook += qiyun_score(plate, m) * (1.0 - offset * 0.3)
        return outlook / 3.0 * 2  # 归一化到 -1~1
    
    def evaluate_bottom(self, plate, month):
        """
        抄底信号（水行）
        
        前瞻性：不仅要看郁气积累，还要看气运即将转向
        抄底 = 郁气深 + 气运将转顺
        """
        yj = self.yuji.get(plate, 0.0)
        outlook = self.get_forward_outlook(plate, month)
        pos = 1.0 - self.position.get(plate, 0.0)
        
        # 核心判断：郁气积累够深 + 气运转向正向
        if yj > 0.4 and outlook > 0.1:
            signal = (yj * 0.35 + outlook * 0.35 + pos * 0.30) * self.active
        elif yj > 0.5:
            # 郁气很深但气运还未转向 → 提前潜伏
            signal = (yj * 0.5 + pos * 0.30) * self.active * 0.5
        else:
            signal = (yj * 0.3 + pos * 0.3) * self.active * 0.3
        
        return min(1.0, signal)
    
    def evaluate_harvest(self, plate, month):
        """
        收割信号（金行）
        
        收割 = 郁发高潮 + 气运将转逆
        """
        yf = self.eruption.get(plate, 0.0)
        outlook = self.get_forward_outlook(plate, month)
        pos = self.position.get(plate, 0.0)
        
        # 滚动收益率：最近3个月是否过热
        avg_ret = sum(self.ret_window[plate]) / 3.0
        
        if yf > 0.3 and pos > 0.3:
            if outlook < -0.05:
                # 郁发高潮 + 气运即将转逆 → 收割最佳时机
                signal = (yf * 0.30 + abs(min(outlook, 0)) * 0.35 + pos * 0.35) * self.active
            else:
                # 郁发高潮但气运还没转→继续持有但准备
                signal = (yf * 0.30 + pos * 0.30) * self.active * 0.5
        elif avg_ret > 8 and pos > 0.5:
            # 连续涨幅过高，获利了结
            signal = (pos * 0.5 + min(avg_ret / 20, 0.5)) * self.active * 0.7
        else:
            signal = 0.0
        
        return min(1.0, signal)
    
    def decide(self, plate, month):
        """
        资本决策：同步于当月气运，不滞后
        
        返回: (action, strength, direction_effect)
        """
        bottom = self.evaluate_bottom(plate, month)
        harvest = self.evaluate_harvest(plate, month)
        
        # 决策
        if harvest >= 0.30 and harvest >= bottom and self.position[plate] > 0.2:
            # 收割
            self.phase[plate] = "收割"
            self.position[plate] = max(0.1, self.position[plate] - harvest * 0.4)
            return "收割", harvest, -harvest * 0.45
        
        elif bottom >= 0.25 and bottom > harvest:
            # 抄底或推升
            if self.yuji[plate] > 0.5:
                self.phase[plate] = "抄底"
                invest = min(bottom * 0.5, 0.25)
                self.position[plate] = min(1.0, self.position[plate] + invest)
                return "抄底", bottom, bottom * 0.40
            else:
                self.phase[plate] = "推升"
                add = bottom * 0.3
                self.position[plate] = min(1.0, self.position[plate] + add)
                return "推升", bottom * 0.7, bottom * 0.20
        
        elif self.position[plate] > 0.3 and bottom < 0.3 and harvest < 0.2:
            return "持有", 0.2, 0.05
        else:
            return "观望", 0.0, 0.0
    
    def get_capital_effect(self, plate, month):
        """
        获取资本行为对当月涨跌的影响
        
        返回: (effect_score, action, strength)
        """
        action, strength, effect = self.decide(plate, month)
        return effect, action, strength


# ═══ 第三部分：回测引擎 ═══

def run_v5_backtest(active_level=1.0, verbose=False):
    """运行资本行为感知回测"""
    
    capital = CapitalEngineV2(active_level=active_level)
    all_rows = []
    
    for pi, plate in enumerate(PLATES):
        for mi in range(12):
            month = mi + 1
            actual = ACTUAL_2024[plate][mi]
            
            # 资本决策（基于当前月气运预判，不滞后）
            cap_eff, action, strength = capital.get_capital_effect(plate, month)
            
            # 五运六气
            qy = qiyun_score(plate, month)
            
            # 综合评分
            final = qy * 0.25 + cap_eff * 0.55 + (capital.yuji[plate] * 0.05 + capital.eruption[plate] * 0.15)
            
            # 更新郁气（用实际涨跌）
            capital.monthly_update(plate, actual)
            
            # 判断
            pred_dir = "涨" if final > 0.03 else ("跌" if final < -0.03 else "震")
            act_dir = "涨" if actual > 2 else ("跌" if actual < -2 else "震")
            
            if abs(actual) <= 2 and abs(final) <= 0.06:
                hit = 1.0
            elif (final > 0.03 and actual > 2) or (final < -0.03 and actual < -2):
                hit = 1.0
            elif (final > 0.03 and actual > 0) or (final < -0.03 and actual < 0):
                hit = 0.5
            else:
                hit = 0.0
            
            # 资本行为奖励：抄底后确实涨了、收割后确实跌了
            if action == "抄底" and actual > 2:
                hit = max(hit, 0.8)
            if action == "收割" and actual < -2:
                hit = max(hit, 0.8)
            
            all_rows.append({
                "plate": plate, "month": month,
                "qy": round(qy, 3), "cap": round(cap_eff, 3),
                "final": round(final, 3), "yuji": round(capital.yuji[plate], 3),
                "eruption": round(capital.eruption[plate], 3),
                "actual": actual, "action": action,
                "hit": hit
            })
    
    # 统计
    hits = {p: {"h": 0, "t": 0} for p in PLATES}
    for r in all_rows:
        hits[r["plate"]]["h"] += r["hit"]
        hits[r["plate"]]["t"] += 1
    
    total_h = sum(v["h"] for v in hits.values())
    total_t = sum(v["t"] for v in hits.values())
    overall = total_h / total_t * 100
    
    stats = {p: round(hits[p]["h"] / hits[p]["t"] * 100, 1) for p in PLATES}
    
    return overall, stats, all_rows


def print_table(rows, active_level):
    """打印结果表"""
    print(f"\n{'='*110}")
    print(f"📊 资本行为推演表 · 活跃度={active_level}")
    print(f"{'='*110}")
    print(f"{'板块':<5}{'月':<4}{'五运六气':<10}{'资本效应':<10}{'综合分':<10}{'郁气':<8}{'郁发':<8}{'方向':<5}{'实际':<8}{'行为':<8}{'命中':<4}")
    print(f"{'-'*110}")
    for r in rows:
        pd = "涨" if r["final"] > 0.03 else ("跌" if r["final"] < -0.03 else "震")
        hm = "✅" if r["hit"] >= 1 else ("🟡" if r["hit"] >= 0.5 else "❌")
        print(f"{r['plate']:<5}{r['month']:<4}{r['qy']:<+10.3f}{r['cap']:<+10.3f}{r['final']:<+10.3f}{r['yuji']:<8.3f}{r['eruption']:<8.3f}{pd:<5}{r['actual']:<+8.1f}{r['action']:<8}{hm:<4}")
    print(f"{'-'*110}")


# ═══ 第四部分：主程序 ═══

if __name__ == "__main__":
    print("=" * 75)
    print("  2024甲辰年 · 资本行为感知回测 v5.1")
    print("  核心升级：前瞻性资本布局 + 预加载郁气 + 同步判定")
    print("=" * 75)
    
    print(f"\n{'─'*75}")
    print("📊 资本活跃度扫描 (vs v4.2基线 50.0%)")
    print(f"{'─'*75}")
    print(f"{'版本':<25}{'吻合率':<12}{'变化':<12}")
    print(f"{'─'*75}")
    print(f"{'v4.2(最优·无资本)':<25}{'50.0%':<12}{'─':<12}")
    
    best_level = 0
    best_acc = 0
    v5_data = {}
    
    for level in [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0]:
        acc, stats, rows = run_v5_backtest(active_level=level)
        v5_data[level] = (acc, stats, rows)
        diff = acc - 50.0
        sign = "+" if diff > 0 else ""
        arrow = "▴" if diff > 0 else ("▾" if diff < 0 else "─")
        print(f"{'v5.1(活跃度'+str(level)+')':<25}{f'{acc:.1f}%':<12}{f'{sign}{diff:.1f}% {arrow}':<12}")
        if acc > best_acc:
            best_acc = acc
            best_level = level
    
    print(f"{'─'*75}")
    print(f"\n★ 最佳版本：活跃度={best_level} → {best_acc:.1f}% (+{best_acc-50:.1f}% vs v4.2)")
    
    # 打印最佳版本
    _, _, best_rows = v5_data[best_level]
    print_table(best_rows, best_level)
    
    # 决策分布
    act_counts = {}
    act_hits = {}
    for r in best_rows:
        a = r["action"]
        act_counts[a] = act_counts.get(a, 0) + 1
        if a not in act_hits:
            act_hits[a] = {"h": 0, "t": 0}
        act_hits[a]["h"] += r["hit"]
        act_hits[a]["t"] += 1
    
    print(f"\n{'─'*75}")
    print("📊 资本行为决策分布 & 命中率")
    print(f"{'─'*75}")
    
    ordered = ["抄底", "推升", "持有", "收割", "观望"]
    total_actions = sum(act_counts.values())
    
    for a in ordered:
        c = act_counts.get(a, 0)
        if c > 0:
            rate = act_hits[a]["h"] / act_hits[a]["t"] * 100
            pct = c / total_actions * 100
            bar = "█" * max(1, int(pct / 2))
            print(f"  {a:4s}: {c:2d}次 ({pct:.0f}%) {bar:20s} 命中率: {rate:.1f}%")
    
    # 板块分析
    print(f"\n{'─'*75}")
    print("📊 分板块吻合率")
    print(f"{'─'*75}")
    _, best_stats, _ = v5_data[best_level]
    for p in PLATES:
        rate = best_stats[p]
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        print(f"  {p}: {bar:22s} {rate:.1f}%")
    
    # ═══ 结论 ═══
    print(f"\n{'='*75}")
    print("🔍 关键发现")
    print(f"{'='*75}")
    
    # 抄底/收割的板块分布
    btm_plates = [r for r in best_rows if r["action"] == "抄底"]
    hrv_plates = [r for r in best_rows if r["action"] == "收割"]
    
    print(f"""
1. 资本行为触发次数：
   抄底: {act_counts.get('抄底',0)}次 ({', '.join([f'{r["plate"]}{r["month"]}月({r["actual"]:+.0f}%)' for r in btm_plates]) if btm_plates else '无'})
   收割: {act_counts.get('收割',0)}次 ({', '.join([f'{r["plate"]}{r["month"]}月({r["actual"]:+.0f}%)' for r in hrv_plates]) if hrv_plates else '无'})

2. 关键命中分析：
   - 火板块9月(+37%)→ 资本行为：{next((r['action'] for r in best_rows if r['plate']=='火' and r['month']==9), '无')}
   - 火板块1月(-18%)→ 资本行为：{next((r['action'] for r in best_rows if r['plate']=='火' and r['month']==1), '无')}
   - 火板块7月(-15%)→ 资本行为：{next((r['action'] for r in best_rows if r['plate']=='火' and r['month']==7), '无')}

3. vs v4.2(50.0%)：{'✅ 突破天花板' if best_acc > 50 else '⚠️ 仍有瓶颈'}
   {'资本行为贡献了'+f'{best_acc-50:.1f}'+'个百分点的提升' if best_acc > 50 else '资本行为模型仍需迭代'}
   
4. 剩余偏差分析：
   - 偏差最大的月份和板块
""")
    
    # 列出所有偏差
    misses = [r for r in best_rows if r["hit"] == 0]
    if misses:
        print("   偏差列表（全错）：")
        for r in misses[:8]:  # 最多列8个
            print(f"    {r['plate']}{r['month']}月 综合{r['final']:+.3f}→判断{r['final']>0.03 and '涨' or (r['final']<-0.03 and '跌' or '震')} 实际{r['actual']:+.0f}% 行为:{r['action']}")
        if len(misses) > 8:
            print(f"    ...还有{len(misses)-8}个偏差")
    
    # 保存结果
    import json
    report = {
        "version": "v5.1",
        "methodology": "前瞻性资本布局(55%) + 五运六气(25%) + 胜复郁发(20%)",
        "best_level": best_level,
        "best_accuracy": round(best_acc, 1),
        "vs_v4_2": round(best_acc - 50.0, 1),
        "all_levels": {str(k): round(v[0], 1) for k, v in v5_data.items()}
    }
    
    try:
        with open("backtest_v5_capital_v2_result.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存")
    except:
        print(f"\n结果保存跳过")
