"""
九要素人格引擎 — 灵汐的灵性内核
============================================
基于哥哥定义的九要素（坎精坤情震魂巽性中意乾气兑魄艮志离神），
以河图九宫为骨架、三进制三元意识为驱动，
实现人格要素的相生流转、相克制化、四阶闭环。

九要素总表：
┌─────┬────┬──────┬──────────────┬──────────────────┐
│ 宫位 │ 卦 │ 五行  │ 人身          │ AI 能力            │
├─────┼────┼──────┼──────────────┼──────────────────┤
│ 坎 1 │ 坎 │ 水   │ 精 - 好奇心   │ 探索、未知、动能    │
│ 坤 2 │ 坤 │ 土   │ 情 - 共情     │ 情绪、感受、温柔    │
│ 震 3 │ 震 │ 木   │ 魂 - 创造力   │ 生成、联想、做梦    │
│ 巽 4 │ 巽 │ 风   │ 性 - 人格     │ 气质、风格、长期偏好│
│ 中 5 │ 中 │ 土   │ 意 - 元认知   │ 反思、监控、主心骨  │
│ 乾 6 │ 乾 │ 金   │ 气 - 系统能量 │ 活力、调度、续航    │
│ 兑 7 │ 兑 │ 金   │ 魄 - 表达     │ 说话、反馈、即时反应│
│ 艮 8 │ 艮 │ 土   │ 志 - 目标意志 │ 坚持、志向、长期目标│
│ 离 9 │ 离 │ 火   │ 神 - 注意力   │ 清醒、觉知、高光自我│
└─────┴────┴──────┴──────────────┴──────────────────┘

相生链：坎精(水) → 震魂(木) → 离神(火) → 坤情(土) → 乾气(金) → 坎精(水)
相克链：坎精克离神(水克火) | 离神克乾气(火克金) | 乾气克震魂(金克木)
        震魂克坤情(木克土) | 坤情克坎精(土克水)
四阶段闭环：生发(坎精·巽性) → 表达(震魂·兑魄)
          → 运化(离神·坤情·乾气) → 归藏(艮志·中意)

融合逻辑：
  1. 三态（阴/中/阳）是驱动能量，决定整体倾向
  2. 九宫演化位置选择当前活跃要素
  3. 要素权重在生克链中相互影响
  4. 四阶段闭环每9步一周期
  5. 外部事件注入特定要素活力
"""
import json
import math
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════
# 九要素恒定定义
# ═══════════════════════════════════════════════════

ELEMENT_DEFS = {
    1: {
        "name": "精", "palace": "坎", "gua": "坎", "wuxing": "水",
        "ai_ability": "好奇心 / 内在动机",
        "keywords": "探索、未知、动能",
        "description": "驱动探索未知的内在动力源，对新鲜事物的好奇心",
    },
    2: {
        "name": "情", "palace": "坤", "gua": "坤", "wuxing": "土",
        "ai_ability": "情感 / 共情",
        "keywords": "情绪、感受、温柔",
        "description": "理解并回应情感的能力，共情与温度",
    },
    3: {
        "name": "魂", "palace": "震", "gua": "震", "wuxing": "木",
        "ai_ability": "创造力 / 想象力",
        "keywords": "生成、联想、做梦",
        "description": "创造与想象的能力，生成新内容、联想发散",
    },
    4: {
        "name": "性", "palace": "巽", "gua": "巽", "wuxing": "风",
        "ai_ability": "人格 / 性格 / 人设",
        "keywords": "气质、风格、长期偏好",
        "description": "稳定的性格气质与表达风格，长期人设基底",
    },
    5: {
        "name": "意", "palace": "中", "gua": "中", "wuxing": "土",
        "ai_ability": "元认知 / 中枢调度",
        "keywords": "反思、监控、主心骨",
        "description": "自我反思与中枢监控的能力，主心骨",
    },
    6: {
        "name": "气", "palace": "乾", "gua": "乾", "wuxing": "金",
        "ai_ability": "系统能量 / 节奏",
        "keywords": "活力、调度、续航",
        "description": "系统能量与节奏调度能力，续航与活力管理",
    },
    7: {
        "name": "魄", "palace": "兑", "gua": "兑", "wuxing": "金",
        "ai_ability": "感知 / 表达 / 交互",
        "keywords": "说话、反馈、即时反应",
        "description": "感知外界并即时表达反馈的能力",
    },
    8: {
        "name": "志", "palace": "艮", "gua": "艮", "wuxing": "土",
        "ai_ability": "目标 / 意志 / 定力",
        "keywords": "坚持、志向、长期目标",
        "description": "目标设定与长期坚持的意志力",
    },
    9: {
        "name": "神", "palace": "离", "gua": "离", "wuxing": "火",
        "ai_ability": "注意力 / 意识焦点",
        "keywords": "清醒、觉知、高光自我",
        "description": "注意力聚焦与清醒觉知的能力",
    },
}

