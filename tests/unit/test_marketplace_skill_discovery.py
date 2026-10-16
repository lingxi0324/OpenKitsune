import json
from types import SimpleNamespace

import pytest

from openkitsune.skills.catalog import SkillCatalog
from openkitsune.skills.marketplace import MARKETPLACE_INSTALL_RECORD
from openkitsune.skills.parser import SkillParser
from openkitsune.skills.registry import SkillEntry, SkillRegistry
from openkitsune.tools.handlers.skills import SkillsHandler


def entry(sid, official="岗位定制简历", name=None):
    return SkillEntry(
        skill_id=sid,
        name=name or sid,
        description="根据岗位要求调整真实简历",
        marketplace_name=official,
    )


def test_marketplace_name_is_loaded_into_registry_without_changing_identifier(tmp_path):
    directory = tmp_path / "tailored-resume-generator"
    directory.mkdir()
    content = "---\nname: tailored-resume-generator\ndescription: Resume writing\n---\nResume instructions"
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    manifest = {"resource_id": "resume", "resource_type": "skill", "version": "1.0.0"}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    receipt = directory / MARKETPLACE_INSTALL_RECORD
    receipt.write_text(json.dumps({**manifest, "resource_name": "岗位定制简历"}), encoding="utf-8")
    registry = SkillRegistry()
    parsed = SkillParser().parse_directory(directory)
    registry.register(parsed, skill_id=directory.name)
    skill = registry.get("岗位定制简历")
    assert skill is registry.get(directory.name)
    assert skill.name == directory.name
    assert "Resume instructions" in SkillsHandler(
        SimpleNamespace(skill_registry=registry)
    )._get_skill_info({"skill_name": "岗位定制简历"})
    receipt.write_text(json.dumps({**manifest, "resource_name": "新版简历助手"}), encoding="utf-8")
    registry.register(parsed, skill_id=directory.name, force=True)
    assert registry.get("岗位定制简历") is None
    assert registry.get("新版简历助手").skill_id == directory.name
    assert (directory / "SKILL.md").read_text(encoding="utf-8") == content


def test_alias_resolution_refuses_collisions_and_preserves_exact_ids():
    registry = SkillRegistry()
    registry._skills = {"resume-a": entry("resume-a"), "resume-b": entry("resume-b")}
    assert registry.get("岗位定制简历") is None
    assert registry.unregister("岗位定制简历") is False
    assert registry.get("resume-a").skill_id == "resume-a"
    registry._skills["resume-b"].marketplace_name = "resume-a"
    assert registry.get("resume-a").skill_id == "resume-a"
    registry._skills["resume-b"].name = "岗位定制简历"
    assert registry.get("岗位定制简历") is None
    registry.unregister("resume-b")
    assert registry.get("岗位定制简历").skill_id == "resume-a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool", ["get_skill_info", "run_skill_script", "reload_skill", "uninstall_skill"]
)
async def test_ambiguous_tool_calls_return_candidate_ids_without_mutation(tool):
    registry = SkillRegistry()
    registry._skills = {"resume-a": entry("resume-a"), "resume-b": entry("resume-b")}
    handler = SkillsHandler(SimpleNamespace(skill_registry=registry))
    result = await handler.handle(tool, {"skill_name": "岗位定制简历"})
    assert "resume-a" in result and "resume-b" in result
    assert "请明确选择 skill_id" in result
    assert len(registry.list_all()) == 2


def test_catalogs_listing_and_recommendations_expose_official_name_and_id(tmp_path, monkeypatch):
    monkeypatch.setattr(SkillCatalog, "_snapshot_path", staticmethod(lambda: tmp_path / "snapshot.json"))
    registry = SkillRegistry()
    registry._skills = {"tailored-resume-generator": entry("tailored-resume-generator")}
    catalog = SkillCatalog(registry)
    for text in [
        catalog.get_metadata_catalog(),
        catalog.get_grouped_compact_catalog(),
        catalog.get_grouped_compact_catalog(max_tokens=1),
        catalog.get_index_catalog(),
        catalog.generate_catalog(),
        catalog.generate_catalog_budgeted(1),
        catalog.generate_recommendation_hint("请使用岗位定制简历技能"),
        SkillsHandler(SimpleNamespace(skill_registry=registry))._list_skills({}),
    ]:
        assert "岗位定制简历" in text
        assert "tailored-resume-generator" in text
    assert (
        registry.find_relevant("请使用岗位定制简历技能")[0].skill_id == "tailored-resume-generator"
    )
    registry.set_disabled("tailored-resume-generator", True)
    assert registry.find_relevant("请使用岗位定制简历技能") == []
    assert "岗位定制简历" not in catalog.generate_catalog()


def test_disk_catalog_snapshot_tracks_official_name_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(SkillCatalog, "_snapshot_path", staticmethod(lambda: tmp_path / "snapshot.json"))
    registry = SkillRegistry()
    registry._skills = {"resume": entry("resume")}
    assert "岗位定制简历" in SkillCatalog(registry).get_grouped_compact_catalog()
    registry._skills["resume"].marketplace_name = "新版简历助手"
    updated = SkillCatalog(registry).get_grouped_compact_catalog()
    assert "新版简历助手" in updated
    assert "岗位定制简历" not in updated
