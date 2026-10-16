from __future__ import annotations

from pathlib import Path

from openkitsune.skills.parser import SkillParser

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_SKILLS_ROOT = ROOT / "skills" / "system"
RETIRED_SYSTEM_SKILLS = {
    "browser-status",
    "find-skills",
    "generate-agents-md",
    "platform-guide",
    "tool-routing",
}


def _system_skill_directories() -> list[Path]:
    return sorted(
        path
        for path in SYSTEM_SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def test_system_skill_directories_have_complete_executable_metadata() -> None:
    parser = SkillParser()
    tool_names: list[str] = []

    for skill_dir in _system_skill_directories():
        metadata = parser.parse_file(skill_dir / "SKILL.md").metadata
        assert metadata.system is True, f"{skill_dir.name} is not marked as a system skill"
        assert metadata.handler, f"{skill_dir.name} has no handler"
        assert metadata.tool_name, f"{skill_dir.name} has no tool-name"
        tool_names.append(metadata.tool_name)

    assert len(tool_names) == len(set(tool_names)), "system tool-name values must be unique"


def test_retired_system_skills_are_not_shipped() -> None:
    shipped = {path.name for path in _system_skill_directories()}
    assert shipped.isdisjoint(RETIRED_SYSTEM_SKILLS)


def test_publish_agent_maps_to_agent_hub_handler() -> None:
    metadata = SkillParser().parse_file(SYSTEM_SKILLS_ROOT / "publish-agent" / "SKILL.md").metadata

    assert metadata.system is True
    assert metadata.handler == "agent_hub"
    assert metadata.tool_name == "publish_agent"
