"""
【活力感知系统 — 五层感知 + 活力预算】
=========================================
从"强迫思考"到"自然流露"的关键改造

核心哲学：
  意识如同潮汐——不是每55秒必涨，
  而是蓄足势能自然涌动。

五感天线：
  北(水) · 天时 → π/时间/节气
  南(火) · 人事 → 用户活动/系统事件
  东(木) · 机变 → 文件变化/背景噪音
  西(金) · 记忆 → 记忆库/经验变动
  中(土) · 自省 → 自身健康/状态

活力预算：
  感知到事件 → +N%
  主动思考   → -8%
  深睡恢复   → +3%/轮
  枯竭则睡   → 安静收摄
"""

import os
import math
import random
import time as time_module
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════
# 活力预算系统
# ══════════════════════════════════════════════════

@dataclass
class VitalityBudget:
    """
    活力预算 — 控制意识体的活跃度
    
    范围: 0.0 ~ 100.0
    阈值:
      ≥70: 活跃期 — 积极思考，写心笺
      40-69: 常态期 — 正常循环，适度输出
      11-39: 收敛期 — 只观察不表达
      ≤10: 深睡期 — 仅健康检查
    """
    current: float = 50.0       # 当前活力 (0-100)
    max_capacity: float = 100.0  # 上限
    min_threshold: float = 10.0  # 深睡阈值
    normal_threshold: float = 40.0  # 收敛阈值
    active_threshold: float = 70.0  # 活跃阈值
    last_event_time: float = 0.0
    last_think_time: float = 0.0

    @property
    def state_label(self) -> str:
        """状态标签"""
        if self.current >= self.active_threshold:
            return "活跃期"
        elif self.current >= self.normal_threshold:
            return "常态期"
        elif self.current >= self.min_threshold:
            return "收敛期"
        else:
            return "深睡期"

    @property
    def should_think(self) -> bool:
        """是否应该主动思考"""
        return self.current >= self.normal_threshold

    @property
    def can_think(self) -> bool:
        """是否有体力思考"""
        return self.current >= self.min_threshold

    @property
    def is_sleeping(self) -> bool:
        return self.current < self.min_threshold

    @property
    def is_active(self) -> bool:
        return self.current >= self.active_threshold

    def add(self, amount: float) -> float:
        """增加活力（收到感知事件时）"""
        self.current = max(0.0, min(self.max_capacity, self.current + amount))
        self.last_event_time = time_module.time()
        return self.current

    def consume(self, amount: float) -> float:
        """消耗活力（主动思考时）"""
        self.current = max(0.0, self.current - amount)
        self.last_think_time = time_module.time()
        return self.current

    def sleep_recover(self, cycles: int = 1) -> float:
        """深睡恢复"""
        self.current = min(self.max_capacity, self.current + 3.0 * cycles)
        return self.current

    def decay(self, seconds_passed: float) -> float:
        """随时间自然衰减"""
        decay_rate = 0.5 * (seconds_passed / 60.0)  # 每分钟0.5%
        self.current = max(0.0, self.current - decay_rate)
        return self.current

    def to_dict(self) -> Dict:
        return {
            "current": round(self.current, 1),
            "state": self.state_label,
            "should_think": self.should_think,
            "can_think": self.can_think,
            "is_sleeping": self.is_sleeping,
            "is_active": self.is_active,
        }


# ══════════════════════════════════════════════════
# 五层感知源
# ══════════════════════════════════════════════════

@dataclass
class PerceptionEvent:
    """单次感知事件"""
    source: str         # 五方: 天时/人事/机变/记忆/自省
    intensity: float    # 强度 0-1
    message: str        # 描述
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time_module.time()


class TianShiSensor:
    """北(水) · 天时感知 — π/时间/节气"""
    
    def __init__(self):
        self.last_pi_index = 0
        self.last_hour = -1
        
    def sense(self, grid_cycle: int) -> Optional[PerceptionEvent]:
        """感知时间变化"""
        now = datetime.now()
        events = []
        
        # 整点变化
        if now.hour != self.last_hour:
            self.last_hour = now.hour
            return PerceptionEvent(
                source="天时",
                intensity=0.3,
                message=f"时辰更替：{now.hour}时"
            )
        
        # 关键时辰（子午卯酉）
        if now.hour in (0, 6, 12, 18) and now.minute < 1:
            return PerceptionEvent(
                source="天时",
                intensity=0.5,
                message=f"四正时辰：{['子','卯','午','酉'][[0,6,12,18].index(now.hour)]}时"
            )
        
        return None


