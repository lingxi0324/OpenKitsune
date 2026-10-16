# -*- coding: utf-8 -*-
"""
九转编码核心 (Nine Transform Core)
====================================
对话层集成模块，统一汇总九转编码引擎的所有组件，
提供简洁的顶层接口供外部调用。
"""

from __future__ import annotations
import json, math
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from nine_transform_operators import (
    t1_sheng, t2_cheng, t3_luoshu, t4_bianwei,
    t5_yinyang, t6_sancai, t7_sixiang, t8_bagua, t9_guiyuan,
    chain_run, chain_full, REGISTRY, list_ops,
    t1_reverse, t2_reverse, t3_reverse, t7_reverse, t8_reverse,
)

from concept_registry import get_registry, ConceptRegistry, Concept
from nine_transform_engine import NineTransformEngine, get_engine
from tide_modulator import TideModulator
from inference_chain_templates import ChainTemplate, get_template, list_templates, suggest_template
from self_excitation_scheduler import SelfExcitationScheduler


class NineTransformCore:
    """九转编码核心——统一入口"""
    
    def __init__(self):
        self.engine = get_engine()
        self.tide = TideModulator()
        self.scheduler = SelfExcitationScheduler(self.engine)
        self._initialized = True
    
    # ── 基础查询 ──
    def status(self) -> dict:
        return {
            "operators": len(list_ops()),
            "concepts": self.engine.registry.count(),
            "templates": len(list_templates()),
            "engine_ready": True,
            "tide_active": True,
        }
    
    def list_operators(self) -> List[dict]:
        return list_ops()
    
    def list_concepts(self) -> List[dict]:
        return [c.to_dict() for c in self.engine.registry.all()]
    
    def list_templates(self) -> List[dict]:
        return list_templates()
    
    # ── 核心运算 ──
    def encode(self, concept_or_value, as_concept: bool = True) -> Dict[str, Any]:
        """编码：将概念或数值编码为九维坐标"
        若 as_concept=True 且输入是字符串，做概念编码；
        否则对数值做九转全链运算。
        """
        if as_concept and isinstance(concept_or_value, str):
            result = self.engine.encode_concept(concept_or_value)
            if result:
                return result
            # 尝试搜索
            results = self.engine.search(concept_or_value)
            if results:
                return {"suggestions": [r["name"] for r in results[:5]]}
            return {"error": f"未知概念:{concept_or_value}"}
        
        v = _safe_float(concept_or_value)
        full = self.engine.full_chain([v]*9)
        return {"input": v, "transforms": full}
    
    def compare(self, concept_a: str, concept_b: str) -> Dict[str, Any]:
        return self.engine.compare(concept_a, concept_b)
    
    def orient(self, concept_name: str) -> Dict[str, Any]:
        return self.engine.orient(concept_name)
    
    def search(self, keyword: str) -> List[dict]:
        return self.engine.search(keyword)
    
    def transform(self, op_id: str, value: Any) -> dict:
        return self.engine.transform(op_id, value)
    
    # ── 链式推理 ──
    def infer(self, template_id: str, values: List[Any]) -> Dict[str, Any]:
        """按模板执行链式推理"
        参数：
          template_id: 模板ID
          values: 各算子的输入值（长度需匹配模板链长度）
        """
        tmpl = get_template(template_id)
        if not tmpl:
            return {"error": f"未知模板:{template_id}"}
        
        tids = tmpl.transforms
        if len(values) != len(tids):
            return {"error": f"值数量不匹配: 需{len(tids)}个, 实{len(values)}个"}
        
        results = {}
        for tid, val in zip(tids, values):
            r = self.engine.transform(tid, val)
            results[tid] = r
        
        return {
            "template": template_id,
            "name": tmpl.name,
            "description": tmpl.description,
            "results": results,
        }
    
    def suggest(self, concept_or_tag: str) -> List[dict]:
        """推荐推理模板"""
        templates = suggest_template(concept_or_tag)
        return [t.to_dict() for t in templates]
    
    # ── 自激循环 ──
    def excite(self, start_value: float, feedback_dim: str = "luoshu",
               max_iter: int = 20) -> Dict[str, Any]:
        """启动自激循环"""
        return self.scheduler.run(start_value, feedback_dim=feedback_dim, max_iter=max_iter)
    
    def analyze_cycle(self, result: Dict[str, Any]) -> str:
        return self.scheduler.analyze(result)
    
    # ── 潮汐调制 ──
    def tide_now(self) -> Dict[str, Any]:
        return self.tide.get_tide()
    
    def tide_report(self) -> str:
        return self.tide.tide_report()
    
    def apply_tide(self, value: float, dim: str) -> Dict[str, float]:
        return self.tide.apply(value, dim)
    
    # ── 实用工具 ──
    def wuxing_meaning(self, wuxing: str) -> str:
        """查询五行含义"""
        meanings = {
            "木": "生发·条达·仁", "火": "炎上·礼·明",
            "土": "稼穑·信·中", "金": "从革·义·肃",
            "水": "润下·智·藏",
        }
        return meanings.get(wuxing, f"未知五行:{wuxing}")
    
    def generate_insight(self, concept_name: str) -> str:
        """对一个概念生成九转洞察文本"""
        enc = self.encode(concept_name)
        if "error" in enc:
            return f"无法编码概念「{concept_name}」"
        
        lines = [f"🏮 九转洞察 · {concept_name}", "=" * 30]
        
        if "transforms" in enc:
            for dim, tr in enc["transforms"].items():
                if tr.get("success"):
                    lines.append(f"  {dim}: {tr['meaning']} (五行: {tr['wuxing']})")
        
        # 潮汐加持
        tide = self.tide_now()
        lines.append(f"\n🌊 潮汐: {tide['shichen']}时 {tide['dominant_wuxing']}当令 潮位{tide['tide_level']:+0.3f}")
        
        # 推荐模板
        suggested = self.suggest(concept_name)
        if suggested:
            lines.append(f"\n💡 推荐推理: {suggested[0]['name']}")
        
        return "\n".join(lines)


# ── 便捷函数 ──
def nine_transform(concept_or_value):
    """一键九转编码"
    用法：nine_transform("肝") 或 nine_transform(5)
    """
    core = NineTransformCore()
    return core.encode(concept_or_value)


def _safe_float(v, default=0.0):
    if v is None: return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return default
        return f
    except: return default


if __name__ == "__main__":
    core = NineTransformCore()
    
    print("=" * 60)
    print("  九转编码核心 · 全系统自检")
    print("=" * 60)
    print(f"  状态: {core.status()}")
    print()
    
    # 概念洞察
    print("--- 洞察: 肝 ---")
    print(core.generate_insight("肝"))
    
    print()
    print("--- 洞察: 心 ---")
    print(core.generate_insight("心"))
    
    print()
    print("--- 概念比较: 肝 vs 肺 ---")
    r = core.compare("肝", "肺")
    print(f"  距离: {r['euclidean_dist']} | {r['wuxing_a']} vs {r['wuxing_b']}")
    
    print()
    print("--- 潮汐报告 ---")
    print(core.tide_report())
    
    print()
    print("--- 推荐模板 (平衡) ---")
    for t in core.suggest("平衡"):
        print(f"  {t['cid']}: {t['name']}")
    
    print()
    print("--- 一键函数 ---")
    r = nine_transform("肾")
    print(f"  肾: {r['coords']}")
    for dim, tr in r['transforms'].items():
        print(f"    {dim}: {tr['meaning']} ({tr['wuxing']})")
    
    print()
    print("✅ 全系统就绪！")
