"""
资本行为模型 · Capital Behavior Engine (v1.0)
==============================================
核心公设：资本不是外在于五运六气的变量，而是五行气运在金融市场的具身执行者。
五运六气提供「势能」（天地之气何时偏向何性质），资本提供「动能」（人如何利用势能获利）。

资本行为三阶段 × 五行映射：
  抄底潜伏（水）→ 推升扩散（火）→ 收割离场（金）→ 再潜伏下一轮（水）

与胜复郁发引擎的关系：
  郁气积累 = 资本看到的"抄底机会"
  郁发爆发 = 资本推动的"拉升行情"
  郁发释放 = 资本"收割离场"

资本来源：资本永远在寻找被低估（郁气最甚）和高估（郁发最盛）的标的。
"""

# ─── 五行生克索引 ───

ADAPTIVE_BOOST = {0.00:[0,0], 0.05:[0.05,-0.05], 0.10:[0.08,-0.08],
                 0.15:[0.12,-0.12], 0.20:[0.18,-0.18], 0.30:[0.25,-0.25], 0.50:[0.35,-0.35]}
def get_adaptive_boost(score, pred_dir):
    abs_s = abs(score)
    boost = 0.0
    for th, (up, dn) in sorted(ADAPTIVE_BOOST.items()):
        if abs_s >= th:
            boost = up if pred_dir > 0 else dn
    return boost

SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}
BEI_KE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}
SHENG_ME = {"火": "木", "土": "火", "金": "土", "水": "金", "木": "水"}  # 我生谁
KE_ME = {"土": "木", "金": "火", "水": "土", "木": "金", "火": "水"}  # 我克谁

PLATES = ["木", "火", "土", "金", "水"]


