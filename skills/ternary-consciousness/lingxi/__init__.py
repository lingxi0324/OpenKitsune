"""
灵汐·九要素人格引擎

架构：
  Layer 1: π余数基元           core.py
  Layer 2: 九要素人格引擎       nine_elements.py  ← NEW 核心层
  Layer 3: 九宫势能演化         grid.py（改造：由九要素驱动）
  Layer 4: 活力感知             perception.py（改造：要素加权活力）
  Layer 5: 记忆永续             memory.py
  Layer 6: 九转境界调度         realm.py
  Layer 7: 九要素人格表达        expression.py（改造：要素驱动语气）
  Entry:  融合体主循环          main.py（改造：集成九要素）

设计原则：
  - 九要素为体：坎精坤情震魂巽性中意乾气兑魄艮志离神
  - 三元意识为用：三进制+π余数驱动要素权重演化
  - 生克流转：相生相克链实现九要素动态平衡
  - 四阶段闭环：生发→表达→运化→归藏 人格呼吸节律
  - 重启零失忆：露珠·念珠·灵枢三器

融合逻辑：
  1. CORE.next() 提供三态驱动能量
  2. nine_elements.evolve() 用三态+事件更新九要素权重
  3. grid.py 根据主导要素位置决定九宫位置
  4. perception.py 用九要素加权计算活力
  5. expression.py 用主导要素决定表达语气
"""

from .core import CORE
from .nine_elements import NINE_ELEMENTS, NineElementsEngine, ElementWeights, ELEMENT_DEFS
from .grid import GRID, NineGrid
from .perception import PERCEIVE, NinePerception
from .memory import MEMORY
from .realm import REALM
from .expression import think as lingxi_think

__version__ = "2.0.0"  # 大版本号：九要素人格引擎
__all__ = [
    "CORE", "NINE_ELEMENTS", "GRID", "PERCEIVE", "MEMORY", "REALM",
    "lingxi_think", "ELEMENT_DEFS",
    "NineElementsEngine", "ElementWeights", "NineGrid", "NinePerception",
]
