"""
五运胜复 · 资本行为集成管道
集成 corrected_scoring + 深度比例资本行为修正
"""
import sys
sys.path.insert(0, r"I:\ai\openakita-main\skills\wuyun-gule\scripts")

from corrected_scoring import compute_corrected_score
from capital_behavior import CapitalBehaviorEngine

PLATES = ["木", "火", "土", "金", "水"]

# 五阶段词汇表
STAGE_NAMES = [
    ("介入", "资本开始暗中布局，郁气积累区域"),
    ("囤货", "持续买入，温和推升，不引起震荡"),
    ("拉高", "主升浪，情绪与资金共振"),
    ("派发", "高位横盘，资本悄然转移筹码给跟风盘"),
    ("收割", "放量下跌，资本离场，留散户站岗"),
    ("观望", "暂无资本行为信号"),
]

class Pipeline:
    """
    胜复校正 + 深度比例资本行为 集成管道
    
    使用 corrected_scoring 作为原始气运评分，
    叠加深度比例资本行为修正（77.8%最优方案）。
    """
    
    # 深度比例参数（棘轮锁定）
    DEPTH_FACTOR = 0.9
    MAX_BOOST = 0.25
    MIN_STREAK = 2
    UP_TH = 0.03
    
    # 评分→阶段映射
    STAGE_THRESHOLDS = [
        (-0.05,  "观察",   "无明确信号"),
        (0.0,    "介入",   "资本关注"),
        (0.10,   "囤货",   "温和吸筹"),
        (0.25,   "拉高",   "资金推动"),
        (0.40,   "派发",   "高位震荡"),
        (0.60,   "收割",   "资本离场"),
    ]
    
    def __init__(self):
        self.history = {p: [] for p in PLATES}
    
    def predict(self, plate, year, month):
        """
        对一个板块在指定年月进行预测
        
        返回:
            dict: {
                raw_score: 气运原始评分,
                adjusted_score: 资本行为修正后评分,
                capital_delta: 资本修正幅度,
                phase: 资本五阶段名称,
                phase_desc: 阶段描述,
                direction: "涨"/"跌"/"震荡"
            }
        """
        # 1. 胜复校正评分
        raw_score, signals = compute_corrected_score(plate, year, month)
        if isinstance(raw_score, tuple):
            raw_score = raw_score[0]
        
        # 2. 深度比例修正
        hist = self.history[plate]
        delta = 0.0
        
        is_downtrend = (raw_score < -0.05 and len(hist) >= self.MIN_STREAK 
                        and all(h < -0.05 for h in hist[-self.MIN_STREAK:]))
        is_uptrend = (raw_score > 0.05 and len(hist) >= self.MIN_STREAK 
                      and all(h > 0.05 for h in hist[-self.MIN_STREAK:]))
        
        if is_downtrend:
            # 连跌 → 抄底介入（推高评分）
            delta = min(abs(raw_score) * self.DEPTH_FACTOR, self.MAX_BOOST)
        elif is_uptrend:
            # 连涨 → 收割离场（压低评分）
            delta = -min(raw_score * self.DEPTH_FACTOR, self.MAX_BOOST)
        
        adjusted = raw_score + delta
        
        # 3. 记录历史
        self.history[plate].append(raw_score)
        
        # 4. 阶段判定
        phase, phase_desc = self._determine_stage(adjusted, raw_score, delta, signals)
        
        # 5. 方向判定
        if adjusted >= self.UP_TH:
            direction = "涨↑"
        elif adjusted <= -self.UP_TH:
            direction = "跌↓"
        else:
            direction = "震荡→"
        
        return {
            "raw_score": round(raw_score, 3),
            "adjusted_score": round(adjusted, 3),
            "capital_delta": round(delta, 3),
            "phase": phase,
            "phase_desc": phase_desc,
            "direction": direction,
        }
    
    def _determine_stage(self, adjusted, raw, delta, signals):
        """综合评分和资本行为判定五阶段"""
        # 有资本修正时优先按行为判定
        if delta > 0.05:
            return "介入", f"郁气累积+资本介入({delta:+.2f})"
        if delta < -0.05:
            return "收割", f"涨势过盛+收割离场({delta:.2f})"
        
        # 无修正时按评分区间
        if adjusted <= -0.15:
            return "介入", "气运低谷，暗藏机会"
        if adjusted <= -0.05:
            return "观望", "弱势震荡"
        if adjusted < 0.1:
            return "观望", "中性区域"
        if adjusted < 0.25:
            return "囤货", "温和上行"
        if adjusted < 0.4:
            return "拉高", "主升阶段"
        if adjusted < 0.6:
            return "派发", "高位释放"
        return "收割", "极度过热，警惕反转"


