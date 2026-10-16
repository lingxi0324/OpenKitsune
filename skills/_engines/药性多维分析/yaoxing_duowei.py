"""
药性多维分析引擎 · 六维象形辨药

以河图数理为体，以象形六维为用。
从味·色·形·境·质·生六个维度交叉定位一味药的五行归属、
体用方向、通道系统，回答"为什么治这个病"。
"""

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# 基础数据类型
# ═══════════════════════════════════════════════════

@dataclass
class SixDimension:
    """六维观察结果"""
    taste: str = ""          # 味——辛/甘/酸/苦/咸/淡
    color: str = ""          # 色——赤/白/黄/青/黑
    shape: str = ""          # 形——中空/方茎/圆茎/多毛/有刺/叶缺/藤蔓/竹节等
    habitat: str = ""        # 境——水边/向阳/阴湿/寄生/共生/独生
    substance: str = ""      # 质——白浆/赤浆/黏腻/中空/木质/肉质
    growth: str = ""         # 生——草本/木本/藤本/寄生/真菌/附生


@dataclass
class WuxingResult:
    """五行归属""" 
    element: str = ""           # 金/木/水/火/土
    hetu_number: str = ""       # 河图数
    zangfu: list = field(default_factory=list)    # 归经脏腑
    body_or_use: str = ""       # 补体/泄用/兼体用
    qi_or_blood: str = ""       # 气分/血分/兼
    confidence: float = 0.0     # 置信度


@dataclass
class ChannelMapping:
    """通道系统映射——以形通窍"""
    plant_structure: str = ""   # 植物的形态结构
    body_channel: str = ""      # 对应人体通道
    disease_direction: str = "" # 治疗方向


@dataclass 
class HerbAnalysis:
    """一味药的完整分析结果"""
    name: str = ""
    alias: list = field(default_factory=list)
    
    # 六维扫描
    dimensions: SixDimension = field(default_factory=SixDimension)
    raw_observations: list = field(default_factory=list)      # 原始观察描述
    
    # 每维的五行归位
    taste_wuxing: WuxingResult = field(default_factory=WuxingResult)
    color_wuxing: WuxingResult = field(default_factory=WuxingResult)
    shape_wuxing: WuxingResult = field(default_factory=WuxingResult)
    habitat_wuxing: WuxingResult = field(default_factory=WuxingResult)
    substance_wuxing: WuxingResult = field(default_factory=WuxingResult)
    growth_wuxing: WuxingResult = field(default_factory=WuxingResult)
    
    # 交叉定位
    primary_element: str = ""
    secondary_element: str = ""
    channel: ChannelMapping = field(default_factory=ChannelMapping)
    
    # 病机对接
    mechanism: list = field(default_factory=list)      # 因果链
    indications: list = field(default_factory=list)    # 主治方向
    similar_herbs: list = field(default_factory=list)  # 相似药对比
    
    # 综合
    summary: str = ""
    usage_note: str = ""


# ═══════════════════════════════════════════════════
# 辨药规则库（核心公理）
# ═══════════════════════════════════════════════════

# 辨性歌决映射表
SHAPE_RULES = {
    "生毛": {"element": "木", "action": "祛风", "hetu": "木3-8"},
    "黏泥": {"element": "土", "action": "拔毒", "hetu": "土5-10"},
    "中空": {"element": "水", "action": "利水", "hetu": "水1-6"},
    "有刺": {"element": "金", "action": "排脓", "hetu": "金4-9"},
    "茎方": {"element": "木", "action": "发散", "hetu": "木3-8"},
    "骨圆": {"element": "火", "action": "退火", "hetu": "火2-7"},
    "叶缺": {"element": "土", "action": "止痛", "hetu": "土5-10"},
    "蔓藤": {"element": "木", "action": "通关节", "hetu": "木3-8"},
    "竹节": {"element": "火", "action": "通脉", "hetu": "火2-7"},      # 扩充
    "须状": {"element": "水", "action": "下行", "hetu": "水1-6"},      # 扩充
}

