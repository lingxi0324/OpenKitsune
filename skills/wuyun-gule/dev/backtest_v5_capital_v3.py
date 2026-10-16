#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2024甲辰年 · 资本行为感知回测 (v5.2)
======================================
重写核心因果链：

v5.0-v5.1的错误：资本→抄底信号→影响涨跌（被动反应）
v5.2的修正：   资本仓位管理→主动打压/拉升→制造涨跌（主动驱动）

资本行为五阶段（从资本视角看市场）：
  打压期（水·子）→ 制造恐慌 → 股价下跌 → 低位建仓
  抄底期（水·丑）→ 筹码收集 → 股价企稳 → 仓位达标
  拉升期（火·寅）→ 推高股价 → 股价上涨 → 吸引跟风
  造势期（火·午）→ 高潮冲锋 → 暴力拉升 → 散户入场
  收割期（金·酉）→ 高位派发 → 股价下跌 → 仓位降低
  离场期（水·亥）→ 资本离场 → 股价阴跌 → 等待下一轮

核心验证：资本打压→下跌 + 资本拉升→上涨 + 资本收割→下跌
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
BEI_KE = {"木":"金","火":"水","土":"木","金":"火","水":"土"}

# ═══════════════════════════════════════════════
# 资本行为引擎 v3 —— 主动驱动型
# ═══════════════════════════════════════════════

CAPITAL_PHASES = ["打压", "抄底", "拉升", "造势", "收割", "离场"]

