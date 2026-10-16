# -*- coding: utf-8 -*-
"""
九转编码引擎 (Nine Transform Engine)
======================================
总调度入口，统一管理九类转换算子，提供单转、多转链式运算接口。
"""

from __future__ import annotations
import json, math, logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# 导入九转算子
from nine_transform_operators import (
    t1_sheng, t2_cheng, t3_luoshu, t4_bianwei,
    t5_yinyang, t6_sancai, t7_sixiang, t8_bagua, t9_guiyuan,
    chain_run, chain_full, REGISTRY, list_ops, TransformResult
)

# 导入概念注册表
from concept_registry import get_registry, Concept

class NineTransformEngine:
    """九转编码引擎——主调度核心"""
    
    def __init__(self):
        self.registry = get_registry()
        self.history: List[dict] = []
        self._config = {
            "strict_mode": False,       # 严格模式（越界报错）/宽松模式（自动截断）
            "auto_normalize": True,     # 自动归一化
            "log_detail": False,        # 详细日志
            "max_chain_depth": 20,      # 最大链式深度
        }
    
    # ── 配置接口 ──
    def configure(self, **kwargs):
        self._config.update(kwargs)
    
    def get_config(self) -> dict:
        return dict(self._config)
    
    # ── 单转运算 ──
    def transform(self, transform_id: str, value: Any) -> TransformResult:
        """执行单一转换"""
        if transform_id not in REGISTRY:
            return {"success": False, "value": 0, "meaning": "", "wuxing": "", "error": f"未知算子:{transform_id}"}
        try:
            result = REGISTRY[transform_id]["func"](value)
            self._log({"type": "single", "op": transform_id, "input": value, "result": result})
            return result
        except Exception as e:
            err = {"success": False, "value": 0, "meaning": "", "wuxing": "", "error": str(e)}
            self._log({"type": "single", "op": transform_id, "input": value, "result": err})
            return err
    
    # ── 链式运算 ──
    def chain(self, transform_ids: List[str], values: List[Any]) -> Dict[str, TransformResult]:
        """链式多转运算"""
        result = chain_run(transform_ids, values)
        self._log({"type": "chain", "ops": transform_ids, "inputs": values, "results": result})
        return result
    
    def full_chain(self, values: List[Any]) -> Dict[str, TransformResult]:
        """全九转顺序串联"""
        ids = ["1_sheng","2_cheng","3_luoshu","4_bianwei",
               "5_yinyang","6_sancai","7_sixiang","8_bagua","9_guiyuan"]
        return self.chain(ids, values)
    
    # ── 概念坐标转换 ──
    def encode_concept(self, concept_name: str) -> Optional[Dict[str, Any]]:
        """将概念编码为九维坐标并逐转解析"""
        c = self.registry.get(concept_name)
        if not c:
            return None
        
        coords = c.coords
        result = {
            "concept": c.name,
            "cid": c.cid,
            "desc": c.desc,
            "coords": coords,
            "transforms": {}
        }
        
        # 逐转解析
        tid_map = {
            "sheng": ("1_sheng", coords.get("sheng", 3)),
            "cheng": ("2_cheng", coords.get("cheng", 8)),
            "luoshu": ("3_luoshu", coords.get("luoshu", 5)),
            "bianwei": ("4_bianwei", coords.get("bianwei", 0)),
            "yinyang": ("5_yinyang", coords.get("yinyang", 0.0)),
            "sancai": ("6_sancai", coords.get("sancai", 0.5)),
            "sixiang": ("7_sixiang", coords.get("sixiang", 0)),
            "bagua": ("8_bagua", coords.get("bagua", 7)),
            "guiyuan": ("9_guiyuan", coords.get("guiyuan", 0.5)),
        }
        
        for dim, (tid, val) in tid_map.items():
            if dim in coords:
                result["transforms"][dim] = self.transform(tid, val)
        
        return result
    
    # ── 概念比较 ──
    def compare(self, name_a: str, name_b: str) -> Dict[str, Any]:
        """比较两个概念在九维空间中的关系"""
        a = self.registry.get(name_a)
        b = self.registry.get(name_b)
        if not a or not b:
            return {"error": f"未找到概念: {name_a if not a else name_b}"}
        
        dims = ["sheng","cheng","luoshu","bianwei","yinyang","sancai","sixiang","bagua","guiyuan"]
        diffs = {}
        total_dist = 0.0
        for d in dims:
            va = a.coords.get(d, 0)
            vb = b.coords.get(d, 0)
            diff = round(vb - va, 4)
            diffs[d] = {"a": va, "b": vb, "diff": diff}
            total_dist += diff ** 2
        
        total_dist = round(math.sqrt(total_dist), 4)
        
        # 五行关系推导
        wx_a = None
        wx_b = None
        for d in dims:
            r = self.transform(f"{list(REGISTRY.keys())[list(REGISTRY.keys()).index(d+"xx") if d+"xx" in REGISTRY else 0]}" if False else None, 0)
        # 用洛书卦位推导五行
        ls_a = self.transform("3_luoshu", a.coords.get("luoshu", 5))
        ls_b = self.transform("3_luoshu", b.coords.get("luoshu", 5))
        
        return {
            "concept_a": a.name,
            "concept_b": b.name,
            "euclidean_dist": total_dist,
            "dimension_diffs": diffs,
            "wuxing_a": ls_a.get("wuxing", "") if ls_a.get("success") else "",
            "wuxing_b": ls_b.get("wuxing", "") if ls_b.get("success") else "",
        }
    
    # ── 搜索概念 ──
    def search(self, keyword: str) -> List[dict]:
        """搜索概念"""
        return [c.to_dict() for c in self.registry.search(keyword)]
    
    # ── 九宫定位 ──
    def orient(self, concept_name: str) -> Dict[str, Any]:
        """九宫定位：确定概念在九宫格中的位置"""
        c = self.registry.get(concept_name)
        if not c:
            return {"error": f"未找到:{concept_name}"}
        
        ls = c.coords.get("luoshu", 5)
        ls_result = self.transform("3_luoshu", ls)
        
        # 九宫坐标 (3x3 矩阵)
        # 4 9 2
        # 3 5 7
        # 8 1 6
        luoshu_grid = {
            1: (2, 0), 2: (0, 2), 3: (1, 0), 4: (0, 1),
            5: (1, 1), 6: (2, 2), 7: (1, 2), 8: (2, 1), 9: (0, 0)
        }
        grid_pos = luoshu_grid.get(int(ls), (1, 1))
        
        return {
            "concept": c.name,
            "luoshu_number": int(ls),
            "grid_position": grid_pos,
            "palace": ls_result.get("meaning", ""),
            "wuxing": ls_result.get("wuxing", ""),
        }
    
    # ── 日志 ──
    def _log(self, entry: dict):
        entry["timestamp"] = datetime.now().isoformat()
        self.history.append(entry)
        if self._config["log_detail"]:
            logger.info(f"Engine: {json.dumps(entry, ensure_ascii=False)}")
    
    def get_history(self, limit: int = 10) -> List[dict]:
        return self.history[-limit:]
    
    def clear_history(self):
        self.history.clear()
    
    def status(self) -> dict:
        return {
            "operators": len(REGISTRY),
            "concepts": self.registry.count(),
            "history_entries": len(self.history),
            "config": self._config,
        }
    
    def operator_info(self) -> List[dict]:
        return list_ops()

