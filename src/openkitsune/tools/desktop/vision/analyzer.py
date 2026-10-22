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

# JSON 骨架词：宽松文本提取时用于过滤掉模型输出的键名/结构词
_JSON_SKELETON_KEYS = {
    "texts", "main_text", "content", "bbox", "bbox_2d", "type", "title",
    "label", "button", "input", "application", "window_title", "page_type",
    "main_content", "regions", "key_actions", "alerts", "summary",
    "elements", "total_count", "found", "element", "reasoning",
    "confidence", "description", "center", "answer", "relevant_elements",
    "success", "changes", "matches_expectation", "current_state",
    "added", "removed", "changed", "layout_changes", "name", "text",
}


def _is_json_skeleton(s: str) -> bool:
    """判断文本是否为 JSON 骨架（键名/结构词），而非真实屏幕内容。"""
    stripped = s.strip("\"'“”「」『』 ")
    return stripped in _JSON_SKELETON_KEYS


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
            **self._endpoint_kwargs(),
        )

        if response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text

        return ""

    @staticmethod
    def _endpoint_kwargs() -> dict[str, Any]:
        """可选的视觉端点偏好（DESKTOP_VISION_ENDPOINT）。

        默认按端点优先级自动选择；配置后优先使用指定的轻量视觉端点，
        避免桌面截图分析把主对话模型挤下显存或触发冷启动。
        """
        try:
            from ..config import get_config

            endpoint = (get_config().vision.endpoint or "").strip()
        except Exception:
            endpoint = ""
        if not endpoint:
            return {}
        return {"endpoint_name": endpoint, "endpoint_policy": "prefer"}

    def _parse_json_response(self, text: str) -> Any:
        """
        解析模型返回的 JSON，支持 dict 和 list，带容错恢复。

        解析失败时返回 None，调用方应回退到宽松文本提取。

        Args:
            text: 模型响应文本

        Returns:
            解析后的 JSON 对象（dict 或 list），失败返回 None
        """
        # 先归一化 f-string 转义的花括号（模型常把 prompt 里的 {{ 原样返回）
        text = text.replace("{{", "{").replace("}}", "}")
        # 再归一化智能引号/中文引号
        text = self._normalize_quotes(text)

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
            # 模型常在 JSON 前后/中间夹杂解释文字（Extra data），
            # 逐个尝试文本中第一个完整且可解析的 JSON 结构。
            for span in self._balanced_json_spans(text):
                try:
                    return json.loads(span)
                except json.JSONDecodeError:
                    recovered = self._recover_json(span)
                    if recovered is not None:
                        return recovered
            return None

    @staticmethod
    def _balanced_json_spans(text: str, limit: int = 10) -> list[str]:
        """提取文本中以 { 或 [ 开头、括号配平的 JSON 片段（跳过字符串内的括号）。"""
        spans: list[str] = []
        for start, ch in enumerate(text):
            if ch not in "{[":
                continue
            depth = 0
            in_string = False
            escaped = False
            for idx in range(start, len(text)):
                cur = text[idx]
                if in_string:
                    if escaped:
                        escaped = False
                    elif cur == "\\":
                        escaped = True
                    elif cur == '"':
                        in_string = False
                    continue
                if cur == '"':
                    in_string = True
                elif cur in "{[":
                    depth += 1
                elif cur in "}]":
                    depth -= 1
                    if depth == 0:
                        spans.append(text[start:idx + 1])
                        break
            if len(spans) >= limit:
                break
        return spans

    @staticmethod
    def _normalize_quotes(text: str) -> str:
        """把智能引号/中文引号统一为 ASCII 引号，避免 JSON 解析失败。"""
        quote_map = {
            "\u201c": '"',  # "
            "\u201d": '"',  # "
            "\u201e": '"',  # "
            "\u201f": '"',  # "
            "\u2018": "'",  # '
            "\u2019": "'",  # '
            "\u300c": '"',  # 「
            "\u300d": '"',  # 」
            "\u300e": '"',  # 『
            "\u300f": '"',  # 』
            "\uff02": '"',  # ＂
        }
        for src, dst in quote_map.items():
            text = text.replace(src, dst)
        return text

    def _recover_json(self, json_str: str) -> Any | None:
        """尝试宽松恢复 JSON，处理常见格式问题（尾随逗号、多余字符、缺少逗号等）。"""
        # 1. Remove trailing commas before } or ]
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", json_str))
        except json.JSONDecodeError:
            pass
        # 2. Handle missing commas between strings in arrays: "a" "b" -> "a", "b"
        try:
            fixed = re.sub(r'"\s+"', '", "', json_str)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        # 3. Truncate at first complete array/object structure (string-aware depth tracking)
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
        # 4. Strip non-JSON trailing content after last }
        try:
            idx = json_str.rfind("}")
            if idx >= 0:
                return json.loads(json_str[:idx + 1])
        except json.JSONDecodeError:
            pass
        # 5. Strip non-JSON trailing content after last ]
        try:
            idx = json_str.rfind("]")
            if idx >= 0:
                return json.loads(json_str[:idx + 1])
        except json.JSONDecodeError:
            pass
        return None

    @staticmethod
    def _extract_text_fallback(response: str) -> list[str]:
        """
        宽松文本回退：当模型未按 JSON 返回时，从原始响应中提取可见文本。

        依次尝试：
        1. 提取所有被引号包裹的字符串（模型散落的文本条目）
        2. 按行剥离 JSON 骨架/列表符号，保留内容行
        """
        lines: list[str] = []
        # 剥掉 markdown 围栏
        text = re.sub(r"```[a-zA-Z]*\s*", "", response)
        text = re.sub(r"```", "", text)

        # 1. 引号包裹的字符串
        quoted = re.findall(r"[\"']([^\"'\n]{1,200})[\"']", text)
        for q in quoted:
            q = q.strip()
            if q and q not in lines and not _is_json_skeleton(q):
                lines.append(q)

        # 2. 逐行清理：去掉 JSON 骨架/键名/符号前缀
        for raw_line in text.splitlines():
            line = raw_line.strip().strip("[],{}\"' ")
            if not line or len(line) < 2:
                continue
            # 跳过键名行（如 "texts":、main_text:）
            if re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*:$', line):
                continue
            if _is_json_skeleton(line):
                continue
            # 去掉行内键名前缀
            line = re.sub(r'^[A-Za-z_][A-Za-z0-9_]*\s*:\s*', '', line)
            line = line.strip().strip('",[]{} ')
            if line and line not in lines and len(line) >= 2:
                lines.append(line)

        # 去重保序
        seen: set[str] = set()
        unique: list[str] = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return unique

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

            # 兼容 list 形态（模型返回多个候选），取第一个 found=true 的
            if isinstance(result, list):
                for candidate in result:
                    if isinstance(candidate, dict) and candidate.get("found", False):
                        result = candidate
                        break
                else:
                    return None

            if not result.get("found", False):
                logger.debug(f"Element not found: {result.get('reasoning', 'unknown')}")
                return None

            element = result.get("element", {})
            # 兼容 bbox 在顶层或 element 内部两种形态
            bbox_data = element.get("bbox") if isinstance(element, dict) else None
            if not bbox_data:
                bbox_data = result.get("bbox")

            if not bbox_data or len(bbox_data) != 4:
                logger.warning(f"Invalid bbox in response: {bbox_data}")
                return None

            description = (
                element.get("description", description)
                if isinstance(element, dict)
                else description
            )

            return ElementLocation(
                description=description,
                bbox=BoundingBox(
                    left=int(bbox_data[0]),
                    top=int(bbox_data[1]),
                    right=int(bbox_data[2]),
                    bottom=int(bbox_data[3]),
                ),
                confidence=float(element.get("confidence", 0.8) if isinstance(element, dict) else 0.8),
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
            # 兼容 dict {"elements": [...]} 与 list [...] 两种形态
            items = result.get("elements", []) if isinstance(result, dict) else result
            for elem_data in items:
                if not isinstance(elem_data, dict):
                    continue
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
            # 兼容 dict {"elements": [...]} 与 list [...] 两种形态
            items = result.get("elements", []) if isinstance(result, dict) else result
            for elem_data in items:
                if not isinstance(elem_data, dict):
                    continue
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
                # 宽松回退：模型输出非 JSON 时，直接把原文作为分析结果
                logger.debug("analyze_page: JSON parse failed, falling back to raw response")
                return VisionResult(
                    success=True,
                    query="analyze_page",
                    answer=response.strip(),
                    raw_response=response,
                )

            # 提取区域作为元素
            elements = []
            regions = result.get("regions", []) if isinstance(result, dict) else result
            if not isinstance(regions, list):
                regions = []
            for region in regions:
                if not isinstance(region, dict):
                    continue
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

            if isinstance(result, dict):
                answer = result.get("summary", "") or response.strip()
            else:
                # 模型直接返回区域列表：用区域名拼出概要
                names = [str(e.description) for e in elements if e.description]
                answer = "；".join(names) if names else response.strip()

            return VisionResult(
                success=True,
                query="analyze_page",
                answer=answer,
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
            try:
                response = await self._call_vision_model(prompt, image)
            except Exception as e:
                logger.warning(f"LLM vision call failed ({e}), falling back to local OCR")
                return self._extract_text_local_ocr(image, error=f"LLM unavailable: {e}")

            result = self._parse_json_response(response)

            elements: list[ElementLocation] = []

            # 解析成功：按常见结构提取
            if result is not None:
                elements = self._collect_text_elements(result)

            # 宽松回退：JSON 解析失败或结构不符时，直接从原始响应提取文本
            if not elements:
                fallback_lines = self._extract_text_fallback(response)
                for line in fallback_lines:
                    elements.append(
                        ElementLocation(
                            description=line,
                            bbox=BoundingBox(
                                left=0, top=0, right=100, bottom=20,
                            ),
                        )
                    )

            if elements:
                answer = "\n".join(e.description for e in elements)
                return VisionResult(
                    success=True,
                    query="extract_text",
                    answer=answer,
                    elements=elements,
                    raw_response=response,
                )

            # LLM 给了响应但没提取到文字：降级到本地 OCR
            logger.warning("LLM response yielded no text, falling back to local OCR")
            return self._extract_text_local_ocr(image, error="LLM returned no usable text")

        except Exception as e:
            logger.error(f"Failed to extract text: {e}")
            # 兜底：任何异常都尝试本地 OCR
            try:
                return self._extract_text_local_ocr(image, error=str(e))
            except Exception as local_e:
                logger.error(f"Local OCR fallback also failed: {local_e}")
                return VisionResult(
                    success=False,
                    query="extract_text",
                    error=str(e),
                )

    def _extract_text_local_ocr(
        self,
        image: Image.Image,
        error: str = "",
    ) -> VisionResult:
        """
        本地 Tesseract OCR 回退：不依赖 LLM，确定性通道。

        优先用 Tesseract（chi_sim 中文），返回按行聚合的文本。

        Args:
            image: 截图
            error: 上游失败原因（写入 raw_response 供排查）

        Returns:
            提取结果
        """
        import os
        import shutil
        import subprocess
        import tempfile

        tess = shutil.which("tesseract")
        if not tess:
            return VisionResult(
                success=False,
                query="extract_text",
                error=f"Local OCR unavailable (no tesseract). Upstream: {error}",
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                img_path = os.path.join(tmpdir, "screenshot.png")
                out_path = os.path.join(tmpdir, "out")
                image.save(img_path)

                # 用 chi_sim 中文；若不可用则退回 eng
                proc = subprocess.run(
                    [tess, img_path, out_path, "-l", "chi_sim", "--psm", "3"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if proc.returncode != 0:
                    # 尝试 eng
                    proc = subprocess.run(
                        [tess, img_path, out_path, "-l", "eng", "--psm", "3"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                if proc.returncode != 0:
                    return VisionResult(
                        success=False,
                        query="extract_text",
                        error=f"Local OCR failed: {proc.stderr.strip()}",
                    )

                txt_path = out_path + ".txt"
                if not os.path.exists(txt_path):
                    return VisionResult(
                        success=False,
                        query="extract_text",
                        error=f"Local OCR produced no output file. Upstream: {error}",
                    )

                with open(txt_path, encoding="utf-8") as f:
                    raw_text = f.read()

                lines = [
                    line.strip()
                    for line in raw_text.splitlines()
                    if line.strip()
                ]
                if not lines:
                    return VisionResult(
                        success=False,
                        query="extract_text",
                        error=f"Local OCR found no text. Upstream: {error}",
                    )

                elements = [
                    ElementLocation(
                        description=line,
                        bbox=BoundingBox(left=0, top=0, right=100, bottom=20),
                    )
                    for line in lines
                ]
                return VisionResult(
                    success=True,
                    query="extract_text",
                    answer="\n".join(lines),
                    elements=elements,
                    raw_response=f"[local-ocr fallback; upstream: {error or 'none'}]",
                )

        except Exception as e:
            logger.error(f"Local OCR error: {e}")
            return VisionResult(
                success=False,
                query="extract_text",
                error=f"Local OCR error: {e}",
            )

    def _collect_text_elements(self, result: Any) -> list[ElementLocation]:
        """
        从解析后的 JSON 结果中收集文本元素，兼容多种结构形态：

        - dict: {"texts": [{"content"/"text": ..., "bbox": [...]}]}
        - dict: {"texts": ["str1", "str2"]}
        - list: [{"text"/"content": ..., "bbox"/"bbox_2d": [...]}]
        - list: ["str1", "str2"]
        """
        elements: list[ElementLocation] = []

        def _add(text_value: Any, bbox_data: Any = None) -> None:
            text_value = (text_value or "").strip()
            if not text_value or not isinstance(text_value, str):
                return
            if isinstance(bbox_data, (list, tuple)) and len(bbox_data) >= 4:
                try:
                    elements.append(
                        ElementLocation(
                            description=text_value,
                            bbox=BoundingBox(
                                left=int(bbox_data[0]),
                                top=int(bbox_data[1]),
                                right=int(bbox_data[2]),
                                bottom=int(bbox_data[3]),
                            ),
                        )
                    )
                    return
                except (TypeError, ValueError):
                    pass
            # 无有效 bbox：扁平占位
            elements.append(
                ElementLocation(
                    description=text_value,
                    bbox=BoundingBox(left=0, top=0, right=100, bottom=20),
                )
            )

        items: list[Any] = []
        if isinstance(result, dict):
            texts = result.get("texts", result.get("elements", []))
            if isinstance(texts, list):
                items = texts
            else:
                main_text = result.get("main_text") or result.get("answer")
                if main_text:
                    _add(main_text)
        elif isinstance(result, list):
            items = result

        for item in items:
            if isinstance(item, dict):
                text_value = item.get("text") or item.get("content") or item.get("description")
                bbox_data = item.get("bbox") or item.get("bbox_2d")
                _add(text_value, bbox_data)
            elif isinstance(item, str):
                _add(item)

        return elements

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

            if isinstance(result, list):
                result = next((r for r in result if isinstance(r, dict)), None)

            if not isinstance(result, dict):
                # 宽松回退：解析失败时保留原文，由调用方判断
                logger.debug("verify_action: JSON parse failed, falling back to raw response")
                return VisionResult(
                    success=False,
                    query=f"verify: {action_description}",
                    answer=response.strip(),
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