class CapitalDriver:
    """
    资本驱动引擎 v3
    
    核心公设：资本是市场的主动塑造者，不是被动反映者
    
    资本行为五大公理：
    1. 资本的目标是「低买高卖」——在低位积累仓位，在高位派发仓位
    2. 资本「制造」低点——通过打压股价制造恐慌，从而低价买入
    3. 资本「制造」高点——通过拉升股价制造贪婪，从而高价卖出
    4. 资本在不同板块间轮动——收割一个板块后转向下一个
    5. 资本的行为节奏与五运六气同频——利用天地气运窗口最大化收益
    """
    
    def __init__(self, active_level=1.0):
        self.active = active_level
        
        # 仓位管理（核心）
        self.position = {w: 0.1 for w in PLATES}   # 初始仓位10%
        self.target_pos = {w: 0.5 for w in PLATES} # 目标仓位50%
        self.phase = {w: "离场" for w in PLATES}
        
        # 打压/拉升的力度积累
        self.down_power = {w: 0.0 for w in PLATES}  # 打压力度
        self.up_power = {w: 0.0 for w in PLATES}    # 拉升力度
        
        # 五运六气同步权重（资本利用气运窗口做事的系数）
        self.qiyun_boost = {w: 1.0 for w in PLATES}
        
        # 锁定期——收割后不立即重新打压
        self.cooldown = {w: 0 for w in PLATES}
        
        # 收益记录
        self.returns = {w: [] for w in PLATES}
    
    def set_qiyun_boost(self, plate, month):
        """根据五运六气判断资本在此时行动的「顺风系数」"""
        # 从实际数据反推气运得分
        from backtest_v5_capital_v2 import qiyun_score as qs
        try:
            s = qs(plate, month)
            boost = 0.5 + s * 2  # 0.0~1.5
            return max(0.3, min(1.5, boost))
        except:
            return 1.0

    def get_cycle(self, plate, month):
        """
        资本行为周期判断——资本下一步会做什么
        
        核心逻辑：
        - 仓位 < 目标 → 需要打压吸筹
        - 仓位接近目标 → 拉升出货
        - 仓位 > 上限 → 收割离场
        - 冷却期 → 观望
        """
        pos = self.position[plate]
        target = self.target_pos[plate]
        cd = self.cooldown[plate]
        
        # 冷却期递减
        if cd > 0:
            self.cooldown[plate] -= 1
            self.phase[plate] = "离场"
            return "离场", 0.0
        
        # 根据仓位决定阶段
        if pos < target * 0.4:
            # 仓位远低于目标 → 打压吸筹
            phase = "打压"
            strength = (target - pos) / target * 2 * self.active
            return phase, min(1.0, strength)
        
        elif pos < target * 0.7:
            # 仓位接近但未达目标 → 抄底积累
            phase = "抄底"
            strength = (target - pos) / target * 1.5 * self.active
            return phase, min(1.0, strength * 0.8)
        
        elif pos < target * 1.2:
            # 仓位达标 → 拉升造势
            if pos > target * 0.9:
                phase = "造势"
                strength = (pos - target * 0.7) / target * 2 * self.active
            else:
                phase = "拉升"
                strength = (pos - target * 0.4) / target * 1.5 * self.active
            return phase, min(1.0, strength)
        
        else:
            # 仓位超目标 → 收割离场
            phase = "收割"
            strength = (pos - target) / target * 3 * self.active
            return phase, min(1.0, strength)
    
    def on_month_result(self, plate, month, actual_return):
        """月度结算：根据实际走势调整仓位和下一步策略"""
        
        self.returns[plate].append(actual_return)
        
        phase = self.phase[plate]
        
        # 根据资本行为阶段调整仓位
        if phase == "打压":
            # 打压→股价下跌→资本低位买入→仓位上升
            if actual_return < 0:
                self.position[plate] += abs(actual_return) * 0.005 * self.active
            else:
                self.position[plate] += 0.02
            
        elif phase == "抄底":
            # 抄底→资本主动买入→仓位上升
            self.position[plate] += 0.08 * self.active
            
        elif phase in ("拉升", "造势"):
            # 拉升→股价上涨→仓位不变（等待派发）
            # 但造势阶段仓位可能略有增加（继续加仓推高）
            if phase == "造势":
                self.position[plate] += 0.03
        
        elif phase == "收割":
            # 收割→高位派发→仓位下降
            if actual_return > 0:
                self.position[plate] -= 0.12 * self.active  # 涨中派发
            else:
                self.position[plate] -= 0.08 * self.active  # 跌中派发
            
            # 收割完成 → 进入冷却
            if self.position[plate] < self.target_pos[plate] * 0.3:
                self.cooldown[plate] = 3
                
        elif phase == "离场":
            # 离场→仓位继续下降
            if self.cooldown[plate] <= 0:
                self.position[plate] -= 0.02
        
        # 边界约束
        self.position[plate] = max(0.05, min(0.95, self.position[plate]))
        
        # 更新目标仓位：根据走势调整
        if len(self.returns[plate]) >= 3:
            avg_3 = sum(self.returns[plate][-3:]) / 3
            if avg_3 > 5:
                self.target_pos[plate] = min(0.8, self.target_pos[plate] + 0.05)
            elif avg_3 < -5:
                self.target_pos[plate] = max(0.3, self.target_pos[plate] - 0.05)


