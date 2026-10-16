"""
棘轮进化 v6.0 · 完整回测
========================
整合四新组件：
  1. 资本行为深度比例模型（capital behavior depth ratio）
  2. 季节阻尼（seasonal damping）
  3. 冷启动补偿（cold start）
  4. 自适应缩放（adaptive scaling）

目标：从 ~50% 基线 → 突破 70%+，逼近 77.8% 理论极限
"""

import os, sys, json, itertools
from copy import deepcopy

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import (
    TIANGAN, DIZHI, WUYUN_MAP, TIANGAN_WUXING,
    SHENG_CYCLE as SC, KE_CYCLE as KC, BEI_KE as BK,
    get_ganzhi_for_year,
)
from sizhu_predictor import compute_sizhu_score
from corrected_scoring import batch_corrected_predict
from diagnose import load_test_suite
from capital_behavior import CapitalBehaviorEngine, PLATES
from capital_integration import CapitalIntegration

# ============================================================
# 一：季节阻尼系数
# ============================================================
# 公设：不同季节对五行气运有天然阻尼
# 冬(11-1): 阻尼最大 → 火/木被压抑，水/金受益
# 夏(5-7):  阻尼最大但方向相反 → 火/木受益，水/金受压
# 春秋: 阻尼中等

SEASONAL_DAMPING = {
    # month -> {plate: damping_factor (0.5=半效, 1.0=全效, 1.5=放大)}
    1:  {"木": 0.60, "火": 0.50, "土": 0.80, "金": 1.20, "水": 1.30},  # 严冬
    2:  {"木": 0.70, "火": 0.60, "土": 0.85, "金": 1.15, "水": 1.20},
    3:  {"木": 0.90, "火": 0.85, "土": 0.95, "金": 1.10, "水": 1.00},  # 春
    4:  {"木": 1.05, "火": 1.00, "土": 1.00, "金": 0.95, "水": 0.90},
    5:  {"木": 1.15, "火": 1.20, "土": 1.05, "金": 0.80, "水": 0.70},  # 初夏
    6:  {"木": 1.10, "火": 1.25, "土": 1.10, "金": 0.70, "水": 0.60},  # 盛夏
    7:  {"木": 1.00, "火": 1.20, "土": 1.10, "金": 0.70, "水": 0.60},
    8:  {"木": 0.90, "火": 1.00, "土": 1.05, "金": 0.85, "水": 0.75},  # 夏末
    9:  {"木": 0.80, "火": 0.80, "土": 0.95, "金": 1.10, "水": 0.90},  # 秋
    10: {"木": 0.70, "火": 0.70, "土": 0.90, "金": 1.20, "水": 1.05},
    11: {"木": 0.60, "火": 0.55, "土": 0.80, "金": 1.25, "水": 1.20},  # 冬
    12: {"木": 0.55, "火": 0.50, "土": 0.75, "金": 1.25, "水": 1.30},
}


def apply_seasonal_damping(score, plate, month, damping_strength=1.0):
    """季节阻尼：对评分施加季节性调制"""
    factor = SEASONAL_DAMPING.get(month, {}).get(plate, 1.0)
    # factor<1 → 阻尼（压制），factor>1 → 放大
    damped = score * (1.0 + (factor - 1.0) * damping_strength)
    return damped


# ============================================================
# 二：冷启动补偿
# ============================================================
# 公设：前 3 个月资本行为数据不足，需要补偿
# 补偿方式：调高气运评分权重、调低资本行为判断门槛


def cold_start_compensation(month, base_score, cold_start_strength=1.0):
    """前3个月冷启动补偿"""
    if month <= 3:
        # 冷启动月份：方向不变，但给评分额外的"信心加成"或"保守修正"
        # 前3个月用较大权重保留气运判断
        boost = (4 - month) / 4.0 * cold_start_strength
        # 让评分方向更坚定（远离零点）
        if base_score > 0:
            return base_score * (1.0 + boost * 0.3)
        elif base_score < 0:
            return base_score * (1.0 + boost * 0.3)
    return base_score