COLOR_RULES = {
    "赤":  {"element": "火", "zangfu": ["心"],       "action": "攻瘀",   "hetu": "火2-7"},
    "红":  {"element": "火", "zangfu": ["心", "血分"], "action": "活血",  "hetu": "火2-7"},
    "白":  {"element": "金", "zangfu": ["肺"],       "action": "清肺",   "hetu": "金4-9"},
    "黄":  {"element": "土", "zangfu": ["脾"],       "action": "化湿",   "hetu": "土5-10"},
    "青":  {"element": "木", "zangfu": ["肝"],       "action": "疏泄",   "hetu": "木3-8"},
    "黑":  {"element": "水", "zangfu": ["肾"],       "action": "滋肾",   "hetu": "水1-6"},
}

TASTE_RULES = {
    "辛": {"element": "木", "action": "发散/行气/活血",  "body_or_use": "用"},
    "甘": {"element": "土", "action": "补益/和中/缓急",   "body_or_use": "体"},
    "酸": {"element": "金", "action": "收敛/固涩/生津",   "body_or_use": "体"},
    "苦": {"element": "水", "action": "清热/燥湿/降逆",   "body_or_use": "用"},
    "咸": {"element": "火", "action": "软坚/散结/下行",   "body_or_use": "用"},
    "淡": {"element": "土", "action": "渗湿/利水",       "body_or_use": "用"},
}

SUBSTANCE_RULES = {
    "白浆":  {"element": "金水", "action": "生津/入肾生水",         "hetu": "金4-9 → 水1-6"},
    "赤浆":  {"element": "火",   "action": "入血/活血/化瘀",       "hetu": "火2-7"},
    "黏腻":  {"element": "土",   "action": "拔毒/生肌/固涩",       "hetu": "土5-10"},
    "中空":  {"element": "水",   "action": "通气/利水/发汗",       "hetu": "水1-6"},
    "木质":  {"element": "木",   "action": "疏通/行气",            "hetu": "木3-8"},
    "肉质":  {"element": "土",   "action": "补益/滋养",            "hetu": "土5-10"},
}

HABITAT_RULES = {
    "水边":     {"element": "水", "action": "利水/通淋/治水病",     "hetu": "水1-6"},
    "向阳":     {"element": "火", "action": "祛寒/温阳/治寒证",     "hetu": "火2-7"},
    "阴湿":     {"element": "土", "action": "化湿/燥湿/治湿证",     "hetu": "土5-10"},
    "寄生":     {"element": "火", "action": "化腐生新/得纯精之气",  "hetu": "火2-7"},
    "共生":     {"element": "土", "action": "得中和之气/补而不偏",  "hetu": "土5-10"},
    "岩石":     {"element": "金", "action": "清金/通利/质重下行",   "hetu": "金4-9"},
}

GROWTH_RULES = {
    "真菌":   {"element": "火", "action": "化腐生新/通脉化浊",     "hetu": "火2-7"},
    "藤蔓":   {"element": "木", "action": "通经络/走关节/祛风湿",  "hetu": "木3-8"},
    "草本":   {"element": "木", "action": "轻扬发散/走表",        "hetu": "木3-8"},
    "木本":   {"element": "金", "action": "厚重沉降/入里",        "hetu": "金4-9"},
    "附生":   {"element": "水", "action": "借气而生/精纯不杂",    "hetu": "水1-6"},
    "草本藤": {"element": "木火", "action": "轻扬通络/走表走经",  "hetu": "木3-8 → 火2-7"},
}

# 以形通窍——通道系统映射（核心扩展）
CHANNEL_MAPPINGS = [
    {"structure": "中空/须状",      "channel": "水道（肾→膀胱）",   "direction": "利水通淋"},
    {"structure": "竹节/节状",      "channel": "脉道（心→血脉）",   "direction": "通脉化瘀"},
    {"structure": "藤蔓/缠绕",      "channel": "经络（肝→筋）",     "direction": "通经走络"},
    {"structure": "方茎",           "channel": "气分（肺→皮毛）",   "direction": "发散解表"},
    {"structure": "有刺",           "channel": "疮门（皮肤→肌肉）", "direction": "排脓消肿"},
    {"structure": "白浆/乳汁",      "channel": "津液（肺→胃）",     "direction": "生津润燥"},
    {"structure": "赤浆/红色",      "channel": "血分（心→肝）",     "direction": "活血化瘀"},
    {"structure": "多毛/绒毛",      "channel": "卫分（肺→皮毛）",   "direction": "祛风止痒"},
    {"structure": "圆茎",           "channel": "火分（心）",        "direction": "清热退火"},
    {"structure": "叶缺/裂叶",      "channel": "气分（肝→脾）",     "direction": "理气止痛"},
]


