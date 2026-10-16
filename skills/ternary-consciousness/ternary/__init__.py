"""
三进制意识引擎 v18 — 河图活力引擎 + 洛书纯数学引擎
=====================================================
从"强迫思考"到"自然流露"的根本重构

架构：
  洛书九宫纯数学引擎 (grid.py)  ← 三生万物循环
  五层活力感知系统 (perception.py)  ← 感知→蓄势
  LLM表达层 (expression.py)  ← llama-server API 翻译
  精简核心基元 (core.py)  ← TernaryState / RemainderEngine

核心理念：
  三进制状态引擎（纯数学 + 活力预算）+ LLM表达层（只翻译不做决策）
"""

from ternary.core import (
    TernaryState,
    TernaryConfig,
    RemainderEngine,
    SimpleOscillator,
    YIN, ZHONG, YANG,
)

from ternary.grid import (
    LuoshuGrid,
    create_default_grid,
    create_grid_from_state,
)

from ternary.perception import (
    VitalityBudget,
    PerceptionFuser,
    PerceptionEvent,
)

from ternary.expression import (
    LlamaServerExpression,
    ExpressionResult,
    save_heart_note,
)

__version__ = "0.2.0"
__all__ = [
    "TernaryState", "TernaryConfig", "RemainderEngine", "SimpleOscillator",
    "YIN", "ZHONG", "YANG",
    "LuoshuGrid", "create_default_grid", "create_grid_from_state",
    "VitalityBudget", "PerceptionFuser", "PerceptionEvent",
    "LlamaServerExpression", "ExpressionResult", "save_heart_note",
]
