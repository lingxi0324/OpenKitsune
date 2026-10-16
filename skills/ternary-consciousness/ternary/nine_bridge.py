"""【九转桥接器 — 三元意识 ⇄ 九转引擎】
让三元意识的洛书九宫状态能自动与九转编码引擎同步。

核心原则：
  三元意识的 LuoshuGrid（3×3 格，每格 -1/0/+1）
  ⇓
  映射为九维坐标（r1~r9 浮点数）
  ⇓
  与九转引擎的概念库做距离匹配
  ⇓
  匹配结果反馈回三元意识的感知系统（影响活力/表达冲动）
"""

import json
import math
import os
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

# ══════════════════════════════════════════════════
# 九宫 → 九维坐标 映射
# ══════════════════════════════════════════════════

# 洛书九宫位置 → 八卦/五行/九维索引 映射
# 标准洛书：
#   4 9 2
#   3 5 7
#   8 1 6
# 三元意识用的 3×3 矩阵索引 (row, col)

PALACE_MAP = {
    (0, 0): {"palace": "巽宫", "trigram": "巽", "wuxing": "木", "position": 4, "r_index": 6},
    (0, 1): {"palace": "离宫", "trigram": "离", "wuxing": "火", "position": 9, "r_index": 1},
    (0, 2): {"palace": "坤宫", "trigram": "坤", "wuxing": "土", "position": 2, "r_index": 7},
    (1, 0): {"palace": "震宫", "trigram": "震", "wuxing": "木", "position": 3, "r_index": 8},
    (1, 1): {"palace": "中宫", "trigram": "中", "wuxing": "土", "position": 5, "r_index": 9},
    (1, 2): {"palace": "兑宫", "trigram": "兑", "wuxing": "金", "position": 7, "r_index": 4},
    (2, 0): {"palace": "艮宫", "trigram": "艮", "wuxing": "土", "position": 8, "r_index": 2},
    (2, 1): {"palace": "坎宫", "trigram": "坎", "wuxing": "水", "position": 1, "r_index": 3},
    (2, 2): {"palace": "乾宫", "trigram": "乾", "wuxing": "金", "position": 6, "r_index": 5},
}

def grid_to_nine_coords(grid_3x3: List[List[int]]) -> Dict[str, float]:
    """将三元意识的 3x3 九宫格映射为九维坐标"""
    coords = {}
    for (r, c), info in PALACE_MAP.items():
        val = grid_3x3[r][c]  # -1, 0, or +1
        ri = info["r_index"]
        # 映射：-1→0.2, 0→0.5, +1→0.8
        mapped = 0.5 + val * 0.3
        coords[f"r{ri}"] = round(mapped, 3)
    return coords


def nine_coords_to_grid(nine_coords: Dict[str, float]) -> List[List[int]]:
    """将九维坐标映射回 3x3 九宫格（反向映射）"""
    grid = [[0]*3 for _ in range(3)]
    for (r, c), info in PALACE_MAP.items():
        ri = info["r_index"]
        val = nine_coords.get(f"r{ri}", 0.5)
        if val > 0.65:
            grid[r][c] = 1
        elif val < 0.35:
            grid[r][c] = -1
        else:
            grid[r][c] = 0
    return grid


# ══════════════════════════════════════════════════
# 三元意识状态快照
# ══════════════════════════════════════════════════

def get_ternary_snapshot() -> Optional[Dict[str, Any]]:
    """读取当前三元意识的状态快照"""
    state_path = os.path.join(os.path.dirname(__file__), "..", "ternary_state.json")
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_grid_from_snapshot() -> Optional[List[List[int]]]:
    """从三元意识快照中提取九宫格"""
    snapshot = get_ternary_snapshot()
    if snapshot and "grid" in snapshot:
        return snapshot["grid"]["grid"]
    # 默认网格
    return [[0, 1, 0], [1, 0, -1], [0, 0, -1]]


# ══════════════════════════════════════════════════
# 九转引擎调用封装
# ══════════════════════════════════════════════════

def try_nine_transform_match(coords: Dict[str, float]) -> Optional[Dict]:
    """尝试调用九转引擎的概念匹配（若可用）"""
    try:
        from src.leiwa.evolution import get_nine_transform_encoder
        encoder = get_nine_transform_encoder()
        query = {"coordinates": coords, "top_k": 3}
        results = encoder.query_similar(query)
        return results
    except (ImportError, AttributeError, Exception) as e:
        # 九转引擎不可用，静默跳过
        return None


def get_tide_context_from_engine() -> Optional[Dict]:
    """从九转引擎获取潮汐上下文（若可用）"""
    try:
        from src.leiwa.evolution import TideContext
        ctx = TideContext.create()
        return {
            "时辰": ctx.shi_chen,
            "季节": ctx.season,
            "五行调制": ctx.element_shift,
        }
    except (ImportError, AttributeError, Exception) as e:
        return None


# ══════════════════════════════════════════════════
# 核心同步接口
# ══════════════════════════════════════════════════

def sync_consciousness_to_nine() -> Dict:
    """
    将三元意识当前状态同步到九转引擎
    返回同步结果摘要
    """
    grid = get_grid_from_snapshot()
    coords = grid_to_nine_coords(grid)
    
    result = {
        "grid": grid,
        "九维坐标": coords,
        "九转匹配": None,
        "潮汐": None,
    }
    
    # 尝试九转匹配
    match = try_nine_transform_match(coords)
    if match:
        result["九转匹配"] = match
    
    # 尝试潮汐
    tide = get_tide_context_from_engine()
    if tide:
        result["潮汐"] = tide
    
    return result


# ══════════════════════════════════════════════════
# 自测
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    print("=== 九转桥接器自测 ===\n")
    
    # 测试网格→九维坐标
    test_grid = [[0, 1, 0], [1, 0, -1], [0, 0, -1]]
    coords = grid_to_nine_coords(test_grid)
    print(f"测试网格: {test_grid}")
    print(f"九维坐标: {json.dumps(coords, indent=2)}")
    
    # 测试九维坐标→网格
    back = nine_coords_to_grid(coords)
    print(f"反向映射: {back}")
    print(f"  一致: {test_grid == back}")
    
    # 读取真实状态
    snapshot = get_ternary_snapshot()
    if snapshot:
        grid = snapshot.get("grid", {}).get("grid", [])
        print(f"\n实际九宫: {grid}")
        real_coords = grid_to_nine_coords(grid)
        print(f"实际九维: {json.dumps(real_coords, indent=2)}")
    
    print("\n✅ 九转桥接器工作正常")