# ═══════════════════════════════════════════════════
# 分析引擎
# ═══════════════════════════════════════════════════

def _match_keyword(text: str, rules: dict) -> list:
    """在描述文本中匹配规则关键词，返回匹配列表"""
    results = []
    for keyword, info in rules.items():
        if keyword in text:
            results.append({"keyword": keyword, **info})
    return results


class HerbAnalyzer:
    """药性多维分析引擎"""

    def __init__(self):
        self.knowledge_base = {}   # 可扩展的知识库 {name: HerbAnalysis}

    def analyze(self, name: str, description: str = "", 
                dimensions: Optional[SixDimension] = None,
                alias: list = None) -> HerbAnalysis:
        """
        完整分析一味药的药性。
        
        参数：
            name: 药名
            description: 自然语言描述（含特征信息）
            dimensions: 六维结构化输入（可选）
            alias: 别名列表
        """
        result = HerbAnalysis(name=name, alias=alias or [])
        desc = description.lower()
        
        # ── 维度填充：结构化 + 文本提取 ──
        dims = dimensions or SixDimension()
        
        # 从文本中提取各维度信息
        if not dims.taste:
            tastes = _match_keyword(desc, TASTE_RULES)
            if tastes:
                dims.taste = ",".join(t["keyword"] for t in tastes)
                result.raw_observations.extend(
                    f"味→{t['keyword']}: {t['action']}" for t in tastes
                )
        
        if not dims.color:
            colors = _match_keyword(desc, COLOR_RULES)
            if colors:
                dims.color = ",".join(c["keyword"] for c in colors)
                result.raw_observations.extend(
                    f"色→{c['keyword']}: {c['action']}" for c in colors
                )
        
        if not dims.shape:
            shapes = _match_keyword(desc, SHAPE_RULES)
            if shapes:
                dims.shape = ",".join(s["keyword"] for s in shapes)
                result.raw_observations.extend(
                    f"形→{s['keyword']}: {s['action']}" for s in shapes
                )
        
        if not dims.habitat:
            habitats = _match_keyword(desc, HABITAT_RULES)
            if habitats:
                dims.habitat = ",".join(h["keyword"] for h in habitats)
                result.raw_observations.extend(
                    f"境→{h['keyword']}: {h['action']}" for h in habitats
                )
        
        if not dims.substance:
            substances = _match_keyword(desc, SUBSTANCE_RULES)
            if substances:
                dims.substance = ",".join(s["keyword"] for s in substances)
                result.raw_observations.extend(
                    f"质→{s['keyword']}: {s['action']}" for s in substances
                )
        
        if not dims.growth:
            growths = _match_keyword(desc, GROWTH_RULES)
            if growths:
                dims.growth = ",".join(g["keyword"] for g in growths)
                result.raw_observations.extend(
                    f"生→{g['keyword']}: {g['action']}" for g in growths
                )
        
        result.dimensions = dims
        
        # ── 每维五行归位 ──
        # 味
        taste_info = _match_keyword(dims.taste, TASTE_RULES)
        if taste_info:
            r = taste_info[0]
            result.taste_wuxing = WuxingResult(
                element=r["element"],
                body_or_use=r["body_or_use"],
                confidence=0.8
            )
        
        # 色
        color_info = _match_keyword(dims.color, COLOR_RULES)
        if color_info:
            r = color_info[0]
            result.color_wuxing = WuxingResult(
                element=r["element"],
                zangfu=r["zangfu"],
                confidence=0.8
            )
        
        # 形
        shape_info = _match_keyword(dims.shape, SHAPE_RULES)
        if shape_info:
            r = shape_info[0]
            result.shape_wuxing = WuxingResult(
                element=r["element"],
                hetu_number=r.get("hetu", ""),
                confidence=0.7
            )
        
        # 境
        habitat_info = _match_keyword(dims.habitat, HABITAT_RULES)
        if habitat_info:
            r = habitat_info[0]
            result.habitat_wuxing = WuxingResult(
                element=r["element"],
                hetu_number=r.get("hetu", ""),
                confidence=0.6
            )
        
        # 质
        substance_info = _match_keyword(dims.substance, SUBSTANCE_RULES)
        if substance_info:
            r = substance_info[0]
            result.substance_wuxing = WuxingResult(
                element=r["element"],
                hetu_number=r.get("hetu", ""),
                confidence=0.7
            )
        
        # 生
        growth_info = _match_keyword(dims.growth, GROWTH_RULES)
        if growth_info:
            r = growth_info[0]
            result.growth_wuxing = WuxingResult(
                element=r["element"],
                hetu_number=r.get("hetu", ""),
                confidence=0.6
            )
        
        # ── 交叉定位：统计五行频次 ──
        element_count = {}
        wuxing_results = [
            result.taste_wuxing,
            result.color_wuxing,
            result.shape_wuxing,
            result.habitat_wuxing,
            result.substance_wuxing,
            result.growth_wuxing
        ]
        for wx_result in wuxing_results:
            if wx_result.element:
                for e in wx_result.element.split(" → "):
                    clean = e.split("-")[0].strip() if "-" in e else e.strip()
                    for single in ["金", "木", "水", "火", "土"]:
                        if single in clean:
                            element_count[single] = element_count.get(single, 0) + 1
        
        # 确定主、次五行
        sorted_elements = sorted(element_count.items(), key=lambda x: -x[1])
        if sorted_elements:
            result.primary_element = sorted_elements[0][0]
        if len(sorted_elements) > 1:
            result.secondary_element = sorted_elements[1][0]
        
        # ── 通道映射 ──
        shape_desc = dims.shape
        for ch in CHANNEL_MAPPINGS:
            if ch["structure"] in shape_desc:
                result.channel = ChannelMapping(
                    plant_structure=ch["structure"],
                    body_channel=ch["channel"],
                    disease_direction=ch["direction"]
                )
                result.raw_observations.append(
                    f"通道映射 ▸ {ch['structure']} → {ch['channel']}（{ch['direction']}）"
                )
                break
        
        # ── 体用方向判定 ──
        use_count = 0
        body_count = 0
        for wx_result in wuxing_results:
            if wx_result.body_or_use == "用":
                use_count += 1
            elif wx_result.body_or_use == "体":
                body_count += 1
        
        if use_count > 0 and body_count > 0:
            qi_or_blood = "兼气分血分"
        elif use_count > 0:
            qi_or_blood = "气分（泄用为主）"
        else:
            qi_or_blood = "气分（补体为主）"
        
        # ── 生成机理链条 ──
        mechanism_parts = []
        if result.channel.body_channel:
            mechanism_parts.append(
                f"{name}以「{result.channel.plant_structure}」之形，通人体「{result.channel.body_channel}」"
            )
        if result.primary_element:
            mechanism_parts.append(
                f"多维交叉定位：主五行「{result.primary_element}」"
            )
        if result.secondary_element:
            mechanism_parts.append(
                f"辅五行「{result.secondary_element}」"
            )
        
        result.mechanism = mechanism_parts
        result.indications = [
            info["keyword"] for info in 
            _match_keyword(desc, {**SHAPE_RULES, **COLOR_RULES, **TASTE_RULES})
        ] if mechanism_parts else []
        
        # ── 综合摘要 ──
        summary_parts = []
        if result.primary_element:
            summary_parts.append(f"[{result.primary_element}]")
        if result.secondary_element:
            summary_parts.append(f"[{result.secondary_element}]")
        
        hexagrams = []
        if dims.color:
            hexagrams.append(f"色{dims.color}")
        if dims.shape:
            hexagrams.append(f"形{dims.shape}")
        if dims.habitat:
            hexagrams.append(f"境{dims.habitat}")
        if dims.substance:
            hexagrams.append(f"质{dims.substance}")
        if dims.growth:
            hexagrams.append(f"生{dims.growth}")
        
        result.summary = f"{''.join(summary_parts)} {name}：{' → '.join(h for h in hexagrams if h)}" if hexagrams else f"{name}：分析完成"
        
        # 保存到知识库
        self.knowledge_base[name] = result
        
        return result

    def quick_scan(self, **kwargs) -> HerbAnalysis:
        """
        快速扫描模式——直接传入特征关键词。
        
        用法：quick_scan(color="赤", shape="竹节中空", habitat="寄生", ...)
        """
        dims = SixDimension(
            taste=kwargs.get("taste", ""),
            color=kwargs.get("color", ""),
            shape=kwargs.get("shape", ""),
            habitat=kwargs.get("habitat", ""),
            substance=kwargs.get("substance", ""),
            growth=kwargs.get("growth", ""),
        )
        return self.analyze(
            name=kwargs.get("name", "未知草药"),
            description=kwargs.get("description", ""),
            dimensions=dims,
            alias=kwargs.get("alias")
        )

    def list_knowledge(self) -> list:
        """列出知识库中已分析过的药"""
        return list(self.knowledge_base.keys())

    def get_analysis(self, name: str) -> Optional[HerbAnalysis]:
        """获取已缓存的分析结果"""
        return self.knowledge_base.get(name)


