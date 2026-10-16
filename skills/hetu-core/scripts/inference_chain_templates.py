# -*- coding: utf-8 -*-
"""
链式思维模板 (Inference Chain Templates)
==========================================
预定义的推论链模式，用于引导九转推理的典型路径。
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any

class ChainTemplate:
    """单条链式模板"""
    
    def __init__(self, cid: str, name: str, description: str,
                 transforms: List[str], context_hint: str = ""):
        self.cid = cid
        self.name = name
        self.description = description
        self.transforms = transforms  # 算子ID链
        self.context_hint = context_hint
    
    def to_dict(self) -> dict:
        return {"cid": self.cid, "name": self.name, "desc": self.description,
                "transforms": self.transforms, "hint": self.context_hint}

# ── 预置模板库 ──

TEMPLATES = [
    ChainTemplate("wuxing_cycle", "五行生克链",
        "从河图生数开始，经洛书定位，到阴阳消长，推导五行生克关系",
        ["1_sheng", "3_luoshu", "5_yinyang"],
        "适用于分析五脏/五味/五色之间的生克关系"),

    ChainTemplate("organ_diagnosis", "脏腑诊断链",
        "从洛书定位到四象方向到八卦辨象，推断脏腑性质",
        ["3_luoshu", "7_sixiang", "8_bagua"],
        "适用于中医脏腑辨证，推断脏腑间关系"),

    ChainTemplate("yin_yang_evolution", "阴阳演化链",
        "从阴阳消长到三才层次到归元转化，推演状态演化",
        ["5_yinyang", "6_sancai", "9_guiyuan"],
        "适用于分析事物从产生到发展再到归元的全过程"),

    ChainTemplate("hetu_complete", "河图全息链",
        "生数+成数完整编码，推演河图全息结构",
        ["1_sheng", "2_cheng"],
        "适用于分析天地生成数之间的全息对应关系"),

    ChainTemplate("orientation_map", "空间定位链",
        "洛书+四象+八卦三重定位，确定空间方位",
        ["3_luoshu", "7_sixiang", "8_bagua"],
        "适用于确定事物在空间中的方位属性"),

    ChainTemplate("full_spectrum", "全频谱分析链",
        "九转全序列贯通，做最完整的概念频谱分析",
        ["1_sheng", "2_cheng", "3_luoshu", "4_bianwei",
         "5_yinyang", "6_sancai", "7_sixiang", "8_bagua", "9_guiyuan"],
        "适用于需要全面理解一个概念的所有属性维度"),

    ChainTemplate("causality", "因果推论链",
        "从现象(洛书变位)溯因(河图生数)，再推果(归元转化)",
        ["4_bianwei", "1_sheng", "9_guiyuan"],
        "适用于分析因果关系：现象→根源→结果"),

    ChainTemplate("balance_analysis", "平衡分析链",
        "阴阳+变位+三才，综合评价平衡状态",
        ["5_yinyang", "4_bianwei", "6_sancai"],
        "适用于评估系统的平衡性和稳定性"),
]

TEMPLATE_MAP = {t.cid: t for t in TEMPLATES}

def get_template(cid: str) -> Optional[ChainTemplate]:
    return TEMPLATE_MAP.get(cid)

def list_templates() -> List[dict]:
    return [t.to_dict() for t in TEMPLATES]

def suggest_template(concept_name: str = "", tags: List[str] = None) -> List[ChainTemplate]:
    """根据概念名或标签推荐合适的模板"""
    tags = tags or []
    kw = concept_name.lower()
    
    # 关键词-模板映射
    kw_map = {
        "肝": ["wuxing_cycle"], "心": ["wuxing_cycle", "full_spectrum"],
        "脾": ["balance_analysis"], "肺": ["wuxing_cycle"], "肾": ["wuxing_cycle"],
        "病": ["organ_diagnosis", "causality"], "证": ["organ_diagnosis"],
        "方": ["orientation_map"], "位": ["orientation_map"],
        "时": ["yin_yang_evolution"], "变": ["yin_yang_evolution"],
        "因果": ["causality"], "平衡": ["balance_analysis"],
    }
    
    matched_ids = set()
    for tag in tags:
        for k, v in kw_map.items():
            if tag.lower() in k or k in tag.lower():
                matched_ids.update(v)
    
    for k, v in kw_map.items():
        if k in kw:
            matched_ids.update(v)
    
    results = [TEMPLATE_MAP[cid] for cid in matched_ids if cid in TEMPLATE_MAP]
    if not results:
        results = [TEMPLATE_MAP["full_spectrum"]]  # 默认全频谱
    
    return results


if __name__ == "__main__":
    print("=" * 50)
    print("  链式思维模板 · 清单")
    print("=" * 50)
    for t in TEMPLATES:
        print(f"\n  [{t.cid}] {t.name}")
        print(f"  描述: {t.description}")
        print(f"  链: {' → '.join(t.transforms)}")
    
    print()
    print("--- 推荐模板 (概念=肝) ---")
    for t in suggest_template("肝"):
        print(f"  {t.cid}: {t.name}")
    
    print()
    print("--- 推荐模板 (概念=平衡) ---")
    for t in suggest_template("平衡"):
        print(f"  {t.cid}: {t.name}")
    
    print(f"\n共 {len(TEMPLATES)} 个模板")