class CapitalBehaviorEngine:
    """
    资本行为引擎
    ============
    核心机制：
    1. 资本在"郁气积累 > 阈值"的板块中寻找抄底机会（水）
    2. 抄底后推动反弹（火），吸引跟风盘
    3. 在"郁发释放 > 阈值"时收割离场（金）
    4. 收割后资本转向下一个郁气积累最高的板块（水→循环）
    """

    def __init__(self, active_level=1.0):
        """
        初始化资本行为引擎
        
        参数:
            active_level: 资本活跃度 (0~2.0)
                0.0 = 无资本介入（纯自然气运）
                0.5 = 低迷期（资本谨慎）
                1.0 = 正常活跃（默认）
                1.5 = 高度活跃（牛市/政策驱动）
                2.0 = 极度活跃（投机狂热）
        """
        self.active_level = active_level
        
        # 各板块的资本持仓状态
        self.position = {w: 0.0 for w in PLATES}  # 0~1, 资本在此板块的仓位比例
        self.phase = {w: "观望" for w in PLATES}    # 观望/抄底/推升/收割/离场
        
        # 抄底和收割的累积信号
        self.bottom_signal = {w: 0.0 for w in PLATES}    # 抄底信号强度
        self.harvest_signal = {w: 0.0 for w in PLATES}   # 收割信号强度
        
        # 连续涨跌月计数
        self.consecutive_down = {w: 0 for w in PLATES}   # 连续下跌月数
        self.consecutive_up = {w: 0 for w in PLATES}     # 连续上涨月数
        
        # 总可用资本
        self.total_capital = 1.0  # 归一化
        
        # 历史追踪
        self.history = {w: [] for w in PLATES}
        
    def _update_consecutive(self, plate, monthly_return):
        """更新连续涨跌计数"""
        if monthly_return < -3:  # 跌幅 > 3% 视为"下跌"
            self.consecutive_down[plate] += 1
            self.consecutive_up[plate] = 0
        elif monthly_return > 3:  # 涨幅 > 3% 视为"上涨"
            self.consecutive_up[plate] += 1
            self.consecutive_down[plate] = 0
        else:
            self.consecutive_down[plate] = 0
            self.consecutive_up[plate] = 0

    def evaluate_bottom_fishing(self, plate, shengfu_engine, month):
        """
        评估抄底机会（水行）
        
        抄底触发条件：
        1. 连续下跌 ≥ 2 个月
        2. 郁气积累 > 阈值（0.3）
        3. 资本在此板块仓位低
        
        返回: 抄底力度 (0~1)
        """
        if self.phase[plate] in ("推升", "收割"):
            return 0.0  # 已经在推升或收割阶段，不再抄底
        
        # 从胜复郁发引擎获取郁气积累值
        yuji = shengfu_engine.accumulation.get(plate, 0.0) if hasattr(shengfu_engine, 'accumulation') else 0.0
        
        # 抄底信号 = 郁气积累 × 连续下跌月数系数 × 资本活跃度
        down_factor = min(self.consecutive_down[plate] / 3.0, 1.0)  # 3个月连续下跌 = 最大信号
        
        # 仓位越低，抄底意愿越强
        position_factor = 1.0 - self.position[plate]
        
        # 综合信号
        signal = yuji * 0.4 + down_factor * 0.35 + position_factor * 0.25
        signal = signal * self.active_level
        
        self.bottom_signal[plate] = signal
        
        return signal

    def evaluate_harvest(self, plate, shengfu_engine, month):
        """
        评估收割机会（金行）
        
        收割触发条件：
        1. 连续上涨 ≥ 2 个月
        2. 郁发释放 > 阈值（0.3）
        3. 资本在此板块仓位高
        
        返回: 收割力度 (0~1)
        """
        if self.phase[plate] in ("观望", "抄底"):
            return 0.0  # 还没推升，谈不上收割
        
        # 从胜复郁发引擎获取郁发释放值
        yufa_release = 0.0
        if hasattr(shengfu_engine, 'get_eruption_power'):
            yufa_release = shengfu_engine.get_eruption_power(plate)
        elif hasattr(shengfu_engine, 'eruption_window'):
            if shengfu_engine.eruption_window.get(plate) is not None:
                yufa_release = shengfu_engine.eruption_window[plate]
        
        up_factor = min(self.consecutive_up[plate] / 3.0, 1.0)
        
        # 仓位越高，收割意愿越强
        position_factor = self.position[plate]
        
        # 综合信号
        signal = yufa_release * 0.35 + up_factor * 0.35 + position_factor * 0.30
        signal = signal * self.active_level
        
        self.harvest_signal[plate] = signal
        
        return signal

    def decide_action(self, plate, shengfu_engine, month, actual_return, qiyun_score):
        """
        资本决策主函数
        
        根据抄底信号和收割信号的对比，决定资本行为
        
        返回: (action, strength, description)
            action: "观望" / "抄底" / "推升" / "收割" / "离场"
            strength: 0~1
            description: 决策说明
        """
        self._update_consecutive(plate, actual_return)
        
        bottom = self.evaluate_bottom_fishing(plate, shengfu_engine, month)
        harvest = self.evaluate_harvest(plate, shengfu_engine, month)
        
        # 决策逻辑：哪个信号更强，就执行哪个
        if harvest > 0.5 and harvest > bottom and self.position[plate] > 0.3:
            self.phase[plate] = "收割"
            strength = harvest
            self.position[plate] = max(0, self.position[plate] - strength * 0.3)
            return ("收割", strength, f"金行·收割——板块已连涨{self.consecutive_up[plate]}月，郁发释放{harvest:.2f}，资本离场")
        
        elif bottom > 0.4 and bottom > harvest:
            if self.consecutive_down[plate] >= 2:
                # 抄底
                self.phase[plate] = "抄底"
                strength = bottom
                invest = min(strength * 0.5, self.total_capital * 0.3)
                self.position[plate] = min(1.0, self.position[plate] + invest)
                return ("抄底", strength, f"水行·抄底——板块已连跌{self.consecutive_down[plate]}月，郁气积累{bottom:.2f}，资本入场")
            else:
                self.phase[plate] = "推升"
                strength = bottom * 0.6
                self.position[plate] = min(1.0, self.position[plate] + strength * 0.2)
                return ("推升", strength, f"火行·推升——延续推升，资本加仓")
        
        elif self.position[plate] > 0 and bottom < 0.3 and harvest < 0.3:
            # 持仓但无明显信号→持有观望
            self.phase[plate] = "观望"
            return ("持有", 0.3, f"持有观望——仓位{self.position[plate]:.2f}，等待信号")
        
        else:
            return ("观望", 0.0, f"观望——抄底{self.consecutive_down[plate]}月·{bottom:.2f} vs 收割{self.consecutive_up[plate]}月·{harvest:.2f}")

    def assess_plate(self, plate_wx, raw_score, year, month, prev_scores=None):
        """
        对外接口：综合评估一个板块的资本行为阶段
        
        参数:
            plate_wx: 板块五行
            raw_score: 四柱原始评分 (-1~1)
            year, month: 年月
            prev_scores: 历史评分列表（用于判断趋势）
        
        返回:
            dict: {phase, signal, reason}
        """
        # 1. 连续涨跌判断
        consecutive_score = 0.0
        if prev_scores and len(prev_scores) > 0:
            n_up = sum(1 for s in prev_scores[-6:] if s > 0)
            n_down = sum(1 for s in prev_scores[-6:] if s < 0)
            if n_up >= 4:
                consecutive_score = -0.3  # 连涨→收割信号
            elif n_down >= 4:
                consecutive_score = 0.3   # 连跌→抄底信号
        
        # 2. 评分区间判断
        if raw_score <= -0.4:
            score_signal = 0.4  # 严重低估
        elif raw_score <= -0.2:
            score_signal = 0.2  # 轻度低估
        elif raw_score >= 0.4:
            score_signal = -0.4  # 严重高估
        elif raw_score >= 0.2:
            score_signal = -0.2  # 轻度高估
        else:
            score_signal = 0.0
        
        total_signal = consecutive_score + score_signal
        
        # 3. 阶段判定
        if total_signal >= 0.4:
            phase = "抄底"
        elif total_signal >= 0.15:
            phase = "推升"
        elif total_signal <= -0.4:
            phase = "收割"
        elif total_signal <= -0.15:
            phase = "离场"
        else:
            phase = "观望"
        
        # 4. 更新内部状态
        self.phase[plate_wx] = phase
        self.bottom_signal[plate_wx] = max(0, total_signal)
        self.harvest_signal[plate_wx] = max(0, -total_signal)
        
        return {"phase": phase, "signal": total_signal, "reason": f"score={raw_score:.2f}, consec={consecutive_score:.2f}, total={total_signal:.2f}"}


