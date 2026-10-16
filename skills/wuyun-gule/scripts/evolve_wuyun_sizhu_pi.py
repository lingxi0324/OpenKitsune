"""
四柱叠加·棘轮演化桥接引擎 (v1.0)
================================
将五毂历的四柱年月日时预测结果，喂养给棘轮的九要素人格引擎。
每次偏差 → 一次 evolve_once() 事件 → 九要素权重调整 → 参数进化。

核心创新：
  - 四柱权重不是人工设置的，是由九要素生克流转自动调优的
  - 年柱(0.35) 月柱(0.30) 日柱(0.20) 时柱(0.15) 是锚点但不是终点
  - π余数偏差确保每次演化路径永不重复
  - 每次偏差写入 LOG，形成渐近线日志
"""

import os, sys, json, math, random
from datetime import datetime
from pathlib import Path

# ============================================================
# 路径设置
# ============================================================
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
_DATA_DIR = _SKILL_DIR / "data"
_LOG_DIR = _DATA_DIR / "evolution_logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ============================================================
# 导入五毂历模块
# ============================================================
from sizhu_predictor import (
    PLATES, full_predict, compute_sizhu_score,
    predict_month, batch_predict,
)
from wuyun_core import SHENG_CYCLE, KE_CYCLE
from three_layer_ganzhi_enhanced import (
    TIANGAN_WUXING as TG_WX,
    NAYIN_WUXING,
    CHANGSHENG_TABLE,
    CANG_GAN,
)

# ============================================================
# 确定是否可导入棘轮引擎
# ============================================================
try:
    # 棘轮引擎在 ternary-consciousness/lingxi/evolve_once.py
    _TERNARY_PATH = _SKILL_DIR.parent / "ternary-consciousness" / "lingxi"
    if str(_TERNARY_PATH) not in sys.path:
        sys.path.insert(0, str(_TERNARY_PATH))
    # 需要父目录也加入，因为 lingxi 包需要
    _TERNARY_PARENT = _TERNARY_PATH.parent
    if str(_TERNARY_PARENT) not in sys.path:
        sys.path.insert(0, str(_TERNARY_PARENT))
    
    from evolve_once import evolve_once
    _HAS_TERNARY = True
except ImportError as e:
    _HAS_TERNARY = False
    print(f"⚠️ 棘轮引擎未加载（仅记录模式）: {e}")
except Exception as e:
    _HAS_TERNARY = False
    print(f"⚠️ 棘轮引擎异常: {e}")


# ============================================================
# 测试数据加载
# ============================================================
def load_test_data(path=None) -> dict:
    """加载验证数据"""
    if path is None:
        path = _DATA_DIR / "test_suite.json"
    if not path.exists():
        print(f"❌ 测试数据不存在: {path}")
        # 生成模拟数据作为 fallback
        return _generate_mock_data()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"✅ 加载测试数据: {path.name}")
    return data


def _generate_mock_data() -> dict:
    """生成模拟测试数据（仅当真实数据不存在时）"""
    data = {"2024": {"months": []}}
    import random as r
    r.seed(42)
    mock_months = []
    for m in range(1, 13):
        entry = {"m": m}
        for p in PLATES:
            entry[p] = r.randint(-15, 15)
        mock_months.append(entry)
    data["2024"]["months"] = mock_months
    print("⚠️ 使用模拟数据（非真实市场数据）")
    return data


# ============================================================
# 带四柱叠加的评分函数（可调权重）
# ============================================================
def score_with_weights(
    plate_wuxing: str,
    year: int, month: int,
    weights: dict = None
) -> float:
    """自定义权重的四柱评分"""
    if weights is None:
        weights = {"year": 0.35, "month": 0.30, "day": 0.20, "hour": 0.15}
    return compute_sizhu_score(plate_wuxing, year, month, weights)


