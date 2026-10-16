#!/usr/bin/env python3
"""本地 OCR 共享模块（rapidocr_onnxruntime，纯本地推理）。

供 baidu-paddleocr-doc / baidu-paddleocr-text 技能调用，
输出与百度 OCR API 同构（words_result / words_result_num），便于调用方无缝切换。

环境变量:
    USE_CLOUD_OCR=1   强制走云端（配合 BAIDU_OCR_AK/SK）
    LOCAL_OCR_BACKEND 保留扩展位（当前仅 rapidocr）
"""

import os
import sys
import tempfile
import urllib.request


def _download(url: str) -> str:
    """下载 URL 图片到临时文件，返回本地路径。"""
    suffix = ".img"
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        if url.lower().endswith(ext):
            suffix = ext
            break
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp.name, "wb") as f:
        f.write(resp.read())
    return tmp.name


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def local_ocr(image_input: str) -> dict:
    """本地 OCR 推理（rapidocr_onnxruntime）。

    Args:
        image_input: 本地图片路径或 http(s) URL

    Returns:
        百度同构结果: {"words_result": [{"words": ...}], "words_result_num": N, "provider": "local"}
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise RuntimeError(
            "本地 OCR 引擎未安装。请先执行: pip install rapidocr_onnxruntime"
            "（或设置 BAIDU_OCR_AK/BAIDU_OCR_SK 走云端）"
        )

    is_url = image_input.startswith("http://") or image_input.startswith("https://")
    local_path = _download(image_input) if is_url else image_input

    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"文件不存在: {local_path}")

    try:
        engine = RapidOCR()
        result, _elapse = engine(local_path)
    finally:
        if is_url:
            _cleanup(local_path)

    words = []
    if result:
        # result: list of [box, text, score]
        for item in result:
            text = str(item[1]).strip()
            if text:
                words.append({"words": text})

    return {
        "words_result": words,
        "words_result_num": len(words),
        "provider": "local",
        "note": "本地 rapidocr_onnxruntime 推理",
    }


def local_ocr_doc(image_input: str) -> dict:
    """本地文档识别（文字识别 + 按置信度排序），输出百度 doc_analysis 同构。"""
    base = local_ocr(image_input)
    return {
        "results": [{"words": w["words"]} for w in base["words_result"]],
        "results_num": base["words_result_num"],
        "provider": "local",
        "note": "本地模式：文档结构/表格还原请配置百度 key 走云端（doc_analysis_office）",
    }