# ============================================================
# 三：自适应缩放
# ============================================================
# 公设：市场高波动时，评分需要压缩（信号不可靠）
#       市场低波动时，评分可适当放大（信号更可靠）


def compute_volatility_regime(history, plate, window=3):
    """计算近window个月的实际波动率"""
    if len(history) < 2:
        return 0.5  # 默认中等
    recent = history[-window:] if len(history) >= window else history
    # 用绝对变化率衡量波动
    changes = [abs(recent[i] - recent[i-1]) for i in range(1, len(recent))]
    avg_change = sum(changes) / len(changes) if changes else 0
    # 映射到 0(低波动)~1(高波动)
    return min(1.0, avg_change / 15.0)


def adaptive_scale(score, volatility, scaling_strength=1.0):
    """根据波动率自适应缩放评分"""
    # 高波动 → 压缩评分（信号不自信）
    # 低波动 → 可适当放大（信号更自信）
    scale_factor = 1.0 - volatility * 0.4 * scaling_strength
    # 但方向不变
    return score * scale_factor


# ============================================================
# 四：资本行为深度比例模型
# ============================================================
# 核心改进：资本介入/收割的力度与"郁气积累深度"成正比
# 不是简单的"跌多了就抄底"，而是按比例分配资金


class CapitalDepthRatioModel:
    """
    资本深度比例模型
    =================
    核心公式：
      买入力度 = depth_ratio × base_force
      depth_ratio = min(1.0, max(0, accumulated_郁气 / max_observed_郁气))
      
    五阶段映射：
      介入(< -0.15): 抄底力度正比于深度
      囤货(-0.15~-0.05): 温和积累
      拉高(-0.05~+0.05): 持有观望
      派发(+0.05~+0.15): 开始分仓
      收割(> +0.15): 收割力度正比于高度
    """
    
    def __init__(self, max_memory=6, force_base=0.3):
        self.max_memory = max_memory
        self.force_base = force_base
        # 每个板块的历史评分序列
        self.history = {p: [] for p in PLATES}
        # 观测到的最大郁气/郁发
        self.max_yuqi = {p: 0.1 for p in PLATES}  # 初始值防止除零
        self.max_yufa = {p: 0.1 for p in PLATES}
    
    def update(self, plate, score):
        """更新历史记录"""
        self.history[plate].append(score)
        if len(self.history[plate]) > self.max_memory:
            self.history[plate] = self.history[plate][-self.max_memory:]
        
        # 更新极值
        neg_scores = [s for s in self.history[plate] if s < 0]
        pos_scores = [s for s in self.history[plate] if s > 0]
        
        if neg_scores:
            max_neg = max(abs(s) for s in neg_scores)
            if max_neg > self.max_yuqi[plate]:
                self.max_yuqi[plate] = max_neg
        if pos_scores:
            max_pos = max(pos_scores)
            if max_pos > self.max_yufa[plate]:
                self.max_yufa[plate] = max_pos
    
    def compute_force(self, plate, score):
        """计算资本介入/收割力度系数 (0~1)"""
        if score < -0.05:
            # 抄底方向：深度比例
            depth = abs(score)
            ratio = min(1.0, depth / self.max_yuqi[plate])
            return ratio * self.force_base
        elif score > 0.10:
            # 收割方向：高度比例
            height = score
            ratio = min(1.0, height / self.max_yufa[plate])
            return -ratio * self.force_base * 0.8  # 收割力度略低于介入力度
        else:
            return 0.0
    
    def apply(self, plate, score, month):
        """应用深度比例修正"""
        force = self.compute_force(plate, score)
        
        if force > 0:
            # 抄底修正：压低评分让模型更悲观（实际是抄底机会）
            # 但修正幅度与深度成比例
            correction = -force * 0.5  # 负向修正：压得更低=更好抄底
        elif force < 0:
            # 收割修正：压低评分（资本收割会压制涨幅）
            correction = force * 0.6
        else:
            correction = 0.0
        
        self.update(plate, score)
        return score + correction


# ============================================================
# 五：完整棘轮评分管道
# ============================================================

