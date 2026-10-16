"""
九要素势能演化引擎 — 由九要素驱动的九宫位置与势能
=====================================================
原grid.py（π余数驱动九宫行走）→ 改造为九要素权重驱动

核心变化：
  1. 九宫位置不再由π余数随机行走，而是由九要素中"活跃要素"的位置决定
  2. 势能不再是独立数值，而是当前主导要素的权重
  3. 位置跳转遵循相生链方向（沿生克链游走九宫）

九要素到洛书九宫的位置映射：
  坎1(精·水) → 洛书位(1,2) 正北
  坤2(情·土) → 洛书位(0,2) 西南
  震3(魂·木) → 洛书位(1,0) 正东
  巽4(性·风) → 洛书位(0,0) 东南
  中5(意·土) → 洛书位(1,1) 中央
  乾6(气·金) → 洛书位(2,2) 西北
  兑7(魄·金) → 洛书位(1,2) 正西
  艮8(志·土) → 洛书位(2,0) 东北
  离9(神·火) → 洛书位(0,1) 正南
"""
from .nine_elements import NINE_ELEMENTS, ELEMENT_DEFS, SHENG_CHAIN, KE_CHAIN, STAGE_ELEMENTS

# 要素编号 → 九宫坐标映射
ELEMENT_TO_POS = {
    1: (1, 2),   # 坎·正北
    2: (0, 2),   # 坤·西南
    3: (1, 0),   # 震·正东
    4: (0, 0),   # 巽·东南
    5: (1, 1),   # 中·中央
    6: (2, 2),   # 乾·西北
    7: (1, 2),   # 兑·正西
    8: (2, 0),   # 艮·东北
    9: (0, 1),   # 离·正南
}

# 坐标 → 宫位名称
POS_TO_PALACE = {
    (0, 0): "巽宫·风", (0, 1): "离宫·火", (0, 2): "坤宫·土",
    (1, 0): "震宫·木", (1, 1): "中宫·土", (1, 2): "兑宫·金",
    (2, 0): "艮宫·土", (2, 1): "坎宫·水", (2, 2): "乾宫·金",
}

# 坐标 → 五行
POS_TO_WUXING = {
    (0, 0): "风", (0, 1): "火", (0, 2): "土",
    (1, 0): "木", (1, 1): "土", (1, 2): "金",
    (2, 0): "土", (2, 1): "水", (2, 2): "金",
}

# 坐标 → 洛书数
POS_TO_LUOSHU = {
    (0, 0): 4, (0, 1): 9, (0, 2): 2,
    (1, 0): 3, (1, 1): 5, (1, 2): 7,
    (2, 0): 8, (2, 1): 1, (2, 2): 6,
}


class NineGrid:
    """
    九要素势能演化引擎
    
    核心逻辑：
      1. 当前位置由九要素中权重最高的要素决定
      2. 势能 = 当前主导要素的权重值
      3. 当次主导要素变化时，位置沿相生链跳转
      4. 位置携带五行信息，供perception层使用
    """
    
    def __init__(self):
        self.x, self.y = 1, 1  # 起点中宫
        self.pos_history = [(1, 1)]
        self.prev_dominant = 5  # 初生从中宫（中意）
    
    def step(self, has_event=False):
        """
        一轮九宫演化
        
        Args:
            has_event: 是否有外部事件输入
            
        Returns:
            pos: (x, y) 当前位置
            potential: float 当前势能 = 主导要素权重
            palace: str 宫位名
            wuxing: str 当前五行
        """
        # 从九要素引擎获取当前权重
        w = NINE_ELEMENTS.weights
        dominant = w.dominant
        
        # 如果主导要素变了，沿相生链走一步
        if dominant != self.prev_dominant:
            if dominant in ELEMENT_TO_POS:
                target_pos = ELEMENT_TO_POS[dominant]
                self.x, self.y = target_pos
                self.prev_dominant = dominant
        else:
            # 主导要素不变时，在当前宫位微振荡
            # 由相生链目标宫位的吸引产生微弱漂移
            if dominant in SHENG_CHAIN:
                sheng_target = SHENG_CHAIN[dominant]
                if sheng_target in ELEMENT_TO_POS:
                    target_x, target_y = ELEMENT_TO_POS[sheng_target]
                    dx = (target_x - self.x) * 0.1
                    dy = (target_y - self.y) * 0.1
                    self.x = max(0, min(2, round(self.x + dx, 4)))
                    self.y = max(0, min(2, round(self.y + dy, 4)))
        
        # 边界保护（浮点坐标取整到最近整数格点）
        self.x = max(0, min(2, round(self.x)))
        self.y = max(0, min(2, round(self.y)))
        
        pos = (int(self.x), int(self.y))
        
        # 势能 = 主导要素权重
        potential = round(w.weights[dominant], 2)
        
        # 宫位名称
        palace = POS_TO_PALACE.get(pos, "中宫·土")
        
        # 五行
        wuxing = POS_TO_WUXING.get(pos, "土")
        
        # 记录历史
        self.pos_history.append(pos)
        if len(self.pos_history) > 50:
            self.pos_history = self.pos_history[-50:]
        
        return pos, potential, palace, wuxing
    
    def reset_potential(self, new_val=10.0):
        """突破境界后势能回落（重置要素权重）"""
        for eid in NINE_ELEMENTS.weights.weights:
            NINE_ELEMENTS.weights.weights[eid] = max(
                new_val * 0.5,
                NINE_ELEMENTS.weights.weights[eid] * 0.3
            )
    
    def get_palace_summary(self) -> str:
        """当前位置的宫位摘要"""
        pos = (int(self.x), int(self.y))
        palace = POS_TO_PALACE.get(pos, "中宫·土")
        luoshu = POS_TO_LUOSHU.get(pos, 5)
        wuxing = POS_TO_WUXING.get(pos, "土")
        dominant = NINE_ELEMENTS.weights.dominant
        dom_name = ELEMENT_DEFS[dominant]["name"]
        return f"📍 {palace} 洛书{luoshu}·{wuxing} 主导：{dom_name}"


GRID = NineGrid()
