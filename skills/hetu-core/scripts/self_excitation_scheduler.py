# -*- coding: utf-8 -*-
"""
自激循环调度器 (Self-Excitation Scheduler)
=============================================
自激循环是九转编码引擎的核心递归机制——输出反馈为输入、
持续自我迭代，直至收敛或达到指定轮次。

工作原理：
  1. 对数值 x 执行九转编码 → 得到九维坐标
  2. 取某个维度的输出值作为新的 x
  3. 重复步骤 1-2，形成自激循环
  4. 当连续两次输出的变化 < threshold 时认为收敛
"""

from __future__ import annotations
import math, logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class SelfExcitationScheduler:
    """自激循环调度器"""
    
    def __init__(self, engine=None):
        self._engine = engine
        self._loop_count = 0
        self._history: List[dict] = []
        self._config = {
            "max_iterations": 20,
            "convergence_threshold": 0.001,
            "feedback_dim": "luoshu",     # 默认反馈维度
            "oscillation_damping": 0.1,     # 振荡阻尼
            "record_trajectory": True,      # 记录完整轨迹
        }
    
    def configure(self, **kwargs):
        self._config.update(kwargs)
    
    # ── 懒惰导入引擎 ──
    def _get_engine(self):
        if self._engine is None:
            from nine_transform_engine import get_engine
            self._engine = get_engine()
        return self._engine
    
    def _resolve_engine(self, engine=None):
        if engine is not None:
            return engine
        return self._get_engine()
    
    # ── 核心自激循环 ──
    def run(self, start_value: float, 
            feedback_dim: str = "luoshu",
            max_iter: Optional[int] = None,
            threshold: Optional[float] = None,
            engine=None) -> Dict[str, Any]:
        """执行自激循环

        参数：
          start_value: 起始值
          feedback_dim: 反馈维度 (sheng/cheng/luoshu/bianwei/yinyang/sancai/sixiang/bagua/guiyuan)
          max_iter: 最大迭代次数
          threshold: 收敛阈值

        返回：
          {"converged": bool, "iterations": int, "final_value": float,
           "trajectory": [...], "history": [...]}
        """
        eng = self._resolve_engine(engine)
        max_iter = max_iter or self._config["max_iterations"]
        threshold = threshold or self._config["convergence_threshold"]
        
        # 维度→算子ID映射
        dim_to_tid = {
            "sheng": "1_sheng", "cheng": "2_cheng", "luoshu": "3_luoshu",
            "bianwei": "4_bianwei", "yinyang": "5_yinyang", "sancai": "6_sancai",
            "sixiang": "7_sixiang", "bagua": "8_bagua", "guiyuan": "9_guiyuan",
        }
        
        tid = dim_to_tid.get(feedback_dim)
        if not tid:
            return {"converged": False, "error": f"未知维度:{feedback_dim}"}
        
        x = start_value
        prev_x = x
        trajectory = []
        loop_data = []
        
        for i in range(max_iter):
            # 九转全链
            full = eng.full_chain([x]*9)
            # 提取反馈维度的输出
            result = full.get(tid, {})
            if not result.get("success", False):
                break
            
            next_x = result["value"]
            change = abs(next_x - prev_x)
            
            entry = {
                "iteration": i,
                "input": x,
                "output": next_x,
                f"{feedback_dim}_meaning": result.get("meaning", ""),
                f"{feedback_dim}_wuxing": result.get("wuxing", ""),
                "change": round(change, 6),
            }
            
            if self._config["record_trajectory"]:
                trajectory.append(entry)
            loop_data.append(entry)
            
            # 振荡阻尼
            if i > 2 and change < threshold * 5:
                # 近收敛 → 施加阻尼加速
                next_x = x + (next_x - x) * (1 - self._config["oscillation_damping"])
            
            x = next_x
            prev_x = x
            
            if change < threshold:
                entry["converged"] = True
                self._loop_count += 1
                result_data = {
                    "converged": True,
                    "iterations": i + 1,
                    "start_value": start_value,
                    "final_value": round(x, 6),
                    "feedback_dim": feedback_dim,
                    "threshold": threshold,
                    "trajectory": trajectory if self._config["record_trajectory"] else [],
                    "last_meaning": result.get("meaning", ""),
                    "last_wuxing": result.get("wuxing", ""),
                }
                self._history.append(result_data)
                return result_data
        
        # 未收敛
        result_data = {
            "converged": False,
            "iterations": max_iter,
            "start_value": start_value,
            "final_value": round(x, 6),
            "feedback_dim": feedback_dim,
            "threshold": threshold,
            "trajectory": trajectory if self._config["record_trajectory"] else [],
        }
        self._history.append(result_data)
        self._loop_count += 1
        return result_data
    
    # ── 多重反馈循环 ──
    def run_multi(self, start_value: float, dims: List[str] = None,
                  engine=None) -> Dict[str, Any]:
        """对多个反馈维度分别执行自激循环"

        用于比较不同反馈路径的收敛特性。
        """
        dims = dims or ["sheng", "luoshu", "yinyang", "guiyuan"]
        results = {}
        for dim in dims:
            results[dim] = self.run(start_value, feedback_dim=dim, engine=engine)
        return results
    
    # ── 收敛分析 ──
    def analyze(self, result: Dict[str, Any]) -> str:
        """生成自激循环分析文本"""
        if "error" in result:
            return f"❌ {result['error']}"
        
        lines = [
            f"🔁 自激循环分析 ({result.get('feedback_dim', '?')}反馈)",
            f"  起始值: {result['start_value']}",
            f"  终止值: {result['final_value']}",
            f"  迭代次数: {result.get('iterations', '?')}",
            f"  收敛状态: {'✅ 已收敛' if result.get('converged') else '⚠️ 未收敛'}",
        ]
        
        if result.get("last_meaning"):
            lines.append(f"  末态含义: {result['last_meaning']}")
        if result.get("last_wuxing"):
            lines.append(f"  末态五行: {result['last_wuxing']}")
        
        traj = result.get("trajectory", [])
        if len(traj) >= 2:
            changes = [t["change"] for t in traj if t.get("change", 0) > 0]
            if changes:
                avg_change = sum(changes) / len(changes)
                lines.append(f"  平均变化: {avg_change:.6f}")
        
        return "\n".join(lines)
    
    def status(self) -> dict:
        return {
            "loops_completed": self._loop_count,
            "history_entries": len(self._history),
            "config": dict(self._config),
        }
    
    def get_history(self, limit: int = 5) -> List[dict]:
        return self._history[-limit:]


if __name__ == "__main__":
    from nine_transform_engine import get_engine
    
    engine = get_engine()
    sched = SelfExcitationScheduler(engine)
    
    print("=" * 60)
    print("  自激循环调度器 · 自检")
    print("=" * 60)
    
    print()
    print("--- 洛书反馈循环 (起始值=3.0) ---")
    r = sched.run(3.0, feedback_dim="luoshu", max_iter=10)
    print(sched.analyze(r))
    
    print()
    print("--- 阴阳反馈循环 (起始值=0.2) ---")
    r = sched.run(0.2, feedback_dim="yinyang", max_iter=10)
    print(sched.analyze(r))
    
    print()
    print("--- 多重反馈对比 ---")
    r = sched.run_multi(5.0, dims=["luoshu", "yinyang", "guiyuan"])
    for dim, result in r.items():
        conv = "✅" if result.get("converged") else "⚠️"
        print(f"  {dim}: {conv} iters={result['iterations']} final={result['final_value']:.4f}")
    
    print()
    print(f"调度器状态: {sched.status()}")