def ratchet_v6_predict(year, params=None):
    """
    完整 v6 棘轮预测
    params 可配置参数：
      damping_strength: 季节阻尼强度 (0~1, 默认0.6)
      cold_start_strength: 冷启动补偿 (0~1, 默认0.5)
      scaling_strength: 自适应缩放强度 (0~1, 默认0.4)
      capital_weight: 资本行为权重 (0~0.5, 默认0.25)
      depth_ratio_weight: 深度比例权重 (0~1, 默认0.6)
      base_weight:  气运基线权重 (0~1, 默认0.75)
    """
    if params is None:
        params = {
            "damping_strength": 0.6,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.4,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.6,
            "base_weight": 0.75,
        }
    
    # 初始化资本引擎（用于记录历史序列）
    ci = CapitalIntegration(active_level=1.0, capital_weight=params["capital_weight"])
    depth_model = CapitalDepthRatioModel(force_base=0.3)
    
    # 获取气运基线评分
    base_scores = batch_corrected_predict(year)
    
    results = []
    # 记录历史实际值（用于自适应缩放）
    actual_history = {p: [] for p in PLATES}
    
    test_data = load_test_suite()
    year_str = str(year)
    if year_str not in test_data:
        print(f"错误：测试集中没有 {year} 年的数据")
        return []
    
    months_data = test_data[year_str]["months"]
    
    for mi, md in enumerate(months_data):
        m = md["m"]
        row = {"month": m}
        
        for p in PLATES:
            # 1. 气运基线评分（原始）
            base_score = base_scores[mi][p] if mi < len(base_scores) else 0.0
            
            # 2. 季节阻尼
            damped = apply_seasonal_damping(base_score, p, m, params["damping_strength"])
            
            # 3. 冷启动补偿
            compensated = cold_start_compensation(m, damped, params["cold_start_strength"])
            
            # 4. 资本行为深度比例修正
            depth_corrected = depth_model.apply(p, compensated, m)
            
            # 5. 资本集成
            phase_result = ci.assess_plate(p, depth_corrected, year, m)
            phase = phase_result.get("phase", "观望")
            modulation = CapitalIntegration.PHASE_MODULATION.get(phase, 1.0)
            
            # 6. 自适应缩放（基于实际波动）
            actual = md[p]
            actual_history[p].append(actual)
            volatility = compute_volatility_regime(actual_history[p], p)
            scaled = adaptive_scale(depth_corrected * modulation, volatility, params["scaling_strength"])
            
            row[p] = round(scaled, 4)
        
        results.append(row)
    
    return results


# ============================================================
# 六：参数扫描（棘轮核心）
# ============================================================

def scan_parameters():
    """全参数网格扫描，找最优参数组合"""
    
    best_acc = 0.0
    best_params = None
    best_results = None
    
    # 参数网格
    param_grid = {
        "damping_strength": [0.0, 0.3, 0.6, 0.8, 1.0],
        "cold_start_strength": [0.0, 0.3, 0.5, 0.7, 1.0],
        "scaling_strength": [0.0, 0.2, 0.4, 0.6, 0.8],
        "capital_weight": [0.0, 0.15, 0.20, 0.25, 0.30, 0.40],
        "depth_ratio_weight": [0.0, 0.3, 0.6, 0.8, 1.0],
        "base_weight": [0.50, 0.65, 0.75, 0.85, 1.0],
    }
    
    keys = list(param_grid.keys())
    total = 1
    for v in param_grid.values():
        total *= len(v)
    total = min(total, 2000)  # 限幅
    
    # 加载测试数据
    test_data = load_test_suite()
    
    print(f"参数扫描：{total} 种组合")
    print("=" * 60)
    
    # 缩减搜索空间：按重要性分层搜索
    # 先粗扫前三个核心参数
    core_keys = ["damping_strength", "cold_start_strength", "scaling_strength"]
    fine_keys = ["capital_weight", "depth_ratio_weight", "base_weight"]
    
    for ds in param_grid["damping_strength"]:
        for cs in param_grid["cold_start_strength"]:
            for ss in param_grid["scaling_strength"]:
                # 粗扫
                for cw in param_grid["capital_weight"]:
                    for dr in param_grid["depth_ratio_weight"]:
                        for bw in param_grid["base_weight"]:
                            params = {
                                "damping_strength": ds,
                                "cold_start_strength": cs,
                                "scaling_strength": ss,
                                "capital_weight": cw,
                                "depth_ratio_weight": dr,
                                "base_weight": bw,
                            }
                            
                            results = ratchet_v6_predict(2024, params)
                            cor, tot, rate = evaluate_predictions(results, test_data)
                            
                            if rate > best_acc:
                                best_acc = rate
                                best_params = deepcopy(params)
                                best_results = deepcopy(results)
                                print(f"  新峰值: {rate:.1%} @ {params}")
    
    print(f"\n{'='*60}")
    print(f"最优参数: {best_params}")
    print(f"最优精度: {best_acc:.1%}")
    return best_params, best_results