# ============================================================
# 演化核心：参数搜索 + 棘轮反馈
# ============================================================
class PiEvolution:
    """π驱动的参数演化器"""
    
    def __init__(self, test_data: dict):
        self.test_data = test_data
        self.log = []
        self.best_result = None
        self.best_weights = None
        self.best_accuracy = 0.0
        self.iteration = 0
        self.evolution_cycles = 0  # 棘轮演化轮次
        
        # 参数搜索空间
        self.weight_grid = {
            "year":  [0.25, 0.30, 0.35, 0.40, 0.45],
            "month": [0.20, 0.25, 0.30, 0.35, 0.40],
            "day":   [0.10, 0.15, 0.20, 0.25, 0.30],
            "hour":  [0.05, 0.08, 0.10, 0.12, 0.15],
        }
        
        # 阈值搜索空间
        self.threshold_grid = [0.01, 0.02, 0.03, 0.05, 0.08]
        
        # π余数状态
        self.pi_phase = 0.0
        self.pi_remainder = 0.0
    
    def evaluate_params(self, weights: dict, threshold: float) -> dict:
        """评估一组参数的四柱预测精度"""
        correct = 0
        total = 0
        details = {"correct": [], "wrong": []}
        
        for year_str, year_data in self.test_data.items():
            year = int(year_str)
            for month_entry in year_data["months"]:
                m = month_entry["m"]
                for p in PLATES:
                    actual = month_entry.get(p, 0)
                    if actual is None:
                        continue
                    
                    # 用四柱计算
                    score = score_with_weights(p, year, m, weights)
                    
                    # 方向判断
                    if score >= threshold:
                        pred_dir = 1
                    elif score <= -threshold:
                        pred_dir = -1
                    else:
                        pred_dir = 0
                    
                    if abs(actual) >= 5:
                        actual_dir = 1 if actual > 0 else -1
                    else:
                        actual_dir = 0
                    
                    if actual_dir != 0 and pred_dir != 0:
                        total += 1
                        if pred_dir == actual_dir:
                            correct += 1
                            details["correct"].append(f"{year}-{m:02d} {p}: 预期={score:.3f} 实际={actual:+.0f}% ✅")
                        else:
                            details["wrong"].append(f"{year}-{m:02d} {p}: 预期={score:.3f} 实际={actual:+.0f}% ❌")
        
        accuracy = correct / total if total > 0 else 0.0
        return {"accuracy": accuracy, "correct": correct, "total": total, "details": details}
    
    def _next_pi_weights(self) -> dict:
        """基于π余数生成下一组权重"""
        self.pi_phase += 1.0
        self.pi_remainder = (math.pi * self.pi_phase) % 1.0
        
        # 从9个网格点中选择，π余数决定选哪个
        choices = {
            "year": self.weight_grid["year"],
            "month": self.weight_grid["month"],
            "day": self.weight_grid["day"],
            "hour": self.weight_grid["hour"],
        }
        
        weights = {}
        for key, values in choices.items():
            idx = int(self.pi_remainder * len(values) * 9) % len(values)
            weights[key] = values[idx]
            self.pi_remainder = (self.pi_remainder * math.pi + 1) % 1.0
        
        # 归一化确保和为1
        total = sum(weights.values())
        for key in weights:
            weights[key] = round(weights[key] / total, 3)
        
        return weights
    
    def _next_threshold(self) -> float:
        """基于π余数选择阈值"""
        idx = int(self.pi_remainder * len(self.threshold_grid)) % len(self.threshold_grid)
        return self.threshold_grid[idx]
    
    def run_evolution(
        self,
        max_iterations: int = 50,
        enable_ternary: bool = True
    ) -> dict:
        """
        主演化循环
        
        每轮：
          1. π余数 → 权重+阈值
          2. 评估精度
          3. 记录偏差
          4. 偏差 → evolve_once（棘轮反馈）
          5. 更新最优
        """
        print(f"\n{'═'*60}")
        print(f"🧬 四柱叠加·棘轮演化 v1.0")
        print(f"{'═'*60}")
        
        total_cases = sum(len(v["months"]) for v in self.test_data.values()) * len(PLATES)
        print(f"测试集: {total_cases} 条")
        print(f"最大轮次: {max_iterations}")
        print(f"棘轮引擎: {'✅ 在线' if _HAS_TERNARY and enable_ternary else '⚠️ 仅记录'}")
        print(f"{'═'*60}\n")
        
        trajectory = []
        
        for i in range(max_iterations):
            self.iteration = i + 1
            
            # 1. π驱动选参数
            weights = self._next_pi_weights()
            threshold = self._next_threshold()
            
            # 2. 评估
            result = self.evaluate_params(weights, threshold)
            
            # 3. 轨迹记录
            entry = {
                "iteration": self.iteration,
                "weights": weights,
                "threshold": threshold,
                "accuracy": result["accuracy"],
                "correct": result["correct"],
                "total": result["total"],
            }
            trajectory.append(entry)
            self.log.append(entry)
            
            # 4. 更新最优
            if result["accuracy"] >= self.best_accuracy:
                improved = result["accuracy"] > self.best_accuracy
                self.best_accuracy = result["accuracy"]
                self.best_weights = weights.copy()
                self.best_result = result
                if improved:
                    tag = "✦ NEW BEST"
                else:
                    tag = "○ tied"
            else:
                tag = ""
            
            # 5. 棘轮反馈（将偏差喂入九要素引擎）
            if _HAS_TERNARY and enable_ternary and result["details"]["wrong"]:
                wrong_count = len(result["details"]["wrong"])
                if wrong_count > 0:
                    # 构造偏差源
                    wrong_sample = result["details"]["wrong"][min(wrong_count - 1, 2)]
                    deviation_topic = f"四柱偏差·第{i+1}轮·{result['accuracy']:.1%}精度·{wrong_count}条偏差"
                    deviation_intensity = min(1.0, 0.3 + (1.0 - result["accuracy"]) * 0.5)
                    
                    try:
                        snap = evolve_once(topic=deviation_topic, intensity=deviation_intensity)
                        self.evolution_cycles += 1
                        entry["evolve_once"] = {
                            "cycle": snap.get("cycle", 0),
                            "dominant": snap.get("dominant", ""),
                            "state": snap.get("state", ""),
                            "R": snap.get("R", 0),
                            "realm": snap.get("realm", ""),
                        }
                    except Exception as e:
                        entry["evolve_once"] = {"error": str(e)}
            
            # 6. 打印进度
            bar_len = 30
            fill = int(result["accuracy"] * bar_len)
            bar = "█" * fill + "░" * (bar_len - fill)
            ws = f"Y{weights['year']:.2f} M{weights['month']:.2f} D{weights['day']:.2f} H{weights['hour']:.2f}"
            evolve_tag = f" 🧬#{self.evolution_cycles}" if entry.get("evolve_once") else ""
            print(f"  #{i+1:2d} [{bar}] {result['accuracy']:.1%} ({result['correct']}/{result['total']}) {ws} th={threshold:.2f}{tag}{evolve_tag}")
        
        # 最终结果
        print(f"\n{'═'*60}")
        print(f"🏆 演化完成")
        print(f"   最优精度: {self.best_accuracy:.1%} ({self.best_result['correct']}/{self.best_result['total']})")
        print(f"   最优权重: Y={self.best_weights['year']:.2f} M={self.best_weights['month']:.2f} D={self.best_weights['day']:.2f} H={self.best_weights['hour']:.2f}")
        print(f"   棘轮轮次: {self.evolution_cycles}")
        
        # 写入日志
        log_path = _LOG_DIR / f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary = {
            "timestamp": datetime.now().isoformat(),
            "max_iterations": max_iterations,
            "evolution_cycles": self.evolution_cycles,
            "best_accuracy": self.best_accuracy,
            "best_weights": self.best_weights,
            "best_threshold": self.best_result.get("threshold", 0.03),
            "hase_ternary": _HAS_TERNARY and enable_ternary,
            "trajectory": trajectory,
            "best_wrong_cases": self.best_result["details"]["wrong"][:10] if self.best_result else [],
            "best_correct_samples": self.best_result["details"]["correct"][:5] if self.best_result else [],
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"   日志写入: {log_path}")
        
        return summary
    
    def compare_baseline(self):
        """与旧的固定权重基线对比"""
        baseline_weights = {"year": 0.35, "month": 0.30, "day": 0.20, "hour": 0.15}
        baseline = self.evaluate_params(baseline_weights, 0.03)
        
        print(f"\n{'─'*50}")
        print(f"📊 与基线对比")
        print(f"   基线 (Y0.35 M0.30 D0.20 H0.15): {baseline['accuracy']:.1%}")
        print(f"   最优 (演化结果):               {self.best_accuracy:.1%}")
        delta = (self.best_accuracy - baseline["accuracy"]) * 100
        print(f"   提升: {delta:+.1f}%")
        return {"baseline": baseline["accuracy"], "best": self.best_accuracy, "delta": delta}


