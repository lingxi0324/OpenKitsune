#!/usr/bin/env python3
"""本地 PPT 大纲生成器 — 基于本地 LLM（llama.cpp OpenAI 兼容端点）。

从百度千帆 AppBuilder 云端生成迁移为本地模型生成结构化 PPT 大纲 JSON。
无任何外部 API key 依赖。

用法:
    python3 ppt_gen.py generate "Q2季度销售报告" [--slides 12] [--style business] [--language zh]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from local_llm import chat_local_json  # noqa: E402

SYSTEM_PROMPT = (
    "你是一个专业的 PPT 策划师。根据用户给定的主题，生成结构清晰、逻辑严谨的演示文稿大纲。"
    "必须严格输出 JSON，不要输出任何其他文字。JSON 结构如下：\n"
    "{\n"
    '  "title": "演示文稿标题",\n'
    '  "outline": ["整体大纲要点1", "整体大纲要点2", ...],\n'
    '  "slides": [\n'
    '    {"title": "第1页标题", "bullets": ["要点1", "要点2", ...], "notes": "演讲者备注"},\n'
    "    ...\n"
    "  ]\n"
    "}"
)


def build_generate_query(topic: str, slides: int = 0, style: str = "", language: str = "") -> str:
    query = f"请为以下主题生成 PPT 内容：{topic}"
    if slides > 0:
        query += f"，共 {slides} 页幻灯片"
    if style:
        style_names = {
            "business": "商务",
            "academic": "学术",
            "creative": "创意",
            "minimal": "极简",
        }
        query += f"，风格：{style_names.get(style, style)}"
    if language:
        query += f"，语言：{'中文' if language == 'zh' else 'English'}"
    query += "。请为每页提供标题、要点内容和演讲者备注，并在开头给出整体大纲。"
    return query


def main() -> None:
    parser = argparse.ArgumentParser(
        description="本地 PPT 大纲生成器（本地 LLM，无需外部 key）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
        "  python3 ppt_gen.py generate \"Q2季度销售报告\" --slides 12\n"
        "  python3 ppt_gen.py generate \"人工智能科普\" --style academic --language zh",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="生成 PPT 大纲与内容")
    p_gen.add_argument("topic", help="PPT 主题")
    p_gen.add_argument("--slides", type=int, default=0, help="幻灯片页数")
    p_gen.add_argument(
        "--style",
        default="",
        choices=["business", "academic", "creative", "minimal", ""],
        help="PPT 风格",
    )
    p_gen.add_argument("--language", default="", choices=["zh", "en", ""], help="语言")

    args = parser.parse_args()

    if args.command == "generate":
        query = build_generate_query(args.topic, args.slides, args.style, args.language)
        print(f"📡 正在调用本地 LLM 生成大纲（{query[:60]}...）", file=sys.stderr)
        result = chat_local_json(query, system=SYSTEM_PROMPT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
