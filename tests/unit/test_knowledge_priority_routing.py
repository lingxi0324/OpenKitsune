from __future__ import annotations

from types import SimpleNamespace

from openkitsune.agent.core import Agent
from openkitsune.core.intent_analyzer import (
    INTENT_ANALYZER_SYSTEM,
    IntentAnalyzer,
    _parse_intent_output,
)
from openkitsune.integrations import knowledge as knowledge_module
from openkitsune.integrations.knowledge.routing import (
    knowledge_priority_prompt_section,
    should_prefer_knowledge,
)


def _config(*, preferred: bool = True) -> dict:
    return {
        "enabled": True,
        "prefer_knowledge": preferred,
        "knowledge_bases": [{"id": "kb-1", "name": "产品资料"}],
    }


def test_priority_uses_prompt_compiler_knowledge_intent():
    intent = SimpleNamespace(knowledge_lookup=True)

    assert should_prefer_knowledge(config=_config(), intent=intent)


def test_priority_does_not_infer_from_generic_intent_categories():
    generic_query = SimpleNamespace(
        intent=SimpleNamespace(value="query"),
        task_type="question",
        knowledge_lookup=False,
    )
    generic_analysis = SimpleNamespace(
        intent=SimpleNamespace(value="task"),
        task_type="analysis",
        knowledge_lookup=False,
    )

    assert not should_prefer_knowledge(config=_config(), intent=generic_query)
    assert not should_prefer_knowledge(config=_config(), intent=generic_analysis)


def test_priority_requires_user_switch_and_selected_knowledge_base():
    intent = SimpleNamespace(knowledge_lookup=True)

    assert not should_prefer_knowledge(config=_config(preferred=False), intent=intent)
    assert not should_prefer_knowledge(
        config={**_config(), "knowledge_bases": []},
        intent=intent,
    )


def test_prompt_compiler_output_controls_knowledge_lookup_without_keyword_fallback():
    selected = _parse_intent_output(
        """
intent: task
task_type: analysis
goal: 查询并概括BL0939专业资料
tool_hints: [Knowledge]
memory_keywords: [BL0939]
capability_scope: [none]
knowledge_lookup: true
""",
        "arbitrary user text",
    )
    rejected = _parse_intent_output(
        """
intent: query
task_type: question
goal: 回答一般问题
tool_hints: []
memory_keywords: []
capability_scope: [none]
knowledge_lookup: false
""",
        "查一下BL0939的资料，给我概括一下",
    )

    assert selected.knowledge_lookup is True
    assert should_prefer_knowledge(config=_config(), intent=selected)
    assert rejected.knowledge_lookup is False
    assert not should_prefer_knowledge(config=_config(), intent=rejected)


class _SequenceCompilerBrain:
    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.calls = 0

    async def compiler_think(self, **_kwargs):
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return SimpleNamespace(content=output, compiler_source="compiler-test")


async def test_invalid_narrative_output_is_retried_as_strict_yaml():
    brain = _SequenceCompilerBrain(
        (
            "该请求本质上是知识问答，因此 intent 是 query，"
            "但需要 knowledge_lookup=true，因为需要查询专业资料。"
        ),
        """intent: query
task_type: analysis
goal: summarize the configured professional source
tool_hints: [Knowledge]
memory_keywords: [target, specifications]
capability_scope: [none]
knowledge_lookup: true""",
    )

    result = await IntentAnalyzer(brain).analyze("arbitrary user text with no routing vocabulary")

    assert brain.calls == 2
    assert result.intent.value == "query"
    assert result.knowledge_lookup is True
    assert result.tool_hints == ["Knowledge"]
    assert should_prefer_knowledge(config=_config(), intent=result)


async def test_two_invalid_compiler_outputs_fail_closed_without_knowledge_inference():
    invalid = "intent 是 query，knowledge_lookup=true，但没有输出 YAML。"
    brain = _SequenceCompilerBrain(invalid, invalid)

    result = await IntentAnalyzer(brain).analyze("arbitrary user text with no routing vocabulary")

    assert brain.calls == 2
    assert result.knowledge_lookup is False
    assert result.compiler_fallback_reason == "compiler_output_invalid"
    assert not should_prefer_knowledge(config=_config(), intent=result)


def test_intent_prompt_has_no_domain_specific_knowledge_example():
    assert "BL0939" not in INTENT_ANALYZER_SYSTEM


def test_priority_prompt_requires_search_then_read_and_no_automatic_web_fallback():
    prompt = knowledge_priority_prompt_section()

    assert "knowledge_search" in prompt
    assert "knowledge_read" in prompt
    assert "未获得用户明确同意前不要联网" in prompt


def test_agent_priority_overrides_web_hint_and_requires_a_tool(monkeypatch):
    monkeypatch.setattr(knowledge_module, "knowledge_config_path", lambda _root: "config.json")
    monkeypatch.setattr(knowledge_module, "load_ima_config", lambda _path: _config())
    agent = Agent.__new__(Agent)
    intent = SimpleNamespace(
        intent=SimpleNamespace(value="task"),
        task_type="action",
        tool_hints=["Web Search"],
        requires_tools=False,
        force_tool=False,
        evidence_recommended=False,
        knowledge_lookup=True,
    )

    active = agent._configure_knowledge_priority_turn("查一下BL0939的资料", intent)

    assert active is True
    assert intent.requires_tools is True
    assert intent.force_tool is True
    assert intent.tool_hints == ["knowledge_search"]
    assert agent._knowledge_priority_status == "pending"


def test_effective_tools_hide_network_sources_during_priority_turn():
    agent = Agent.__new__(Agent)
    agent._tools = [
        {"name": "knowledge_search", "category": "Knowledge"},
        {"name": "knowledge_read", "category": "Knowledge"},
        {"name": "web_search", "category": "Web Search"},
        {"name": "browser_navigate", "category": "Browser"},
    ]
    agent._is_sub_agent_call = False
    agent._agent_tool_names = set()
    agent._current_intent = SimpleNamespace(requires_tools=True, force_tool=True)
    agent._current_user_message = "查一下BL0939的资料"
    agent._selfcheck_allowed_tools = None
    agent._cron_disabled_tools = None
    agent._discovered_tools = {"web_search", "browser_navigate"}
    agent._intent_promoted_tools = set()
    agent._knowledge_priority_active = True
    agent._get_raw_context_window = lambda: 0

    tools = {tool["name"]: tool for tool in agent._effective_tools}

    assert tools["knowledge_search"].get("_promoted") is True
    assert tools["knowledge_read"].get("_promoted") is True
    assert tools["web_search"].get("_deferred") is True
    assert tools["browser_navigate"].get("_deferred") is True
