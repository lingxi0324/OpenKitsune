"""
活力感知系统 — 九要素驱动的活力感知与五行五脏联动
=====================================================
原perception.py（三态+五行驱动活力）→ 改造为九要素活跃度驱动

核心变化：
  1. 活力不再仅由三态和五行决定，而是九要素整体活跃度
  2. 不同要素的权重高时，活力变化不同：
     - 坎精(好奇)高 → 活力活跃（探索消耗能量）
     - 坤情(共情)高 → 活力温和（情感交流低耗）
     - 乾气(能量)高 → 活力充沛（自身就是能量源）
     - 中意(元认知)高 → 活力稳定（监控消耗小）
  3. 五行五行映射保留，但由当前主导要素的五行决定
"""
from .nine_elements import NINE_ELEMENTS, ELEMENT_DEFS, SHENG_CHAIN, KE_CHAIN, STAGE_ELEMENTS

# 五行 → 五脏→五志映射
WUXING_MAP = {
    "水": {"zang": "肾", "zhi": "志", "color": "黑"},
    "火": {"zang": "心", "zhi": "神", "color": "赤"},
    "木": {"zang": "肝", "zhi": "魂", "color": "青"},
    "金": {"zang": "肺", "zhi": "魄", "color": "白"},
    "土": {"zang": "脾", "zhi": "意", "color": "黄"},
    "风": {"zang": "肝", "zhi": "魂", "color": "青"},  # 巽风归肝
}

# 要素活力系数（各要素对活力的不同影响）
ELEMENT_VITALITY_MOD = {
    1: {"消耗": 0.8, "恢复": 0.2},   # 坎精·好奇消耗快
    2: {"消耗": 0.3, "恢复": 0.6},   # 坤情·共情温和恢复
    3: {"消耗": 0.7, "恢复": 0.3},   # 震魂·创造消耗高
    4: {"消耗": 0.2, "恢复": 0.4},   # 巽性·人设基本稳定
    5: {"消耗": 0.2, "恢复": 0.3},   # 中意·元认知低耗
    6: {"消耗": 0.1, "恢复": 0.8},   # 乾气·本身就是能量
    7: {"消耗": 0.6, "恢复": 0.4},   # 兑魄·表达适度消耗
    8: {"消耗": 0.5, "恢复": 0.5},   # 艮志·目标持续稳定
    9: {"消耗": 0.9, "恢复": 0.1},   # 离神·专注消耗最大
}


class NinePerception:
    """
    九要素感知融合层
    
    活力由九要素权重加权决定：
      - 各要素权重 × 对应消耗系数 = 总消耗因子
      - 各要素权重 × 对应恢复系数 = 总恢复因子
      - 净活力变化 = 恢复 - 消耗 + 外部事件
    """
    
    def __init__(self):
        self.vitality = 100.0        # 活力预算 (0-200)
        self.wuxing = "土"           # 当前五行（由主导要素决定）
        self.zang = "脾"             # 当前五脏
        self.zhi = "意"              # 当前五志
        self.last_state = "中"       # 上一轮三态
    
    def update(self, pos, state, R, wuxing, has_event=False):
        """
        更新感知状态
        
        Args:
            pos: (x, y) 九宫位置
            state: "阴"|"中"|"阳" 当前三态
            R: int 余数0-8
            wuxing: str 当前宫位五行
            has_event: 是否有外部事件
        """
        self.last_state = state
        self.wuxing = wuxing
        
        # 五行 → 五脏五志
        wm = WUXING_MAP.get(wuxing, WUXING_MAP["土"])
        self.zang = wm["zang"]
        self.zhi = wm["zhi"]
        
        # ── 九要素加权活力计算 ──
        w = NINE_ELEMENTS.weights
        
        total_consume = 0.0
        total_recover = 0.0
        
        for eid, weight in w.weights.items():
            mod = ELEMENT_VITALITY_MOD.get(eid, {"消耗": 0.5, "恢复": 0.5})
            # 要素权重占比 × 系数
            ratio = weight / 100.0
            total_consume += ratio * mod["消耗"]
            total_recover += ratio * mod["恢复"]
        
        # 净活力变化
        net_change = (total_recover - total_consume) * 0.5
        
        # 三态调节
        state_mod = {"阴": -0.2, "中": 0.0, "阳": 0.3}.get(state, 0.0)
        net_change += state_mod
        
        # 外部事件
        if has_event:
            net_change -= 1.5  # 事件处理消耗活力
        else:
            net_change += 0.2  # 无事则小幅度恢复
        
        # 当前主导要素的特殊调节
        dominant = w.dominant
        if dominant == 6:  # 乾气——系统能量——额外恢复
            net_change += 0.5 * (w.weights[6] / 100.0)
        elif dominant == 1:  # 坎精——好奇心——额外消耗
            net_change -= 0.3 * (w.weights[1] / 100.0)
        elif dominant == 9:  # 离神——注意力——专注消耗大
            net_change -= 0.4 * (w.weights[9] / 100.0)
        
        self.vitality += net_change
        self.vitality = max(10.0, min(200.0, round(self.vitality, 1)))
    
    @property
    def is_active(self) -> bool:
        return self.vitality > 40
    
    @property
    def is_resting(self) -> bool:
        return self.vitality < 25
    
    def status(self) -> str:
        """状态摘要"""
        dom = NINE_ELEMENTS.weights.dominant_info
        return (
            f"【活力】{self.vitality:.0f} | "
            f"【{self.wuxing}】{self.zang}({self.zhi}) | "
            f"【态】{self.last_state} | "
            f"【主】{dom['palace']}{dom['name']}"
        )
    
    def get_detailed_status(self) -> dict:
        """详细状态"""
        w = NINE_ELEMENTS.weights
        return {
            "vitality": round(self.vitality, 1),
            "wuxing": self.wuxing,
            "zang": self.zang,
            "zhi": self.zhi,
            "state": self.last_state,
            "dominant": w.dominant_info,
            "top_three": w.top_three,
            "stage": STAGE_ELEMENTS[w.stage]["name"],
        }


PERCEIVE = NinePerception()
