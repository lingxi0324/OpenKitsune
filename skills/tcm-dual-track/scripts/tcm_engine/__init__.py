# -*- coding: utf-8 -*-
"""中医辨证计算引擎（移植自 hermes divination/tcm）。

公开 API：
  - build_dialectic_input() / normalize_symptoms()   输入归一化
  - dialectic()                                      双轨辨证统一管线
  - liujing_score()                                  六经加权评分
  - analyze_formula() / analyze_recommended_formulas()
  - wuyun_full_chain() / build_wuyun_output()        五运六气
  - tide_context()                                   潮汐上下文
  - plan()                                           北斗七星针法
  - build_prescription()                             处方（组成/加减/药证映射）
"""

from .clinical_types import DialecticInput
from .dialectic import dialectic
from .liujing import liujing_score
from .normalize import build_dialectic_input, normalize_pulse, normalize_symptoms
from .wuwei import FORMULAS, CLASSIC_ALIASES, CLASSIC_ONLY, analyze_formula, analyze_recommended_formulas
from .wuyun import build_wuyun_output, wuyun_full_chain
from .tide import tide_context
from .acupuncture.planner import plan
from .prescription import build_prescription

__version__ = "1.10.0-openkitsune"

__all__ = [
    "DialecticInput",
    "dialectic",
    "liujing_score",
    "build_dialectic_input",
    "normalize_pulse",
    "normalize_symptoms",
    "FORMULAS",
    "CLASSIC_ALIASES",
    "CLASSIC_ONLY",
    "analyze_formula",
    "analyze_recommended_formulas",
    "wuyun_full_chain",
    "build_wuyun_output",
    "tide_context",
    "plan",
    "build_prescription",
]
