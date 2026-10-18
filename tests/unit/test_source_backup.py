import json
import zipfile
from pathlib import Path

import pytest

from openkitsune.workspace.source_backup import (
    MANIFEST_FILE,
    create_source_backup,
    default_output_dir,
    list_source_backups,
    restore_source_backup,
)


def _make_project(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("// junk\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "agent.db").write_text("db", encoding="utf-8")
    (root / "workspaces").mkdir()
    (root / "workspaces" / "ws1").mkdir()
    (root / "workspaces" / "ws1" / "memory.db").write_text("db", encoding="utf-8")
    # New root-level files and directories must be picked up without a
    # whitelist update.
    (root / "_audit_lib").mkdir()
    (root / "_audit_lib" / "log_grep.py").write_text("x = 1\n", encoding="utf-8")
    (root / "win_steps.json").write_text("{}", encoding="utf-8")
    # Nested toolchain output stays out.
    (root / "apps" / "setup-center" / "android" / "app" / "build").mkdir(parents=True)
    (root / "apps" / "setup-center" / "android" / "app" / "build" / "out.apk").write_text(
        "apk", encoding="utf-8"
    )


def test_create_and_restore_roundtrip(tmp_path):
    project = tmp_path / "demo-project"
    project.mkdir()
    _make_project(project)
    archives = tmp_path / "archives"

    archive = create_source_backup(project, archives, include_env=False)

    assert archive.exists()
    assert archive.name.startswith("openkitsune-source-demo-project-")
    assert archive.name.endswith(".zip")

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(MANIFEST_FILE))
    assert "src/app.py" in names
    assert "tests/test_app.py" in names
    assert "README.md" in names
    assert "pyproject.toml" in names
    assert "_audit_lib/log_grep.py" in names
    assert "win_steps.json" in names
    assert "node_modules/junk.js" not in names
    assert "data/agent.db" not in names
    assert "workspaces/ws1/memory.db" not in names
    assert "apps/setup-center/android/app/build/out.apk" not in names
    assert ".env" not in names
    assert manifest["kind"] == "source"
    assert manifest["file_count"] == len(names) - 1

    (project / "src" / "app.py").write_text("print('broken')\n", encoding="utf-8")
    (project / "README.md").unlink()

    result = restore_source_backup(archive, project, safety_backup=False)

    assert result["restored_count"] == 6
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert (project / "README.md").read_text(encoding="utf-8") == "# demo\n"


def test_include_env_is_opt_in(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    _make_project(project)

    archive = create_source_backup(project, tmp_path / "archives", include_env=True)

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(MANIFEST_FILE))
    assert ".env" in names
    assert manifest["include_env"] is True


def test_restore_creates_safety_backup_by_default(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    _make_project(project)
    archives = tmp_path / "archives"
    archive = create_source_backup(project, archives)

    (project / "src" / "app.py").write_bytes(b"print('newer')\n")

    result = restore_source_backup(archive, project)

    safety = Path(result["safety_backup"])
    assert safety.exists()
    assert "-pre-restore" in safety.name
    with zipfile.ZipFile(safety) as zf:
        assert zf.read("src/app.py").decode("utf-8") == "print('newer')\n"


def test_restore_rejects_path_traversal(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("ok\n", encoding="utf-8")

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(
            MANIFEST_FILE,
            json.dumps({"kind": "source", "format_version": 1}),
        )
        zf.writestr("../evil.txt", "pwned")

    with pytest.raises(ValueError, match="Unsafe path"):
        restore_source_backup(bad, project, safety_backup=False)
    assert not (tmp_path / "evil.txt").exists()


def test_list_source_backups_returns_manifest(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    _make_project(project)
    archives = tmp_path / "archives"

    first = create_source_backup(project, archives, label="first")
    second = create_source_backup(project, archives, label="second")

    items = list_source_backups(archives, project_id=project.name)

    assert [item["filename"] for item in items[:2]] == [second.name, first.name]
    assert items[0]["manifest"]["label"] == "second"
    assert default_output_dir(project) == project / "backups" / "source"
