"""Contracts for package-owned prompt assets used by the prompt builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from openkitsune.core.policy_v2.prompt_hardening import TOOL_RESULT_HARDENING_RULES
from openkitsune.prompt import builder

PROMPT_ROOT = Path(__file__).resolve().parents[2] / "src" / "openkitsune" / "prompts"


@pytest.mark.parametrize(
    ("constant", "relative_path"),
    [
        ("_ALWAYS_ON_RULES", "core/always_on.md"),
        ("_EXTENDED_RULES", "core/extended.md"),
        ("_INFO_SOURCE_HONESTY_SECTION", "core/source_honesty.md"),
        ("_ASK_MODE_RULES", "modes/ask.md"),
        ("_AGENT_MODE_RULES", "modes/agent.md"),
        ("_PLAN_MODE_RULES", "modes/plan.md"),
        ("_MEMORY_SYSTEM_GUIDE", "memory/guide.md"),
        ("_MEMORY_SYSTEM_GUIDE_COMPACT", "memory/guide_compact.md"),
        ("_TOOLS_GUIDE", "tools/guide.md"),
    ],
)
def test_builder_constant_matches_packaged_asset(constant: str, relative_path: str) -> None:
    expected = (PROMPT_ROOT / relative_path).read_text(encoding="utf-8").strip()

    assert getattr(builder, constant) == expected


def test_safety_section_combines_asset_with_runtime_hardening_rules() -> None:
    safety = (PROMPT_ROOT / "core" / "safety.md").read_text(encoding="utf-8").strip()

    assert safety + "\n" + TOOL_RESULT_HARDENING_RULES == builder._SAFETY_SECTION


@pytest.mark.parametrize(
    ("mode", "relative_path"),
    [("ask", "modes/ask.md"), ("agent", "modes/agent.md"), ("plan", "modes/plan.md")],
)
def test_mode_rules_use_the_canonical_asset(mode: str, relative_path: str) -> None:
    expected = (PROMPT_ROOT / relative_path).read_text(encoding="utf-8").strip()

    assert builder.build_mode_rules(mode) == expected


def test_prompt_asset_loader_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid prompt asset path"):
        builder._load_prompt_asset("../identity/SOUL.md")


def test_legacy_mode_prompt_directory_is_empty_or_absent() -> None:
    legacy_dir = Path(builder.__file__).resolve().parent / "modes"

    assert not legacy_dir.exists() or not any(legacy_dir.iterdir())
