from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from openkitsune.agent import Agent
from openkitsune.agent.brain import Brain
from openkitsune.agent.reasoning import Decision, DecisionType, ReasoningEngine
from openkitsune.core.agent_state import AgentState
from openkitsune.tools.handlers.tool_search import ToolSearchHandler


@pytest.mark.asyncio
async def test_tool_search_promotes_deferred_tool_for_next_main_chat_turn():
    tools = [
        {
            "name": "run_shell",
            "category": "File System",
            "description": "Run a shell command",
            "input_schema": {"type": "object"},
        },
        {
            "name": "web_search",
            "category": "Web Search",
            "description": "Search the web for current information",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    ]
    agent = SimpleNamespace(_tools=tools, _discovered_tools=set())

    before = Agent._stable_main_chat_tool_set(agent, tools)
    assert before[1]["_deferred"] is True

    result = await ToolSearchHandler(agent)._search({"query": "web search"})
    result_schemas = json.loads(result.split("\n\n", 1)[1])
    assert result_schemas[0]["name"] == "web_search"
    assert "web_search" in agent._discovered_tools

    after = Agent._stable_main_chat_tool_set(agent, tools)
    assert after[1].get("_deferred") is None
    assert after[1]["_promoted"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("restrict_after_discovery", [False, True])
async def test_discovered_list_skills_schema_reaches_next_stream_request(
    monkeypatch, tmp_path, restrict_after_discovery
):
    from openkitsune.config import settings
    from openkitsune.core.policy_v2.enums import DecisionAction

    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "supervisor_enabled", False)
    monkeypatch.setattr(
        "openkitsune.core.policy_v2.adapter.evaluate_via_v2",
        lambda *args, **kwargs: SimpleNamespace(action=DecisionAction.ALLOW),
    )
    tools = [
        {
            "name": "tool_search",
            "description": "Discover tools",
            "input_schema": {"type": "object"},
        },
        {
            "name": "list_skills",
            "description": "List installed skills",
            "input_schema": {
                "type": "object",
                "properties": {"category": {"type": "string"}},
            },
        },
    ]

    class SearchAgent:
        _tools = tools

        def __init__(self):
            self._discovered_tools = set()

        @property
        def _effective_tools(self):
            return Agent._stable_main_chat_tool_set(self, self._tools)

    agent = SearchAgent()
    handler = ToolSearchHandler(agent)

    async def execute_tool(**kwargs):
        return await handler.handle(kwargs["tool_name"], kwargs["tool_input"]), None

    executor = SimpleNamespace(
        _agent_ref=agent,
        canonicalize_tool_name=lambda name: name,
        execute_tool_with_policy=AsyncMock(side_effect=execute_tool),
    )
    context = Mock()
    context.estimate_messages_tokens.return_value = 0
    context.estimate_tools_tokens.return_value = 0
    context.get_max_context_tokens.return_value = 0
    context.pre_request_cleanup.side_effect = lambda messages: messages
    context.compress_if_needed = AsyncMock(side_effect=lambda messages, **kwargs: messages)
    context.calculate_context_pressure.return_value = SimpleNamespace(
        messages_tokens=0,
        system_tokens=0,
        tools_tokens=0,
        trigger_tokens=0,
        soft_limit=10000,
        hard_limit=12000,
        max_tokens=16000,
    )
    # 与真实 ContextManager 默认一致：不触发任务恢复卡注入/角色规范化
    context.context_preparation_pending = False
    context.normalize_turn_roles = lambda messages, **_: messages
    brain = SimpleNamespace(model="test", get_current_endpoint_info=lambda: {})
    engine = ReasoningEngine(
        brain=brain,
        tool_executor=executor,
        context_manager=context,
        response_handler=Mock(),
        agent_state=AgentState(),
    )
    monkeypatch.setattr(engine, "_save_react_trace", Mock())
    requests = []

    class RequestsCaptured(BaseException):
        pass

    async def capture_request(messages, **kwargs):
        # Use the real provider-schema conversion, not just the catalog names.
        requests.append(Brain._convert_tools_to_llm(brain, kwargs["tools"]))
        if len(requests) == (3 if restrict_after_discovery else 2):
            raise RequestsCaptured
        if len(requests) == 2:
            # Model a Supervisor restriction after discovery. With no new
            # discovery, the next iteration must keep the restricted tools.
            kwargs["tools"].clear()
        yield {
            "type": "decision",
            "decision": Decision(
                type=DecisionType.TOOL_CALLS,
                tool_calls=[
                    {
                        "id": f"search-{len(requests)}",
                        "name": "tool_search",
                        "input": {"query": "list_skills"},
                    }
                ],
            ),
        }

    monkeypatch.setattr(engine, "_reason_stream_iter", capture_request)
    with pytest.raises(RequestsCaptured):
        async with asyncio.timeout(10):
            async for _ in engine._reason_stream_impl(
                [{"role": "user", "content": "List my installed skills"}],
                tools=agent._effective_tools,
            ):
                pass

    assert executor.execute_tool_with_policy.await_count >= 1
    assert "list_skills" not in {tool.name for tool in requests[0]}
    schemas = {tool.name: tool.input_schema for tool in requests[1]}
    assert "list_skills" in schemas
    assert schemas["list_skills"] == tools[1]["input_schema"]
    if restrict_after_discovery:
        assert requests[2] is None


_DESKTOP_TOOLS = [
    {
        "name": "desktop_screenshot",
        "category": "Desktop",
        "description": "Capture desktop screenshot",
        "input_schema": {"type": "object"},
    },
    {
        "name": "desktop_click",
        "category": "Desktop",
        "description": "Click a desktop element",
        "input_schema": {"type": "object"},
    },
    {
        "name": "web_search",
        "category": "Web Search",
        "description": "Search the web",
        "input_schema": {"type": "object"},
    },
]


def test_desktop_intent_promotes_desktop_action_bundle():
    agent = SimpleNamespace(
        _tools=_DESKTOP_TOOLS,
        _discovered_tools=set(),
        _current_user_message="帮我点击桌面上的 PING 按钮，然后截图确认",
    )

    result = {t["name"]: t for t in Agent._stable_main_chat_tool_set(agent, _DESKTOP_TOOLS)}

    assert result["desktop_screenshot"]["_promoted"] is True
    assert result["desktop_click"]["_promoted"] is True
    assert result["web_search"]["_deferred"] is True


def test_non_desktop_message_keeps_desktop_tools_deferred():
    agent = SimpleNamespace(
        _tools=_DESKTOP_TOOLS,
        _discovered_tools=set(),
        _current_user_message="帮我写一个 Python 函数",
    )

    result = {t["name"]: t for t in Agent._stable_main_chat_tool_set(agent, _DESKTOP_TOOLS)}

    assert result["desktop_screenshot"]["_deferred"] is True
    assert result["desktop_click"]["_deferred"] is True