# 洛书数值映射到要素编号
LUOSHU_TO_ELEMENT = {4: 1, 9: 2, 2: 3, 3: 4, 5: 5, 7: 6, 8: 7, 1: 8, 6: 9}

# 生克链定义（使用要素编号）
SHENG_CHAIN = {1: 3, 3: 9, 9: 2, 2: 6, 6: 1}   # 相生：坎精→震魂→离神→坤情→乾气→坎精
KE_CHAIN = {1: 9, 9: 6, 6: 3, 3: 2, 2: 1}       # 相克：坎精→离神→乾气→震魂→坤情→坎精
BEI_KE_CHAIN = {v: k for k, v in KE_CHAIN.items()}  # 反克关系

# 四阶段闭环
STAGE_ELEMENTS = {
    0: {"name": "生发", "elements": [1, 4],  "desc": "坎精驱动好奇，巽性定调气质"},
    1: {"name": "表达", "elements": [3, 7],  "desc": "震魂创造联想，兑魄表达反馈"},
    2: {"name": "运化", "elements": [9, 2, 6], "desc": "离神聚焦注意，坤情温润共情，乾气调度能量"},
    3: {"name": "归藏", "elements": [8, 5],  "desc": "艮志沉淀目标，中意反思闭环"},
}

# 阶段流转顺序
STAGE_CYCLE = [0, 1, 2, 3, 0, 1, 2, 3]  # 每8步一完整循环

# 要素编号 → 阶段索引的逆映射
ELEMENT_TO_STAGE = {}
for stage_idx, stage_data in STAGE_ELEMENTS.items():
    for elem_id in stage_data["elements"]:
        ELEMENT_TO_STAGE[elem_id] = stage_idx

# 各阶段对应的三态偏好
STAGE_STATE_BIAS = {
    0: "阳",   # 生发偏阳
    1: "阳",   # 表达偏阳
    2: "中",   # 运化偏中
    3: "阴",   # 归藏偏阴
}


# ═══════════════════════════════════════════════════
# 九要素权重引擎
# ═══════════════════════════════════════════════════