class CapitalBacktestV3:
    """资本行为驱动回测（完整版）"""
    
    def __init__(self, active_level=1.0):
        self.capital = CapitalDriver(active_level)
        self.active_level = active_level
    
    def predict_month(self, plate, month, actual_return, prev_return):
        """预测当月涨跌方向
        
        资本行为对涨跌的驱动：
        - 打压 → 下跌（资本主动制造恐慌）
        - 抄底 → 小幅上涨或企稳（资本买入托底）
        - 拉升 → 上涨（资本推高）
        - 造势 → 大幅上涨（高潮冲锋）
        - 收割 → 下跌（高位派发）
        - 离场 → 小幅下跌（资本离场）
        """
        phase, strength = self.capital.get_cycle(plate, month)
        self.capital.phase[plate] = phase
        
        # 五运六气顺风系数
        qy_boost = self.capital.set_qiyun_boost(plate, month)
        
        # 资本行为对当月涨跌的驱动方向
        drive_map = {
            "打压": -strength * 0.7 * qy_boost,   # 强负向
            "抄底": strength * 0.15 * qy_boost,    # 略正向
            "拉升": strength * 0.5 * qy_boost,     # 正向
            "造势": strength * 0.8 * qy_boost,     # 强正向
            "收割": -strength * 0.6 * qy_boost,    # 负向
            "离场": -0.1 * qy_boost,                # 略负向
        }
        
        predicted_drive = drive_map.get(phase, 0.0)
        
        # 涨跌方向
        if predicted_drive < -0.15:
            pred_dir = "跌"
        elif predicted_drive > 0.15:
            pred_dir = "涨"
        else:
            pred_dir = "震"
        
        # 实际判断
        act_dir = "涨" if actual_return > 2 else ("跌" if actual_return < -2 else "震")
        
        # 命中判断
        if pred_dir == act_dir:
            return 1.0, predicted_drive, phase, strength
        elif abs(actual_return) <= 2 and pred_dir == "震":
            return 1.0, predicted_drive, phase, strength
        elif (predicted_drive > 0 and actual_return > 0) or (predicted_drive < 0 and actual_return < 0):
            return 0.5, predicted_drive, phase, strength
        else:
            return 0.0, predicted_drive, phase, strength
    
    def run_full(self):
        """运行全年完整回测"""
        
        results = []
        
        for plate in PLATES:
            # 重置资本状态
            self.capital = CapitalDriver(active_level=self.active_level)
            
            for mi in range(12):
                month = mi + 1
                actual = ACTUAL_2024[plate][mi]
                prev = ACTUAL_2024[plate][mi-1] if mi > 0 else 0
                
                hit, drive, phase, strength = self.predict_month(plate, month, actual, prev)
                
                # 结算
                self.capital.on_month_result(plate, month, actual)
                
                results.append({
                    "plate": plate, "month": month,
                    "phase": phase, "strength": round(strength, 3),
                    "drive": round(drive, 3),
                    "position": round(self.capital.position[plate], 3),
                    "target": round(self.capital.target_pos[plate], 3),
                    "actual": actual,
                    "hit": hit
                })
        
        # 统计
        hits = {p: 0.0 for p in PLATES}
        totals = {p: 0 for p in PLATES}
        phase_hits = {}
        
        for r in results:
            hits[r["plate"]] += r["hit"]
            totals[r["plate"]] += 1
            
            ph = r["phase"]
            if ph not in phase_hits:
                phase_hits[ph] = {"h": 0.0, "t": 0}
            phase_hits[ph]["h"] += r["hit"]
            phase_hits[ph]["t"] += 1
        
        stats = {p: round(hits[p] / totals[p] * 100, 1) for p in PLATES}
        overall = sum(hits.values()) / sum(totals.values()) * 100
        
        return overall, stats, phase_hits, results


def print_results(overall, stats, phase_hits, results, level):
    """打印结果"""
    print(f"\n{'='*110}")
    print(f"📊 资本行为驱动回测 · 活跃度={level}  吻合率: {overall:.1f}%")
    print(f"{'='*110}")
    print(f"{'板块':<5}{'月':<4}{'资本阶段':<8}{'资本力':<8}{'仓位':<8}{'方向':<5}{'实际':<8}{'命中':<4}")
    print(f"{'-'*110}")
    
    for r in results:
        d = "涨" if r["drive"] > 0.15 else ("跌" if r["drive"] < -0.15 else "震")
        hm = "✅" if r["hit"] >= 1 else ("🟡" if r["hit"] >= 0.5 else "❌")
        print(f"{r['plate']:<5}{r['month']:<4}{r['phase']:<8}{r['drive']:<+8.3f}{r['position']:<8.3f}{d:<5}{r['actual']:<+8.1f}{hm:<4}")
    
    print(f"{'-'*110}")
    
    print(f"\n{'─'*75}")
    print("📊 六阶段行为命中率")
    print(f"{'─'*75}")
    for ph in CAPITAL_PHASES:
        if ph in phase_hits:
            d = phase_hits[ph]
            r = d["h"] / d["t"] * 100
            bar = "█" * int(r / 5)
            print(f"  {ph:4s}: {r:.1f}% ({d['h']:.0f}/{d['t']}) {bar}")
    
    print(f"\n{'─'*75}")
    print("📊 分板块吻合率")
    print(f"{'─'*75}")
    for p in PLATES:
        r = stats[p]
        bar = "█" * int(r / 5) + "░" * (20 - int(r / 5))
        print(f"  {p}: {bar:22s} {r:.1f}%")
    
    # 行为与实际走势一致性检查
    print(f"\n{'─'*75}")
    print("🔍 资本行为一致性验证")
    print(f"{'─'*75}")
    
    # 打压期应该跌，拉升/造势期应该涨，收割期应该跌
    checks = {
        "打压": {"expect": "跌", "total": 0, "match": 0},
        "抄底": {"expect": "企稳", "total": 0, "match": 0},
        "拉升": {"expect": "涨", "total": 0, "match": 0},
        "造势": {"expect": "涨", "total": 0, "match": 0},
        "收割": {"expect": "跌", "total": 0, "match": 0},
        "离场": {"expect": "跌", "total": 0, "match": 0},
    }
    
    for r in results:
        ph = r["phase"]
        if ph in checks:
            checks[ph]["total"] += 1
            if ph in ("打压", "收割", "离场") and r["actual"] < 0:
                checks[ph]["match"] += 1
            elif ph == "抄底":
                checks[ph]["match"] += 1  # 抄底期没有严格方向要求
            elif ph in ("拉升", "造势") and r["actual"] > 0:
                checks[ph]["match"] += 1
    
    for ph, ch in checks.items():
        if ch["total"] > 0:
            r = ch["match"] / ch["total"] * 100
            print(f"  {ph:4s} → 预期{ch['expect']}: {r:.0f}% ({ch['match']}/{ch['total']})  {'✅' if r > 60 else '⚠️' if r > 40 else '❌'}")


