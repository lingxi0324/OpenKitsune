"""技能/桌面能力"注册可见性"回归测试。

覆盖三块注册面（让 AI 知道能力可用）：
1. ``exposure_level`` frontmatter 解析 → ``SkillMetadata.exposure_level``；
2. 意图相关性注入（``get_intent_catalog``）命中玄学/中医技能（默认开启的
   ``skills_intent_injection`` 是运行时按需可见通道）；
3. 桌面工具进入全局定义面（``BASE_TOOLS`` / ``get_tool_definition``），
   与 ``POWERSHELL_TOOLS`` 同一模式（定义无条件进目录，处理器按平台注册）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openkitsune.skills.parser import SkillMetadata, SkillParser
from openkitsune.skills.loader import SkillLoader
from openkitsune.skills.catalog import SkillCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]

XUANXUE_SKILLS = [
    "nongli-paipan",
    "qimen-diagnosis",
    "taiyi-shenshu",
    "tcm-dual-track",
    "zhenfa-jiugong",
    "ziwei-doushu",
    "bazi-analysis",
    "liushijiazi",
]


# ── 1. exposure_level frontmatter 解析 ──────────────────────────


def test_parser_reads_exposure_level(tmp_path: Path):
    skill_dir = tmp_path / "expo-probe"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: expo-probe
description: exposure probe skill
exposure_level: core
---

body
""".strip(),
        encoding="utf-8",
    )
    parsed = SkillParser().parse_directory(skill_dir)
    assert parsed.metadata.exposure_level == "core"


def test_parser_exposure_level_missing_defaults_empty(tmp_path: Path):
    skill_dir = tmp_path / "no-expo"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: no-expo
description: no exposure field
---

body
""".strip(),
        encoding="utf-8",
    )
    parsed = SkillParser().parse_directory(skill_dir)
    assert parsed.metadata.exposure_level == ""


def test_parser_exposure_level_kebab_alias(tmp_path: Path):
    """``exposure-level`` (kebab) 是 ``exposure_level`` 的别名写法。"""
    skill_dir = tmp_path / "expo-kebab"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: expo-kebab
description: exposure kebab alias probe
exposure-level: core
---

body
""".strip(),
        encoding="utf-8",
    )
    parsed = SkillParser().parse_directory(skill_dir)
    assert parsed.metadata.exposure_level == "core"


# ── 2. 意图相关性注入命中玄学/中医技能 ─────────────────────────


def _load_catalog() -> SkillCatalog:
    loader = SkillLoader()
    loader.load_all(base_path=REPO_ROOT)
    return SkillCatalog(loader.registry)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("帮我排个八字，看运势", {"bazi-analysis", "ziwei-doushu"}),
        ("今天是农历几号", {"nongli-paipan"}),
        ("奇门遁甲看这个病", {"qimen-diagnosis"}),
        ("帮我排紫微斗数命盘", {"ziwei-doushu"}),
    ],
)
def test_intent_catalog_injects_xuanxue_skills(query: str, expected: set[str]):
    """意图注入（默认开启）必须让玄学/中医技能进入模型可见热区。"""
    catalog = _load_catalog()
    out = catalog.get_intent_catalog(query=query, top_k=12, max_tokens=1000, index_mode="count")
    assert expected <= set(XUANXUE_SKILLS) and any(s in out for s in expected)


# ── 3. 桌面工具全局定义面注册 ───────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="desktop tools are Windows-only")
def test_desktop_tools_registered_in_base_tools():
    from openkitsune.tools.definitions import (
        BASE_TOOLS,
        _TOOL_DEFINITIONS_BY_NAME,
        get_tool_definition,
    )

    names = [t["name"] for t in BASE_TOOLS]
    desktop = [n for n in names if n.startswith("desktop_")]
    assert len(desktop) == 14
    assert len(set(desktop)) == len(desktop), "desktop tools must be unique in BASE_TOOLS"

    for tool in (
        "desktop_screenshot",
        "desktop_find_element",
        "desktop_click",
        "desktop_mouse",
        "desktop_type",
        "desktop_press",
        "desktop_key",
        "desktop_hotkey",
        "desktop_scroll",
        "desktop_window",
        "desktop_wait",
        "desktop_inspect",
        "desktop_batch",
        "desktop_macro",
    ):
        assert tool in _TOOL_DEFINITIONS_BY_NAME, f"{tool} missing from tool definitions"
        assert get_tool_definition(tool) is not None, f"{tool} unresolvable via get_tool_definition"


@pytest.mark.skipif(sys.platform != "win32", reason="desktop tools are Windows-only")
def test_desktop_tools_in_catalog_prompt():
    from openkitsune.tools.catalog import ToolCatalog
    from openkitsune.tools.definitions import BASE_TOOLS

    text = ToolCatalog(list(BASE_TOOLS)).get_catalog()
    assert "Desktop (Windows)" in text
    assert "desktop_screenshot" in text
    assert "desktop_macro" in text


def test_desktop_tool_definition_source_matches_runtime():
    """definitions 与运行时 schema 同源：Windows 上两者必须是同一份列表。"""
    if sys.platform != "win32":
        pytest.skip("desktop tools are Windows-only")
    from openkitsune.tools.definitions import DESKTOP_TOOLS as DEF_DESKTOP
    from openkitsune.tools.desktop.tools import DESKTOP_TOOLS as RUNTIME_DESKTOP

    assert DEF_DESKTOP is RUNTIME_DESKTOP