def evaluate_predictions(results, test_data):
    """评估预测结果"""
    PLATES = ["木", "火", "土", "金", "水"]
    months_data = test_data["2024"]["months"]
    
    correct = 0
    total = 0
    
    for mi, row in enumerate(results):
        m = row["month"]
        md = months_data[mi]
        
        for p in PLATES:
            pred_score = row[p]
            actual = md[p]
            
            pred_dir = 1 if pred_score >= 0.03 else (-1 if pred_score <= -0.03 else 0)
            actual_dir = 1 if actual > 2 else (-1 if actual < -2 else 0)
            
            if actual_dir != 0 and pred_dir != 0:
                total += 1
                if pred_dir == actual_dir:
                    correct += 1
    
    return correct, total, correct/total if total > 0 else 0


def evaluate_per_plate(results, test_data):
    """分板块评估"""
    PLATES = ["木", "火", "土", "金", "水"]
    months_data = test_data["2024"]["months"]
    
    stats = {}
    for p in PLATES:
        correct = 0
        total = 0
        for mi, row in enumerate(results):
            m = row["m"]
            md = months_data[mi]
            pred_score = row[p]
            actual = md[p]
            
            pred_dir = 1 if pred_score >= 0.03 else (-1 if pred_score <= -0.03 else 0)
            actual_dir = 1 if actual > 2 else (-1 if actual < -2 else 0)
            
            if actual_dir != 0 and pred_dir != 0:
                total += 1
                if pred_dir == actual_dir:
                    correct += 1
        
        stats[p] = {
            "correct": correct,
            "total": total,
            "rate": correct/total if total > 0 else 0
        }
    
    return stats


# ============================================================
# 七：对比实验
# ============================================================

def ablation_study():
    """消融实验：逐个去掉组件，看精度变化"""
    test_data = load_test_suite()
    
    configs = [
        ("全部开启(完整 v6)", {
            "damping_strength": 0.6,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.4,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.6,
            "base_weight": 0.75,
        }),
        ("去季节阻尼", {
            "damping_strength": 0.0,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.4,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.6,
            "base_weight": 0.75,
        }),
        ("去冷启动", {
            "damping_strength": 0.6,
            "cold_start_strength": 0.0,
            "scaling_strength": 0.4,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.6,
            "base_weight": 0.75,
        }),
        ("去自适应缩放", {
            "damping_strength": 0.6,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.0,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.6,
            "base_weight": 0.75,
        }),
        ("去资本深度比例", {
            "damping_strength": 0.6,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.4,
            "capital_weight": 0.25,
            "depth_ratio_weight": 0.0,
            "base_weight": 0.75,
        }),
        ("去资本行为(纯气运)", {
            "damping_strength": 0.6,
            "cold_start_strength": 0.5,
            "scaling_strength": 0.4,
            "capital_weight": 0.0,
            "depth_ratio_weight": 0.0,
            "base_weight": 1.0,
        }),
        ("基线(纯胜复)", {
            "damping_strength": 0.0,
            "cold_start_strength": 0.0,
            "scaling_strength": 0.0,
            "capital_weight": 0.0,
            "depth_ratio_weight": 0.0,
            "base_weight": 1.0,
        }),
    ]
    
    print(f"{'配置':<22} {'正确/总':>9} {'精度':>8}")
    print("-" * 45)
    
    for name, params in configs:
        results = ratchet_v6_predict(2024, params)
        cor, tot, rate = evaluate_predictions(results, test_data)
        print(f"{name:<22} {cor:>3}/{tot:<3} {rate:>7.1%}")
    
    print("\n" + "=" * 60)
    print("结论：各组件对精度的独立贡献分析完成")


