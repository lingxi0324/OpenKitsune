# -*- coding: utf-8 -*-
"""
TCM Dialectic — 双轨辩证统一推理管线（Python 原生翻译自 dialectic.rs）

统一管线: 体用检测 → 六经辨证 → 方剂分析 → 五运六气推演 → 火候次第 → 潮汐上下文
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .clinical_types import (
    ContradictionResult,
    DialecticInput,
    FireRecommendation,
    TideContext,
)
from .engine import detect_contradiction, recommend_fire
from .liujing import liujing_score
from .normalize import normalize_pulse, normalize_symptoms
from .wuwei import analyze_recommended_formulas
from .wuyun import wuyun_full_chain, build_wuyun_output
from .tide import tide_context


# ════════════════════════════════════════════════════════════════════════════
# 统一输出类型
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class LiujingScoreOutput:
    推荐经: str = ""
    置信度: str = ""
    体用倾向: str = ""
    体用映射: Dict[str, float] = field(default_factory=dict)
    推荐方: List[str] = field(default_factory=list)
    方剂说明: str = ""
    疑似经: List[Dict] = field(default_factory=list)
    六经传变: str = ""
    亚型: Optional[str] = None
    各经评分: Dict[str, float] = field(default_factory=dict)
    原始得分: float = 0.0
    脉证合参: str = ""
    匹配方证: List[Dict] = field(default_factory=list)
    证据链: List[Dict] = field(default_factory=list)
    合病检测: Optional[Dict] = None


@dataclass
class FormulaAnalysis:
    方剂: List[dict] = field(default_factory=list)
    推荐方说明: str = ""


@dataclass
class WuyunDeductionOutput:
    """五运六气全链推演输出"""
    纪元: str = ""
    岁运: str = ""
    太过不及: str = ""
    司天: str = ""
    在泉: str = ""
    客气: str = ""
    主气: str = ""
    顺逆: str = ""
    六气定位: str = ""
    体用验证: Dict[str, str] = field(default_factory=dict)
    方剂匹配: List[str] = field(default_factory=list)


@dataclass
class SynthesisConclusion:
    总纲: str = ""
    体用型: str = ""
    核心病机: str = ""
    治法方向: str = ""
    处方方向: str = ""


@dataclass
class DialecticResult:
    """dialectic() 统一输出"""
    体用检测: Optional[ContradictionResult] = None
    六经辨证: Optional[LiujingScoreOutput] = None
    方剂分析: Optional[FormulaAnalysis] = None
    五运六气推演: Optional[WuyunDeductionOutput] = None
    火候次第: Optional[FireRecommendation] = None
    潮汐上下文: Optional[TideContext] = None
    综合结论: Optional[SynthesisConclusion] = None


# ════════════════════════════════════════════════════════════════════════════
# 体用型判定工具
# ════════════════════════════════════════════════════════════════════════════

def _tiyong_type_key(ty: str) -> str:
    """从体用三型字符串提取键名"""
    if "相悖" in ty:
        return "体用相悖"
    if "偏颇" in ty:
        return "体用偏颇"
    return "体用一致"


# ════════════════════════════════════════════════════════════════════════════
# 主管线
# ════════════════════════════════════════════════════════════════════════════

def dialectic(inp: DialecticInput) -> DialecticResult:
    """
    双轨辩证统一推理管线主函数。

    输入: DialecticInput(舌象/苔/脉/症状/医师/体质/专科/年份)
    输出: DialecticResult(体用+六经+方剂+五运+火候+潮汐+综合)

    症状/脉象在入口自动归一化：口语词条（"不士气"→纳呆）、
    列表/逗号串、脉象补全（"沉细"→脉沉细）均直接可用，不改变评分算法。
    """
    # ── 0. 输入归一化（格式自适应）──
    symptoms = normalize_symptoms(inp.symptoms)
    pulse = normalize_pulse(inp.pulse)

    # ── 1. 体用检测 ──
    tiyong = detect_contradiction(inp.tongue, inp.coat, pulse, symptoms)
    tiyong_key = _tiyong_type_key(tiyong.体用三型)

    # ── 2. 六经辨证 ──
    lj = liujing_score(inp.tongue, inp.coat, pulse,
                       symptoms, tiyong_key, inp.year)

    liujing_out = LiujingScoreOutput(
        推荐经=lj.推荐经,
        置信度=lj.置信度,
        体用倾向=lj.体用倾向,
        体用映射=dict(lj.体用映射),
        推荐方=list(lj.推荐方),
        方剂说明=lj.方剂说明,
        疑似经=[
            {"经": w.经, "得分": w.得分, "差距百分比": w.差距百分比, "提示": w.提示}
            for w in lj.疑似经
        ],
        六经传变=lj.六经传变,
        亚型=lj.亚型,
        各经评分=dict(lj.各经评分),
        原始得分=lj.原始得分,
        脉证合参=lj.脉证合参,
        匹配方证=[
            {"方证": m.方证, "方": m.方, "匹配度": m.匹配度}
            for m in lj.匹配方证
        ],
        证据链=[
            {"经": e.经, "得分": e.得分, "证据": e.证据}
            for e in lj.证据链
        ],
        合病检测=(
            {
                "主经": lj.合病检测.主经,
                "主经得分": lj.合病检测.主经得分,
                "合病经": list(lj.合病检测.合病经),
                "合病得分": dict(lj.合病检测.合病得分),
                "合方推荐": list(lj.合病检测.合方推荐),
                "合病说明": lj.合病检测.合病说明,
                "合病类型": lj.合病检测.合病类型,
            }
            if lj.合病检测 else None
        ),
    )

    # ── 3. 方剂分析 ──
    formula_results = analyze_recommended_formulas(lj.推荐方)

    formula_out = FormulaAnalysis(
        方剂=formula_results,
        推荐方说明=lj.方剂说明,
    )

    # ── 4. 五运六气推演 ──
    year_int: Optional[int] = None
    if inp.year:
        # year 可能是 int 或 str，统一转 str 再处理
        yr = str(inp.year).strip()
        if yr.isdigit():
            year_int = int(yr)

    wuyun_out: Optional[WuyunDeductionOutput] = None
    if year_int is not None:
        chain = wuyun_full_chain(year_int)
        wd = build_wuyun_output(chain)
        wuyun_out = WuyunDeductionOutput(
            纪元=wd.get("纪元", ""),
            岁运=wd.get("岁运", ""),
            太过不及=wd.get("太过不及", ""),
            司天=wd.get("司天", ""),
            在泉=wd.get("在泉", ""),
            客气=wd.get("客气", ""),
            主气=wd.get("主气", ""),
            顺逆=wd.get("顺逆", ""),
            六气定位=wd.get("六气定位", ""),
            体用验证=wd.get("体用验证", {}),
            方剂匹配=wd.get("方剂匹配", []),
        )

    # ── 5. 火候次第 ──
    fermentation_phase = ""
    if tiyong.匹配模式:
        fp = tiyong.匹配模式[0].发酵阶段
        if fp:
            fermentation_phase = fp

    fire = recommend_fire(
        tiyong_key,
        fermentation_phase,
        inp.constitution,
        inp.specialty,
        "缓",
    )

    # ── 6. 潮汐上下文 ──
    tide_out: Optional[TideContext] = None
    if inp.collect_tide:
        tide_out = tide_context()

    # ── 7. 综合结论 ──
    top_formula = lj.推荐方[0] if lj.推荐方 else "待议方"

    # 病机描述
    if lj.亚型:
        jibing = f"{lj.推荐经}·{lj.亚型}（{lj.体用倾向}）"
    else:
        jibing = f"{lj.推荐经}（{lj.体用倾向}）"

    # 治法方向
    if tiyong.匹配模式:
        zhifa = tiyong.匹配模式[0].治法原则
    else:
        zhifa = f"以{lj.推荐经}治则为主，兼顾{tiyong.体用三型}"

    conclusion = SynthesisConclusion(
        总纲=f"{lj.推荐经} · {tiyong.体用三型}",
        体用型=tiyong_key,
        核心病机=jibing,
        治法方向=zhifa,
        处方方向=top_formula,
    )

    return DialecticResult(
        体用检测=tiyong,
        六经辨证=liujing_out,
        方剂分析=formula_out,
        五运六气推演=wuyun_out,
        火候次第=fire,
        潮汐上下文=tide_out,
        综合结论=conclusion,
    )