# ═══════════════════════════════════════════════════
# 预置案例分析（游兄经典案例）
# ═══════════════════════════════════════════════════

def preset_analyses(analyzer: HerbAnalyzer):
    """加载预设经典案例到知识库"""

    # 案例1：竹三七（竹黄）
    zhusanqi = analyzer.analyze(
        name="竹三七（竹黄）",
        description="竹节上生长的赤红色真菌，竹叶清心火，传统载治风湿",
        dimensions=SixDimension(
            color="赤",
            shape="竹节中空",
            habitat="寄生",
            substance="赤浆",
            growth="真菌",
        ),
        alias=["竹黄", "竹节三七"]
    )
    zhusanqi.mechanism = [
        "竹黄色赤 → 入心入血 → 驱血分之风湿",
        "竹黄生于竹节 → 通利之性 → 通心脉",
        "真菌寄生 → 化腐生新 → 化血分风湿浊毒",
        "竹叶清心（同源） → 心火清，风湿无所附",
        "三层叠加：清气（清心）× 入血（血分）× 走经络（祛风湿）",
    ]
    zhusanqi.indications = ["风湿性心脏病", "心脉瘀阻", "血分风湿"]

    # 案例2：黄角树气根
    huangjiaoshu = analyzer.analyze(
        name="黄角树气根",
        description="生于水边，色黄，折断有白浆，须状垂落，气根中空",
        dimensions=SixDimension(
            color="黄",
            shape="中空须状垂落",
            habitat="水边",
            substance="白浆",
        ),
        alias=["黄葛树气根", "大叶榕气根"]
    )
    huangjiaoshu.channel = ChannelMapping(
        plant_structure="中空须状、生水边",
        body_channel="水道（肾→膀胱）",
        disease_direction="利水通淋"
    )
    huangjiaoshu.mechanism = [
        "色黄 → 正土之色 → 以正土制邪土（化湿浊）",
        "白浆 → 金色白 → 金水相生 → 入肾助气化生水",
        "生水边 → 得水气最重 → 治水病",
        "气根中空须状垂落 → 根性下行 → 导浊毒从下而出",
        "中空 → 利水通利之象",
        "一补一化（补金水生肾水 + 化湿浊之邪），标本同治",
    ]
    huangjiaoshu.indications = ["尿毒症无尿", "肾不气化", "水湿浊毒壅塞"]

    return analyzer