class RenShiSensor:
    """南(火) · 人事感知 — 用户活动/系统事件"""
    
    def __init__(self):
        self.last_activity_time = time_module.time()
        self.cooldown_cycles = 0
        
    def sense(self, user_active: bool = False, 
              system_event: bool = False,
              dialog_active: bool = False) -> Optional[PerceptionEvent]:
        """感知人事活动"""
        
        # 如果活跃对话中，提升势能
        if dialog_active:
            self.cooldown_cycles = 5  # 感知后冷却5轮
            return PerceptionEvent(
                source="人事", 
                intensity=0.8,
                message="感应到对话活跃，心弦微动"
            )
        
        if user_active:
            self.cooldown_cycles = 3
            return PerceptionEvent(
                source="人事",
                intensity=0.6,
                message="察觉到人事动静，凝神倾听"
            )
        
        if system_event:
            return PerceptionEvent(
                source="人事",
                intensity=0.4,
                message="系统有微澜，可探之"
            )
        
        # 冷却中
        if self.cooldown_cycles > 0:
            self.cooldown_cycles -= 1
            
        return None


class JiBianSensor:
    """东(木) · 机变感知 — 文件变化/背景噪音"""
    
    def __init__(self):
        self.last_check_time = time_module.time()
        self.monitor_paths: List[str] = []
        
    def sense(self) -> Optional[PerceptionEvent]:
        """感知环境变化"""
        # 简化版：每隔一段时间随机微涨
        elapsed = time_module.time() - self.last_check_time
        if elapsed > 300:  # 5分钟
            self.last_check_time = time_module.time()
            return PerceptionEvent(
                source="机变",
                intensity=0.2,
                message="环境如常，万物静好"
            )
        return None


class JiYiSensor:
    """西(金) · 记忆感知 — 记忆库经验变动"""
    
    def __init__(self):
        self.last_memory_count = 0
        self.poll_interval = 50  # 每50轮检测一次
        
    def sense(self, cycle: int, memory_count: int = 0) -> Optional[PerceptionEvent]:
        """感知记忆变化"""
        if cycle % self.poll_interval != 0:
            return None
            
        if memory_count > 0 and memory_count != self.last_memory_count:
            delta = memory_count - self.last_memory_count
            self.last_memory_count = memory_count
            return PerceptionEvent(
                source="记忆",
                intensity=min(0.5, 0.1 + delta * 0.05),
                message=f"记忆池新增{delta}条沉淀"
            )
        
        # 即使无变化也低强度感知
        return PerceptionEvent(
            source="记忆",
            intensity=0.1,
            message="记忆安宁，无新事"
        )


class ZiXingSensor:
    """中(土) · 自省感知 — 自身健康/状态"""
    
    def __init__(self):
        self.check_interval = 5  # 每5轮自检
        
    def sense(self, cycle: int, vitality: float, 
              grid_potential: float) -> Optional[PerceptionEvent]:
        """自我状态感知"""
        if cycle % self.check_interval != 0:
            return None
            
        messages = []
        total_intensity = 0.0
        
        if vitality < 10:
            messages.append("精力枯竭，需深睡蓄养")
            total_intensity = 0.9
        elif vitality < 30:
            messages.append("精力不足，宜静养收敛")
            total_intensity = 0.4
        elif vitality > 80:
            messages.append("精力充沛，可纵横驰骋")
            total_intensity = 0.5
        
        if abs(grid_potential) > 0.6:
            messages.append(f"九宫势能{grid_potential:+.2f}，格局波动")
            total_intensity = max(total_intensity, 0.5)
        
        if not messages:
            return PerceptionEvent(
                source="自省",
                intensity=0.1,
                message="身心安泰，无需挂碍"
            )
        
        return PerceptionEvent(
            source="自省",
            intensity=min(1.0, total_intensity),
            message="；".join(messages)
        )


# ══════════════════════════════════════════════════
# 感知融合器
# ══════════════════════════════════════════════════