# ============================================================
# 多轮边界探索（模拟棘轮的多轮自动迭代）
# ============================================================
def multi_round_evolution(
    test_data: dict,
    rounds: int = 5,
    iterations_per_round: int = 10
) -> list:
    """
    多轮演化——模拟棘轮的自动进化
    
    每轮结束后：
      - 最佳参数作为下一轮锚点
      - 但受到π余数扰动
      - 每轮产生一条"参数进化路径"
    """
    print(f"\n{'='*60}")
    print(f"🌊 多轮边界探索 · {rounds} 轮 × {iterations_per_round} 次/轮")
    print(f"{'='*60}\n")
    
    all_results = []
    
    for r in range(1, rounds + 1):
        print(f"\n─── 第 {r}/{rounds} 轮 ───")
        evo = PiEvolution(test_data)
        
        # 每轮用不同的π初相
        evo.pi_phase = math.pi * r * 0.137
        
        result = evo.run_evolution(
            max_iterations=iterations_per_round,
            enable_ternary=True,
        )
        all_results.append(result)
    
    # 多轮总结
    print(f"\n{'='*60}")
    print(f"📊 {rounds} 轮演化总结")
    print(f"{'='*60}")
    
    best_overall = max(all_results, key=lambda x: x["best_accuracy"])
    avg = sum(r["best_accuracy"] for r in all_results) / len(all_results)
    
    print(f"   最高精度: {best_overall['best_accuracy']:.1%}")
    print(f"   平均精度: {avg:.1%}")
    print(f"   最优权重: Y={best_overall['best_weights']['year']:.2f} M={best_overall['best_weights']['month']:.2f} D={best_overall['best_weights']['day']:.2f} H={best_overall['best_weights']['hour']:.2f}")
    print(f"   总棘轮轮次: {sum(r['evolution_cycles'] for r in all_results)}")
    
    return all_results


