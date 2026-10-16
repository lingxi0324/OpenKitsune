"""Fix-6 回归测试：lint_builtin_skills.py 校验逻辑。"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.lint_builtin_skills import _violations_for_skill


def _write_skill(dir_path: Path, frontmatter: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    skill_md = dir_path / "SKILL.md"
    skill_md.write_text(
        textwrap.dedent(f"---\n{frontmatter}\n---\n\nbody"),
        encoding="utf-8",
    )
    return skill_md


def test_valid_hyphen_skill_passes(tmp_path: Path):
    skill_md = _write_skill(
        tmp_path / "agent-ui",
        "name: agent-ui\ndescription: ok",
    )
    assert _violations_for_skill(skill_md) == []


def test_underscore_in_directory_is_flagged(tmp_path: Path):
    skill_md = _write_skill(
        tmp_path / "agent_ui",
        "name: agent-ui\ndescription: ok",
    )
    issues = _violations_for_skill(skill_md)
    assert any("contains '_'" in issue for issue in issues)


def test_underscore_in_name_field_is_flagged(tmp_path: Path):
    skill_md = _write_skill(
        tmp_path / "agent-ui",
        "name: agent_ui\ndescription: ok",
    )
    issues = _violations_for_skill(skill_md)
    assert any("violates naming rule" in issue for issue in issues)


def test_missing_name_is_flagged(tmp_path: Path):
    skill_md = _write_skill(tmp_path / "agent-ui", "description: ok")
    issues = _violations_for_skill(skill_md)
    assert any("missing required `name`" in issue for issue in issues)


def test_missing_frontmatter_is_flagged(tmp_path: Path):
    bad = tmp_path / "agent-ui"
    bad.mkdir()
    md = bad / "SKILL.md"
    md.write_text("no frontmatter at all", encoding="utf-8")
    issues = _violations_for_skill(md)
    assert any("missing or unparsable" in issue for issue in issues)


def test_namespaced_name_is_valid(tmp_path: Path):
    skill_md = _write_skill(
        tmp_path / "browser-automation",
        "name: openkitsune/skills@browser-automation\ndescription: ok",
    )
    assert _violations_for_skill(skill_md) == []
