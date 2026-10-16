"""
资本行为集成层 · CapitalBehaviorIntegration (v1.0)
===============================================
将资本行为引擎作为第五维度，叠加在四柱之上。
核心机制：
- 资本在"郁气积累 > 阈值"的板块抄底（推高评分）
- 资本在"涨势过盛 > 阈值"的板块收割（压低评分）
- 抄底和收割之间存在时间差（积累→爆发周期）
"""

import os, sys, json
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from capital_behavior import CapitalBehaviorEngine, PLATES, SHENG_CYCLE, KE_CYCLE


class CapitalIntegration:
    def cold_start_boost(self, plate_wx, year, month, raw_score):
        """首月冷启动：用初始评分方向代替历史"""
        if month <= 2:
            return raw_score * 0.3 if abs(raw_score) > 0.1 else 0
        return 0

    """
    资本行为集成器
    将四柱评分通过资本行为阶段进行调制
    """
    
    # 资本行为阶段对评分的调制系数
    PHASE_MODULATION = {
        "观望": 1.0,    # 不干预
        "抄底": 1.3,    # 资金流入，推高真实涨幅
        "推升": 1.2,    # 持续推动
        "收割": 0.6,    # 资金流出，压低涨幅甚至反转
        "离场": 0.8,    # 余波
    }
    
    # 各阶段的时间窗口（月数）
    PHASE_DURATION = {
        "抄底": 2,
        "推升": 2,
        "收割": 1.5,
        "离场": 1,
        "观望": 99,
    }
    
    def __init__(self, active_level=1.0, capital_weight=0.20):
        self.engine = CapitalBehaviorEngine(active_level=active_level)
        self.active_level = active_level
        self.capital_weight = capital_weight  # 资本行为在最终评分中的权重
        self.history = {}  # 记录各板块各月评分
        
    def modulate_score(self, plate_wx, raw_score, year, month, prev_scores=None):
        """
        用资本行为阶段调制四柱评分
        Args:
            plate_wx: 板块五行
            raw_score: 四柱引擎原始评分 (-1~1)
            year, month: 年月
            prev_scores: 历史评分（用于判断积累/释放状态）
        Returns:
            modulated_score: 调制后评分
            phase: 资本所处阶段
        """
        # 1. 获取资本对该板块的判读
        phase_data = self.engine.assess_plate(
            plate_wx, raw_score, year, month, prev_scores
        )
        phase = phase_data.get("phase", "观望")
        
        # 2. 应用调制系数
        mod = self.PHASE_MODULATION.get(phase, 1.0)
        modulated = raw_score * (1.0 - self.capital_weight) + raw_score * self.capital_weight * mod
        
        # 3. 极端修正
        if phase == "抄底" and raw_score < -0.3:
            modulated += 0.15  # 被低估时资本介入提供底部支撑
        elif phase == "收割" and raw_score > 0.3:
            modulated -= 0.15  # 涨势过盛时资本收割压低
        
        return max(-1.0, min(1.0, modulated)), phase
    
    def assess_plate(self, plate_wx, raw_score, year, month, prev_scores=None):
        """四层集成：返回阶段+评分信号+调制后评分"""
        raw = self.engine.assess_plate(plate_wx, raw_score, year, month, prev_scores)
        phase = raw.get('phase', '观望')
        # 计算signal：基于阶段的调制信号
        mod = self.PHASE_MODULATION.get(phase, 1.0)
        signal = raw_score * (mod - 1.0) * self.capital_weight
        return {
            'phase': phase,
            'signal': max(-0.5, min(0.5, signal)),
            'raw_score': raw_score,
            'modulated': raw_score + signal,
        }
    
    def get_state(self):
        """返回当前全部板块的资本阶段状态"""
        return {
            "active_level": self.active_level,
            "capital_weight": self.capital_weight,
            "positions": self.engine.position,
            "phases": self.engine.phase,
        }


if __name__ == "__main__":
    ci = CapitalIntegration(active_level=1.0, capital_weight=0.20)
    for plate in PLATES:
        result = ci.assess_plate(plate, 0.0, 2024, 6)
        print(f"{plate}: {result['phase']} (signal={result.get('signal',0):.3f})")
    print("CapitalIntegration OK")
