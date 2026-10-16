import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openkitsune.skills.parser import (
    _GLOBAL_PARSE_CACHE,
    SkillParser,
    invalidate_global_parse_cache,
)


@pytest.fixture
def skill(tmp_path):
    path = tmp_path / "probe" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("---\nname: probe\ndescription: original\n---\n\nbody", encoding="utf-8")
    yield path, tmp_path / "cache.json"
    invalidate_global_parse_cache()


def parse(path, cache):
    parser = SkillParser()
    with parser.persistent_cache(cache):
        return parser.parse_file(path)


def test_new_process_uses_disk_metadata_without_parsing_yaml(skill):
    path, cache = skill
    parse(path, cache)
    code = """
import sys
from pathlib import Path
from openkitsune.skills.parser import SkillParser
parser = SkillParser()
def unexpected(*args):
    raise AssertionError('unchanged metadata should come from disk cache')
parser._parse_metadata_file = unexpected
with parser.persistent_cache(Path(sys.argv[2])):
    result = parser.parse_file(Path(sys.argv[1]))
    assert result.metadata.description == 'original'
    assert not result.body_loaded
    assert result.get_body() == 'body'
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), str(cache)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_changed_source_wins_even_with_preserved_mtime(skill):
    path, cache = skill
    parse(path, cache)
    before = path.stat()
    path.write_text(
        "---\nname: probe\ndescription: changed description\n---\nnew body", encoding="utf-8"
    )
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert parse(path, cache).metadata.description == "changed description"


def test_mutating_caller_metadata_does_not_pollute_disk_cache(skill):
    path, cache = skill
    result = parse(path, cache)
    result.metadata.category = "caller-only"
    _GLOBAL_PARSE_CACHE.clear()  # simulate a fresh interpreter without deleting the disk snapshot
    assert parse(path, cache).metadata.category != "caller-only"


def test_invalid_cache_falls_back_and_explicit_invalidation_removes_snapshot(skill):
    path, cache = skill
    cache.write_text("{broken", encoding="utf-8")
    assert parse(path, cache).metadata.description == "original"
    assert json.loads(cache.read_text(encoding="utf-8"))["version"] == 1
    invalidate_global_parse_cache(path)
    assert not cache.exists()


def test_cache_write_failure_does_not_break_loading(skill, monkeypatch):
    path, cache = skill

    def denied(*args):
        raise PermissionError("read-only cache")

    monkeypatch.setattr("openkitsune.skills.metadata_cache.os.replace", denied)
    assert parse(path, cache).metadata.name == "probe"


def test_cli_discovery_reads_only_matching_distribution_metadata(tmp_path, monkeypatch):
    from openkitsune.skills.loader import SkillLoader

    unrelated = tmp_path / "unrelated-1.0.dist-info"
    unrelated.mkdir()
    (unrelated / "METADATA").write_text("Name: unrelated\nVersion: 1.0\n")
    dist = tmp_path / "cli_anything_demo-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Name: cli-anything-demo\nVersion: 1.0\n")
    (dist / "RECORD").write_text("cli_anything/demo/SKILL.md,,\n")
    skill_dir = tmp_path / "cli_anything/demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n")
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    loader = SkillLoader()
    visited = []
    monkeypatch.setattr(loader, "load_skill", lambda path, **_: visited.append(path))
    original = Path.read_text

    def read(path, *args, **kwargs):
        assert path != unrelated / "METADATA"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    loader._load_cli_anything_skills()
    assert visited == [skill_dir]
