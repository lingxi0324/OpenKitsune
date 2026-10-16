"""
Tab-Agent 风格空间推理工具

模仿 TAB-Agent 的 spatial reasoning / spatial_query 能力，
让 LLM 多模端点能够回答关于图像中对象空间关系的问题。

使用方式：
    spatial = SpatialReasoner(vision_analyzer)
    answer = await spatial.query("Where is the red car relative to the building?")
"""

import json
import re
from typing import Any
from PIL import Image

from .analyzer import VisionAnalyzer, get_vision_analyzer


class SpatialReasoner:
    """
    空间推理器
    
    使用 LLM 视觉端点进行空间关系推理：
    - 相对位置判断（左/右/上/下/前/后/内/外）
    - 距离估计（近/远/中等）
    - 遮挡关系判断
    - 空间关系链推理（A 在 B 左边，B 在 C 前 → A 在 C 的左前）
    - 3D 空间推断（从 2D 图像推断深度/层次）
    
    使用方式：
        reasoner = SpatialReasoner(vision_analyzer)
        answer = await reasoner.query("Is the cat to the left of the dog?")
    """

    def __init__(self, analyzer: VisionAnalyzer = None):
        self._analyzer = analyzer or get_vision_analyzer()

    def _get_analyzer(self) -> VisionAnalyzer:
        if not self._analyzer:
            self._analyzer = get_vision_analyzer()
        return self._analyzer

    async def query(
        self,
        question: str,
        image: Image.Image | None = None,
        answer_options: list[str] = None,
    ) -> dict[str, Any]:
        """
        回答关于图像空间关系的问题。
        
        Args:
            question: 空间关系问题（如 "Where is the red car relative to the building?"）
            image: 输入图像，None 则自动截图
            answer_options: 预定义选项列表，如 ["left", "right", "above", "below", "in_front", "behind", "left_front", "left_behind", "right_front", "right_behind"]
            
        Returns:
            推理结果，包含:
            - question: str
            - answer: str
            - reasoning: str
            - confidence: float
            - spatial_relationships: list[dict] (对象间关系)
        """
        analyzer = self._get_analyzer()
        
        options_text = ""
        if answer_options:
            options_text = f"""

Available answer options: {', '.join(answer_options)}. Choose one if applicable."""

        prompt = f"""You are an expert spatial reasoning assistant. Analyze this image and answer the question.

Question: "{question}"{options_text}

Instructions:
1. Identify relevant objects in the image
2. Determine their spatial relationship to each other
3. Consider depth cues: relative size, occlusion, position in image
4. Provide a confident answer

Return your answer in JSON format:
```json
{{
    "question": "{question}",
    "answer": "direct answer to the question",
    "reasoning": "detailed reasoning about the spatial relationship",
    "confidence": 0.0-1.0,
    "spatial_relationships": [
        {{
            "object1": "object1 description",
            "object2": "object2 description",
            "relationship": "left/right/above/below/front/behind/etc",
            "confidence": 0.0-1.0
        }}
    ]
}}
```

Notes:
- Be precise about spatial relationships
- Consider depth (objects higher in the image are often further away)
- Use relative terms like 'to the left of', 'in front of', 'above'
- Only return the JSON, nothing else."""

        result_text = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return analyzer._parse_json_response(result_text) or {
            "question": question,
            "answer": "unknown",
            "reasoning": "Failed to parse response",
            "confidence": 0,
            "spatial_relationships": [],
        }

    async def compare_objects(
        self,
        object1_description: str,
        object2_description: str,
        relationship: str = "relative_position",
        image: Image.Image | None = None,
    ) -> dict[str, Any]:
        """
        比较两个对象的空间关系。
        
        Args:
            object1_description: 第一个对象描述（如 "the red car"）
            object2_description: 第二个对象描述（如 "the building"）
            relationship: 关系类型（"relative_position", "distance", "occlusion", "relative_size", "depth_order"）
            image: 输入图像
        """
        analyzer = self._get_analyzer()
        
        relationship_prompts = {
            "relative_position": (
                f"What is the relative position of '{object1_description}' compared to '{object2_description}'?\n"
                "Consider: left/right, above/below, in_front_of/behind"
            ),
            "distance": (
                f"What is the approximate distance between '{object1_description}' and '{object2_description}'?\n"
                "Use relative terms: very close, close, moderate, far, very far"
            ),
            "occlusion": (
                f"Does '{object1_description}' occlude or is occluded by '{object2_description}'?\n"
                "Also: are they at the same depth level, or is one clearly in front?"
            ),
            "relative_size": (
                f"How does the apparent size of '{object1_description}' compare to '{object2_description}'?\n"
                "Consider actual size vs distance from camera"
            ),
            "depth_order": (
                f"What is the depth ordering of '{object1_description}' and '{object2_description}'?\n"
                "Which one is closer to the camera? Are they at similar depth?"
            ),
        }

        prompt = relationship_prompts.get(relationship, relationship_prompts["relative_position"])
        
        result_text = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return analyzer._parse_json_response(result_text) or {
            "question": f"{relationship}: {object1_description} vs {object2_description}",
            "answer": "unknown",
            "reasoning": "Failed to parse response",
            "confidence": 0,
        }

    async def answer_visual_question(
        self,
        question: str,
        image: Image.Image | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        回答任意视觉问题（通用问答，不限于空间关系）。
        
        Args:
            question: 问题（如 "How many cars are parked?"）
            image: 输入图像
            max_retries: 重试次数
        """
        analyzer = self._get_analyzer()
        
        prompt = f"""You are a visual question answering expert. Analyze this image and answer the question.

Question: "{question}"

Instructions:
1. Carefully analyze the image content
2. Provide a clear, accurate answer
3. Include relevant details and counts
4. If unsure, say so

Return your answer in JSON format:
```json
{{
    "question": "{question}",
    "answer": "direct answer",
    "confidence": 0.0-1.0,
    "details": "additional relevant details"
}}
```

Only return the JSON, nothing else."""

        result_text = await analyzer._call_vision_model(prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        return analyzer._parse_json_response(result_text) or {
            "question": question,
            "answer": "unknown",
            "confidence": 0,
        }


class SpatialChainReasoner:
    """
    空间关系链推理器
    
    模仿 TAB-Agent 的推理链：先识别对象 → 建立空间关系 → 推导间接关系。
    例如：A 在 B 左边，B 在 C 上面 → A 在 C 的左上方。
    """

    def __init__(self, analyzer: VisionAnalyzer = None):
        self._analyzer = analyzer or get_vision_analyzer()
        self._reasoner = SpatialReasoner(analyzer)

    async def chain_reason(
        self,
        scene_description: str,
        chain: list[str],
        image: Image.Image | None = None,
    ) -> dict[str, Any]:
        """
        执行空间关系链推理。
        
        Args:
            scene_description: 场景描述（如 "a living room with a couch, coffee table, and TV"）
            chain: 推理链，如 ["Where is the coffee table?", "Is the TV above the couch?"]
            image: 输入图像
        """
        analyzer = self._get_analyzer()
        results = []
        
        # 第一步：建立对象索引
        objects_prompt = f"""Analyze this image and create an index of all major objects and their spatial relationships.

Scene: {scene_description}

Return objects and their positions in JSON format:
```json
[
    {{
        "object_id": 0,
        "description": "object description",
        "bbox": [x1, y1, x2, y2],
        "position_summary": "e.g., 'left side, in front of couch'"
    }},
    ...
]
```

Only return the JSON, nothing else."""

        objects_result = await analyzer._call_vision_model(objects_prompt, image or (await self._get_analyzer()._capture.capture(use_cache=False)))
        objects = self._parse_json_response(objects_result) or []

        # 第二步：执行推理链
        for question in chain:
            result = await self._reasoner.query(question, image)
            results.append({"question": question, "result": result})

        return {
            "scene_description": scene_description,
            "objects": objects,
            "chain_reasoning": results,
            "image": image,
        }

    @staticmethod
    def _parse_json_response(text: str) -> list[dict[str, Any]]:
        """解析 LLM 返回的 JSON 响应"""
        if not text:
            return []
        try:
            json_match = re.search(r'\[([\s\S]*?)\]', text)
            if json_match:
                return json.loads(json_match.group(1))
            return []
        except (json.JSONDecodeError, IndexError):
            return []

