"""
Tab-Agent 风格时序追踪工具

模仿 TAB-Agent 的 VlmFrameExpansion + ExpandFromSecondaryView，
在连续帧/图像间追踪同一目标对象。

使用本地 LLM 多模端点进行跨帧对象一致性验证。
"""

import json
import re
import os
from typing import Any
from PIL import Image

from .analyzer import VisionAnalyzer, get_vision_analyzer
from .segmenter import LlmSegmenter


class TemporalTracker:
    """
    时序追踪器
    
    模仿 TAB-Agent 的 VlmFrameExpansion 流程：
    - 从参考帧（reference frame）开始
    - 向左右扩展，逐帧验证目标一致性
    - 使用 VLM 验证每帧是否包含目标对象
    
    使用方式：
        tracker = TemporalTracker(vision_analyzer)
        results = await tracker.track_frames(
            image_files=["frame_001.jpg", "frame_002.jpg", ...],
            description="a brown ottoman",
            reference_image="frame_001.jpg"
        )
    """

    def __init__(self, analyzer: VisionAnalyzer = None):
        self._analyzer = analyzer or get_vision_analyzer()
        self._segmenter = LlmSegmenter(analyzer)

    def _get_analyzer(self) -> VisionAnalyzer:
        if not self._analyzer:
            self._analyzer = get_vision_analyzer()
        return self._analyzer

    async def track_frames(
        self,
        image_files: list[str],
        description: str,
        reference_image: str = None,
        max_expand_frames: int = 16,
        verify_method: str = "llm",
    ) -> list[dict[str, Any]]:
        """
        在连续图像序列中追踪目标对象。
        
        Args:
            image_files: 按时间顺序排列的图像文件列表
            description: 目标对象描述
            reference_image: 参考图像（包含目标的帧），None 则自动检测
            max_expand_frames: 最大扩展帧数（每方向）
            verify_method: 验证方法 ("llm"=LLM 视觉, "segment"=分割对比)
            
        Returns:
            追踪结果列表，按时间顺序排列，每个元素:
            - frame_index: int (图像文件索引)
            - frame_file: str
            - has_target: bool
            - bbox: [x1, y1, x2, y2] or None
            - confidence: float or None
            - match_score: float (目标匹配度 0-1)
        """
        if not image_files:
            return []

        analyzer = self._get_analyzer()
        results = []

        if reference_image is None:
            # 自动检测：先对每帧做分割，找包含目标的第一帧
            reference_image, reference_index = await self._detect_reference(
                image_files, description
            )

        # 确定参考帧在列表中的位置
        ref_index = image_files.index(reference_image) if reference_image in image_files else 0

        # 向左扩展
        left_results = await self._expand_direction(
            analyzer, image_files, ref_index, "left", description,
            max_expand_frames, verify_method
        )
        # 向右扩展
        right_results = await self._expand_direction(
            analyzer, image_files, ref_index, "right", description,
            max_expand_frames, verify_method
        )

        # 合并（注意 left_results 已经是逆序的）
        results = left_results + [{"frame_index": ref_index, "frame_file": reference_image, "has_target": True, "bbox": None, "confidence": 1.0, "match_score": 1.0}] + right_results

        return results

    async def _detect_reference(
        self,
        image_files: list[str],
        description: str,
    ) -> tuple[str, int]:
        """自动检测包含目标对象的参考帧"""
        for i, img_path in enumerate(image_files[:20]):
            try:
                with open(img_path, 'rb') as f:
                    img_bytes = f.read()
                
                analyzer = self._get_analyzer()
                result = await self._verify_frame_has_target(
                    analyzer,
                    img_bytes,
                    description,
                    max_score=5.0,
                    min_score=3.0,
                )
                if result.get("has_target", False):
                    return img_path, i
            except Exception:
                continue

        # 回退：返回第一帧
        return image_files[0], 0

    async def _verify_frame_has_target(
        self,
        analyzer: VisionAnalyzer,
        image_bytes: bytes,
        description: str,
        reference_context: bytes = None,
        max_score: float = 5.0,
        min_score: float = 0.0,
    ) -> dict[str, Any]:
        """
        验证单帧是否包含目标对象（模仿 TAB-Agent 的 VLM Frame Expansion）
        """
        # 构造参考上下文
        ref_context = ""
        if reference_context:
            ref_context = f"\nReference context image provided.\n"

        prompt = f"""You are a target object verification assistant. Your job is to determine if the target object exists in the current frame.

Target description: "{description}"
{ref_context}

Instructions:
1. Look at the current frame carefully
2. Determine if the target object (described above) is present
3. If present, provide its bounding box and confidence
4. If NOT present, say "NO" with reason

Return your answer in JSON format:
```json
{{
    "has_target": true/false,
    "bbox": [x1, y1, x2, y2],
    "confidence": 0.0-1.0,
    "match_score": 0-5 (0=no target, 5=perfect match),
    "reason": "brief explanation"
}}
```

Return only the JSON, nothing else."""

        image = await analyzer._capture.from_base64(image_bytes)
        result_text = await analyzer._call_vision_model(prompt, image)
        return analyzer._parse_json_response(result_text) or {
            "has_target": False, "bbox": None, "confidence": 0, "match_score": 0, "reason": "parse_error"
        }

    async def _expand_direction(
        self,
        analyzer: VisionAnalyzer,
        image_files: list[str],
        ref_index: int,
        direction: str,
        description: str,
        max_frames: int = 16,
        verify_method: str = "llm",
    ) -> list[dict[str, Any]]:
        """向一个方向扩展追踪"""
        results = []
        
        start_index = ref_index + 1 if direction == "right" else ref_index - 1
        
        if direction == "right":
            indices = list(range(start_index, min(ref_index + max_frames, len(image_files))))
        else:
            indices = list(range(start_index, max(start_index - max_frames - 1, -1), -1))

        for idx in indices:
            if idx < 0 or idx >= len(image_files):
                break
                
            img_path = image_files[idx]
            try:
                with open(img_path, 'rb') as f:
                    img_bytes = f.read()
                    
                result = await self._verify_frame_has_target(
                    analyzer, img_bytes, description
                )
                results.append({
                    "frame_index": idx,
                    "frame_file": img_path,
                    "has_target": result.get("has_target", False),
                    "bbox": result.get("bbox"),
                    "confidence": result.get("confidence", 0),
                    "match_score": result.get("match_score", 0),
                })
                if not result.get("has_target", False):
                    break  # 目标消失，停止扩展
            except Exception as e:
                break

        return results

    async def find_secondary_view(
        self,
        image_files: list[str],
        description: str,
        existing_results: list[dict[str, Any]],
        max_candidate_frames: int = 5,
    ) -> list[dict[str, Any]]:
        """
        寻找与已有追踪结果在空间/时间上最远的新视角
        （模仿 TAB-Agent ExpandFromSecondaryView）
        
        Returns:
            新视角的追踪结果
        """
        existing_indices = [r.get("frame_index") for r in existing_results if r.get("has_target")]
        
        if not existing_indices:
            return []

        # 找与现有帧最远的候选帧
        distances = []
        for i, (img_path, _idx) in enumerate([(f, idx) for idx, f in enumerate(image_files) if idx not in existing_indices]):
            min_dist = min(abs(idx - _idx) for _idx in existing_indices)
            distances.append((i, min_dist))

        # 取距离最大的候选帧
        distances.sort(key=lambda x: x[1], reverse=True)
        
        candidates = []
        for idx, _dist in distances[:max_candidate_frames]:
            img_path = image_files[idx]
            try:
                with open(img_path, 'rb') as f:
                    img_bytes = f.read()
                result = await self._verify_frame_has_target(
                    self._get_analyzer(), img_bytes, description
                )
                candidates.append({
                    "frame_index": idx,
                    "frame_file": img_path,
                    "has_target": result.get("has_target", False),
                    "bbox": result.get("bbox"),
                    "confidence": result.get("confidence", 0),
                    "match_score": result.get("match_score", 0),
                    "distance_from_existing": _dist,
                })
            except Exception:
                continue

        return candidates


class MultiViewTracker:
    """
    多视角追踪器
    
    整合多个视角的追踪结果，生成完整的对象覆盖轨迹。
    """

    def __init__(self, analyzer: VisionAnalyzer = None):
        self._analyzer = analyzer or get_vision_analyzer()
        self._tracker = TemporalTracker(analyzer)

    async def merge_views(
        self,
        views: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        合并多个视角的追踪结果，去重并按时间排序
        
        Args:
            views: 多个视角的追踪结果列表
        """
        merged = {}
        for view in views:
            for item in view:
                frame_idx = item.get("frame_index")
                if frame_idx not in merged or item.get("match_score", 0) > merged[frame_idx].get("match_score", 0):
                    merged[frame_idx] = item

        sorted_results = sorted(merged.values(), key=lambda x: x.get("frame_index", 0))
        return sorted_results