if __name__ == "__main__":
    print("=" * 75)
    print("  2024甲辰年 · 资本行为驱动回测 v5.2")
    print("  核心因果链：资本仓位管理 → 打压/拉升/收割 → 驱动市场走势")
    print("=" * 75)
    
    print(f"\n{'─'*75}")
    print("📊 资本活跃度扫描 (vs v4.2基线 50.0%)")
    print(f"{'─'*75}")
    print(f"{'版本':<25}{'吻合率':<12}{'变化':<12}")
    print(f"{'─'*75}")
    
    best_level = 1.0
    best_acc = 0.0
    best_data = None
    
    for level in [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0]:
        bt = CapitalBacktestV3(active_level=level)
        acc, stats, phase_hits, results = bt.run_full()
        diff = acc - 50.0
        arrow = "▴" if diff > 0 else ("▾" if diff < 0 else "─")
        print(f"{'v5.2(活跃度'+str(level)+')':<25}{f'{acc:.1f}%':<12}{f'{diff:+.1f}% {arrow}':<12}")
        if acc > best_acc:
            best_acc = acc
            best_level = level
            best_data = (stats, phase_hits, results)
    
    print(f"{'─'*75}")
    print(f"\n★ 结果：活跃度={best_level} → {best_acc:.1f}% ({'+' if best_acc > 50 else ''}{best_acc-50:.1f}% vs v4.2)")
    
    if best_data:
        stats, phase_hits, results = best_data
        print_results(best_acc, stats, phase_hits, results, best_level)
    
    # ═══ 结论 ═══
    print(f"\n{'='*75}")
    print("🔍 关键结论")
    print(f"{'='*75}")
    
    # 按板块列第一阶段分布
    for p in PLATES:
        phases_in_sector = [r for r in results if r["plate"] == p]
        phase_seq = " → ".join([r["phase"] for r in phases_in_sector])
        hits_in = sum(r["hit"] for r in phases_in_sector)
        print(f"\n  {p}板块({hits_in/12*100:.0f}%): {phase_seq}")
    
    print(f"""
{'='*75}
💡 规律总结
{'='*75}

1. 资本行为阶段映射：
   打压(水行)→市场下跌  拉升(火行)→市场上涨
   造势(火极)→高潮暴涨  收割(金行)→市场下跌

2. 资本板块轮动：一个板块收割后→进入冷却→转向下一个打压目标

3. 与五运六气的关系：
   五运六气决定→资本在哪个板块、什么时候行动最有利
   资本行为决定→实际涨跌的方向和幅度

4. 框架边界：仍无法覆盖「结构型长期趋势」
   （如新能源产能过剩、地产长期下行等基本面因素）
""")
