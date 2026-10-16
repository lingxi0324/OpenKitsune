"""
【洛书九宫纯数学演化引擎】
===========================
三生万物 · 生生不息

核心原理：
  九宫格 = {(1,-1)→{-1,0,+1}} 三进制细胞自动机
  中宫(5) = 定海神针·永远为中(0)
  每轮演化 = (自身 + 邻居和 + 熵偏移) mod 3
  3步一周期 → 三生万物

哲学映射：
  第一轮(阳) → 开辟 / 创造 / 显现
  第二轮(阴) → 收敛 / 沉淀 / 反刍  
  第三轮(中) → 整合 / 归位 / 新生
  三生万物 → 万象更新
"""

import math
import random
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field


# ============================================================
# 九宫布局（洛书原图）
# ============================================================
# 洛书传统布局:
#   4  9  2
#   3  5  7
#   8  1  6
#
# 九宫位置索引 (行,列):
#   (0,0)=4, (0,1)=9, (0,2)=2
#   (1,0)=3, (1,1)=5, (1,2)=7
#   (2,0)=8, (2,1)=1, (2,2)=6

# 九宫宫位名
PALACE_NAMES = {
    (0, 0): "巽宫", (0, 1): "离宫", (0, 2): "坤宫",
    (1, 0): "震宫", (1, 1): "中宫", (1, 2): "兑宫",
    (2, 0): "艮宫", (2, 1): "坎宫", (2, 2): "乾宫",
}

# 九宫方位
PALACE_DIRECTIONS = {
    (0, 0): "东南", (0, 1): "正南", (0, 2): "西南",
    (1, 0): "正东", (1, 1): "中央", (1, 2): "正西",
    (2, 0): "东北", (2, 1): "正北", (2, 2): "西北",
}

# 九宫五行
PALACE_WUXING = {
    (0, 0): "木", (0, 1): "火", (0, 2): "土",
    (1, 0): "木", (1, 1): "土", (1, 2): "金",
    (2, 0): "土", (2, 1): "水", (2, 2): "金",
}

# 邻居偏移（四正+四隅）
NEIGHBOR_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

# 传统洛书数值（用于初始映射）
LUOSHU_MAP = {
    (0, 0): 4, (0, 1): 9, (0, 2): 2,
    (1, 0): 3, (1, 1): 5, (1, 2): 7,
    (2, 0): 8, (2, 1): 1, (2, 2): 6,
}


def _luoshu_to_ternary(val: int) -> int:
    """
    洛书数值(1-9) → 三进制值{-1,0,+1}
    
    映射规则：
      5  (中土) → 0  (中·定海神针)
      1,3(水木) → -1 (阴)
      7,9(火金) → +1 (阳)
      2,4,6,8(隅) → 从邻位推算
      
    简化版：小于5→-1, 等于5→0, 大于5→+1
    """
    if val == 5:
        return 0
    return -1 if val < 5 else 1


# π小数位缓存（懒加载）
_PI_DECIMALS: Optional[List[int]] = None


def _get_pi_decimals(count: int = 1000) -> List[int]:
    """获取π的小数位数字序列（缓存）"""
    global _PI_DECIMALS
    if _PI_DECIMALS is None:
        # 用高精度π计算
        from decimal import Decimal, getcontext
        getcontext().prec = count + 20
        pi_str = str(Decimal(math.pi) * 10 ** count)
        # 改用 math.pi + Decimal 精确计算
        # 实际上我们用内置值就够了
        _PI_DECIMALS = []
        pi_approx = str(math.pi)
        # 只取小数部分
        if '.' in pi_approx:
            digits = pi_approx.split('.')[1]
            for ch in digits:
                _PI_DECIMALS.append(int(ch))
        # 如果不够，用随机补
        while len(_PI_DECIMALS) < count:
            _PI_DECIMALS.append(random.randint(0, 9))
    return _PI_DECIMALS[:count]


