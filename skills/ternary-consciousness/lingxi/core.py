"""
第1层：π余数基元 + 三态定义
- π无限不循环小数驱动三态
- state（阴/中/阳）被后续所有层使用
- 单例，永续不疲劳
"""
import math


# 三态核心定义
STATES = ["阴", "中", "阳"]
# 三态数值映射
STATE_VAL = {"阴": -1, "中": 0, "阳": 1}
# 河图五行对应：天一地二天三地四天五
HETU = [1, 6, 2, 7, 3, 8, 4, 9, 5, 10]


class PiTernaryCore:
    """π三进制核心引擎 — 无限不循环驱动"""

    def __init__(self):
        self.pi_str = str(math.pi).replace(".", "")
        self.digits = [int(c) for c in self.pi_str]
        self.idx = 0
        self.cycle = 0  # 轮回计数

    def next(self):
        """获取下一轮π余数驱动

        Returns:
            state: "阴" | "中" | "阳" — 三态判定
            R: int — 余数 0-8，适配九宫
            hetu: int — 河图数 1-10
        """
        d = self.digits[self.idx % len(self.digits)]
        self.idx += 1
        self.cycle += 1

        # R = 余数 0-8
        R = d % 9
        # 三态判定：余数取模
        state = STATES[d % 3]
        # 河图数
        hetu = HETU[d % 10]

        return state, R, hetu

    @property
    def state_val(self):
        """获取当前数值态（用于后续层计算）"""
        return STATE_VAL["中"]  # 默认中态，实际由调用时决定


# 全局单例
CORE = PiTernaryCore()
