"""
ToolSearch 工具处理器

参考 CC ToolSearchTool：接受自然语言查询，在所有工具（含延迟加载的）中
搜索匹配项，返回完整 schema，并将发现的工具注册到 discovered 集合，
使其在后续请求中自动以完整 schema 加载。

# ApprovalClass checklist (新增 / 修改工具时必读)
# 1. 在本文件 Handler 类的 TOOLS 列表加新工具名
# 2. 在同 Handler 类的 TOOL_CLASSES 字典加 ApprovalClass 显式声明
#    （或在 agent.py:_init_handlers 的 register() 调用里加 tool_classes={...}）
# 3. 行为依赖参数 → 在 policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
# 详见 docs/policy_v2_research.md §4.21
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens for matching.

    Supports both Latin (a-z0-9_) and CJK characters.
    CJK characters are treated as individual tokens (bigrams for short queries).
    """
    latin = set(re.findall(r"[a-z0-9_]+", text.lower()))
    # Extract CJK characters as individual tokens
    cjk = set(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]+", text))
    # Split CJK runs into individual characters for matching
    cjk_chars = set()
    for run in cjk:
        for ch in run:
            cjk_chars.add(ch)
    return latin | cjk_chars


def _score_tool(query_tokens: set[str], hint: str) -> float:
    """Score a tool against query tokens using token overlap."""
    hint_tokens = _tokenize(hint)
    if not hint_tokens:
        return 0.0
    overlap = query_tokens & hint_tokens
    return len(overlap) / max(len(query_tokens), 1)


class ToolSearchHandler:
    """ToolSearch 工具处理器"""

    TOOLS = ["tool_search"]
    TOOL_CLASSES = {"tool_search": ApprovalClass.READONLY_SEARCH}

    # 会话级查询缓存：同一关键词重复搜索时直接返回上次结果并提示，
    # 避免模型"失忆重搜"同一查询（对标 Hermes：重复搜索无新信息即视为浪费）。
    # key = (会话作用域, 规范化后的 query)；value = (首次命中结果 JSON 列表, 命中工具名列表)
    # 注意：必须是实例级（__init__ 中初始化）——类属性会在多个会话/Agent 之间
    # 共享，导致别的会话命中原会话缓存后跳过 discovery 注册，破坏渐进式工具披露。

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self._query_cache: dict[tuple[str, str], tuple[list[dict], list[str]]] = {}

    @staticmethod
    def _session_scope(agent: "Agent") -> str:
        """会话作用域：优先取当前 session 的 conversation_id/id，取不到用进程级作用域。"""
        session = getattr(agent, "_current_session", None)
        for attr in ("conversation_id", "id"):
            value = getattr(session, attr, None)
            if value:
                return str(value)
        return "global"

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name == "tool_search":
            return await self._search(params)
        return f"Unknown tool_search tool: {tool_name}"

    async def _search(self, params: dict[str, Any]) -> str:
        query = params.get("query", "").strip()
        if not query:
            return "tool_search requires a 'query' parameter."

        from ..defer_config import build_search_hint

        query_tokens = _tokenize(query)
        if not query_tokens:
            return "Query too short or contains no searchable terms."

        # —— 重复查询检测：同一关键词已搜过 → 直接返回缓存 + 明确提示 ——
        cache_key = (self._session_scope(self.agent), query.strip().lower())
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            cached_results, cached_names = cached
            logger.info(
                "[ToolSearch] repeated query %r → returning cached %d hits %s",
                query,
                len(cached_names),
                cached_names,
            )
            return (
                f"该查询「{query}」已在本次会话搜索过，命中结果不变（见下）。"
                "请勿重复搜索同一关键词；如需其他能力请换用新的关键词。\n\n"
                f"Found {len(cached_results)} tool(s) matching '{query}'.\n"
                "These tools are now available with full parameters:\n\n"
                + json.dumps(cached_results, ensure_ascii=False, indent=2)
            )

        all_tools = getattr(self.agent, "_tools", [])
        if not all_tools:
            return "No tools available."

        scored: list[tuple[float, dict]] = []
        for tool in all_tools:
            name = tool.get("name", "")
            if not name:
                continue
            hint = build_search_hint(tool)
            score = _score_tool(query_tokens, hint)
            # 阈值 0.1 过于宽松：查询含 10 个词时只要 1 个词重叠（10%）即命中，
            # 会把无关工具顶上来，逼着模型反复换词搜索。收紧到 0.25（≥1/4 词重叠）。
            if score >= 0.25:
                scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:MAX_RESULTS]

        if not top:
            return (
                f"No tools found matching '{query}'. "
                "Try different keywords — 不要重复提交相同的查询词。"
            )

        # Register discovered tools for full-schema loading in future turns
        discovered_names = []
        for _, tool in top:
            name = tool.get("name", "")
            if hasattr(self.agent, "_discovered_tools"):
                self.agent._discovered_tools.add(name)
            discovered_names.append(name)

        logger.info(
            "[ToolSearch] query=%r → discovered %d tools: %s",
            query,
            len(discovered_names),
            discovered_names,
        )

        results = []
        for _score, tool in top:
            entry = {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema", {}),
                "category": tool.get("category", ""),
            }
            results.append(entry)

        # 写入会话缓存：命中结果 + 工具名（用于后续重复查询提示）
        self._query_cache[cache_key] = (results, discovered_names)
        header = (
            f"Found {len(results)} tool(s) matching '{query}'.\n"
            "These tools are now available with full parameters:\n\n"
        )
        body = json.dumps(results, ensure_ascii=False, indent=2)
        return header + body


def create_handler(agent: "Agent"):
    handler = ToolSearchHandler(agent)
    return handler.handle