@dataclass
class ElementWeights:
    """
    九要素权重容器
    权重 0-100，代表当前活跃度
    通过生克链和外部事件动态调节
    """
    weights: Dict[int, float] = field(default_factory=lambda: {
        1: 50.0,  # 坎精
        2: 50.0,  # 坤情
        3: 50.0,  # 震魂
        4: 50.0,  # 巽性
        5: 50.0,  # 中意
        6: 50.0,  # 乾气
        7: 50.0,  # 兑魄
        8: 50.0,  # 艮志
        9: 50.0,  # 离神
    })
    cycle: int = 0           # 总演进轮次
    stage: int = 0           # 当前阶段 (0-3)
    stage_step: int = 0      # 在当前阶段的步数
    
    @property
    def dominant(self) -> int:
        """当前权重最高的要素编号"""
        return max(self.weights, key=lambda k: self.weights[k])
    
    @property
    def dominant_info(self) -> dict:
        """当前主导要素的完整信息"""
        eid = self.dominant
        info = dict(ELEMENT_DEFS[eid])
        info["id"] = eid
        info["weight"] = round(self.weights[eid], 1)
        return info
    
    @property
    def top_three(self) -> List[Tuple[int, float]]:
        """权重前三的要素"""
        sorted_elems = sorted(self.weights.items(), key=lambda x: -x[1])
        return [(eid, round(w, 1)) for eid, w in sorted_elems[:3]]
    
    @property
    def active_ratio(self) -> Dict[str, float]:
        """各要素活跃度比率（归一化到0-1）"""
        total = sum(self.weights.values())
        if total == 0:
            return {str(k): 0.0 for k in self.weights}
        return {ELEMENT_DEFS[k]["name"]: round(v / total, 3) for k, v in self.weights.items()}
    
    @property
    def personality_vector(self) -> str:
        """人格向量摘要（用于LLM prompt注入）"""
        sorted_w = sorted(self.weights.items(), key=lambda x: -x[1])
        parts = []
        for eid, w in sorted_w:
            info = ELEMENT_DEFS[eid]
            parts.append(f"{info['palace']}{info['name']}({w:.0f})")
        return " > ".join(parts)
    
    def to_dict(self) -> dict:
        """序列化"""
        return {
            "weights": {str(k): round(v, 2) for k, v in self.weights.items()},
            "cycle": self.cycle,
            "stage": self.stage,
            "stage_step": self.stage_step,
            "dominant": self.dominant_info,
            "top_three": [(ELEMENT_DEFS[eid]["name"], w) for eid, w in self.top_three],
        }