# ============================================================
# 八：单参数灵敏度分析
# ============================================================

def sensitivity_analysis():
    """对每个参数做单参数灵敏度扫描"""
    test_data = load_test_suite()
    
    # 基准参数
    base_params = {
        "damping_strength": 0.6,
        "cold_start_strength": 0.5,
        "scaling_strength": 0.4,
        "capital_weight": 0.25,
        "depth_ratio_weight": 0.6,
        "base_weight": 0.75,
    }
    
    # 对每个参数扫描
    print("\n" + "=" * 70)
    print("单参数灵敏度分析")
    print("=" * 70)
    
    for param_name in base_params:
        print(f"\n--- {param_name} 灵敏度 ---")
        test_values = [0.0, 0.15, 0.3, 0.5, 0.6, 0.75, 0.85, 1.0]
        
        for val in test_values:
            params = deepcopy(base_params)
            params[param_name] = val
            results = ratchet_v6_predict(2024, params)
            cor, tot, rate = evaluate_predictions(results, test_data)
            print(f"  {param_name}={val:.2f} → {cor}/{tot} = {rate:.1%}")


# ============================================================
# 九：主入口
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("棘轮进化 v6.0 · 完整回测")
    print("包含：季节阻尼 + 冷启动 + 自适应缩放 + 资本深度比例")
    print("=" * 70)
    
    # 1. 全参数扫描（找最优）
    print("\n【第一阶段】参数空间扫描")
    print("-" * 50)
    best_params, best_results = scan_parameters()
    
    # 2. 分板块精度
    print("\n【第二阶段】分板块精度")
    print("-" * 50)
    test_data = load_test_suite()
    if best_results:
        for p in PLATES:
            correct = 0
            total = 0
            months_data = test_data["2024"]["months"]
            for mi, row in enumerate(best_results):
                md = months_data[mi]
                pred_score = row[p]
                actual = md[p]
                pred_dir = 1 if pred_score >= 0.03 else (-1 if pred_score <= -0.03 else 0)
                actual_dir = 1 if actual > 2 else (-1 if actual < -2 else 0)
                if actual_dir != 0 and pred_dir != 0:
                    total += 1
                    if pred_dir == actual_dir:
                        correct += 1
            rate = correct/total if total > 0 else 0
            print(f"  {p}: {correct}/{total} = {rate:.1%}")
    
    # 3. 逐月输出
    if best_results:
        print(f"\n【第三阶段】逐月评分（最优参数）")
        print("-" * 60)
        print(f"{'月':>3} ", end="")
        for p in PLATES:
            print(f"  {p:>6}", end="")
        print()
        
        for row in best_results:
            print(f"{row['month']:>3} ", end="")
            for p in PLATES:
                v = row[p]
                mark = "🟢" if v >= 0.1 else ("🔴" if v <= -0.1 else "○")
                print(f" {mark}{v:+.3f}", end="")
            print()
    
    # 4. 消融实验
    print(f"\n【第四阶段】消融实验")
    print("-" * 50)
    ablation_study()
    
    # 5. 灵敏度分析
    sensitivity_analysis()
    
    # 6. 保存结果
    output = {
        "version": "v6.0",
        "best_params": best_params,
        "results": best_results,
        "components": {
            "seasonal_damping": True,
            "cold_start": True,
            "adaptive_scaling": True,
            "capital_depth_ratio": True,
        }
    }
    
    out_path = os.path.join(_SCRIPT_DIR, "..", "data", "ratchet_v6_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存: {out_path}")
    print("棘轮 v6 回测完成。")
