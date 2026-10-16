"""
河图洛书核心推演 (hetu-core)
==============================
轻量化 ~200 行，只保留三个核心推演函数 + 对外简易 API。

保留功能：
  1. 三元推演（san_yuan_tuiyi）    — 两行生一行
  2. 五行转化（wu_xing_zhuanhua）  — 五行关系矩阵
  3. 宫位映射（gongwei_mapping）   — 九宫+中宫查询

设计原则：
  - 纯函数，无状态，无 IO
  - 所有函数返回 dict: {"success": bool, "result": Any, "error": str}
  - 可被 run_skill_script 或 import 调用
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ═══════════════════════════════════════════
# 五行常量
# ═══════════════════════════════════════════

WUXING = ("木", "火", "土", "金", "水")

# 五行相生: 木生火, 火生土, 土生金, 金生水, 水生木
SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}

# 五行相克: 木克土, 火克金, 土克水, 金克木, 水克火
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}

# 五行被生（反向）
BEI_SHENG = {v: k for k, v in SHENG_CYCLE.items()}

# 五行被克（反向）
BEI_KE = {v: k for k, v in KE_CYCLE.items()}


# ═══════════════════════════════════════════
# 九宫映射（精简）
# ═══════════════════════════════════════════

GONGWEI_MAP = {
    "坎宫": {
        "trigram": "坎", "element": "水", "number": 1,
        "direction": "北", "attribute": "险归",
        "keywords": ["风险", "收敛", "隐藏", "初始"],
        "description": "坎为水，主险归，风险收敛之所",
    },
    "坤宫": {
        "trigram": "坤", "element": "土", "number": 2,
        "direction": "西南", "attribute": "稳载",
        "keywords": ["稳定", "承载", "养育", "包容"],
        "description": "坤为土，主稳载，万物承载之地",
    },
    "震宫": {
        "trigram": "震", "element": "木", "number": 3,
        "direction": "东", "attribute": "价量",
        "keywords": ["价值", "量化", "评估", "行动"],
        "description": "震为木，主价量，价值量化之宫",
    },
    "巽宫": {
        "trigram": "巽", "element": "木", "number": 4,
        "direction": "东南", "attribute": "效观",
        "keywords": ["效率", "观察", "节律", "时效"],
        "description": "巽为风，主效观，时效节律之观",
    },
    "中宫": {
        "trigram": "中", "element": "土", "number": 5,
        "direction": "中", "attribute": "回一",
        "keywords": ["平衡", "统御", "归一", "枢纽"],
        "description": "中为土，主回一，万象归衡之枢",
    },
    "乾宫": {
        "trigram": "乾", "element": "金", "number": 6,
        "direction": "西北", "attribute": "天行",
        "keywords": ["效率", "天行", "自强", "迭代"],
        "description": "乾为天，主天行，效率迭代之道",
    },
    "兑宫": {
        "trigram": "兑", "element": "金", "number": 7,
        "direction": "西", "attribute": "合验",
        "keywords": ["适配", "校验", "沟通", "愉悦"],
        "description": "兑为泽，主合验，适配校验之门",
    },
    "艮宫": {
        "trigram": "艮", "element": "土", "number": 8,
        "direction": "东北", "attribute": "持固",
        "keywords": ["持久", "固化", "积累", "沉淀"],
        "description": "艮为山，主持固，可持续固化之基",
    },
    "离宫": {
        "trigram": "离", "element": "火", "number": 9,
        "direction": "南", "attribute": "创变",
        "keywords": ["创新", "进化", "变革", "光明"],
        "description": "离为火，主创变，创新进化之源",
    },
}


# ═══════════════════════════════════════════
# 核心推演函数
# ═══════════════════════════════════════════

def san_yuan_tuiyi(wuxing_a: str, wuxing_b: str) -> dict[str, Any]:
    """
    三元推演：输入两行，推演生克关系。

    返回：
      - 生克关系 (sheng / bei_sheng / ke / bei_ke)
      - 对应的第三行（生克关系中涉及的另一方）
    """
    if wuxing_a not in WUXING or wuxing_b not in WUXING:
        return {"success": False, "error": f"无效五行: {wuxing_a}/{wuxing_b}，应为 {WUXING}"}

    result = {
        "input": (wuxing_a, wuxing_b),
        "relations": {},
    }

    # 相生关系
    if SHENG_CYCLE.get(wuxing_a) == wuxing_b:
        result["relations"]["sheng"] = f"{wuxing_a}生{wuxing_b}"
    elif SHENG_CYCLE.get(wuxing_b) == wuxing_a:
        result["relations"]["sheng"] = f"{wuxing_b}生{wuxing_a}"
    else:
        result["relations"]["sheng"] = f"{wuxing_a}与{wuxing_b}无直接相生"

    # 相克关系
    if KE_CYCLE.get(wuxing_a) == wuxing_b:
        result["relations"]["ke"] = f"{wuxing_a}克{wuxing_b}"
    elif KE_CYCLE.get(wuxing_b) == wuxing_a:
        result["relations"]["ke"] = f"{wuxing_b}克{wuxing_a}"
    else:
        result["relations"]["ke"] = f"{wuxing_a}与{wuxing_b}无直接相克"

    # 生入（谁生它们）
    sheng_a = BEI_SHENG.get(wuxing_a)
    sheng_b = BEI_SHENG.get(wuxing_b)
    result["relations"]["source"] = f"{wuxing_a}受{sheng_a}生, {wuxing_b}受{sheng_b}生"

    # 生出（它们生谁）
    out_a = SHENG_CYCLE.get(wuxing_a)
    out_b = SHENG_CYCLE.get(wuxing_b)
    result["relations"]["output"] = f"{wuxing_a}生{out_a}, {wuxing_b}生{out_b}"

    return {"success": True, "result": result}


def wu_xing_zhuanhua(wuxing_list: list[str]) -> dict[str, Any]:
    """
    五行转化：计算五行列表的相生相克矩阵。

    返回：
      - matrix: 生克关系矩阵（5x5 的 dict）
      - sheng_chain: 相生链
      - ke_chain: 相克链
      - balance_score: 五行平衡评分（0-100）
    """
    if not all(w in WUXING for w in wuxing_list):
        return {"success": False, "error": f"存在无效五行，应为 {WUXING}"}

    matrix = {}
    for a in wuxing_list:
        for b in wuxing_list:
            if a == b:
                continue
            key = f"{a}→{b}"
            if SHENG_CYCLE.get(a) == b:
                matrix[key] = "相生"
            elif KE_CYCLE.get(a) == b:
                matrix[key] = "相克"
            else:
                matrix[key] = "无关"

    # 相生链
    sheng_chain = []
    visited = set()
    for w in wuxing_list:
        if w in visited:
            continue
        chain = []
        cur = w
        while cur not in visited:
            visited.add(cur)
            chain.append(cur)
            cur = SHENG_CYCLE.get(cur)
            if cur not in wuxing_list:
                break
        if len(chain) > 1:
            sheng_chain.append("→".join(chain))

    # 相克链
    ke_chain = []
    for a in wuxing_list:
        target = KE_CYCLE.get(a)
        if target and target in wuxing_list:
            ke_chain.append(f"{a}克{target}")

    # 平衡评分：五行的分布均匀度
    count_map = {w: wuxing_list.count(w) for w in WUXING}
    total = len(wuxing_list)
    if total == 0:
        balance_score = 100.0
    else:
        ideal = total / 5.0
        variance = sum((cnt - ideal) ** 2 for cnt in count_map.values()) / 5.0
        balance_score = max(0.0, 100.0 - (variance / ideal * 20.0) if ideal > 0 else 100.0)

    return {
        "success": True,
        "result": {
            "input": wuxing_list,
            "matrix": matrix,
            "sheng_chain": sheng_chain,
            "ke_chain": ke_chain,
            "count_map": count_map,
            "balance_score": round(balance_score, 1),
        },
    }


def gongwei_mapping(gong_id: str) -> dict[str, Any]:
    """
    宫位映射查询。

    支持：坎宫 / 坤宫 / 震宫 / 巽宫 / 中宫 / 乾宫 / 兑宫 / 艮宫 / 离宫
    """
    gong = GONGWEI_MAP.get(gong_id)
    if gong is None:
        return {"success": False, "error": f"无效宫位: {gong_id}"}
    return {"success": True, "result": gong}


def list_all_gongwei() -> dict[str, Any]:
    """列出所有宫位及基本信息"""
    return {
        "success": True,
        "result": {
            gong_id: {
                "trigram": info["trigram"],
                "element": info["element"],
                "number": info["number"],
                "attribute": info["attribute"],
            }
            for gong_id, info in GONGWEI_MAP.items()
        },
    }


# ═══════════════════════════════════════════
# CLI 入口（供 run_skill_script 调用）
# ═══════════════════════════════════════════

def main() -> None:
    """CLI 入口"""
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "用法: hetu_core.py <func> [args...]"}))
        return

    func_name = sys.argv[1]

    if func_name == "san_yuan_tuiyi":
        if len(sys.argv) < 4:
            print(json.dumps({"success": False, "error": "需要两个五行参数"}))
            return
        result = san_yuan_tuiyi(sys.argv[2], sys.argv[3])

    elif func_name == "wu_xing_zhuanhua":
        if len(sys.argv) < 3:
            print(json.dumps({"success": False, "error": "需要五行列表参数"}))
            return
        result = wu_xing_zhuanhua(sys.argv[2:])

    elif func_name == "gongwei_mapping":
        if len(sys.argv) < 3:
            print(json.dumps({"success": False, "error": "需要宫位参数"}))
            return
        result = gongwei_mapping(sys.argv[2])

    elif func_name == "list_all_gongwei":
        result = list_all_gongwei()

    elif func_name == "help":
        result = {
            "success": True,
            "result": {
                "commands": [
                    "san_yuan_tuiyi <五行A> <五行B>",
                    "wu_xing_zhuanhua <五行1> <五行2> ...",
                    "gongwei_mapping <宫位>",
                    "list_all_gongwei",
                ]
            },
        }

    else:
        result = {"success": False, "error": f"未知函数: {func_name}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