# 全局单例
_instance: Optional[NineTransformEngine] = None

def get_engine() -> NineTransformEngine:
    global _instance
    if _instance is None:
        _instance = NineTransformEngine()
    return _instance

if __name__ == "__main__":
    engine = get_engine()
    print("=" * 60)
    print("  九转编码引擎 · 自检报告")
    print("=" * 60)
    print(f"  已注册算子: {len(engine.operator_info())} 个")
    print(f"  已注册概念: {engine.registry.count()} 个")
    print()
    
    print("--- 单转测试: t3_luoshu(5) ---")
    r = engine.transform("3_luoshu", 5)
    print(f"  {r}")
    
    print()
    print("--- 概念编码: 心 ---")
    r = engine.encode_concept("心")
    print(f"  概念: {r["concept"]}")
    print(f"  坐标: {r["coords"]}")
    for dim, tr in r["transforms"].items():
        print(f"  {dim}: {tr["value"]} -> {tr["wuxing"]} {tr["meaning"]}")
    
    print()
    print("--- 概念比较: 肝 vs 肺 ---")
    r = engine.compare("肝", "肺")
    print(f"  欧氏距离: {r["euclidean_dist"]}")
    print(f"  肝: {r["wuxing_a"]}, 肺: {r["wuxing_b"]}")
    
    print()
    print("--- 九宫定位: 心 ---")
    r = engine.orient("心")
    print(f"  {r}")
    
    print()
    print("--- 引擎状态 ---")
    print(f"  {engine.status()}")
    print()
    print("✅ 引擎就绪！")
