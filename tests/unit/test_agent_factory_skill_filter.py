from types import SimpleNamespace

from openkitsune.agents.factory import AgentFactory
from openkitsune.agents.profile import AgentProfile, SkillsMode


class _FakeRegistry:
    def __init__(self, skills):
        self._skills = list(skills)
        self.unregistered: list[str] = []
        self.catalog_hidden: list[str] = []

    def list_all(self, include_disabled: bool = False):
        return list(self._skills)

    def unregister(self, skill_name: str) -> None:
        self.unregistered.append(skill_name)
        self._skills = [skill for skill in self._skills if skill.skill_id != skill_name]

    def set_catalog_hidden(self, skill_name: str, hidden: bool = True) -> bool:
        if hidden:
            self.catalog_hidden.append(skill_name)
        for s in self._skills:
            if s.skill_id == skill_name:
                s.catalog_hidden = hidden
                return True
        return False


class _FakeCatalog:
    def __init__(self) -> None:
        self.invalidated = 0
        self.generated = 0

    def invalidate_cache(self) -> None:
        self.invalidated += 1

    def generate_catalog(self) -> None:
        self.generated += 1


def _tool(name: str) -> dict:
    return {"name": name, "description": name, "input_schema": {"type": "object"}}


def test_inclusive_hides_non_selected_from_catalog():
    """INCLUSIVE mode: non-selected skills are catalog_hidden, not unregistered."""
    registry = _FakeRegistry(
        [
            SimpleNamespace(
                skill_id="plugin-a@duplicate-skill",
                name="duplicate-skill",
                disabled=False,
                catalog_hidden=False,
            ),
            SimpleNamespace(
                skill_id="plugin-b@duplicate-skill",
                name="duplicate-skill",
                disabled=False,
                catalog_hidden=False,
            ),
            SimpleNamespace(
                skill_id="plugin-c@kept-skill",
                name="kept-skill",
                disabled=False,
                catalog_hidden=False,
            ),
        ]
    )
    catalog = _FakeCatalog()
    agent = SimpleNamespace(
        skill_registry=registry,
        skill_catalog=catalog,
        _update_skill_tools=lambda: None,
    )
    profile = AgentProfile(
        id="worker",
        name="Worker",
        skills=["plugin-c@kept-skill"],
        skills_mode=SkillsMode.INCLUSIVE,
    )

    AgentFactory._apply_skill_filter(agent, profile)

    assert registry.unregistered == [], "INCLUSIVE should not unregister skills"
    assert sorted(registry.catalog_hidden) == [
        "plugin-a@duplicate-skill",
        "plugin-b@duplicate-skill",
    ]
    assert len(registry._skills) == 3, "All skills should remain in registry"
    assert catalog.invalidated == 1
    assert catalog.generated == 1


def test_inclusive_empty_skills_hides_all_non_essential():
    """INCLUSIVE with empty skills list: all non-essential skills are catalog_hidden."""
    registry = _FakeRegistry(
        [
            SimpleNamespace(
                skill_id="list-skills", name="list-skills", disabled=False, catalog_hidden=False
            ),
            SimpleNamespace(
                skill_id="my-external-skill",
                name="my-external-skill",
                disabled=False,
                catalog_hidden=False,
            ),
            SimpleNamespace(
                skill_id="another-skill", name="another-skill", disabled=False, catalog_hidden=False
            ),
        ]
    )
    catalog = _FakeCatalog()
    agent = SimpleNamespace(
        skill_registry=registry,
        skill_catalog=catalog,
        _update_skill_tools=lambda: None,
    )
    profile = AgentProfile(
        id="content-creator",
        name="自媒体达人",
        skills=[],
        skills_mode=SkillsMode.INCLUSIVE,
    )

    AgentFactory._apply_skill_filter(agent, profile)

    assert registry.unregistered == [], "INCLUSIVE should not unregister skills"
    assert sorted(registry.catalog_hidden) == [
        "another-skill",
        "my-external-skill",
    ]
    assert len(registry._skills) == 3, "All skills should remain in registry"
    assert catalog.invalidated == 1
    assert catalog.generated == 1