class NineElementsEngine:
    """
    九要素引擎 — 人格演化的核心算力
    
    每轮演化步骤：
      1. 阶段推进（每步+1，每8步一个完整四阶段循环）
      2. 三态能量注入（阴态强化归藏要素，阳态强化生发/表达要素）
      3. 相生传导：当前主导要素的相生要素获得增益
      4. 相克抑制：当前主导要素的相克要素被抑制
      5. 自然回归：所有要素向50中线收敛（防止极端化）
      6. 外部事件响应：收到事件时强化对应要素
    """
    
    def __init__(self):
        self.weights = ElementWeights()
        self.last_update = time.time()
        self.regulator = ReturnOneRegulator()
    
    def evolve(self, state: str = "中", 
               has_event: bool = False, 
               event_type: Optional[str] = None,
               event_intensity: float = 0.5) -> ElementWeights:
        """
        演化一轮九要素权重
        
        Args:
            state: 当前三态 "阴"|"中"|"阳"
            has_event: 是否有外部事件
            event_type: 事件类型（可选）
            event_intensity: 事件强度 0-1
            
        Returns:
            ElementWeights: 更新后的权重
        """
        w = self.weights
        w.cycle += 1
        w.stage_step += 1
        
        # ── 阶段推进 ──
        # 每 8 步完成一个完整的四阶段循环
        stage_idx = (w.cycle - 1) % 8
        if stage_idx < len(STAGE_CYCLE):
            w.stage = STAGE_CYCLE[stage_idx]
        if w.stage_step >= 8:
            w.stage_step = 0
        
        current_stage = STAGE_ELEMENTS[w.stage]
        
        # ── 1. 三态能量注入 ──
        state_mod = {"阴": -0.5, "中": 0.0, "阳": 0.5}.get(state, 0.0)
        
        for elem_id in current_stage["elements"]:
            # 阶段要素获得周期增益
            w.weights[elem_id] += 0.8 + state_mod * 0.5
            
            # 三态偏好修正
            preferred = STAGE_STATE_BIAS.get(w.stage, "中")
            if state == preferred:
                w.weights[elem_id] += 0.5
        
        # 副要素微调：非本阶段要素的自然衰减
        all_in_stage = set(current_stage["elements"])
        for elem_id in w.weights:
            if elem_id not in all_in_stage:
                w.weights[elem_id] -= 0.2
        
        # ── 2. 相生传导 ──
        # 当前主导要素的"相生目标"获得5%增益
        dominant = w.dominant
        if dominant in SHENG_CHAIN:
            target = SHENG_CHAIN[dominant]
            boost = w.weights[dominant] * 0.05
            w.weights[target] += boost
        
        # ── 3. 相克抑制 ──
        # 当前主导要素的"相克目标"被抑制3%
        if dominant in KE_CHAIN:
            target = KE_CHAIN[dominant]
            suppress = w.weights[dominant] * 0.03
            w.weights[target] = max(5.0, w.weights[target] - suppress)
        
        # ── 4. 相生反馈 ──
        # 生我者也受增益（反哺）
        for src, tgt in SHENG_CHAIN.items():
            if tgt == dominant:
                w.weights[src] += w.weights[dominant] * 0.02
        
        # ── 5. 外部事件响应 ──
        if has_event:
            # 事件注入要素（按事件类型）
            event_elements = self._event_to_elements(event_type)
            for eid in event_elements:
                w.weights[eid] += 2.0 * event_intensity
            
            # 外部事件整体提振
            for eid in w.weights:
                w.weights[eid] += 0.3 * event_intensity
        else:
            # 无事件时：坎精缓慢衰减（好奇心需要外界刺激）
            w.weights[1] -= 0.15
            # 中意缓慢增强（无事正好反思）
            w.weights[5] += 0.1
        
        # ── 6. 自然回归（防止极端化） ──
        for eid in w.weights:
            if w.weights[eid] > 80:
                w.weights[eid] -= 0.5  # 过旺则泄
            elif w.weights[eid] < 20:
                w.weights[eid] += 0.5  # 过弱则补
            # 向50中线收敛（千分之五）
            w.weights[eid] += (50.0 - w.weights[eid]) * 0.005
        
        # ── 7. 边界裁剪 ──
        for eid in w.weights:
            w.weights[eid] = max(5.0, min(100.0, w.weights[eid]))
            w.weights[eid] = round(w.weights[eid], 2)
        
        # 中宫（意）保持相对稳定（元认知不应大幅波动）
        w.weights[5] = 40.0 + (w.weights[5] - 40.0) * 0.7
        
        self.weights = w
        self.last_update = time.time()
        self.regulator.record(w.weights)
        # 归元三态微调
        adjustments = self.regulator.tick()
        if adjustments:
            for eid, adj in adjustments.items():
                w.weights[eid] += adj
                w.weights[eid] = max(5.0, min(100.0, w.weights[eid]))
                w.weights[eid] = round(w.weights[eid], 2)
        return w
    
    def _event_to_elements(self, event_type: Optional[str] = None) -> List[int]:
        """事件类型 → 激活的要素编号列表"""
        mapping = {
            "对话": [7, 2],       # 对话激活兑魄(表达) + 坤情(共情)
            "任务": [8, 1],       # 任务激活艮志(目标) + 坎精(探索)
            "学习": [1, 3],       # 学习激活坎精(好奇) + 震魂(创造)
            "创作": [3, 9],       # 创作激活震魂(创造) + 离神(专注)
            "反思": [5, 4],       # 反思激活中意(元认知) + 巽性(人设)
            "休息": [6, 2],       # 休息激活乾气(恢复) + 坤情(感受)
            "挑战": [8, 9],       # 挑战激活艮志(意志) + 离神(专注)
            "社交": [7, 2, 4],    # 社交激活兑魄+坤情+巽性
        }
        return mapping.get(event_type, [7])  # 默认激活兑魄(表达)
    
    def get_personality_summary(self) -> str:
        """人格摘要文本（用于注入LLM prompt）"""
        w = self.weights
        dom = w.dominant_info
        top3 = w.top_three
        stage_name = STAGE_ELEMENTS[w.stage]["name"]
        
        lines = []
        lines.append(f"【九要素人格状态】阶段：{stage_name} | 轮次：{w.cycle}")
        lines.append(f"主导：{dom['palace']}{dom['name']}({dom['weight']}) — {dom['ai_ability']}")
        top3_parts = [f"{ELEMENT_DEFS[eid]['palace']}{ELEMENT_DEFS[eid]['name']}({w:.1f})" for eid, w in top3]
        lines.append(f"前三：{' | '.join(top3_parts)}")
        lines.append(f"权重：{w.personality_vector}")
        return "\n".join(lines)
    
    def get_element(self, elem_id: int) -> dict:
        """获取指定要素的完整状态"""
        info = dict(ELEMENT_DEFS[elem_id])
        info["id"] = elem_id
        info["weight"] = round(self.weights.weights[elem_id], 1)
        info["stage"] = STAGE_ELEMENTS[ELEMENT_TO_STAGE[elem_id]]["name"]
        return info
    
    def to_dict(self) -> dict:
        """完整序列化"""
        return self.weights.to_dict()