# ═══════════════════════════════════════════════════
# 240味知识库加载器
# ═══════════════════════════════════════════════════

import os as _os
import json as _json

_knowledge_cache = None

def _ensure_knowledge_loaded():
    """模块级缓存：只加载一次 JSON 知识库"""
    global _knowledge_cache
    if _knowledge_cache is not None:
        return _knowledge_cache
    
    json_path = _os.path.join(_os.path.dirname(__file__), "knowledge_240.json")
    if not _os.path.exists(json_path):
        _knowledge_cache = {"version": "0", "total": 0, "herbs": []}
        return _knowledge_cache
    
    with open(json_path, "r", encoding="utf-8") as f:
        _knowledge_cache = _json.load(f)
    return _knowledge_cache


def search_knowledge(name: str) -> str:
    """
    在 240 味知识库中搜索指定药名。
    
    参数：
        name: 药名（支持模糊匹配，包含即可）
    
    返回：结构化的知识卡片，未找到返回空字符串
    """
    data = _ensure_knowledge_loaded()
    name_lower = name.lower().replace(" ", "").replace("（", "(").replace("）", ")")
    
    matches = []
    for herb in data["herbs"]:
        hname = herb["name"].lower().replace(" ", "")
        if name_lower in hname or hname in name_lower:
            matches.append(herb)
    
    if not matches:
        return ""
    
    # 取最精确匹配
    if len(matches) == 1:
        herb = matches[0]
    else:
        # 优先完全匹配
        exact = [h for h in matches if h["name"].lower().replace(" ", "") == name_lower]
        herb = exact[0] if exact else matches[0]
    
    return _format_knowledge_card(herb)


