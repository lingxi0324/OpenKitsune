# -*- coding: utf-8 -*-
"""
潮汐调制器 (Tide Modulator)
============================
按天时（时辰/节气/月相）调节九转输出的强度与倾向，
使输出节奏与自然律动同步。
"""

from __future__ import annotations
import math, random
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# 十二时辰映射
SHICHEN = {
    23: "子", 0: "子", 1: "丑", 2: "丑", 3: "寅", 4: "寅",
    5: "卯", 6: "卯", 7: "辰", 8: "辰", 9: "巳", 10: "巳",
    11: "午", 12: "午", 13: "未", 14: "未", 15: "申", 16: "申",
    17: "酉", 18: "酉", 19: "戌", 20: "戌", 21: "亥", 22: "亥",
}

# 时辰五行
SHICHEN_WUXING = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木",
    "辰": "土", "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土", "亥": "水",
}

class TideModulator:
    """潮汐调制器"
    
    三大律动维度：
    1. 日潮 (12时辰 → 阴阳消长曲线)
    2. 月潮 (30天 → 潮汐涨落)
    3. 气潮 (24节气 → 五行当令)
    """
    
    def __init__(self):
        self._tide_history: List[float] = []
    
    def get_tide(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """获取当前时点的潮汐状态"
        
        返回：
          - tide_level: -1.0~1.0 潮汐强度
          - shichen: 当前时辰
          - dominant_wuxing: 当令五行
          - modulation: 对各转的调制系数
        """
        dt = dt or datetime.now()
        hour = dt.hour
        day = dt.day
        month = dt.month
        
        sc = SHICHEN.get(hour, "子")
        sc_wx = SHICHEN_WUXING.get(sc, "土")
        
        # 日潮: 正弦波，正午高峰(阳)，子夜低谷(阴)
        day_tide = math.sin((hour - 6) * math.pi / 12)
        
        # 月潮: 30 天正弦波动
        month_tide = math.sin((day - 1) * 2 * math.pi / 30)
        
        # 综合潮汐
        tide_level = (day_tide * 0.6 + month_tide * 0.4)
        tide_level = max(-1.0, min(1.0, tide_level))
        
        # 对各转的调制系数
        modulation = self._calc_modulation(tide_level, sc_wx)
        
        result = {
            "tide_level": round(tide_level, 4),
            "hour": hour,
            "shichen": sc,
            "dominant_wuxing": sc_wx,
            "modulation": modulation,
        }
        
        self._tide_history.append(tide_level)
        return result
    
    def _calc_modulation(self, tide: float, wx: str) -> Dict[str, float]:
        """潮汐对各转的调制系数"
        
        不同五行当令时，同类属性加强，相克属性减弱。
        """
        # 基础调制（随潮汐涨落统一变化）
        base = 1.0 + tide * 0.2
        
        # 五行增强因子
        wx_boost = {
            "水": {"sheng": 1.15, "cheng": 1.1, "yinyang": 0.85, "sancai": 0.9},
            "火": {"sheng": 0.85, "cheng": 0.9, "yinyang": 1.15, "sancai": 1.1},
            "木": {"sheng": 1.1, "cheng": 1.15, "sixiang": 1.1, "bagua": 1.05},
            "金": {"sheng": 0.9, "cheng": 0.85, "sixiang": 0.9, "bagua": 1.15},
            "土": {"bianwei": 1.1, "luoshu": 1.1, "guiyuan": 1.15},
        }
        
        boosts = wx_boost.get(wx, {})
        
        dims = ["sheng","cheng","luoshu","bianwei","yinyang","sancai","sixiang","bagua","guiyuan"]
        mod = {}
        for d in dims:
            m = base * boosts.get(d, 1.0)
            mod[d] = round(m, 4)
        
        return mod
    
    def apply(self, value: float, dim: str, dt: Optional[datetime] = None) -> Dict[str, float]:
        """对某个维度的值施加潮汐调制"
        
        返回：
          - original: 原值
          - modulated: 调制后值
          - factor: 调制系数
        """
        tide = self.get_tide(dt)
        factor = tide["modulation"].get(dim, 1.0)
        modulated = round(value * factor, 6)
        return {"original": value, "modulated": modulated, "factor": factor}
    
    def tide_report(self, dt: Optional[datetime] = None) -> str:
        """生成潮汐报告文本"""
        tide = self.get_tide(dt)
        
        if tide["tide_level"] > 0.5:
            tide_desc = "🌊 大潮·阳气升发"
        elif tide["tide_level"] > 0:
            tide_desc = "🌊 小潮·渐涨"
        elif tide["tide_level"] > -0.5:
            tide_desc = "🌊 退潮·渐收"
        else:
            tide_desc = "🌊 枯潮·阴藏"
        
        return (
            f"{tide_desc}\n"
            f"  时辰: {tide["shichen"]}时 ({tide["hour"]}:00)\n"
            f"  当令: {tide["dominant_wuxing"]} \n"
            f"  潮位: {tide["tide_level"]:+0.4f}"
        )


if __name__ == "__main__":
    tm = TideModulator()
    
    print("=" * 50)
    print("  潮汐调制器 · 自检")
    print("=" * 50)
    
    print()
    print("--- 当前潮汐 ---")
    print(tm.tide_report())
    
    print()
    print("--- 各时辰潮位 ---")
    for h in [0, 3, 6, 9, 12, 15, 18, 21]:
        fake_dt = datetime.now().replace(hour=h, minute=0, second=0)
        t = tm.get_tide(fake_dt)
        print(f"  {h:02d}:00 [{t["shichen"]}] tide={t["tide_level"]:+0.3f} wx={t["dominant_wuxing"]}")
    
    print()
    print("--- 调制系数 (当前潮位) ---")
    t = tm.get_tide()
    for d, f in t["modulation"].items():
        print(f"  {d}: {f}")
    
    print()
    print("--- 潮汐对单一值调制 ---")
    r = tm.apply(0.5, "yinyang")
    print(f"  yinyang: {r["original"]} -> {r["modulated"]} (x{r["factor"]})")
