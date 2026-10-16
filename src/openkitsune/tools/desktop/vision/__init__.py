"""
Tab-Agent 风格视觉工具包

模仿 TAB-Agent (Think, Act, Build) 框架，将 LLM 多模端点（如 llama-cpp-server 视觉模型）
集成为视觉对象分割、时序追踪、空间推理等能力。

模块组成：
- segmenter.py: 对象分割（模仿 SAM 流程，用 LLM 视觉替代）
- tracker.py: 时序追踪 + 多视角追踪（模仿 VlmFrameExpansion）
- spatial.py: 空间关系推理（模仿 TAB-Agent spatial reasoning）
- analyzer.py: 视觉分析（OCR、页面分析、问答、验证）
"""

from .analyzer import VisionAnalyzer, get_vision_analyzer
from .prompts import PromptTemplates
from .segmenter import LlmSegmenter
from .spatial import SpatialChainReasoner, SpatialReasoner
from .tracker import MultiViewTracker, TemporalTracker

__all__ = [
    "LlmSegmenter",
    "TemporalTracker",
    "MultiViewTracker",
    "SpatialReasoner",
    "SpatialChainReasoner",
    "VisionAnalyzer",
    "get_vision_analyzer",
]
