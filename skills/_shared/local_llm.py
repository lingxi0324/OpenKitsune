#!/usr/bin/env python3
"""本地 LLM 共享调用模块（llama.cpp OpenAI 兼容端点，标准库实现）。

供 baidu-ppt-gen 等技能调用本地文本模型生成内容。

环境变量:
    LOCAL_LLM_URL    本地 LLM 端点（默认 http://127.0.0.1:8220/v1）
    LOCAL_LLM_MODEL  模型名（默认 qwen3.6-35b-a3b，llama.cpp 不校验 model 字段）
    LOCAL_LLM_TIMEOUT 超时秒数（默认 300）
"""

import json
import os
import urllib.error
import urllib.request

LOCAL_LLM_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8220/v1").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3.6-35b-a3b")


def chat_local(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: int = 0,
) -> str:
    """调用本地 LLM，返回文本内容。

    Args:
        prompt: 用户消息
        system: 系统提示（可选）
        temperature: 采样温度
        max_tokens: 最大生成长度
        timeout: 超时秒数（0 用环境变量 LOCAL_LLM_TIMEOUT，默认 300）

    Returns:
        LLM 返回文本

    Raises:
        RuntimeError: 端点不可达或返回异常
    """
    if timeout <= 0:
        timeout = int(os.environ.get("LOCAL_LLM_TIMEOUT", "300"))

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": LOCAL_LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{LOCAL_LLM_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"本地 LLM 端点返回 {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"本地 LLM 端点不可达（{LOCAL_LLM_URL}）。"
            f"请确认 llama-server 已在 {LOCAL_LLM_URL} 提供服务。原始错误: {e.reason}"
        )

    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"本地 LLM 返回格式异常: {str(result)[:500]}")


def chat_local_json(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> dict:
    """调用本地 LLM 并解析 JSON 返回。

    Raises:
        RuntimeError: JSON 解析失败
    """
    text = chat_local(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"本地 LLM 未返回 JSON: {text[:300]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"本地 LLM JSON 解析失败: {e}，原文: {text[start : end + 1][:300]}")
