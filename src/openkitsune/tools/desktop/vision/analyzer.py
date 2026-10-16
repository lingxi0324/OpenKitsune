"""
Windows 桌面自动化 - 视觉分析器

基于 DashScope Qwen-VL 实现 UI 视觉识别
"""

import json
import logging
import re
import sys
from typing import Any

from PIL import Image

from ..capture import ScreenCapture, get_capture
from ..types import (
    BoundingBox,
    ElementLocation,
    VisionResult,
)
from .prompts import PromptTemplates

# 平台检查
if sys.platform != "win32":
    raise ImportError(
        f"Desktop automation module is Windows-only. Current platform: {sys.platform}"
    )

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    """
    视觉分析器

    使用 DashScope Qwen-VL 分析截图，识别 UI 元素
    """

    def __init__(
        self,
        capture: ScreenCapture | None = None,
    ):
        """
        Args:
            capture: 截图实例，None 使用全局实例
        """
        self._capture = capture or get_capture()
        self._llm_client = None

    @property
    def llm_client(self):
        """懒加载 LLM 客户端"""
        if self._llm_client is None:
            from openkitsune.llm.client import get_default_client

            self._llm_client = get_default_client()
        return self._llm_client

    async def _call_vision_model(
        self,
        prompt: str,
        image: Image.Image,
    ) -> str:
        """
        调用视觉模型（模型由 LLM 端点配置决定）

        Args:
            prompt: 提示词
            image: 图片

        Returns:
            模型响应文本
        """
        from openkitsune.llm.types import ImageBlock, ImageContent, Message, TextBlock

        b64_data = self._capture.to_base64(image, resize_for_api=True)

        messages = [
            Message(
                role="user",
                content=[
                    ImageBlock(image=ImageContent.from_base64(b64_data, "image/jpeg")),
                    TextBlock(text=prompt),
                ],
            )
        ]

        response = await self.llm_client.chat(
            messages=messages,
            max_tokens=4096,
            temperature=1.0,
        )

        if response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text

        return ""

    def _parse_json_response(self, text: str) -> Any:
        """
        解析模型返回的 JSON，支持 dict 和 list，带容错恢复。

        Args:
            text: 模型响应文本

        Returns:
            解析后的 JSON 对象（dict 或 list）
        """
        # Try 1: extract markdown JSON block
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try 2: extract markdown code/text block
            json_match = re.search(r"```\s*\n([\s\S]*?)\s*```", text)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try 3: find JSON array in text
                start = text.find("[")
                end = text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_str = text[start:end]
                else:
                    # Try 4: find JSON object
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    json_str = text[start:end] if start >= 0 and end > start else text.strip()

        # Try to parse, with lenient recovery
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}...")
            recovered = self._recover_json(json_str)
            if recovered is not None:
                return recovered
            # Try normalizing escaped curly braces (f-string template format {{ -> {)
            try:
                fixed = json_str.replace("{{", "{").replace("}}", "}")
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
            return None

    def _recover_json(self, json_str: str) -> Any | None:
        """尝试宽松恢复 JSON，处理常见格式问题（尾随逗号、多余字符、缺少逗号、中文引号等）。"""
        # 1. Remove trailing commas before } or ]
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", json_str))
        except json.JSONDecodeError:
            pass
        # 2. Handle missing commas between strings in arrays: ,"text"  →  ,"text"
        #    Common issue: model outputs ["a" "b"] instead of ["a", "b"]
        try:
            fixed = re.sub(r'"(\s*)"', r'",\1"', json_str)
            fixed = re.sub(r'(\s*)"(\s*)"', r'\1",\2"', fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        # 3. Handle unicode/smart quotes
        try:
            fixed = json_str.replace(chr(0x201C), chr(0x2018)).replace(chr(0x201C), chr(0x22)).replace(chr(0x201D), chr(0x22))
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        # 4. Truncate at first complete array/object structure
        try:
            depth = 0
            in_string = False
            for i, ch in enumerate(json_str):
                if ch == '"' and (i == 0 or json_str[i - 1] != "\\"):
                    in_string = not in_string
                if not in_string:
                    if ch in "{[":
                        depth += 1
                    elif ch in "}]":
                        depth -= 1
                        if depth == 0:
                            return json.loads(json_str[:i + 1])
        except json.JSONDecodeError:
            pass
        # 5. Strip non-JSON trailing content
        try:
            return json.loads(json_str[:json_str.rfind("}") + 1])
        except json.JSONDecodeError:
            pass
        # 6. Try to find complete array by tracking bracket depth with string awareness
        try:
            depth = 0
            in_string = False
            brace_count = 0
            for i, ch in enumerate(json_str):
                if ch == '"' and (i == 0 or json_str[i - 1] != "\\"):
                    in_string = not in_string
                if not in_string:
                    if ch == "[":
                        depth += 1
                        brace_count += 1
                    elif ch == "]":
                        depth -= 1
                        brace_count -= 1
                        if depth == 0:
                            return json.loads(json_str[:i + 1])
        except json.JSONDecodeError:
            pass
        return None

    async def find_element(
        self,
        description: str,
        image: Image.Image | None = None,
    ) -> ElementLocation | None:
        """
        Find a UI element in the screenshot by description.
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.get_find_element_prompt(description)

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                return None

            if not result.get("found", False):
                logger.debug(f"Element not found: {result.get('reasoning', 'unknown')}")
                return None

            element = result.get("element", {})
            bbox_data = element.get("bbox")

            if not bbox_data or len(bbox_data) != 4:
                logger.warning(f"Invalid bbox in response: {bbox_data}")
                return None

            return ElementLocation(
                description=element.get("description", description),
                bbox=BoundingBox(
                    left=int(bbox_data[0]),
                    top=int(bbox_data[1]),
                    right=int(bbox_data[2]),
                    bottom=int(bbox_data[3]),
                ),
                confidence=float(element.get("confidence", 0.8)),
                reasoning=result.get("reasoning", ""),
            )

        except Exception as e:
            logger.error(f"Failed to find element: {e}")
            return None

    async def find_all_clickable(
        self,
        image: Image.Image | None = None,
    ) -> list[ElementLocation]:
        """
        查找所有可点击元素

        Args:
            image: 截图

        Returns:
            可点击元素列表
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.LIST_CLICKABLE

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                return []

            elements = []
            for elem_data in result.get("elements", []):
                bbox_data = elem_data.get("bbox")
                if not bbox_data or len(bbox_data) != 4:
                    continue

                elements.append(
                    ElementLocation(
                        description=elem_data.get("description", "unknown"),
                        bbox=BoundingBox(
                            left=int(bbox_data[0]),
                            top=int(bbox_data[1]),
                            right=int(bbox_data[2]),
                            bottom=int(bbox_data[3]),
                        ),
                        confidence=0.8,
                    )
                )

            return elements

        except Exception as e:
            logger.error(f"Failed to find clickable elements: {e}")
            return []

    async def find_all_input(
        self,
        image: Image.Image | None = None,
    ) -> list[ElementLocation]:
        """
        查找所有输入元素

        Args:
            image: 截图

        Returns:
            输入元素列表
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.LIST_INPUT

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                return []

            elements = []
            for elem_data in result.get("elements", []):
                bbox_data = elem_data.get("bbox")
                if not bbox_data or len(bbox_data) != 4:
                    continue

                elements.append(
                    ElementLocation(
                        description=elem_data.get("description", "unknown"),
                        bbox=BoundingBox(
                            left=int(bbox_data[0]),
                            top=int(bbox_data[1]),
                            right=int(bbox_data[2]),
                            bottom=int(bbox_data[3]),
                        ),
                        confidence=0.8,
                    )
                )

            return elements

        except Exception as e:
            logger.error(f"Failed to find input elements: {e}")
            return []

    async def analyze_page(
        self,
        image: Image.Image | None = None,
    ) -> VisionResult:
        """
        分析页面内容

        Args:
            image: 截图

        Returns:
            分析结果
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.ANALYZE_PAGE

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                return VisionResult(
                    success=False,
                    query="analyze_page",
                    error="Failed to parse response",
                    raw_response=response,
                )

            # 提取区域作为元素
            elements = []
            for region in result.get("regions", []):
                bbox_data = region.get("bbox")
                if bbox_data and len(bbox_data) == 4:
                    elements.append(
                        ElementLocation(
                            description=region.get("name", "region"),
                            bbox=BoundingBox(
                                left=int(bbox_data[0]),
                                top=int(bbox_data[1]),
                                right=int(bbox_data[2]),
                                bottom=int(bbox_data[3]),
                            ),
                        )
                    )

            return VisionResult(
                success=True,
                query="analyze_page",
                answer=result.get("summary", ""),
                elements=elements,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"Failed to analyze page: {e}")
            return VisionResult(
                success=False,
                query="analyze_page",
                error=str(e),
            )

    async def answer_question(
        self,
        question: str,
        image: Image.Image | None = None,
    ) -> VisionResult:
        """
        回答关于截图的问题

        Args:
            question: 问题
            image: 截图

        Returns:
            回答结果
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.get_answer_question_prompt(question)

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                # 如果 JSON 解析失败，直接返回原始响应
                return VisionResult(
                    success=True,
                    query=question,
                    answer=response,
                    raw_response=response,
                )

            # 提取相关元素
            elements = []
            for elem_data in result.get("relevant_elements", []):
                bbox_data = elem_data.get("bbox")
                if bbox_data and len(bbox_data) == 4:
                    elements.append(
                        ElementLocation(
                            description=elem_data.get("description", ""),
                            bbox=BoundingBox(
                                left=int(bbox_data[0]),
                                top=int(bbox_data[1]),
                                right=int(bbox_data[2]),
                                bottom=int(bbox_data[3]),
                            ),
                        )
                    )

            return VisionResult(
                success=True,
                query=question,
                answer=result.get("answer", ""),
                elements=elements,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"Failed to answer question: {e}")
            return VisionResult(
                success=False,
                query=question,
                error=str(e),
            )

    async def extract_text(
        self,
        image: Image.Image | None = None,
    ) -> VisionResult:
        """
        从截图中提取文本（OCR）

        使用专用 OCR 模型 (qwen-vl-ocr) 进行文本提取

        Args:
            image: 截图

        Returns:
            提取结果
        """
        if image is None:
            image = self._capture.capture(use_cache=False)

        prompt = PromptTemplates.EXTRACT_TEXT

        try:
            response = await self._call_vision_model(prompt, image)
            result = self._parse_json_response(response)

            if not result:
                return VisionResult(
                    success=False,
                    query="extract_text",
                    error="Failed to parse response",
                    raw_response=response,
                )

            # Handle list results (LLM may return array instead of dict)
            elements = []
            if isinstance(result, list):
                for text_data in result:
                    if isinstance(text_data, dict):
                        bbox_data = text_data.get("bbox") or text_data.get("bbox_2d")
                        if bbox_data and len(bbox_data) == 4:
                            elements.append(
                                ElementLocation(
                                    description=text_data.get("text", "") or text_data.get("content", ""),
                                    bbox=BoundingBox(
                                        left=int(bbox_data[0]),
                                        top=int(bbox_data[1]),
                                        right=int(bbox_data[2]),
                                        bottom=int(bbox_data[3]),
                                    ),
                                )
                            )
                    elif isinstance(text_data, str):
                        # Flat string list (e.g., ["text1", "text2", ...])
                        elements.append(
                            ElementLocation(
                                description=text_data,
                                bbox=BoundingBox(
                                    left=0, top=0, right=100, bottom=20,
                                ),
                            )
                        )
                if elements:
                    return VisionResult(
                        success=True,
                        query="extract_text",
                        answer="\n".join(e.description for e in elements),
                        elements=elements,
                        raw_response=response,
                    )

            # Extract text elements from dict format
            if not elements:
                for text_data in result.get("texts", []):
                    bbox_data = text_data.get("bbox")
                    if bbox_data and len(bbox_data) == 4:
                        elements.append(
                            ElementLocation(
                                description=text_data.get("content", ""),
                                bbox=BoundingBox(
                                    left=int(bbox_data[0]),
                                    top=int(bbox_data[1]),
                                    right=int(bbox_data[2]),
                                    bottom=int(bbox_data[3]),
                                ),
                            )
                        )

            return VisionResult(
                success=True,
                query="extract_text",
                answer=result.get("main_text", ""),
                elements=elements,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"Failed to extract text: {e}")
            return VisionResult(
                success=False,
                query="extract_text",
                error=str(e),
            )

    async def verify_action(
        self,
        before_image: Image.Image,
        after_image: Image.Image,
        action_description: str,
        expected_result: str,
    ) -> VisionResult:
        """
        验证操作是否成功

        对比操作前后的截图，判断操作是否成功

        Args:
            before_image: 操作前截图
            after_image: 操作后截图
            action_description: 操作描述
            expected_result: 预期结果

        Returns:
            验证结果
        """
        # 将两张图片合并（左右排列）
        total_width = before_image.width + after_image.width
        max_height = max(before_image.height, after_image.height)
        combined = Image.new("RGB", (total_width, max_height))
        combined.paste(before_image, (0, 0))
        combined.paste(after_image, (before_image.width, 0))

        prompt = PromptTemplates.get_verify_action_prompt(action_description, expected_result)

        try:
            response = await self._call_vision_model(prompt, combined)
            result = self._parse_json_response(response)

            if not result:
                return VisionResult(
                    success=False,
                    query=f"verify: {action_description}",
                    error="Failed to parse response",
                    raw_response=response,
                )

            return VisionResult(
                success=result.get("success", False),
                query=f"verify: {action_description}",
                answer=result.get("reasoning", ""),
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"Failed to verify action: {e}")
            return VisionResult(
                success=False,
                query=f"verify: {action_description}",
                error=str(e),
            )


# 全局实例
_analyzer: VisionAnalyzer | None = None


def get_vision_analyzer() -> VisionAnalyzer:
    """获取全局视觉分析器"""
    global _analyzer
    if _analyzer is None:
        _analyzer = VisionAnalyzer()
    return _analyzer