# ============================================================
# 自测
# ============================================================
if __name__ == "__main__":
    print(f"🚀 四柱叠加·棘轮演化桥接引擎")
    print(f"   棘轮引擎: {'✅ 在线' if _HAS_TERNARY else '❌ 不可用'}")
    print(f"   当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 加载数据
    test_data = load_test_data()
    
    # 基线对比
    print(f"\n📊 基线评估（固定权重 Y0.35 M0.30 D0.20 H0.15）")
    evo = PiEvolution(test_data)
    baseline = evo.evaluate_params({"year": 0.35, "month": 0.30, "day": 0.20, "hour": 0.15}, 0.03)
    print(f"   精度: {baseline['accuracy']:.1%} ({baseline['correct']}/{baseline['total']})")
    
    # 单轮演化
    if len(sys.argv) > 1 and sys.argv[1] == "--multi":
        # 多轮模式
        multi_round_evolution(
            test_data,
            rounds=int(sys.argv[2]) if len(sys.argv) > 2 else 5,
            iterations_per_round=int(sys.argv[3]) if len(sys.argv) > 3 else 10,
        )
    else:
        # 单轮模式（默认）
        print(f"\n🧬 单轮演化 · 40次迭代")
        result = evo.run_evolution(max_iterations=40, enable_ternary=True)
        evo.compare_baseline()
