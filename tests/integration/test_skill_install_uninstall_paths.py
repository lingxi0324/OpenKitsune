"""Exercise actual skill files across installation and HTTP uninstallation."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from openkitsune.api.routes import skills
from openkitsune.config import settings
from openkitsune.integrations.marketplace.installer import MarketplaceInstallManager
from openkitsune.setup_center import bridge
from openkitsune.skills import allowlist_io


@pytest.fixture(params=["development", "named-workspace"])
def workspace(request, tmp_path, monkeypatch):
    home = tmp_path / "custom-home"
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(home))
    project = (
        tmp_path / "source-checkout"
        if request.param == "development"
        else home / "workspaces" / "research"
    )
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "project_root", project)
    expected = (
        home / "workspaces" / "default"
        if request.param == "development"
        else project
    )
    assert settings.skills_path == expected / "skills"
    config = project / "data" / "skills.json"
    monkeypatch.setattr(allowlist_io, "_skills_json_path", lambda: config)
    propagate = AsyncMock()
    monkeypatch.setattr(skills, "_propagate", propagate)
    monkeypatch.setattr(skills, "_resolve_agent", lambda request: None)
    app = FastAPI()
    app.include_router(skills.router)
    return SimpleNamespace(
        project=project, root=expected / "skills", config=config,
        propagate=propagate, app=app,
    )


def write_skill(path, *, system=False):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        "---\nname: resume\ndescription: Resume helper\n"
        + ("system: true\n" if system else "")
        + "---\nInstructions\n",
        encoding="utf-8",
    )


async def post(workspace, endpoint, body):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=workspace.app), base_url="http://test"
    ) as client:
        return (await client.post(endpoint, json=body)).json()


@pytest.mark.parametrize("enabled", [True, False])
async def test_marketplace_install_can_be_uninstalled(workspace, tmp_path, enabled):
    source = tmp_path / "package"
    write_skill(source)
    allowlist_io.overwrite_allowlist({"keep"})
    await MarketplaceInstallManager._install_skill(source, "resume", None)
    assert (workspace.root / "resume" / "SKILL.md").is_file()
    write_skill(workspace.root / "keep")
    if not enabled:
        allowlist_io.remove_skill_ids({"resume"})

    # A source checkout (or another workspace) can contain an identically named skill.
    other = workspace.project / "skills" / "resume"
    if other == workspace.root / "resume":
        other = workspace.root.parent.parent / "other" / "skills" / "resume"
    write_skill(other)
    workspace.propagate.reset_mock()

    result = await post(workspace, "/api/skills/uninstall", {"skill_id": "resume"})

    assert result == {"status": "ok", "skill_id": "resume"}
    assert not (workspace.root / "resume").exists()
    assert (workspace.root / "keep" / "SKILL.md").is_file()
    assert (other / "SKILL.md").is_file()
    assert json.loads(workspace.config.read_text())["external_allowlist"] == ["keep"]
    workspace.propagate.assert_awaited_once()
    assert workspace.propagate.await_args.args[1] == "uninstall"


async def test_regular_install_uses_same_workspace(workspace, monkeypatch):
    def install(workspace_dir, url, *, category, emit_result):
        assert bridge._resolve_skills_dir(workspace_dir) == workspace.root
        assert not emit_result
        write_skill(workspace.root / "resume")
        return workspace.root / "resume"

    monkeypatch.setattr(bridge, "install_skill", install)
    allowlist_io.overwrite_allowlist({"keep"})
    result = await post(workspace, "/api/skills/install", {"url": "owner/resume"})
    assert result["status"] == "ok"
    assert result["skill_id"] == "resume"
    result = await post(workspace, "/api/skills/uninstall", {"skill_id": "resume"})
    assert result["status"] == "ok"
    assert not (workspace.root / "resume").exists()


@pytest.mark.parametrize("skill_id", ["missing", ".", "..", "../outside", "system"])
async def test_rejected_uninstall_preserves_files_and_state(workspace, skill_id):
    write_skill(workspace.root / "system", system=True)
    write_skill(workspace.root / "keep")
    write_skill(workspace.root.parent / "outside")
    allowlist_io.overwrite_allowlist({"keep", skill_id})
    before = workspace.config.read_bytes()

    result = await post(workspace, "/api/skills/uninstall", {"skill_id": skill_id})

    assert "error" in result
    assert (workspace.root / "system" / "SKILL.md").is_file()
    assert (workspace.root / "keep" / "SKILL.md").is_file()
    assert (workspace.root.parent / "outside" / "SKILL.md").is_file()
    assert workspace.config.read_bytes() == before
    workspace.propagate.assert_not_awaited()