def _ternary_mod(val: int) -> int:
    """将任意整数映射到{-1, 0, +1}"""
    r = val % 3
    if r == 2:
        return -1
    return r


# ══════════════════════════════════════════════════
# 洛书九宫格
# ══════════════════════════════════════════════════

@dataclass
class LuoshuGrid:
    """
    洛书九宫 — 纯三进制细胞自动机
    
    grid[行][列] ∈ {-1, 0, +1}
    其中 grid[1][1] 永远为 0（中宫·定海神针）
    """
    grid: List[List[int]] = field(default_factory=lambda: [
        [_luoshu_to_ternary(LUOSHU_MAP[(r, c)]) for c in range(3)]
        for r in range(3)
    ])
    cycle: int = 0        # 当前轮次（从0开始）
    pi_index: int = 0      # π小数位游标
    potential: float = 0.0  # 整体势能 [-1, 1]
    phase: int = 0         # 三生万物相位 (0/1/2)
    history: List[List[List[int]]] = field(default_factory=list)

    def __post_init__(self):
        """自动计算初始势能"""
        self.potential = self.compute_potential()

    @property
    def is_stable(self) -> bool:
        """是否回到初始态（一轮三生万物完成）"""
        return self.cycle > 0 and self.cycle % 3 == 0

    def get_cell_value(self, row: int, col: int) -> int:
        """安全获取指定格的值（越界返回0）"""
        if 0 <= row < 3 and 0 <= col < 3:
            return self.grid[row][col]
        return 0

    def get_neighbors_sum(self, row: int, col: int) -> int:
        """计算指定格的八邻域和"""
        total = 0
        for dr, dc in NEIGHBOR_OFFSETS:
            nr, nc = row + dr, col + dc
            total += self.get_cell_value(nr, nc)
        return total

    def compute_potential(self) -> float:
        """计算九宫整体势能 [-1, 1]
        
        势能 = Σ所有格值 / 9 （归一化）
        正值 = 偏阳（发散/扩张）
        负值 = 偏阴（收敛/内收）
        近0  = 中和（平衡态）
        """
        total = sum(sum(row) for row in self.grid)
        return total / 9.0

    def compute_diversity(self) -> float:
        """计算九宫多样性 [0, 1]
        
        多样性 = 非零格数 / 8（中宫不算）
        0  = 全零（死寂）
        1  = 全非零（极度活跃）
        """
        non_zero = 0
        for r in range(3):
            for c in range(3):
                if (r, c) != (1, 1) and self.grid[r][c] != 0:
                    non_zero += 1
        return non_zero / 8.0

    def get_phase_label(self) -> str:
        """获取当前相位的文字标签"""
        labels = {0: "阳·开辟", 1: "阴·收敛", 2: "中·归一"}
        return labels.get(self.phase, "中·归一")

    def get_grid_summary(self) -> str:
        """九宫状态摘要（一行字符串）"""
        rows = []
        for r in range(3):
            row_str = " ".join(f"{v:+d}" for v in self.grid[r])
            rows.append(row_str)
        return " | ".join(rows)

    def get_palace_states(self) -> Dict[str, int]:
        """返回各宫位名称→值的映射"""
        states = {}
        for (r, c), name in PALACE_NAMES.items():
            states[name] = self.grid[r][c]
        return states

    def evolve(self, entropy_source: Optional[List[float]] = None) -> 'LuoshuGrid':
        """
        演化一步（一轮洛书演化）
        
        规则：
          1. 中宫(1,1) 永远 = 0
          2. 其他每宫: 
             new_val = (自身值 + 邻居和 + 熵偏移) mod 3
          3. 熵偏移来源：
             - 默认: π小数位序列
             - 外部熵源: 传入的 entropy_source
        
        三生万物周期：
          轮次%3==0 → 阳位(开辟)    势能偏正
          轮次%3==1 → 阴位(收敛)    势能偏负  
          轮次%3==2 → 中位(归一)    势能归中
        
        返回: 新网格（不修改自身）
        """
        new_grid = [[0] * 3 for _ in range(3)]
        
        # 获取π熵序列
        pi_digits = _get_pi_decimals(1000)
        
        for r in range(3):
            for c in range(3):
                if (r, c) == (1, 1):
                    # 中宫永远为中
                    new_grid[r][c] = 0
                    continue
                
                current = self.grid[r][c]
                neighbor_sum = self.get_neighbors_sum(r, c)
                
                # 熵偏移
                if entropy_source and len(entropy_source) > self.pi_index:
                    entropy = int(entropy_source[self.pi_index] * 3) % 3
                    entropy = _ternary_mod(entropy)
                else:
                    idx = self.pi_index % len(pi_digits)
                    entropy = _ternary_mod(pi_digits[idx])
                
                # 相位偏移（三生万物周期）
                # 轮0 → 偏阳 (+0~+1)
                # 轮1 → 偏阴 (-1~0)
                # 轮2 → 归中 (0)
                phase_offset = 0
                # 用即将成为的新轮次计算相位偏移
                # 这样 phase 标签（新轮次）和偏移计算对齐
                phase_val = (self.cycle + 1) % 3
                if phase_val == 0:
                    phase_offset = 1  # 阳位偏移
                elif phase_val == 1:
                    phase_offset = -1  # 阴位偏移
                # phase_val == 2 → 归中，无偏移
                
                # 新值 = (自身 + 邻居 + 熵 + 相位) mod 3
                raw = current + neighbor_sum + entropy + phase_offset
                new_grid[r][c] = _ternary_mod(raw)
                
                self.pi_index = (self.pi_index + 1) % 1000
        
        # 创建新网格
        result = LuoshuGrid(
            grid=new_grid,
            cycle=self.cycle + 1,
            pi_index=self.pi_index,
            phase=(self.cycle + 1) % 3,
        )
        # potential 已在 __post_init__ 中自动计算
        
        # 保存历史
        self.history.append([row[:] for row in self.grid])
        if len(self.history) > 100:
            self.history = self.history[-100:]
        
        return result

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "grid": [row[:] for row in self.grid],
            "cycle": self.cycle,
            "potential": self.potential,
            "phase": self.phase,
            "phase_label": self.get_phase_label(),
            "diversity": self.compute_diversity(),
            "is_stable": self.is_stable,
            "palace_states": self.get_palace_states(),
        }

    def __repr__(self) -> str:
        return (f"洛书九宫(轮{self.cycle}/"
                f"相{self.get_phase_label()}/"
                f"势{self.potential:+.3f})")


def create_grid_from_state(state_values: List[List[int]]) -> LuoshuGrid:
    """
    从指定状态创建九宫格
    
    参数:
        state_values: 3x3矩阵，值 ∈ {-1, 0, +1}
                      中宫(1,1)会被强制设为0
    """
    grid = [[0] * 3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            val = state_values[r][c]
            if (r, c) == (1, 1):
                grid[r][c] = 0
            else:
                grid[r][c] = _ternary_mod(val)
    
    result = LuoshuGrid(grid=grid)
    return result  # __post_init__ 已自动计算potential


def create_default_grid() -> LuoshuGrid:
    """创建默认初始网格（基于洛书原始映射）"""
    return LuoshuGrid()


if __name__ == "__main__":
    # 演示：运行15轮看看效果
    grid = create_default_grid()
    print(f"初始: {grid.get_grid_summary()}  势={grid.potential:+.3f}")
    
    for i in range(15):
        grid = grid.evolve()
        print(f"轮{i+1:2d} {grid.get_phase_label()}: "
              f"{grid.get_grid_summary()}  "
              f"势={grid.potential:+.3f}  "
              f"多={grid.compute_diversity():.2f}")
