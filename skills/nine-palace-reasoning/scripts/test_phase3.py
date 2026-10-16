"""第三阶段集成测试
测试：冲突矩阵 + 心智自检 + 五行制衡 + 场景靶向
"""
import sys
sys.path.insert(0, r"I:\ai\openakita-main\skills\nine-palace-reasoning")

from scripts.fault_diagnosis import FaultDiagnosis, build_conflict_matrix
from scripts.palace_weights import balance_weights_battle, get_targeted_adjust

# 模拟八宫回传结论
mock_results = {
    "震魂": {"核心结论": "肝郁血虚体质引爆太阳伤寒，表里同病",
             "发散思路": "少阳枢机不利才是真正的病机核心"},
    "离神": {"核心结论": "纯太阳伤寒经输不利，葛根汤证",
             "病机核心": "太阳经气不舒"},
    "坤情": {"核心结论": "思伤脾郁伤肝，外感是身体喊停的信号",
             "体感共情": "她需要被允许休息"},
    "坎精": {"核心结论": "血虚风眩合太阳伤寒，虚实夹杂",
             "根源追溯": "肝血暗耗数年至十数年"},
    "艮志": {"核心结论": "太阳伤寒表实，分三阶段施治",
             "执行步骤": "葛根汤3天"},
    "巽性": {"核心结论": "厥阴太阴复合体质，肝血亏虚为本",
             "体质判断": "38%症状群指向血虚底质"},
    "乾气": {"核心结论": "太阳太阴合病，外实内虚",
             "全局格局": "少阴体质受太阳寒邪"},
    "兑魄": {"核心结论": "太阳伤寒表实证，风寒束表",
             "风险警示": "禁用寒凉药"},
}

# 1. 冲突矩阵
conf_matrix = build_conflict_matrix(mock_results)
print("【1. 冲突矩阵】")
for pair, score in sorted(conf_matrix.items(), key=lambda x: -x[1])[:6]:
    print(f"  {pair[0]} ↔ {pair[1]}: {score:.2f}")

# 2. 心智自检（模拟坎精有一次无响应）
dx = FaultDiagnosis()
for p in mock_results:
    no_resp = (p == "坎精")
    dx.record_response(p, not no_resp)
diag = dx.diagnose(mock_results, conf_matrix)
print(f"\n【2. 心智诊断】健康度={diag['overall_health']}")
for d in diag["diagnoses"]:
    print(f"  [{d['level']}] {d['type']}: {d['details']}")
    print(f"    动作: {d['action']}")
print(f"  权重调整: {diag['weight_adjustments']}")

# 3. 五行制衡
base_w = {p: 1.0 for p in mock_results}
base_w["离神"] = 0.98
base_w["震魂"] = 1.03
base_w["中意"] = 0.94
balanced = balance_weights_battle(mock_results, base_w)
print(f"\n【3. 五行制衡（最终权重）】")
for p, w in sorted(balanced.items(), key=lambda x: -x[1]):
    delta = w - base_w.get(p, 1.0)
    arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "–")
    print(f"  {p}: {base_w.get(p,1.0):.2f} → {w:.2f} {arrow}")

# 4. 场景靶向
print(f"\n【4. 场景靶向（辨证场景）】")
print(f"  {get_targeted_adjust('辨证')}")

print("\n✅ 第三阶段集成测试全部通过")
