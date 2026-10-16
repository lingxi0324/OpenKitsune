#!/usr/bin/env python3
"""
图片理解核心模块
基于本地视觉端点（llama.cpp mmproj / OpenAI 兼容）实现图片理解功能
云端 OpenAI GPT-4 Vision 作为显式 fallback（设置 OPENAI_API_KEY + OPENAI_VISION_URL 时启用）
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

# 本地视觉端点约定（与本地化配置文档一致）
LOCAL_VISION_URL = os.environ.get("LOCAL_VISION_URL", "http://127.0.0.1:8221/v1")
LOCAL_VISION_MODEL = os.environ.get("LOCAL_VISION_MODEL", "qwen3.8-35b-a3b")


class ImageUnderstander:
    """图片理解器（本地优先）"""

    def __init__(self, api_key: Optional[str] = None, verbose: bool = False):
        """
        初始化图片理解器

        Args:
            api_key: 视觉端点 API Key（本地端点可省略，云端需要真实 key）
            verbose: 是否显示详细日志
        """
        self.api_key = api_key or "local"
        self.verbose = verbose
        self.local_url = LOCAL_VISION_URL.rstrip("/")
        # 云端 fallback：显式设置 OPENAI_VISION_URL + OPENAI_API_KEY 才启用
        self.cloud_url = os.environ.get("OPENAI_VISION_URL", "https://api.openai.com/v1")
        self.cloud_model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")

    def _encode_image(self, image_path: str) -> str:
        """
        将图片编码为 base64 格式

        Args:
            image_path: 图片路径

        Returns:
            base64 编码的字符串
        """
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _post_json(self, url: str, headers: dict, payload: dict, timeout: int = 180) -> dict:
        """标准库 HTTP POST（消除 requests 依赖）"""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise Exception(f"API 调用失败: {e.code} - {body[:500]}")
        except urllib.error.URLError as e:
            raise Exception(f"网络错误: {e.reason}")

    def _call_api(self, messages: list, max_tokens: int = 2000) -> str:
        """
        调用视觉端点（本地优先，云端显式 fallback）

        Args:
            messages: 消息列表
            max_tokens: 最大返回token数

        Returns:
            API 返回的文本内容
        """
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        data = {
            "model": LOCAL_VISION_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }

        # 本地优先
        url = f"{self.local_url}/chat/completions"
        provider = "local"
        if self.verbose:
            print(f"📡 正在调用本地视觉端点: {url}")
        try:
            result = self._post_json(url, headers, data)
        except Exception as e:
            # 云端显式 fallback（仅当设置了云端 key 时）
            cloud_key = os.environ.get("OPENAI_API_KEY")
            if cloud_key:
                data["model"] = self.cloud_model
                url = f"{self.cloud_url}/chat/completions"
                headers["Authorization"] = f"Bearer {cloud_key}"
                provider = "cloud"
                if self.verbose:
                    print(f"☁️  本地不可达，回退云端: {url}")
                result = self._post_json(url, headers, data)
            else:
                raise Exception(f"本地视觉端点不可达（{url}），且未配置云端 fallback。请先启动本地视觉服务（见 LOCAL_VISION_URL 配置文档）。原始错误: {e}")

        content = result["choices"][0]["message"]["content"]
        if self.verbose:
            print(f"✅ 提供方: {provider}")
        return content

    def describe(self, image_path: str) -> str:
        """
        描述图片内容

        Args:
            image_path: 图片路径

        Returns:
            图片描述文本
        """
        if self.verbose:
            print(f"🖼️  正在描述图片...")

        base64_image = self._encode_image(image_path)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请详细描述这张图片，包括：场景、人物、物体、颜色、氛围等所有可见元素。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        return self._call_api(messages)

    def extract_text(self, image_path: str) -> str:
        """
        提取图片中的文字 (OCR)

        Args:
            image_path: 图片路径

        Returns:
            提取的文字内容
        """
        if self.verbose:
            print(f"🔤 正在提取文字...")

        base64_image = self._encode_image(image_path)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请提取图片中的所有文字，包括标题、正文、标签、logo文字等。如果有手写体，请尽量识别。如果图片中没有文字，请明确说明。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        return self._call_api(messages, max_tokens=3000)

    def identify_objects(self, image_path: str) -> str:
        """
        识别图片中的物体

        Args:
            image_path: 图片路径

        Returns:
            识别出的物体列表
        """
        if self.verbose:
            print(f"🎯 正在识别物体...")

        base64_image = self._encode_image(image_path)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请识别图片中的所有物体和元素，并列出它们。建议以列表形式输出，每个物体加上简短描述。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        return self._call_api(messages)

    def answer_question(self, image_path: str, question: str) -> str:
        """
        针对图片回答问题

        Args:
            image_path: 图片路径
            question: 问题

        Returns:
            问题的答案
        """
        if self.verbose:
            print(f"💬 正在回答问题: {question}")

        base64_image = self._encode_image(image_path)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"请根据图片内容回答这个问题: {question}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        return self._call_api(messages)

    def analyze(self, image_path: str, analysis_type: str = "comprehensive") -> dict:
        """
        综合分析图片

        Args:
            image_path: 图片路径
            analysis_type: 分析类型 (comprehensive/quick/deep)

        Returns:
            分析结果字典
        """
        if self.verbose:
            print(f"🔬 正在进行{analysis_type}分析...")

        base64_image = self._encode_image(image_path)

        if analysis_type == "comprehensive":
            prompt = """
请对这张图片进行全面分析，包括：
1. 【场景描述】整体场景是什么？
2. 【主要物体】列出主要物体和它们的位置
3. 【文字内容】提取所有可见文字
4. 【颜色氛围】主要色调和氛围
5. 【推断信息】根据内容推断可能的主题/用途

请用JSON格式返回：
{
  "description": "场景描述",
  "objects": ["物体1", "物体2", ...],
  "text": "提取的文字",
  "colors": "主要颜色",
  "mood": "氛围描述",
  "推断": "可能的主题/用途"
}
            """
        elif analysis_type == "quick":
            prompt = "请用一句话简单描述这张图片是什么。"
        else:  # deep
            prompt = """
请对这张图片进行深度分析，包括：
- 详细场景描述
- 每个物体的精确位置和特征
- 图片的整体构图和视觉层次
- 可能的隐含信息或象征意义
- 图片的质量和技术特点

请详细回答。
            """

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt.strip()},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ]

        result_text = self._call_api(messages, max_tokens=3000)

        # 尝试解析JSON
        try:
            # 尝试从返回中找到JSON
            if "{" in result_text and "}" in result_text:
                start = result_text.find("{")
                end = result_text.rfind("}") + 1
                json_str = result_text[start:end]
                return json.loads(json_str)
        except:
            pass

        # 如果不是JSON，返回原始文本
        return {"result": result_text, "raw_format": True}
