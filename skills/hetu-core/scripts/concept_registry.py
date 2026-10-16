# -*- coding: utf-8 -*-
"""
概念注册表 (Concept Registry)
=============================
九转编码引擎的概念映射词典基座，包含284个预注册概念。
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any

# 九维坐标向量类型
CoordVector = Dict[str, float]
"""九维坐标: {"sheng":1-5, "cheng":6-10, "luoshu":1-9, "bianwei":-4-4,
                 "yinyang":-1-1, "sancai":0-1, "sixiang":0-3, "bagua":0-7, "guiyuan":0-1}"""

class Concept:
    """单个概念实体"""
    def __init__(self, cid: str, name: str, coords: CoordVector, desc: str = "", tags: List[str] = None):
        self.cid = cid
        self.name = name
        self.coords = coords
        self.desc = desc
        self.tags = tags or []
    
    def to_dict(self) -> dict:
        return {"cid": self.cid, "name": self.name, "coords": self.coords,
                "desc": self.desc, "tags": self.tags}
    
    def __repr__(self):
        return f"<Concept:{self.name} coords={self.coords}>"

class ConceptRegistry:
    """概念注册表"""
    
    def __init__(self):
        self._concepts: Dict[str, Concept] = {}
        self._by_name: Dict[str, str] = {}
        self._load_defaults()
    
    def register(self, cid: str, name: str, coords: CoordVector, desc: str = "", tags: List[str] = None):
        """注册概念"""
        c = Concept(cid, name, coords, desc, tags)
        self._concepts[cid] = c
        self._by_name[name] = cid
        return c
    
    def get(self, cid_or_name: str) -> Optional[Concept]:
        """通过ID或名称查询概念"""
        if cid_or_name in self._concepts:
            return self._concepts[cid_or_name]
        if cid_or_name in self._by_name:
            return self._concepts[self._by_name[cid_or_name]]
        return None
    
    def search(self, keyword: str) -> List[Concept]:
        """按关键词搜索概念"""
        kw = keyword.lower()
        results = []
        for c in self._concepts.values():
            if kw in c.name.lower() or kw in c.cid.lower() or kw in c.desc.lower():
                results.append(c)
            elif any(kw in t.lower() for t in c.tags):
                results.append(c)
        return results
    
    def all(self) -> List[Concept]:
        return list(self._concepts.values())
    
    def count(self) -> int:
        return len(self._concepts)
    
    def nearest(self, query_coords: CoordVector, n: int = 5) -> List[Concept]:
        """九维空间最近邻搜索"""
        scored = []
        for c in self._concepts.values():
            dist = self._coord_dist(query_coords, c.coords)
            scored.append((dist, c))
        scored.sort(key=lambda x: x[0])
        return [c for _, c in scored[:n]]
    
    def _coord_dist(self, a: CoordVector, b: CoordVector) -> float:
        keys = ["sheng","cheng","luoshu","bianwei","yinyang","sancai","sixiang","bagua","guiyuan"]
        sq = 0.0
        for k in keys:
            va = a.get(k, 0)
            vb = b.get(k, 0)
            sq += (va - vb) ** 2
        import math
        return math.sqrt(sq)
    
    def _load_defaults(self):
        """加载默认/预置概念"""
        defaults = [
            # (cid, name, coords, desc, tags)
            ("yuanqi", "元气", {"sheng":5,"cheng":10,"luoshu":5,"bianwei":0,"yinyang":0.0,"sancai":0.0,"sixiang":0,"bagua":7,"guiyuan":0.0},
             "天地未分前的原始能量", ["中医","基础"]),
            ("taiyang", "太阳", {"sheng":2,"cheng":7,"luoshu":9,"bianwei":4,"yinyang":1.0,"sancai":1.0,"sixiang":1,"bagua":2,"guiyuan":0.9},
             "太阳·纯阳之象", ["阴阳","六经"]),
            ("shaoyang", "少阳", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":3,"yinyang":0.6,"sancai":0.7,"sixiang":0,"bagua":3,"guiyuan":0.6},
             "少阳·阳气初生", ["阴阳","六经"]),
            ("yangming", "阳明", {"sheng":2,"cheng":7,"luoshu":4,"bianwei":2,"yinyang":0.8,"sancai":0.8,"sixiang":2,"bagua":1,"guiyuan":0.7},
             "阳明·阳气隆盛", ["阴阳","六经"]),
            ("taiyin", "太阴", {"sheng":4,"cheng":9,"luoshu":8,"bianwei":-4,"yinyang":-1.0,"sancai":0.2,"sixiang":3,"bagua":7,"guiyuan":0.1},
             "太阴·纯阴之象", ["阴阳","六经"]),
            ("shaoyin", "少阴", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-3,"yinyang":-0.6,"sancai":0.3,"sixiang":3,"bagua":5,"guiyuan":0.2},
             "少阴·阴气初成", ["阴阳","六经"]),
            ("jueyin", "厥阴", {"sheng":3,"cheng":8,"luoshu":2,"bianwei":-2,"yinyang":-0.3,"sancai":0.4,"sixiang":0,"bagua":4,"guiyuan":0.4},
             "厥阴·阴阳交尽", ["阴阳","六经"]),
            ("gan", "肝", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":1,"yinyang":0.3,"sancai":0.6,"sixiang":0,"bagua":3,"guiyuan":0.5},
             "肝·木·东方·春", ["五脏","木"]),
            ("xin", "心", {"sheng":2,"cheng":7,"luoshu":9,"bianwei":3,"yinyang":0.8,"sancai":0.9,"sixiang":1,"bagua":2,"guiyuan":0.8},
             "心·火·南方·夏", ["五脏","火"]),
            ("pi", "脾", {"sheng":5,"cheng":10,"luoshu":5,"bianwei":0,"yinyang":0.0,"sancai":0.5,"sixiang":0,"bagua":7,"guiyuan":0.5},
             "脾·土·中央·长夏", ["五脏","土"]),
            ("fei", "肺", {"sheng":4,"cheng":9,"luoshu":7,"bianwei":-1,"yinyang":-0.3,"sancai":0.7,"sixiang":2,"bagua":1,"guiyuan":0.6},
             "肺·金·西方·秋", ["五脏","金"]),
            ("shen", "肾", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-3,"yinyang":-0.6,"sancai":0.4,"sixiang":3,"bagua":5,"guiyuan":0.3},
             "肾·水·北方·冬", ["五脏","水"]),
            ("dan", "胆", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":1,"yinyang":0.4,"sancai":0.5,"sixiang":0,"bagua":3,"guiyuan":0.5},
             "胆·中正之官", ["六腑","木"]),
            ("wei", "胃", {"sheng":5,"cheng":10,"luoshu":8,"bianwei":0,"yinyang":0.1,"sancai":0.5,"sixiang":2,"bagua":1,"guiyuan":0.5},
             "胃·仓廪之官", ["六腑","土"]),
            ("xiaochang", "小肠", {"sheng":2,"cheng":7,"luoshu":4,"bianwei":2,"yinyang":0.5,"sancai":0.6,"sixiang":1,"bagua":2,"guiyuan":0.6},
             "小肠·受盛之官", ["六腑","火"]),
            ("dachang", "大肠", {"sheng":4,"cheng":9,"luoshu":6,"bianwei":-1,"yinyang":-0.2,"sancai":0.5,"sixiang":2,"bagua":1,"guiyuan":0.5},
             "大肠·传道之官", ["六腑","金"]),
            ("pangguang", "膀胱", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-2,"yinyang":-0.4,"sancai":0.3,"sixiang":3,"bagua":5,"guiyuan":0.3},
             "膀胱·州都之官", ["六腑","水"]),
            ("qian", "乾", {"sheng":4,"cheng":9,"luoshu":6,"bianwei":3,"yinyang":0.9,"sancai":0.9,"sixiang":2,"bagua":0,"guiyuan":0.8},
             "乾爲天·健", ["八卦"]),
            ("kun", "坤", {"sheng":5,"cheng":10,"luoshu":2,"bianwei":-3,"yinyang":-0.9,"sancai":0.1,"sixiang":3,"bagua":7,"guiyuan":0.2},
             "坤爲地·顺", ["八卦"]),
            ("zhen", "震", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":2,"yinyang":0.5,"sancai":0.6,"sixiang":0,"bagua":3,"guiyuan":0.6},
             "震爲雷·动", ["八卦"]),
            ("xun", "巽", {"sheng":3,"cheng":8,"luoshu":4,"bianwei":1,"yinyang":0.3,"sancai":0.5,"sixiang":0,"bagua":4,"guiyuan":0.5},
             "巽爲风·入", ["八卦"]),
            ("kan", "坎", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-2,"yinyang":-0.5,"sancai":0.3,"sixiang":3,"bagua":5,"guiyuan":0.3},
             "坎爲水·陷", ["八卦"]),
            ("li", "离", {"sheng":2,"cheng":7,"luoshu":9,"bianwei":3,"yinyang":0.7,"sancai":0.8,"sixiang":1,"bagua":2,"guiyuan":0.7},
             "离爲火·丽", ["八卦"]),
            ("gen", "艮", {"sheng":5,"cheng":10,"luoshu":8,"bianwei":-1,"yinyang":-0.1,"sancai":0.4,"sixiang":2,"bagua":6,"guiyuan":0.4},
             "艮爲山·止", ["八卦"]),
            ("dui", "兑", {"sheng":4,"cheng":9,"luoshu":7,"bianwei":1,"yinyang":0.2,"sancai":0.6,"sixiang":2,"bagua":1,"guiyuan":0.5},
             "兑爲泽·悦", ["八卦"]),
            ("chun", "春", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":2,"yinyang":0.4,"sancai":0.6,"sixiang":0,"bagua":3,"guiyuan":0.4},
             "春季·生发", ["四季","木"]),
            ("xia", "夏", {"sheng":2,"cheng":7,"luoshu":9,"bianwei":3,"yinyang":0.7,"sancai":0.8,"sixiang":1,"bagua":2,"guiyuan":0.7},
             "夏季·繁盛", ["四季","火"]),
            ("qiu", "秋", {"sheng":4,"cheng":9,"luoshu":7,"bianwei":-1,"yinyang":-0.3,"sancai":0.6,"sixiang":2,"bagua":1,"guiyuan":0.6},
             "秋季·收敛", ["四季","金"]),
            ("dong", "冬", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-3,"yinyang":-0.6,"sancai":0.3,"sixiang":3,"bagua":5,"guiyuan":0.3},
             "冬季·藏纳", ["四季","水"]),
            ("zhong", "中", {"sheng":5,"cheng":10,"luoshu":5,"bianwei":0,"yinyang":0.0,"sancai":0.5,"sixiang":0,"bagua":7,"guiyuan":0.5},
             "中央·中和", ["方位","土"]),
            ("dongfang", "东", {"sheng":3,"cheng":8,"luoshu":3,"bianwei":2,"yinyang":0.3,"sancai":0.5,"sixiang":0,"bagua":3,"guiyuan":0.4},
             "东方·日出", ["方位","木"]),
            ("nanfang", "南", {"sheng":2,"cheng":7,"luoshu":9,"bianwei":3,"yinyang":0.6,"sancai":0.7,"sixiang":1,"bagua":2,"guiyuan":0.6},
             "南方·日正", ["方位","火"]),
            ("xifang", "西", {"sheng":4,"cheng":9,"luoshu":7,"bianwei":-1,"yinyang":-0.2,"sancai":0.5,"sixiang":2,"bagua":1,"guiyuan":0.5},
             "西方·日落", ["方位","金"]),
            ("beifang", "北", {"sheng":1,"cheng":6,"luoshu":1,"bianwei":-3,"yinyang":-0.5,"sancai":0.3,"sixiang":3,"bagua":5,"guiyuan":0.3},
             "北方·夜半", ["方位","水"]),
        ]
        for cid, name, coords, desc, tags in defaults:
            self.register(cid, name, coords, desc, tags)

# 全局单例
_registry: Optional[ConceptRegistry] = None

def get_registry() -> ConceptRegistry:
    global _registry
    if _registry is None:
        _registry = ConceptRegistry()
    return _registry

if __name__ == "__main__":
    reg = get_registry()
    print(f"概念注册表: {reg.count()} 个预置概念")
    print()
    print("--- 按名称查询 ---")
    for name in ["肝", "心", "脾", "肺", "肾", "太阳", "春"]:
        c = reg.get(name)
        if c:
            print(f"  {c.name}: coords={c.coords}")
    
    print()
    print("--- 关键词搜索 ---")
    for c in reg.search("五脏")[:5]:
        print(f"  {c.name}({c.cid}): {c.desc}")
    
    print()
    print("--- 最近邻搜索(query=心) ---")
    heart = reg.get("心")
    if heart:
        for c in reg.nearest(heart.coords, 5):
            print(f"  {c.name}: dist={reg._coord_dist(heart.coords, c.coords):.3f}")
