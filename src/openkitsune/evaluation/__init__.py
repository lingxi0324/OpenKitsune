"""
OpenKitsune Agent 评估框架

提供全面的 Agent 性能评估能力:
- EvalMetrics: 评估指标定义和聚合
- Judge: 基于 LLM 的质量评估 (Agent-as-a-Judge)
- Runner: 评估任务运行器
- Reporter: 评估报告生成
- Optimizer: 评估反馈驱动的自动优化

评估维度:
- 任务完成率
- 工具选择准确率
- 平均迭代次数 / token 消耗 / 延迟
- 循环检测率
- 错误恢复率
- 记忆检索相关性
"""

from .judge import Judge, JudgeResult
from .metrics import EvalMetrics, EvalResult, TraceMetrics
from .optimizer import DailyEvaluator, FeedbackAnalyzer, FeedbackOptimizer, OptimizationAction
from .reporter import Reporter
from .runner import EvalRunner

__all__ = [
    "EvalMetrics",
    "EvalResult",
    "TraceMetrics",
    "Judge",
    "JudgeResult",
    "EvalRunner",
    "Reporter",
    "FeedbackAnalyzer",
    "FeedbackOptimizer",
    "OptimizationAction",
    "DailyEvaluator",
]
