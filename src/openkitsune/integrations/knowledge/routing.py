"""Turn-level routing policy for configured cloud knowledge bases."""

from __future__ import annotations

from typing import Any


def should_prefer_knowledge(
    *,
    config: dict[str, Any],
    intent: Any,
) -> bool:
    """Apply only the structured intent produced by the prompt compiler model."""
    connectors = config.get("connectors")
    if isinstance(connectors, dict):
        candidates = list(connectors.values())
    elif isinstance(connectors, list):
        candidates = connectors
    else:
        candidates = [config]
    return bool(
        any(
            isinstance(item, dict)
            and item.get("enabled")
            and item.get("prefer_knowledge")
            and item.get("knowledge_bases")
            for item in candidates
        )
        and getattr(intent, "knowledge_lookup", False)
    )


def knowledge_priority_prompt_section() -> str:
    """Build the model-facing routing rule for a knowledge-priority turn."""
    return (
        "\n\n### 知识来源优先级\n"
        "提示词编译模型已将当前请求判定为知识资料查询，且用户已开启“优先使用知识库”。\n"
        "- 必须先调用 `knowledge_search`；若用户询问文件清单，则先调用 `knowledge_list`。\n"
        "- 搜索命中文档后，必须调用 `knowledge_read` 读取正文，再基于正文回答。\n"
        "- 本轮不得使用网页搜索、新闻搜索、网页抓取或浏览器代替知识库。\n"
        "- 如果知识库无结果或正文无法读取，应如实说明，并询问用户是否改为联网查询；"
        "未获得用户明确同意前不要联网。"
    )