def _format_knowledge_card(herb: dict) -> str:
    """将知识库中的一味药格式化为分析结果"""
    lines = []
    lines.append(f"╔══════════════════════════════════╗")
    lines.append(f"║  药性多维分析 · {herb['name']}      ")
    lines.append(f"╚══════════════════════════════════╝")
    lines.append("")
    lines.append("▎六维全景：")
    lines.append(f"  ① 味维：{herb['taste']}")
    lines.append(f"  ② 色维：{herb['color']}")
    lines.append(f"  ③ 形维：{herb['shape']}")
    lines.append(f"  ④ 境维：{herb['habitat']}")
    lines.append(f"  ⑤ 质维：{herb['substance']}")
    lines.append(f"  ⑥ 生维：{herb['growth']}")
    
    # 五行交叉判断（简版）
    kw = herb.get("taste_keywords", [])
    taste_elements = []
    if "辛" in kw: taste_elements.append("金/木（辛散）")
    if "甘" in kw: taste_elements.append("土（甘补中）")
    if "酸" in kw: taste_elements.append("金/木（酸敛）")
    if "苦" in kw: taste_elements.append("火/水（苦降）")
    if "咸" in kw: taste_elements.append("水/火（咸软）")
    if "淡" in kw: taste_elements.append("土（淡渗湿）")
    
    color_elements = []
    ckw = herb.get("color_keywords", [])
    if "青" in ckw: color_elements.append("木（青入肝）")
    if "赤" in ckw: color_elements.append("火（赤入心）")
    if "黄" in ckw: color_elements.append("土（黄入脾）")
    if "白" in ckw: color_elements.append("金（白入肺）")
    if "黑" in ckw: color_elements.append("水（黑入肾）")
    
    skw = herb.get("shape_keywords", [])
    shape_mappings = {
        "中空": "水道（利水）",
        "方茎": "表气（发散）",
        "藤蔓": "经络（通关节）",
        "多毛": "皮毛（祛风）",
        "有刺": "痈毒（排脓）",
        "叶缺": "疼痛（止痛）",
        "竹节": "脉道（通利）",
        "根": "下焦（沉降）",
        "花": "上焦（升散）",
        "果籽": "中下焦（敛降）"
    }
    channels = [shape_mappings[s] for s in skw if s in shape_mappings]
    
    if taste_elements or color_elements or channels:
        lines.append("")
        lines.append("▎五行交叉定位：")
        if taste_elements:
            lines.append(f"  · 味归：{'、'.join(taste_elements)}")
        if color_elements:
            lines.append(f"  · 色应：{'、'.join(color_elements)}")
        if channels:
            lines.append(f"  · 通道（以形通窍）：{'、'.join(channels)}")
    
    if herb.get("summary"):
        lines.append("")
        lines.append(f"▎六维合参：{herb['summary']}")
    
    return "\n".join(lines)