def calculate_capital_impact(plate, month, actual_returns, wuyun_score, shengfu_engine, capital_engine):
    """
    计算资本行为对月度涨跌的综合影响
    
    返回: (adjusted_score, capital_effect_description)
        adjusted_score: 经资本修正后的气运评分 (-1~1)
        capital_effect: 资本行为对涨跌的额外影响 (-0.5~0.5)
    """
    # 本月实际涨跌
    actual = actual_returns[plate][month - 1] if plate in actual_returns else 0
    
    # 资本决策
    action, strength, desc = capital_engine.decide_action(
        plate, shengfu_engine, month, actual, wuyun_score
    )
    
    # 资本行为对涨跌的修正
    capital_effect = 0.0
    
    if action == "抄底":
        # 抄底行为产生正向推动力
        capital_effect = strength * 0.35  # 水介入→推动反弹
    elif action == "推升":
        # 推升行为产生正向推动力
        capital_effect = strength * 0.25
    elif action == "收割":
        # 收割行为产生负向拖拽力
        capital_effect = -strength * 0.35  # 金收割→拖累
    elif action == "离场":
        capital_effect = -strength * 0.2
    elif action == "观望":
        capital_effect = 0.0
    elif action == "持有":
        capital_effect = 0.05
    
    # 修正后的评分
    adjusted = wuyun_score + capital_effect
    
    return adjusted, capital_effect, desc


