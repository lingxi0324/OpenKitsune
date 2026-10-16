"""
四层棘轮集成 · 全链路回测 + 权重优化 v2.0
===========================================
集成层：
  1️⃣ 胜复校正评分 v2.0（已修） — 五运六气基础
  2️⃣ 资本行为五阶段 — 介入/囤货/拉高/派发/收割
  3️⃣ 九宫奇门 — 年月飞星 + 方向级影响
  4️⃣ 四柱加权 — 年0.35 + 月0.25 + 日0.25 + 时0.15（月度版：年+月）

目标：找到四层最优权重组合，突破75%精度
"""

import os, sys, json, math, itertools
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ===== 导入各层引擎 =====
from corrected_scoring import (
    PLATES, compute_corrected_score, batch_corrected_predict
)
from capital_integration import CapitalIntegration
from qimen_jiugong import QimenJiugongEngine
from diagnose import load_test_suite

# ===== 常量 =====
DEFAULT_WEIGHTS = {
    "wuyun": 0.50,      # 胜复校正评分权重
    "capital": 0.25,    # 资本行为权重
    "qimen": 0.15,      # 九宫奇门权重
    "base_annual": 0.10, # 年度基调修正
}
ERUPTION_MONTHS = {"火": [9], "木": [9]}  # 历史已知爆发月


class FourLayerIntegrator:
    """四层集成器"""

    def __init__(self, weights: dict = None, active_level: float = 1.0):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.capital = CapitalIntegration(active_level=active_level, capital_weight=0.20)
        self.qimen = QimenJiugongEngine()
        # 归一化权重
        total = sum(self.weights.values())
        if total > 0:
            for k in self.weights:
                self.weights[k] /= total

    def predict_month(self, plate_wx: str, year: int, month: int,
                       prev_scores: list = None) -> dict:
        """四层集成预测某板块某月"""
        w = self.weights

        # 1️⃣ 胜复校正评分
        wuyun_score, signals = compute_corrected_score(plate_wx, year, month)

        # 2️⃣ 资本行为调制
        cap_result = self.capital.assess_plate(plate_wx, wuyun_score, year, month, prev_scores)
        capital_phase = cap_result.get("phase", "观望")
        capital_signal = cap_result.get("signal", 0.0)

        # 3️⃣ 九宫奇门
        qimen_monthly = self.qimen.get_full_monthly_assessment(year, month)
        qimen_score = qimen_monthly["plate_scores"].get(plate_wx, 0.0)

        # 4️⃣ 年度基调修正（基于年干司天在泉）
        base_annual = self._calc_annual_bias(plate_wx, year)

        # 加权集成
        final = (w.get("wuyun", 0) * wuyun_score +
                 w.get("capital", 0) * capital_signal +
                 w.get("qimen", 0) * qimen_score +
                 w.get("base_annual", 0) * base_annual)

        return {
            "final": round(max(-1.0, min(1.0, final)), 4),
            "wuyun": round(wuyun_score, 4),
            "capital_signal": round(capital_signal, 4),
            "capital_phase": capital_phase,
            "qimen": round(qimen_score, 4),
            "base_annual": round(base_annual, 4),
            "signals": signals,
        }

    def _calc_annual_bias(self, plate_wx: str, year: int) -> float:
        """计算年度基调修正"""
        from wuyun_core import get_ganzhi_for_year, get_sitian_zaiquan, WUYUN_MAP, LIUQI_WUXING
        year_gan = get_ganzhi_for_year(year)[0]
        dayun_wx = WUYUN_MAP.get(year_gan, "")
        sitian, zaiquan = get_sitian_zaiquan(year)
        st_wx = LIUQI_WUXING.get(sitian, "")
        zq_wx = LIUQI_WUXING.get(zaiquan, "")

        bias = 0.0
        if plate_wx == dayun_wx:
            bias += 0.20
        if plate_wx == st_wx:
            bias += 0.10
        if plate_wx == zq_wx:
            bias += 0.08
        return bias

    def run_backtest(self, year: int) -> dict:
        """全年四层回测"""
        results = []
        for m in range(1, 13):
            row = {"month": m}
            for p in PLATES:
                pred = self.predict_month(p, year, m)
                row[p] = pred["final"]
                row[f"{p}_details"] = pred
            results.append(row)
        return {"year": year, "months": results}

    def evaluate(self, year: int, test_data: dict = None) -> dict:
        """评估方向精度"""
        if test_data is None:
            test_data = load_test_suite()
        year_key = str(year)
        if year_key not in test_data:
            return {"accuracy": 0.0, "total": 0, "correct": 0}

        correct, total, plate_stats = 0, 0, {p: {"cor": 0, "tot": 0} for p in PLATES}
        predictions = self.run_backtest(year)

        for m_entry in test_data[year_key].get("months", []):
            month = m_entry["m"]
            pred_row = predictions["months"][month - 1]
            for p in PLATES:
                actual = m_entry.get(p, 0)
                pred = pred_row.get(p, 0)
                if abs(actual) > 1:
                    actual_dir = 1 if actual > 0 else -1
                else:
                    actual_dir = 0
                pred_dir = 1 if pred >= 0.03 else (-1 if pred <= -0.03 else 0)

                if actual_dir != 0 and pred_dir != 0:
                    total += 1
                    plate_stats[p]["tot"] += 1
                    if pred_dir == actual_dir:
                        correct += 1
                        plate_stats[p]["cor"] += 1

        plate_acc = {}
        for p in PLATES:
            t = plate_stats[p]["tot"]
            plate_acc[p] = round(plate_stats[p]["cor"] / t, 3) if t > 0 else 0.0

        return {
            "accuracy": round(correct / total, 4) if total > 0 else 0.0,
            "correct": correct,
            "total": total,
            "plate_accuracy": plate_acc,
            "predictions": predictions,
        }


