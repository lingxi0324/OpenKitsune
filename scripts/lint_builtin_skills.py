#!/usr/bin/env python3
"""Fix-6 — Lint built-in skills for naming-rule compliance.

Run during packaging (or as a pre-commit step) to catch SKILL.md ``name`` /
directory mismatches before they ship to users and pollute ``error.log``.

Usage::

    python scripts/lint_builtin_skills.py [--root <path>] [--strict]

Exit codes:
    0 — all checks passed
    1 — at least one violation found

The script never modifies files — it only reports.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


_SIMPLE = r"[a-z0-9]+(-[a-z0-9]+)*"
_NAMESPACE = rf"{_SIMPLE}/{_SIMPLE}@{_SIMPLE}"
_NAME_PATTERN = re.compile(rf"^({_NAMESPACE}|{_SIMPLE})$")


def _read_yaml_frontmatter(skill_md: Path) -> dict | None:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    raw = text[3:end].strip()
    try:
        data = yaml.safe_load(raw)
    except Exception as e:
        print(f"[YAML PARSE ERROR] {skill_md}: {e}")
        return None
    return data if isinstance(data, dict) else None


def _violations_for_skill(skill_md: Path) -> list[str]:
    issues: list[str] = []
    fm = _read_yaml_frontmatter(skill_md)
    if fm is None:
        issues.append(f"{skill_md} — missing or unparsable YAML frontmatter")
        return issues
    name = (fm.get("name") or "").strip()
    if not name:
        issues.append(f"{skill_md} — frontmatter missing required `name`")
    elif not _NAME_PATTERN.match(name):
        issues.append(
            f"{skill_md} — name {name!r} violates naming rule "
            "(lowercase + hyphens; e.g. 'agent-ui' not 'agent_ui')"
        )

    dir_name = skill_md.parent.name
    if "_" in dir_name:
        issues.append(
            f"{skill_md.parent} — directory name contains '_'; rename to use "
            "hyphens (e.g. 'agent-ui'). Mixed underscore/hyphen will make the "
            "skill loader log 'Failed to load skill' at startup."
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Root containing builtin_skills/ to lint. Default: "
            "src/openkitsune/builtin_skills (relative to repo root)."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (currently all messages are errors).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    root = args.root or (repo_root / "src" / "openkitsune" / "builtin_skills")
    if not root.exists():
        print(f"[lint_builtin_skills] no builtin_skills root at {root} — nothing to lint.")
        return 0

    all_issues: list[str] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        all_issues.extend(_violations_for_skill(skill_md))

    if not all_issues:
        print(f"[lint_builtin_skills] OK — checked {root}")
        return 0

    print(f"[lint_builtin_skills] {len(all_issues)} issue(s) under {root}:")
    for issue in all_issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
