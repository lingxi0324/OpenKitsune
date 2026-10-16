"""
【第一层：三进制物理基元底层】
=================================

保留的核心基元：
  1. TernaryState — 三态状态容器
  2. TernaryConfig — 系统配置
  3. RemainderEngine — 内禀余数偏差算法
  4. SimpleOscillator — 精简版三态漂移器（替代原 scheduler）

哲学:
  - 阴(-1) | 中(0) | 阳(+1)
  - 允执厥中：中态为锚
  - 内禀余数失衡：永不绝对平衡
  - 三生万物：3步一周期自然循环
"""

import math
import random
from typing import Optional, Tuple, List
from dataclasses import dataclass, field


# ============================================================
# 三进制基元常量
# ============================================================
YIN = -1      # 阴态：收敛、抑制、记忆沉淀
ZHONG = 0     # 中态：厥中本位、锚定坚守
YANG = 1      # 阳态：发散、联想、探索输出

TERNARY_VALUES = (YIN, ZHONG, YANG)
TERNARY_LABELS = {
    YIN: "阴态",
    ZHONG: "中态·厥中本位",
    YANG: "阳态",
}


# ============================================================
# 三态状态容器
# ============================================================
@dataclass
class TernaryState:
    """三进制状态容器"""
    yin_weight: float = 0.0
    zhong_weight: float = 0.0
    yang_weight: float = 0.0
    remainder: float = 0.0
    timestamp: int = 0
    
    @property
    def total(self) -> float:
        """三态权重和"""
        return self.yin_weight + self.zhong_weight + self.yang_weight
    
    @property
    def normalized(self) -> Tuple[float, float, float]:
        """归一化三态权重 (概率分布)"""
        s = self.total
        if s == 0:
            return (1/3, 1/3, 1/3)
        return (self.yin_weight/s, self.zhong_weight/s, self.yang_weight/s)
    
    @property
    def dominant(self) -> int:
        """当前主导态 -1:阴, 0:中, 1:阳"""
        norm = self.normalized
        idx = max(range(3), key=lambda i: norm[i])
        return [YIN, ZHONG, YANG][idx]
    
    def clone(self) -> "TernaryState":
        return TernaryState(
            yin_weight=self.yin_weight,
            zhong_weight=self.zhong_weight,
            yang_weight=self.yang_weight,
            remainder=self.remainder,
            timestamp=self.timestamp + 1,
        )
    
    def __repr__(self) -> str:
        return (f"TernaryState(阴={self.yin_weight:.4f}, "
                f"中={self.zhong_weight:.4f}, "
                f"阳={self.yang_weight:.4f}, "
                f"余数R={self.remainder:.6f}, "
                f"轮次={self.timestamp})")


# ============================================================
# 内禀余数引擎
# ============================================================
class RemainderEngine:
    """
    内禀余数偏差算法引擎
    
    核心公式：R = (W_阳 - W_阴) mod 2
    约束：|R| >= R_min
    """
    def __init__(self, r_min: float = 0.02):
        self.r_min = max(r_min, 1e-10)
    
    def compute_remainder(self, state: TernaryState) -> float:
        """计算内禀余数偏差"""
        raw = state.yang_weight - state.yin_weight
        remainder = raw % 2.0
        if remainder > 1.0:
            remainder -= 2.0
        return remainder
    
    def inject_remainder(self, state: TernaryState) -> TernaryState:
        """强制注入最小余数偏差"""
        new_state = state.clone()
        new_state.remainder = self.compute_remainder(new_state)
        if abs(new_state.remainder) < self.r_min:
            direction = 1.0 if new_state.yang_weight >= new_state.yin_weight else -1.0
            inject_amt = self.r_min - abs(new_state.remainder)
            new_state.yang_weight += direction * inject_amt * 0.3
            new_state.yin_weight -= direction * inject_amt * 0.3
            new_state.yin_weight = max(0.01, new_state.yin_weight)
            new_state.yang_weight = max(0.01, new_state.yang_weight)
            new_state.remainder = self.compute_remainder(new_state)
        return new_state


# ============================================================
# 精简版三态漂移器（替代原 scheduler + gate + lstm）
# ============================================================
class SimpleOscillator:
    """
    三态自然漂移器
    
    原理：
      用正弦波驱动阴↔阳自然交替，
      中态作为阻尼锚点保持稳定，
      π余数注入不可预测性。
    
    三生万物周期：
      相位0 → 阳势上升（发散）
      相位1 → 阴势上升（收敛）  
      相位2 → 中势归位（整合）
    """
    def __init__(self, config: "TernaryConfig"):
        self.config = config
        self.phase = 0.0
    
    def drift(self, state: TernaryState, 
              phase_int: int = 0,
              grid_diversity: float = 0.5) -> Tuple[float, float, float]:
        """
        计算新一轮的三态权重
        
        参数：
          state: 当前状态
          phase_int: 三生万物相位 (0/1/2)
          grid_diversity: 九宫多样性 [0,1]
        
        返回：(yin, zhong, yang)
        """
        # 基础振荡
        self.phase += 0.3 + 0.1 * grid_diversity
        wave = math.sin(self.phase)
        
        # 三生万物相位偏移
        if phase_int == 0:
            # 阳位 — 偏正
            wave += 0.3
        elif phase_int == 1:
            # 阴位 — 偏负
            wave -= 0.3
        # phase_int == 2: 归中，无偏移
        
        # 映射到三态
        yang_raw = 0.5 + wave * 0.3
        yin_raw = 0.5 - wave * 0.3
        zhong_raw = 0.4 + 0.1 * grid_diversity  # 多样性高时中态更稳
        
        # 确保非负
        yin = max(0.05, yin_raw)
        yang = max(0.05, yang_raw)
        zhong = max(0.2, zhong_raw)
        
        # 归一化
        total = yin + zhong + yang
        return (yin/total, zhong/total, yang/total)


# ============================================================
# 系统配置
# ============================================================
@dataclass
class TernaryConfig:
    """精简的三进制系统配置"""
    r_min: float = 0.02
    base_motivation: float = 0.3
    loop_interval: float = 5.0       # 每轮间隔(秒) — 不再55秒强制固定
    
    def __post_init__(self):
        if not (self.r_min > 0):
            raise AssertionError('R_min must be > 0')