def test_exclusive_unregisters_blacklisted_skills():
    """EXCLUSIVE mode: blacklisted skills are fully unregistered."""
    registry = _FakeRegistry(
        [
            SimpleNamespace(
                skill_id="skill-a", name="skill-a", disabled=False, catalog_hidden=False
            ),
            SimpleNamespace(
                skill_id="skill-b", name="skill-b", disabled=False, catalog_hidden=False
            ),
            SimpleNamespace(
                skill_id="skill-c", name="skill-c", disabled=False, catalog_hidden=False
            ),
        ]
    )
    catalog = _FakeCatalog()
    agent = SimpleNamespace(
        skill_registry=registry,
        skill_catalog=catalog,
        _update_skill_tools=lambda: None,
    )
    profile = AgentProfile(
        id="worker",
        name="Worker",
        skills=["skill-b"],
        skills_mode=SkillsMode.EXCLUSIVE,
    )

    AgentFactory._apply_skill_filter(agent, profile)

    assert registry.unregistered == ["skill-b"]
    assert registry.catalog_hidden == [], "EXCLUSIVE should not use catalog_hidden"
    assert len(registry._skills) == 2
    assert catalog.invalidated == 1
    assert catalog.generated == 1


def test_tool_inclusive_empty_keeps_only_independent_basics_when_extensions_empty():
    agent = SimpleNamespace(
        _tools=[
            _tool("run_shell"),
            _tool("web_search"),
            _tool("call_mcp_tool"),
            _tool("list_skills"),
            _tool("get_tool_info"),
        ]
    )
    profile = AgentProfile(
        id="locked",
        name="Locked",
        tools=[],
        tools_mode="inclusive",
        mcp_servers=[],
        mcp_mode="inclusive",
        skills=[],
        skills_mode=SkillsMode.INCLUSIVE,
    )

    AgentFactory._apply_tool_filter(agent, profile)

    assert [tool["name"] for tool in agent._tools] == ["get_tool_info"]


def test_tool_inclusive_preserves_mcp_gateway_when_mcp_servers_are_selected():
    agent = SimpleNamespace(
        _tools=[
            _tool("run_shell"),
            _tool("call_mcp_tool"),
            _tool("list_mcp_servers"),
            _tool("get_mcp_instructions"),
            _tool("web_search"),
            _tool("get_tool_info"),
        ]
    )
    profile = AgentProfile(
        id="mcp-worker",
        name="MCP Worker",
        tools=["filesystem"],
        tools_mode="inclusive",
        mcp_servers=["database"],
        mcp_mode="inclusive",
        skills=[],
        skills_mode=SkillsMode.INCLUSIVE,
    )

    AgentFactory._apply_tool_filter(agent, profile)

    assert [tool["name"] for tool in agent._tools] == [
        "call_mcp_tool",
        "get_mcp_instructions",
        "get_tool_info",
        "list_mcp_servers",
        "run_shell",
    ]


class _FakeMcpCatalog:
    def __init__(self, server_count: int = 2) -> None:
        self.server_count = server_count
        self.clone_calls: list[tuple[list[str], str]] = []

    def clone_filtered(self, server_ids: list[str], *, mode: str = "inclusive"):
        self.clone_calls.append((list(server_ids), mode))
        return _FakeMcpCatalog(server_count=len(server_ids) if mode == "inclusive" else 1)


def test_mcp_inclusive_empty_filters_catalog_to_no_servers():
    catalog = _FakeMcpCatalog()
    agent = SimpleNamespace(mcp_catalog=catalog)
    profile = AgentProfile(
        id="no-mcp",
        name="No MCP",
        mcp_servers=[],
        mcp_mode="inclusive",
    )

    AgentFactory._apply_mcp_filter(agent, profile)

    assert catalog.clone_calls == [([], "inclusive")]
    assert agent.mcp_catalog.server_count == 0
