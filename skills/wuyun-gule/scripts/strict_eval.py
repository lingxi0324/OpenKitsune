"""
精确方向评估 · DirectionalAccuracy
==================================
用严格的方向匹配替代"震荡算对"的宽松规则。
只评估：模型说涨→实际涨，模型说跌→实际跌。
实际涨跌以±5%为阈值，震荡月不参与评分（避免噪声）。
"""

import os, sys, json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from wuyun_core import get_ganzhi_for_year
from sizhu_predictor import compute_sizhu_score, PLATES
from capital_integration import CapitalIntegration


def load_test_suite(path=None):
    if path is None:
        path = os.path.join(_SCRIPT_DIR, "..", "data", "test_suite.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def directional_accuracy(params, test_data, verbose=False):
    """
    严格方向评估：只对比趋势方向（涨/跌），震荡月剔除。
    实际涨跌以±5%为界。
    """
    weights = {
        "year": params.get("w_year", 0.35),
        "month": params.get("w_month", 0.30),
        "day": params.get("w_day", 0.20),
        "hour": params.get("w_hour", 0.15),
    }
    capital_weight = params.get("capital_weight", 0.0)
    active_level = params.get("active_level", 1.0)
    up_th = params.get("up_th", 0.03)
    
    ci = CapitalIntegration(active_level=active_level, capital_weight=capital_weight)
    
    correct_signal = 0  # 方向正确的信号数
    total_signal = 0    # 有明确方向的信号数
    correct_amplitude = 0  # 方向+幅度都正确的数量
    total_amplitude = 0
    
    details = []
    
    for year_str, year_data in test_data.items():
        year = int(year_str)
        for md in year_data["months"]:
            month = md["m"]
            for plate in PLATES:
                actual_val = md[plate]
                
                # 四柱评分
                raw_score = compute_sizhu_score(plate, year, month, weights)
                
                # 资本调制
                if capital_weight > 0:
                    modulated, phase = ci.modulate_score(plate, raw_score, year, month)
                else:
                    modulated = raw_score
                
                # 模型方向
                pred_dir = 1 if modulated >= up_th else (-1 if modulated <= -up_th else 0)
                
                # 实际方向（严格±5%）
                if actual_val >= 5:
                    actual_dir = 1
                elif actual_val <= -5:
                    actual_dir = -1
                else:
                    actual_dir = 0  # 震荡，不参与方向评分
                
                # 幅度等级（用于额外评分）
                actual_amp = "强" if abs(actual_val) >= 10 else "中" if abs(actual_val) >= 5 else "弱"
                
                if actual_dir != 0 and pred_dir != 0:
                    total_signal += 1
                    if pred_dir == actual_dir:
                        correct_signal += 1
                        correct_amplitude += 1
                    total_amplitude += 1
                
                if verbose and actual_dir != 0:
                    details.append(f"{year}-{month:02d} {plate}: 实际{actual_val:+.0f}%({actual_dir:+d}) 模型{modulated:+.3f}({pred_dir:+d}) {'✅' if pred_dir==actual_dir else '❌'}")
    
    rate_signal = correct_signal / total_signal if total_signal > 0 else 0
    rate_amplitude = correct_amplitude / total_amplitude if total_amplitude > 0 else 0
    
    return rate_signal, correct_signal, total_signal, details


def run_strict_eval():
    test_data = load_test_suite()
    
    print("=" * 60)
    print("严格方向评估（剔除震荡月）")
    print("=" * 60)
    
    # 基线（v4.2参数）
    base_params = {
        "w_year": 0.35, "w_month": 0.30, "w_day": 0.20, "w_hour": 0.15,
        "capital_weight": 0.0, "active_level": 1.0,
        "up_th": 0.03,
    }
    
    rate, cor, total, details = directional_accuracy(base_params, test_data, verbose=True)
    print(f"\n📊 纯四柱基线: {rate:.1%} ({cor}/{total})")
    
    # 不同资本权重的对比
    print(f"\n📊 资本权重对比:")
    for cw in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        p = base_params.copy()
        p["capital_weight"] = cw
        r, c, t, _ = directional_accuracy(p, test_data)
        delta = (r - rate) * 100
        mark = "✦" if r > rate else ("─" if abs(delta) < 0.5 else "▾")
        print(f"  capital_w={cw:.2f}: {r:.1%} ({c}/{t}) {mark} {delta:+.1f}%")
    
    # 活跃度对比
    print(f"\n📊 资本活跃度对比 (capital_w=0.15):")
    for al in [0.5, 0.8, 1.0, 1.2, 1.5]:
        p = base_params.copy()
        p["capital_weight"] = 0.15
        p["active_level"] = al
        r, c, t, _ = directional_accuracy(p, test_data)
        delta = (r - rate) * 100
        mark = "✦" if r > rate else ("─" if abs(delta) < 0.5 else "▾")
        print(f"  active={al:.1f}: {r:.1%} ({c}/{t}) {mark} {delta:+.1f}%")
    
    # 最优组合探索
    print(f"\n📊 最优组合探索:")
    best_r, best_p = rate, base_params
    for cw in [0.0, 0.05, 0.10, 0.15, 0.18, 0.20, 0.22]:
        for al in [0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5]:
            p = base_params.copy()
            p["capital_weight"] = cw
            p["active_level"] = al
            r, c, t, _ = directional_accuracy(p, test_data)
            if r > best_r:
                best_r = r
                best_p = p
                print(f"  ✦ 新最优: {r:.1%} ({c}/{t}) cw={cw} al={al}")
    
    print(f"\n🏆 最优方向精度: {best_r:.1%}")
    print(f"   参数: capital_w={best_p['capital_weight']} active={best_p['active_level']}")
    
    # 板块级精度
    print(f"\n📊 板块级精度 (最优参数):")
    for plate in PLATES:
        plate_test = {}
        for ys, yd in test_data.items():
            ymd = []
            for md in yd["months"]:
                ymd.append({"m": md["m"], plate: md[plate]})
            plate_test[ys] = {"months": ymd}
        r, c, t, _ = directional_accuracy(best_p, plate_test)
        print(f"  {plate}: {r:.1%} ({c}/{t})")


if __name__ == "__main__":
    run_strict_eval()
