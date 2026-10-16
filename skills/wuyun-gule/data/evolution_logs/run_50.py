import sys, os, json
from pathlib import Path

# Fixed paths
SKILL_DIR = Path(r"I:\ai\openakita-main\skills\wuyun-gule")
SCRIPTS_DIR = SKILL_DIR / "scripts"
LOG_DIR = SKILL_DIR / "data" / "evolution_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from evolve_wuyun_sizhu_pi import PiEvolution, load_test_data
from datetime import datetime

test_data = load_test_data()

# Run 50-iteration evolution
evo = PiEvolution(test_data)
result = evo.run_evolution(max_iterations=50, enable_ternary=True)

# Baseline comparison
baseline = evo.evaluate_params({"year": 0.35, "month": 0.30, "day": 0.20, "hour": 0.15}, 0.03)

summary = {
    "timestamp": datetime.now().isoformat(),
    "baseline_accuracy": round(baseline["accuracy"] * 100, 1),
    "best_accuracy": round(result["best_accuracy"] * 100, 1),
    "best_weights": result["best_weights"],
    "evolution_cycles": result["evolution_cycles"],
    "improvement": round(result["best_accuracy"] * 100 - baseline["accuracy"] * 100, 1),
}

with open(str(LOG_DIR / "full_evolution_summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"📊 最终总结")
print(f"   基线精度: {summary['baseline_accuracy']}%")
print(f"   最优精度: {summary['best_accuracy']}%")
print(f"   提   升: +{summary['improvement']}%")
print(f"   最优权重: Y={summary['best_weights']['year']:.2f} M={summary['best_weights']['month']:.2f} D={summary['best_weights']['day']:.2f} H={summary['best_weights']['hour']:.2f}")
print(f"   棘轮轮次: {summary['evolution_cycles']}")
print(f"{'='*60}")