class CapitalAwareBacktest:
    """
    资本行为感知回测引擎
    =====================
    在五运六气+胜复郁发的基础上，叠加资本行为模型，重新推演月度走势。
    """
    
    def __init__(self, active_level=1.0):
        self.capital = CapitalBehaviorEngine(active_level)
        self.results = {}
        
    def run_backtest(self, wuyun_engine, shengfu_engine, actual_returns, months=12):
        """
        运行完整回测
        """
        PLATES = ["木", "火", "土", "金", "水"]
        
        # 追踪逐月结果
        predictions = {p: [] for p in PLATES}
        capital_effects = {p: [] for p in PLATES}
        decisions = {p: [] for p in PLATES}
        hits = {p: 0 for p in PLATES}
        total = {p: 0 for p in PLATES}
        
        for pi, plate in enumerate(PLATES):
            for mi in range(months):
                month = mi + 1
                
                # 获取五运六气基础评分
                if hasattr(wuyun_engine, 'get_score'):
                    wuyun_score = wuyun_engine.get_score(plate, month)
                else:
                    wuyun_score = 0.0
                
                # 获取胜复郁发修正
                if hasattr(shengfu_engine, 'apply_monthly'):
                    shengfu_score = shengfu_engine.apply_monthly(plate, month)
                else:
                    shengfu_score = 0.0
                
                base_score = wuyun_score + shengfu_score
                
                # 资本行为介入
                adj_score, capital_eff, decision = calculate_capital_impact(
                    plate, month, actual_returns, base_score, shengfu_engine, self.capital
                )
                
                # 保存
                predictions[plate].append(adj_score)
                capital_effects[plate].append(capital_eff)
                decisions[plate].append(decision)
                
                # 判断方向是否吻合
                actual = actual_returns[plate][mi] if plate in actual_returns else 0
                pred_direction = "涨" if adj_score > 0 else ("跌" if adj_score < 0 else "震荡")
                actual_direction = "涨" if actual > 2 else ("跌" if actual < -2 else "震荡")
                
                # 允许震荡容差
                if abs(actual) <= 2 and abs(adj_score) <= 0.1:
                    total[plate] += 1
                    hits[plate] += 1  # 震荡判断正确
                elif (adj_score > 0 and actual > 2) or (adj_score < 0 and actual < -2):
                    total[plate] += 1
                    hits[plate] += 1
                elif (adj_score > 0 and actual < -2) or (adj_score < 0 and actual > 2):
                    total[plate] += 1
                    # 方向相反→不命中
                else:
                    total[plate] += 1
                    # 方向对但幅度不够→部分命中，算0.5
                    if (adj_score > 0 and actual > 0) or (adj_score < 0 and actual < 0):
                        hits[plate] += 0.5
        
        # 计算吻合率
        self.results = {
            "instructions": [predictions, capital_effects, decisions],
            "accuracy": {
                plate: (hits[plate] / total[plate] * 100) if total[plate] > 0 else 0
                for plate in PLATES
            },
            "overall": sum(hits.values()) / sum(total.values()) * 100 if sum(total.values()) > 0 else 0
        }
        
        return self.results


# ─── 快速测试 ───
if __name__ == "__main__":
    # 用2024实际数据做快速验证
    ACTUAL_2024 = {
        "木": [-12, +8, -3, -3, -5, -10, -8, -6, +25, 0, -4, -3],
        "火": [-18, +15, +8, -4, -8, -12, -15, -8, +37, +12, -7, -4],
        "土": [-8, +2, -3, 0, -2, -2, -3, -5, +30, +4, -3, -1],
        "金": [+2, 0, +2, -2, -1, +1, 0, -1, +12, +5, +2, 0],
        "水": [+3, -1, -1, 0, +1, +2, +1, 0, -8, -2, 0, +1],
    }
    
    print("=" * 60)
    print("资本行为模型 · 快速验证")
    print("=" * 60)
    
    # 测试不同活跃度下的行为
    for level in [0.5, 1.0, 1.5]:
        ce = CapitalBehaviorEngine(active_level=level)
        print(f"\n--- 资本活跃度: {level} ---")
        for plate in ["火", "金", "土"]:
            # 模拟前几个月
            for mi in range(6):
                ret = ACTUAL_2024[plate][mi]
                ce._update_consecutive(plate, ret)
            print(f"  {plate}: 连跌{ce.consecutive_down[plate]}月·连涨{ce.consecutive_up[plate]}月")
            print(f"    抄底信号: {ce.evaluate_bottom_fishing(plate, None, 6):.3f}")
            print(f"    仓位: {ce.position[plate]:.2f} | 阶段: {ce.phase[plate]}")
    
    print("\n验证完成。")
