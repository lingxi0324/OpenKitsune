"""
心智紊乱自检 · 故障诊断与优雅降级
====================================
联动 FaultDiagnosis 体系，实时监控八宫心智状态。

检测维度：
1. 决策内耗 — 多宫结论严重对立冲突
2. 局部缺损 — 单宫长期无响应/结论质量骤降
3. 感知失真 — 多宫感知结论偏差过大

每个维度都有自愈策略，无需人工干预。
"""

import json
import os
from pathlib import Path
from datetime import datetime

# ─── 诊断日志路径 ───
_SCRIPT_DIR = Path(__file__).resolve().parent
DX_LOG_PATH = _SCRIPT_DIR / ".." / "data" / "fault_diagnosis_log.json"

# ─── 阈值配置（可自适应调整） ───
THRESHOLDS = {
    "决策内耗": {
        "warning": 0.5,   # 平均冲突度 > 0.5 → 警告
        "critical": 0.75, # 平均冲突度 > 0.75 → 严重，触发降级
    },
    "局部缺损": {
        "warning": 1,     # 连续 1 次无响应 → 开始记录
        "critical": 3,    # 连续 3 次无响应 → 降级
    },
    "感知失真": {
        "warning": 0.6,   # 某宫与多数宫偏差 > 0.6 → 标记
        "critical": 0.8,  # 偏差 > 0.8 → 过滤该宫结论
    },
}


class FaultDiagnosis:
    """心智紊乱自检器"""

    def __init__(self):
        self._history = self._load_history()
        # 各宫历史跟踪
        self._palace_stats: dict[str, dict] = self._history.get("palace_stats", {})
        # 会话级诊断结果缓存
        self._session_diagnosis: dict = {}

    def _load_history(self) -> dict:
        """加载持久化诊断历史"""
        path = DX_LOG_PATH
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"palace_stats": {}, "diagnosis_history": []}

    def _save_history(self):
        """持久化诊断历史"""
        path = DX_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "palace_stats": self._palace_stats,
                "diagnosis_history": self._history.get("diagnosis_history", []),
            }, f, ensure_ascii=False, indent=2)

    def record_response(
        self,
        palace_name: str,
        responded: bool = True,
        conflict_scores: dict[str, float] = None,
    ):
        """记录一次宫位响应状态"""
        if palace_name not in self._palace_stats:
            self._palace_stats[palace_name] = {
                "total_calls": 0,
                "no_responses": 0,
                "consecutive_no_response": 0,
                "avg_conflict": 0.0,
                "conflict_history": [],
                "last_health": "normal",
            }

        stat = self._palace_stats[palace_name]
        stat["total_calls"] += 1

        if not responded:
            stat["no_responses"] += 1
            stat["consecutive_no_response"] += 1
        else:
            stat["consecutive_no_response"] = 0

        if conflict_scores:
            avg = sum(conflict_scores.values()) / max(len(conflict_scores), 1)
            stat["conflict_history"].append(avg)
            # 只保留最近 10 次
            if len(stat["conflict_history"]) > 10:
                stat["conflict_history"] = stat["conflict_history"][-10:]
            stat["avg_conflict"] = sum(stat["conflict_history"]) / max(len(stat["conflict_history"]), 1)

        self._save_history()

    def diagnose(
        self,
        palace_results: dict[str, dict],
        palace_conflicts: dict[tuple[str, str], float] = None,
    ) -> dict:
        """
        对本次推演结果进行心智状态诊断。

        Returns:
        {
            "overall_health": "normal"|"warning"|"critical",
            "diagnoses": [
                {
                    "type": "决策内耗"|"局部缺损"|"感知失真",
                    "level": "normal"|"warning"|"critical",
                    "details": str,
                    "action": str  # 自动采取的自愈动作
                }
            ],
            "weight_adjustments": {宫名: 额外权重修正因子},
            "analysis": str  # 通俗解读
        }
        """
        diagnoses = []
        weight_adj = {}
        palace_names = list(palace_results.keys())

        # ─── 检测 1：决策内耗 ───
        if len(palace_names) >= 3:
            total_conflict = 0.0
            pairs = 0
            for i in range(len(palace_names)):
                for j in range(i + 1, len(palace_names)):
                    p1, p2 = palace_names[i], palace_names[j]
                    if p1 in palace_results and p2 in palace_results:
                        conf = palace_conflicts.get((p1, p2), 0.5) if palace_conflicts else 0.5
                        total_conflict += conf
                        pairs += 1

            avg_conflict = total_conflict / max(pairs, 1)

            if avg_conflict > THRESHOLDS["决策内耗"]["critical"]:
                diagnoses.append({
                    "type": "决策内耗",
                    "level": "critical",
                    "details": f"八宫平均冲突度 {avg_conflict:.2f}，严重对立",
                    "action": "中宫权重提升 30%，采纳多数派结论，少数派仅保留风险提示",
                })
                weight_adj["中意"] = 1.3
            elif avg_conflict > THRESHOLDS["决策内耗"]["warning"]:
                diagnoses.append({
                    "type": "决策内耗",
                    "level": "warning",
                    "details": f"八宫平均冲突度 {avg_conflict:.2f}，存在显著分歧",
                    "action": "中宫权重提升 15%，优先采信离神和乾气的结论",
                })
                weight_adj["中意"] = 1.15

        # ─── 检测 2：局部缺损 ───
        for p in self._palace_stats:
            stat = self._palace_stats[p]
            if stat["consecutive_no_response"] >= THRESHOLDS["局部缺损"]["critical"]:
                diagnoses.append({
                    "type": "局部缺损",
                    "level": "critical",
                    "details": f"{p} 连续 {stat['consecutive_no_response']} 次无响应",
                    "action": f"自动降低 {p} 权重至 0.5，由相生宫 {_get_sheng_mother(p)} 代行其视角",
                })
                weight_adj[p] = 0.5
            elif stat["consecutive_no_response"] >= THRESHOLDS["局部缺损"]["warning"]:
                diagnoses.append({
                    "type": "局部缺损",
                    "level": "warning",
                    "details": f"{p} 已出现 1 次无响应",
                    "action": f"监控 {p} 下次响应状态",
                })

        # ─── 检测 3：感知失真 ───
        if palace_conflicts and len(palace_names) >= 3:
            for p in palace_names:
                if p == "中意":
                    continue
                conflicts_with_others = [
                    palace_conflicts.get((p, q), 0.0) or palace_conflicts.get((q, p), 0.0)
                    for q in palace_names if q != p and q != "中意"
                ]
                if not conflicts_with_others:
                    continue
                avg_dev = sum(conflicts_with_others) / len(conflicts_with_others)
                if avg_dev > THRESHOLDS["感知失真"]["critical"]:
                    diagnoses.append({
                        "type": "感知失真",
                        "level": "critical",
                        "details": f"{p} 与多数宫平均偏差 {avg_dev:.2f}，观点可能异常",
                        "action": f"过滤 {p} 观点，不纳入中宫整合的主体结论，保留为「异议观点」附录",
                    })
                    weight_adj[p] = 0.3

        # ─── 确定整体健康度 ───
        if any(d["level"] == "critical" for d in diagnoses):
            overall_health = "critical"
        elif any(d["level"] == "warning" for d in diagnoses):
            overall_health = "warning"
        else:
            overall_health = "normal"

        # ─── 通俗解读 ───
        analysis = self._make_analysis(overall_health, diagnoses)

        result = {
            "overall_health": overall_health,
            "diagnoses": diagnoses,
            "weight_adjustments": weight_adj,
            "analysis": analysis,
        }

        self._session_diagnosis = result
        self._history.setdefault("diagnosis_history", []).append({
            "time": datetime.now().isoformat(),
            "overall_health": overall_health,
            "diagnoses_count": len(diagnoses),
        })
        self._save_history()

        return result

    def _make_analysis(self, health: str, diagnoses: list) -> str:
        """生成通俗解读"""
        if health == "normal":
            return "八宫心智状态稳定，无异常。可直接进入整合阶段。"

        parts = []
        for d in diagnoses:
            level_label = "⚠️" if d["level"] == "warning" else "🔴"
            parts.append(f"{level_label} {d['type']}：{d['details']}")

        if health == "critical":
            parts.append("已启动优雅降级——异常宫位权重已调整，整合结论将优先采纳健康宫位的观点。")
        else:
            parts.append("轻度异常已记录，不影响本次整合。")

        return "\n".join(parts)


