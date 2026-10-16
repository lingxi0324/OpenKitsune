"""
Tab-Agent 风格视觉分割工具

使用 LLM 多模端点（如 llama-cpp-server 视觉模型）进行对象分割，
模仿 TAB-Agent 的 SAM 分割流程但不依赖 SAM/segment-anything。

核心思路：
- 发送截图 + 对象描述给 LLM 视觉端点
- 要求返回所有匹配对象的边界框坐标
- 返回格式：JSON，包含对象 ID、bbox、置信度、描述
"""

import json
import re
from typing import Any
from PIL import Image

from .analyzer import VisionAnalyzer, get_vision_analyzer


class LlmSegmenter:
    """
    基于 LLM 视觉能力的对象分割器
    
    模仿 TAB-Agent 的 MasksFilter / ArgmaxImageAndSegId 流程，
    但使用 LLM 视觉端点替代 SAM，适用于任何支持图像输入的 LLM。
    
    使用方式：
        segmenter = LlmSegmenter(vision_analyzer)
        results = segmenter.segment(image, "a red car on the road")
    """

    def __init__(self, analyzer: VisionAnalyzer = None):
        self._analyzer = analyzer or get_vision_analyzer()

    def _get_analyzer(self) -> VisionAnalyzer:
        if not self._analyzer:
            self._analyzer = get_vision_analyzer()
        return self._analyzer

    async def segment(
        self,
        image: Image.Image | None = None,
        description: str = "",
        max_objects: int = 20,
    ) -> list[dict[str, Any]]:
        """
        在图像中分割出匹配描述的对象。
        
        Args:
            image: 输入图像，None 则自动截图
            description: 要分割的对象描述（如 "a brown ottoman"）
            max_objects: 最大返回对象数
            
        Returns:
            匹配对象列表，每个元素包含:
            - object_id: int (从 0 开始)
            - bbox: [x1, y1, x2, y2]
            - confidence: float (0-1)
            - description: str
        """
        analyzer = self._get_analyzer()
        
        prompt = f"""You are an expert visual object detector. Analyze this image and identify all objects that match the description: "{description}"

Requirements:
1. Identify ALL objects in the image that match the description
2. For each match, provide its bounding box coordinates and confidence
3. Objects should be labeled with sequential IDs starting from 0
4. Be specific about object types and attributes

Return your answer in JSON format:
```json
[
    {{
        "object_id": 0,
        "bbox": [x1, y1, x2, y2],
        "confidence": 0.0-1.0,
        "description": "brief description of this object"
    }},
    ...
]
```

Notes:
- bbox values are absolute pixel coordinates (top-left x, top-left y, bottom-right x, bottom-right y)
- confidence is a float between 0.0 and 1.0
- If no objects match, return an empty list []
- Only return the JSON, nothing else."""

        result = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return self._parse_json_response(result)

    async def segment_all(
        self,
        image: Image.Image | None = None,
        max_objects: int = 50,
    ) -> list[dict[str, Any]]:
        """
        在图像中分割出所有可识别的对象（不依赖描述）。
        
        Returns:
            对象列表，每个元素包含:
            - object_id, bbox, confidence, description
        """
        analyzer = self._get_analyzer()
        
        prompt = f"""You are an expert object detection system. Analyze this image and identify ALL distinct objects present.

Requirements:
1. Identify every distinct object in the image
2. Group related items (e.g., "shoes" should be one entry, not two)
3. For each object, provide bounding box and brief description
4. Include non-obvious objects (small items, text, etc.)

Return your answer in JSON format:
```json
[
    {{
        "object_id": 0,
        "bbox": [x1, y1, x2, y2],
        "confidence": 0.0-1.0,
        "description": "brief description of this object"
    }},
    ...
]
```

Notes:
- bbox values are absolute pixel coordinates
- confidence is a float between 0.0 and 1.0
- If no objects found, return an empty list []
- Only return the JSON, nothing else."""

        result = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return self._parse_json_response(result)

    async def refine_segmentation(
        self,
        image: Image.Image | None = None,
        description: str,
        existing_masks: list[dict[str, Any]] = None,
        exclude_ids: list[int] = None,
        refine_area: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        在已有分割结果基础上，细化/修正某个区域的分割。
        
        用途：模仿 TAB-Agent 的 VLM Frame Expansion 流程，
        对特定区域进行二次分割以提高精度。
        """
        analyzer = self._get_analyzer()
        
        context_parts = []
        if existing_masks:
            existing_objects = [f"ID {m.get('object_id')} (bbox: {m.get('bbox')}, desc: {m.get('description')})" for m in existing_masks]
            context_parts.append(f"Existing detected objects: {json.dumps(existing_objects)}")
        
        if exclude_ids:
            context_parts.append(f"Exclude these IDs: {json.dumps(exclude_ids)}")
        
        if refine_area:
            context_parts.append(f"Focus area: {json.dumps(refine_area)}")
            
        context_text = "\n".join(context_parts) if context_parts else "No existing segmentation results."

        prompt = f"""You are an expert visual object detector. Refine the segmentation for this image.

Context:
{context_text}

Target description: "{description}"

Requirements:
1. Focus on the refinement area (if specified)
2. Find additional objects that match "{description}" that were missed before
3. Adjust bounding boxes for objects that need refinement
4. Return updated results

Return your answer in JSON format:
```json
[
    {{
        "object_id": 0,
        "bbox": [x1, y1, x2, y2],
        "confidence": 0.0-1.0,
        "description": "brief description"
    }},
    ...
]
```

Notes:
- Only include objects that match "{description}"
- Do not include objects with IDs in the exclude list
- Only return the JSON, nothing else."""

        result = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return self._parse_json_response(result)

    @staticmethod
    def _parse_json_response(text: str) -> list[dict[str, Any]]:
        """解析 LLM 返回的 JSON 响应"""
        if not text:
            return []
            
        try:
            # 尝试提取 JSON 数组
            json_match = re.search(r'\[([\s\S]*?)\]', text)
            if json_match:
                return json.loads(json_match.group(1))
            return []
        except (json.JSONDecodeError, IndexError):
            return []