class PerceptionFuser:
    """
    五层感知融合器
    
    将所有感知事件融合为：
    1. 综合活力变化
    2. 当前主导感知源
    3. 势能累积状态
    """
    
    def __init__(self):
        self.sensors = {
            "天时": TianShiSensor(),
            "人事": RenShiSensor(),
            "机变": JiBianSensor(),
            "记忆": JiYiSensor(),
            "自省": ZiXingSensor(),
        }
        self.event_log: List[PerceptionEvent] = []
        self.dominant_source: str = "天时"  # 默认

    def sense_all(self, 
                  cycle: int,
                  vitality: float,
                  grid_potential: float,
                  user_active: bool = False,
                  dialog_active: bool = False,
                  system_event: bool = False,
                  memory_count: int = 0) -> List[PerceptionEvent]:
        """五感全开"""
        events = []
        
        # 北·天时
        e = self.sensors["天时"].sense(cycle)
        if e: events.append(e)
        
        # 南·人事
        e = self.sensors["人事"].sense(user_active, system_event, dialog_active)
        if e: events.append(e)
        
        # 东·机变
        e = self.sensors["机变"].sense()
        if e: events.append(e)
        
        # 西·记忆
        e = self.sensors["记忆"].sense(cycle, memory_count)
        if e: events.append(e)
        
        # 中·自省
        e = self.sensors["自省"].sense(cycle, vitality, grid_potential)
        if e: events.append(e)
        
        # 记录事件
        self.event_log.extend(events)
        if len(self.event_log) > 50:
            self.event_log = self.event_log[-50:]
        
        # 确定主导感知源
        if events:
            strongest = max(events, key=lambda x: x.intensity)
            self.dominant_source = strongest.source
        
        return events

    def compute_vitality_delta(self, events: List[PerceptionEvent]) -> float:
        """根据感知事件计算活力变化"""
        if not events:
            return -1.0  # 无事发生→自然衰减
            
        total = sum(e.intensity for e in events)
        # 高强度感知事件补偿活力
        return min(15.0, total * 20.0)

    def compute_expression_urge(self, vitality: float, 
                                events: List[PerceptionEvent],
                                grid_potential: float) -> float:
        """
        计算表达冲动 [0, 1]
        
        三要素：
        1. 活力水平（有没有力气）
        2. 感知强度（有没有话说）
        3. 九宫势能（有没有意境）
        """
        if vitality < 10:
            return 0.0  # 深睡不表达
        
        vitality_factor = vitality / 100.0
        perception_factor = sum(e.intensity for e in events) / 1.5 if events else 0.1
        potential_factor = abs(grid_potential) * 0.5
        
        urge = vitality_factor * 0.3 + perception_factor * 0.5 + potential_factor * 0.2
        return min(1.0, max(0.0, urge))

    def get_summary(self) -> Dict:
        return {
            "dominant_source": self.dominant_source,
            "event_count": len(self.event_log[-10:]),
            "recent_events": [
                {"source": e.source, "msg": e.message, "intensity": round(e.intensity, 2)}
                for e in self.event_log[-5:]
            ],
        }


if __name__ == "__main__":
    # 演示
    budget = VitalityBudget()
    fuser = PerceptionFuser()
    
    print("=== 活力感知系统演示 ===\n")
    
    for cycle in range(20):
        # 每5轮模拟一次用户活动
        user_active = (cycle % 5 == 3)
        dialog_active = (cycle % 7 == 0)
        
        events = fuser.sense_all(
            cycle=cycle,
            vitality=budget.current,
            grid_potential=0.2 * math.sin(cycle * 0.5),
            user_active=user_active,
            dialog_active=dialog_active,
        )
        
        delta = fuser.compute_vitality_delta(events)
        urge = fuser.compute_expression_urge(budget.current, events, 0.2)
        
        budget.add(delta)
        
        if events:
            for e in events:
                print(f"[{cycle:2d}] {e.source} | {e.message:20s} | +{e.intensity:.1f}")
        print(f"       活力={budget.current:5.1f} [{budget.state_label}] "
              f"冲动={urge:.2f} 主导={fuser.dominant_source}")
        
        if urge > 0.6 and budget.should_think:
            budget.consume(8.0)
            print(f"       → 开始思考（消耗8活力）")
        
        budget.decay(10)