def weight_scan(year: int = 2024, test_data: dict = None):
    """权重扫描：找最优四层权重组合"""
    if test_data is None:
        test_data = load_test_suite()

    # 权重网格
    wuyun_vals = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    capital_vals = [0.10, 0.15, 0.20, 0.25, 0.30]
    qimen_vals = [0.05, 0.10, 0.15, 0.20]

    best = {"accuracy": 0.0, "weights": {}, "config": ""}
    results = []

    for w_wuyun in wuyun_vals:
        for w_capital in capital_vals:
            for w_qimen in qimen_vals:
                w_base = max(0.0, 1.0 - w_wuyun - w_capital - w_qimen)
                if w_base < 0:
                    continue

                weights = {
                    "wuyun": w_wuyun,
                    "capital": w_capital,
                    "qimen": w_qimen,
                    "base_annual": w_base,
                }
                integrator = FourLayerIntegrator(weights)
                eval_result = integrator.evaluate(year, test_data)
                acc = eval_result["accuracy"]
                results.append({
                    "weights": dict(weights),
                    "accuracy": acc,
                    "total_evaluated": eval_result["total"],
                })

                if acc > best["accuracy"]:
                    best = {
                        "accuracy": acc,
                        "weights": dict(weights),
                        "total": eval_result["total"],
                        "correct": eval_result["correct"],
                        "plate_accuracy": eval_result["plate_accuracy"],
                    }

    # 排序输出前10
    results.sort(key=lambda r: -r["accuracy"])
    top10 = results[:10]

    return best, top10, results


def run_full_validation(years: list = None):
    """全量验证：多年度交叉验证"""
    if years is None:
        years = [2024, 2025]
    test_data = load_test_suite()
    all_results = {}

    for year in years:
        best, top10, _ = weight_scan(year, test_data)
        all_results[year] = {"best": best, "top10": top10[:5]}
        print(f"\n{'=' * 65}")
        print(f"【{year}年·四层棘轮扫描】")
        print(f"最优权重: wuyun={best['weights'].get('wuyun',0):.2f} "
              f"capital={best['weights'].get('capital',0):.2f} "
              f"qimen={best['weights'].get('qimen',0):.2f} "
              f"base={best['weights'].get('base_annual',0):.2f}")
        print(f"最优精度: {best['accuracy']:.2%} ({best.get('correct',0)}/{best.get('total',0)})")
        print(f"板块精度: {best.get('plate_accuracy', {})}")
        print(f"\nTop5权重组合:")
        for i, r in enumerate(top10[:5]):
            w = r['weights']
            print(f"  #{i+1}: wuyun={w['wuyun']:.2f} cap={w['capital']:.2f} "
                  f"qimen={w['qimen']:.2f} base={w['base_annual']:.2f} → {r['accuracy']:.2%}")

    # 稳健性测试：用2024最优权重跑2025
    if len(years) >= 2:
        y2024best = all_results.get(2024, {}).get("best", {})
        y2025best = all_results.get(2025, {}).get("best", {})
        print(f"\n{'=' * 65}")
        print(f"【跨年泛化测试】")
        print(f"2024最优精度: {y2024best.get('accuracy', 0):.2%}")
        print(f"2025最优精度: {y2025best.get('accuracy', 0):.2%}")

        # 用2024最优权重跑2025
        w = y2024best.get("weights", DEFAULT_WEIGHTS)
        integrator = FourLayerIntegrator(w)
        y2025_result = integrator.evaluate(2025, test_data)
        print(f"2024权重 → 2025泛化: {y2025_result['accuracy']:.2%}")
        print(f"板块精度 (2025): {y2025_result.get('plate_accuracy', {})}")

        all_results["cross_year"] = {
            "y2024_weights_on_2025": y2025_result["accuracy"],
            "plate_2025": y2025_result.get("plate_accuracy", {}),
        }

    return all_results


if __name__ == "__main__":
    import time
    t0 = time.time()

    print("=" * 65)
    print("四层棘轮 v2.0 · 全链路参数扫描 + 验证")
    print("=" * 65)

    all_results = run_full_validation([2024, 2025])

    # 最优权重运用于当前实时推演
    best_2024 = all_results.get(2024, {}).get("best", {})
    best_weights = best_2024.get("weights", DEFAULT_WEIGHTS)
    print(f"\n{'=' * 65}")
    print(f"【最优权重存档】")
    print(json.dumps(best_weights, indent=2, ensure_ascii=False))

    elapsed = time.time() - t0
    print(f"\n扫描耗时: {elapsed:.1f}s")
    print(f"扫描组合数: ~{6*4*3*4}")

    # 保存结果
    out = {
        "timestamp": datetime.now().isoformat(),
        "version": "v2.0-four-layer",
        "best_weights": best_weights,
        "best_2024_accuracy": best_2024.get("accuracy", 0),
        "best_2025_accuracy": all_results.get(2025, {}).get("best", {}).get("accuracy", 0),
        "cross_year_validation": all_results.get("cross_year", {}).get("y2024_weights_on_2025", 0),
        "plate_2024": best_2024.get("plate_accuracy", {}),
        "plate_2025": all_results.get(2025, {}).get("best", {}).get("plate_accuracy", {}),
    }
    out_path = os.path.join(_SCRIPT_DIR, "..", "data", "four_layer_ratchet_result_v2.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")