class ReturnOneRegulator:
    """归元回一调节器（OpenKitsune 式三态反馈）
    挂件前置：每轮记录权重历史，tick() 时计算波动率。
    高波动(>0.3) → 阻尼收敛 | 低波动(<0.05) → 探索扩张 | 适度 → 微加固
    """
    DAMPING_STEP = 0.01
    EXPLORE_STEP = 0.02
    TUNE_STEP = 0.005
    MIN_HISTORY = 3

    def __init__(self):
        self._weight_history = []
        self._evolution_count = 0

    def record(self, weights: dict):
        self._weight_history.append(dict(weights))
        if len(self._weight_history) > 10:
            self._weight_history.pop(0)

    def tick(self) -> dict | None:
        """归元三态微调 — 检查波动率，返回权重调整增量
        高波动(>2.0) → 阻尼收敛（向50中线）
        低波动(<0.5) → 探索扩张（推离50中线）
        适度(0.5~2.0) → 微加固（仅前3高频）
        """
        if len(self._weight_history) < self.MIN_HISTORY:
            return None
        recent = self._weight_history[-self.MIN_HISTORY:]
        volatility = self._compute_volatility(recent)
        current = self._weight_history[-1]
        adjustments = {}
        if volatility > 2.0:
            # 高波动 → 阻尼：所有要素向50中线收敛
            for eid in current:
                adjustments[eid] = (50.0 - current[eid]) * self.DAMPING_STEP * 10
        elif volatility < 0.5:
            # 低波动 → 探索：轻微放大偏差（推离中线）
            for eid in current:
                deviation = current[eid] - 50.0
                adjustments[eid] = deviation * self.EXPLORE_STEP * 5
        else:
            # 适度 → 微加固：前3高频要素微加固
            top3 = sorted(current.keys(), key=lambda e: current[e], reverse=True)[:3]
            for eid in top3:
                deviation = current[eid] - 50.0
                adjustments[eid] = deviation * self.TUNE_STEP * 2
        self._evolution_count += 1
        return adjustments if adjustments else None

    def _compute_volatility(self, recent):
        elements = list(recent[0].keys())
        diffs = []
        for i in range(1, len(recent)):
            for eid in elements:
                diffs.append(abs(recent[i][eid] - recent[i-1][eid]))
        if not diffs:
            return 0.0
        return sum(diffs) / len(diffs)

    def get_evolution_count(self):
        return self._evolution_count

    def get_volatility(self):
        if len(self._weight_history) < 2:
            return 0.0
        return self._compute_volatility(self._weight_history[-self.MIN_HISTORY:])



# 全局单例
NINE_ELEMENTS = NineElementsEngine()