def _get_sheng_mother(palace_name: str) -> str:
    """返回生该宫的宫位"""
    from .palace_weights import PALACE_FIVE_ELEMENT, SHENG_MAP, KE_MAP
    elem = PALACE_FIVE_ELEMENT.get(palace_name, "土")
    mother_elem = None
    for k, v in SHENG_MAP.items():
        if v == elem:
            mother_elem = k
            break
    if not mother_elem:
        return palace_name
    for name, e in PALACE_FIVE_ELEMENT.items():
        if e == mother_elem and name != palace_name:
            return name
    return palace_name


def build_conflict_matrix(palace_results: dict[str, dict]) -> dict[tuple[str, str], float]:
    """
    根据八宫结论构建冲突矩阵。

    Returns:
        {(宫A, 宫B): 冲突度(0~1)}
    """
    from .palace_weights import _estimate_agreement

    matrix = {}
    names = list(palace_results.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            p1, p2 = names[i], names[j]
            if p1 in palace_results and p2 in palace_results:
                agreement = _estimate_agreement(palace_results[p1], palace_results[p2])
                conflict = 1.0 - agreement
                matrix[(p1, p2)] = round(conflict, 3)
                matrix[(p2, p1)] = round(conflict, 3)
    return matrix


if __name__ == "__main__":
    dx = FaultDiagnosis()
    print(f"✅ fault_diagnosis.py 自检通过")
    print(f"  历史记录数: {len(dx._palace_stats)}个宫")
    print(f"  诊断记录数: {len(dx._history.get('diagnosis_history', []))}次")