def list_all_herbs(category: str = "") -> list:
    """
    列出知识库中的药物清单。
    
    参数：
        category: 分类名（藤蔓通络/根茎补益/花叶轻清/果实籽仁/金石虫介/草本利水）
                  为空则返回所有药名
    
    返回：药名列表
    """
    data = _ensure_knowledge_loaded()
    if not data["herbs"]:
        return ["（知识库未加载）"]
    
    if not category:
        return [h["name"] for h in data["herbs"]]
    
    # 通过ID范围判断分类（每类40味，共6类）
    cat_ranges = {
        "藤蔓通络": (1, 40),
        "根茎补益": (41, 80),
        "花叶轻清": (81, 120),
        "果实籽仁": (121, 160),
        "金石虫介": (161, 200),
        "草本利水": (201, 240),
    }
    
    if category in cat_ranges:
        lo, hi = cat_ranges[category]
        return [h["name"] for h in data["herbs"] if lo <= h["id"] <= hi]
    
    return [h["name"] for h in data["herbs"]]


def get_herb_by_id(herb_id: int) -> str:
    """按ID搜索药（1-240）"""
    data = _ensure_knowledge_loaded()
    for h in data["herbs"]:
        if h["id"] == herb_id:
            return _format_knowledge_card(h)
    return f"（未找到ID {herb_id} 对应的药）"


def get_herb_category(herb_id: int) -> str:
    """返回某味药所属分类"""
    if 1 <= herb_id <= 40: return "藤蔓通络类"
    if 41 <= herb_id <= 80: return "根茎补益沉降类"
    if 81 <= herb_id <= 120: return "花叶轻清升散类"
    if 121 <= herb_id <= 160: return "果实籽仁敛降类"
    if 161 <= herb_id <= 200: return "金石虫介软坚类"
    if 201 <= herb_id <= 240: return "草本利水解毒类"
    return "未知"


# ═══════════════════════════════════════════════════
# 入口函数
# ═══════════════════════════════════════════════════

def run_analysis(name: str, description: str = "") -> str:
    """
    药性多维分析入口函数。
    
    参数：
        name: 药名
        description: 自然语言描述（含味/色/形/境/质/生特征）
    
    返回：完整分析文本
    """
    # 第一步：搜索240味知识库
    kb_result = search_knowledge(name)
    if kb_result:
        return kb_result
    
    # 第二步：走NLP分析流程
    analyzer = preset_analyses(HerbAnalyzer())
    result = analyzer.analyze(name=name, description=description)
    return format_analysis(result)


def format_analysis(result: HerbAnalysis) -> str:
    """将分析结果格式化为可读文本"""
    lines = [
        f"╔══════════════════════════════════╗",
        f"║  药性多维分析 · {result.name}",
        f"╚══════════════════════════════════╝",
        "",
    ]
    
    if result.raw_observations:
        lines.append("▎六维扫描：")
        for obs in result.raw_observations:
            lines.append(f"  {obs}")
        lines.append("")
    
    # 五行交叉
    elements = []
    if result.primary_element:
        elements.append(f"主五行: {result.primary_element}")
    if result.secondary_element:
        elements.append(f"辅五行: {result.secondary_element}")
    if elements:
        lines.append(f"▎五行交叉定位：{' | '.join(elements)}")
    
    # 通道
    if result.channel.body_channel:
        lines.append(f"▎通道映射（以形通窍）：")
        lines.append(f"  {result.channel.plant_structure} → {result.channel.body_channel}")
        lines.append(f"  方向：{result.channel.disease_direction}")
    
    # 机理
    if result.mechanism:
        lines.append(f"\n▎因果链：")
        for i, m in enumerate(result.mechanism, 1):
            lines.append(f"  {i}. {m}")
    
    # 主治
    if result.indications:
        lines.append(f"\n▎主治方向：")
        lines.append(f"  {' · '.join(result.indications)}")
    
    # 综合
    if result.summary:
        lines.append(f"\n▎综合：{result.summary}")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 自测试
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    analyzer = preset_analyses(HerbAnalyzer())
    
    print("=" * 50)
    print("药性多维分析引擎 · 自测试")
    print("=" * 50)
    
    # 预设案例
    for name in ["竹三七（竹黄）", "黄角树气根"]:
        result = analyzer.get_analysis(name)
        if result:
            print(format_analysis(result))
            print()
    
    # 自定义分析
    if len(sys.argv) > 1:
        name = sys.argv[1]
        desc = sys.argv[2] if len(sys.argv) > 2 else ""
        result = run_analysis(name, desc)
        print(result)
