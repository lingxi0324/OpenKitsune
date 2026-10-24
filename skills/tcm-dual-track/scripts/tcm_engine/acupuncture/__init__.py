# -*- coding: utf-8 -*-
"""北斗七星针法模块（移植自 hermes divination/acupuncture）。"""

from .planner import (
    Acupoint,
    Formula,
    STAR_ACUPOINTS,
    additions,
    detect_syndrome,
    moxibustion,
    plan,
    rx_pick_for_jing,
    star_alternatives,
    syndrome_map,
    verse,
)

__all__ = [
    "Acupoint",
    "Formula",
    "STAR_ACUPOINTS",
    "additions",
    "detect_syndrome",
    "moxibustion",
    "plan",
    "rx_pick_for_jing",
    "star_alternatives",
    "syndrome_map",
    "verse",
]