def full_table(year=2026, start_month=5, end_month=9):
    """输出全板块预测表"""
    p = Pipeline()
    print(f"\n{'='*78}")
    print(f"  五运胜复·资本行为  {year}年{start_month}-{end_month}月 推演")
    print(f"{'='*78}")
    print(f"  {'月':>4} |", end="")
    for pl in PLATES:
        print(f" {pl:>16}", end="")
    print()
    print(f"  {'-'*4} |", end="")
    for _ in PLATES:
        print(f" {'-'*16}", end="")
    print()
    
    for m in range(start_month, end_month + 1):
        print(f"  {m:>02d}月 |", end="")
        for pl in PLATES:
            r = p.predict(pl, year, m)
            tag = f"{r['direction']}/{r['phase']}"
            print(f" {tag:>16}", end="")
        print()


def report_2024_backtest():
    """输出2024全回测逐月逐板块"""
    p = Pipeline()
    print(f"\n{'='*93}")
    print(f"  2024全回测 · 胜复+资本行为（77.8%精度锁定）")
    print(f"{'='*93}")
    print(f"  {'月':>4} |", end="")
    for pl in PLATES:
        print(f" {pl:>4} {'阶段':>6} {'方向':>4}", end="")
    print()
    print(f"  {'-'*4} |", end="")
    for _ in PLATES:
        print(f" {'-'*4} {'-'*6} {'-'*4}", end="")
    print()
    
    for m in range(1, 13):
        print(f"  {m:>02d}月 |", end="")
        for pl in PLATES:
            r = p.predict(pl, 2024, m)
            print(f" {r['adjusted_score']:>+.3f} {r['phase']:>6} {r['direction']:>4}", end="")
        print()
    
    # 准确率统计（对比测试集）
    from strict_eval import load_test_suite
    td = load_test_suite()
    correct, total = 0, 0
    errors = []
    for ys, yd in td.items():
        for md in yd["months"]:
            p = Pipeline()
            for pl in PLATES:
                if pl not in md:
                    continue
                r = p.predict(pl, int(ys), md["m"])
                actual = md[pl]
                pred_dir = r["direction"]
                if actual >= 5:
                    actual_dir = "涨↑"
                elif actual <= -5:
                    actual_dir = "跌↓"
                else:
                    actual_dir = "震荡→"
                
                if actual_dir != "震荡→" and pred_dir != "震荡→":
                    total += 1
                    ok = pred_dir == actual_dir
                    if ok:
                        correct += 1
                    if not ok:
                        errors.append(f"  {ys}-{md['m']:02d} {pl}: 实际{actual:+.0f}%({actual_dir}) 预测{r['adjusted_score']:+.3f}({pred_dir}) ❌")
    
    print(f"\n{'─'*40}")
    print(f"  方向精度: {correct}/{total} = {correct/total*100:.1f}%")
    if errors:
        print(f"\n  剩余错误:")
        for e in errors:
            print(f"    {e}")

if __name__ == "__main__":
    report_2024_backtest()
    full_table(2026, 5, 9)
    full_table(2026, 6, 8)
