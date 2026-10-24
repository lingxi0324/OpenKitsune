# -*- coding: utf-8 -*-
"""
TCM 临床引擎 — 共享类型定义
对应 Rust `types.rs`。
Rust struct -> Python @dataclass，字段名保持中文。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── 症状映射条目 ───────────────────────────────────────────────────────────

@dataclass
class SymptomMapEntry:
    """症状→体用翻译表中的一条记录"""
    dim: str          # 维度: 寒/热/痰/瘀/阴/气
    type: str         # "体" 或 "用"
    val: float        # 基础分值
    weight: float     # 权重
    label: str        # 可读标签


# ─── 体用相悖模式 ───────────────────────────────────────────────────────────

@dataclass
class TongueMatch:
    """舌象匹配条件"""
    舌质: List[str] = field(default_factory=list)
    苔: List[str] = field(default_factory=list)


@dataclass
class PulseMatch:
    """脉象匹配条件"""
    脉: List[str] = field(default_factory=list)


@dataclass
class SymptomMatch:
    """症状匹配条件（体侧/用侧）"""
    体寒: List[str] = field(default_factory=list)
    用热: List[str] = field(default_factory=list)
    体热: List[str] = field(default_factory=list)
    用寒: List[str] = field(default_factory=list)
    体虚: List[str] = field(default_factory=list)
    用亢: List[str] = field(default_factory=list)
    上热: List[str] = field(default_factory=list)
    下寒: List[str] = field(default_factory=list)


@dataclass
class ParadoxPattern:
    """体用相悖模式定义"""
    name: str
    pattern: dict                       # 灵活: {"体": "寒", "用": "热"} 等
    舌象_match: TongueMatch
    脉象_match: PulseMatch
    symptom_match: SymptomMatch
    description: str
    体用口诀: str
    发酵阶段: str = ""
    代表方: str = ""
    治法原则: str = ""
    误治风险: Dict[str, str] = field(default_factory=dict)


# ─── 匹配结果 ───────────────────────────────────────────────────────────────

@dataclass
class MatchedPattern:
    """一条匹配到的模式结果"""
    模式: str
    置信度: str        # e.g. "75%"
    描述: str
    体用口诀: str
    代表方: str
    治法原则: str
    发酵阶段: str = ""
    误治风险: Dict[str, str] = field(default_factory=dict)


# ─── 检测结果 ───────────────────────────────────────────────────────────────

@dataclass
class EvidenceItem:
    source: str
    key: str
    dim: str
    type: str
    val: float
    weight: float
    label: str


@dataclass
class EvidenceDetail:
    体证据: List[EvidenceItem] = field(default_factory=list)
    用证据: List[EvidenceItem] = field(default_factory=list)


@dataclass
class ContradictionResult:
    """体用检测的完整结果"""
    引擎版本: str
    体用三型: str
    体总分: str
    用总分: str
    势能差: str
    体判定: str
    用判定: str
    匹配模式: List[MatchedPattern] = field(default_factory=list)
    检测日志: List[str] = field(default_factory=list)
    证据明细: Optional[EvidenceDetail] = None


# ─── 火候相关类型 ───────────────────────────────────────────────────────────

@dataclass
class FireStage:
    """火候定义"""
    用度: str
    临床对应: str
    符号: str
    用药特征: str


@dataclass
class FireStep:
    """火候序列中的一步"""
    火候: str
    理由: str
    用度范围: str = ""
    用药特征: str = ""
    剂型: str = ""


@dataclass
class FireRecommendation:
    """火候推荐结果"""
    体用型: str
    火候策略: str
    策略说明: str
    疗程: str
    风险: str = ""
    体质: str = ""
    火候序列: List[FireStep] = field(default_factory=list)
    专科方案: dict = field(default_factory=dict)


# ─── 潮汐上下文 ─────────────────────────────────────────────────────────────

@dataclass
class TideContext:
    """tide_context() 的输出"""
    时间: str
    时辰: str
    节气: str
    季节: str
    岁运: str
    司天: str
    季节调候: str
    时辰体用: str


# ─── dialectic 统一推理管线 ──────────────────────────────────────────────────

@dataclass
class DialecticInput:
    """dialectic() 的输入"""
    tongue: str = ""
    coat: str = ""
    pulse: str = ""
    symptoms: str = ""
    physician: str = ""
    constitution: str = ""
    specialty: str = "内科"
    year: Optional[str] = None
    collect_tide: bool = True
