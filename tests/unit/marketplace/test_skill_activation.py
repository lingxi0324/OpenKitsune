from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
)
from openkitsune.skills import allowlist_io
from openkitsune.skills.loader import SkillLoader


@pytest.mark.asyncio
async def test_installed_skill_api_exposes_persisted_marketplace_identity(installation):
    from openkitsune.api.routes.skills import _build_skills_list_response

    source, loader = installation
    original_content = (source / "SKILL.md").read_bytes()
    await MarketplaceInstallManager._install_skill(
        source,
        "demo",
        None,
        marketplace_manifest={
            "resource_id": "resource_demo",
            "resource_type": "skill",
            "version": "1.0.0",
        },
        resource_name="Official Demo Name",
    )
    # Even disabled resources are installed. Re-scan disk as a fresh page load does.
    allowlist_io.overwrite_allowlist(set())
    result = await _build_skills_list_response(None)
    demo = next(skill for skill in result["skills"] if skill["skill_id"] == "demo")
    assert demo["marketplace_resource_id"] == "resource_demo"
    assert demo["marketplace_name"] == "Official Demo Name"
    assert demo["name"] == "demo"
    installed_path = Path(loader.registry.get("demo").skill_path)
    assert installed_path.read_bytes() == original_content
    assert demo["enabled"] is False

    await MarketplaceInstallManager._install_skill(
        source,
        "demo",
        None,
        marketplace_manifest={
            "resource_id": "resource_demo",
            "resource_type": "skill",
            "version": "2.0.0",
        },
        resource_name="Updated Official Name",
    )
    updated = await _build_skills_list_response(None)
    demo = next(skill for skill in updated["skills"] if skill["skill_id"] == "demo")
    assert demo["marketplace_name"] == "Updated Official Name"
    assert installed_path.read_bytes() == original_content


@pytest.fixture
def installation(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    source = tmp_path / "package"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A test skill.\n---\nTest instructions.",
        encoding="utf-8",
    )
    monkeypatch.setattr(allowlist_io, "_skills_json_path", lambda: tmp_path / "skills.json")
    monkeypatch.setattr(
        "openkitsune.integrations.marketplace.installer.settings",
        SimpleNamespace(skills_path=skills, project_root=tmp_path),
    )
    monkeypatch.setattr(SkillLoader, "discover_skill_directories", lambda self, base: [skills])
    loader = SkillLoader()
    agent = SimpleNamespace(skill_loader=loader, skill_registry=loader.registry)
    monkeypatch.setattr("openkitsune.api.routes.skills._resolve_agent", lambda request: agent)

    async def propagate(*args):
        loader.load_all(tmp_path)
        _, allowlist = allowlist_io.read_allowlist()
        loader.prune_external_by_allowlist(loader.compute_effective_allowlist(allowlist))

    monkeypatch.setattr("openkitsune.api.routes.skills._propagate", propagate)
    return source, loader


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [set(), {"other-skill"}, None])
async def test_first_install_is_enabled_and_loaded_before_success(installation, initial):
    source, loader = installation
    if initial is not None:
        allowlist_io.overwrite_allowlist(initial)
    enabled, restart = await MarketplaceInstallManager._install_skill(source, "demo", None)
    assert enabled and not restart
    assert loader.registry.get("demo") is not None
    assert not loader.registry.get("demo").disabled
    path, allowlist = allowlist_io.read_allowlist()
    if initial is None:
        assert allowlist is None and not path.exists()
    else:
        assert allowlist == initial | {"demo"}


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_reinstall_preserves_user_switch(installation, enabled):
    source, loader = installation
    await MarketplaceInstallManager._install_skill(source, "demo", None)
    selected = {"other-skill", "demo"} if enabled else {"other-skill"}
    allowlist_io.overwrite_allowlist(selected)
    result, restart = await MarketplaceInstallManager._install_skill(source, "demo", None)
    assert result is enabled
    assert not restart
    assert allowlist_io.read_allowlist()[1] == selected
    assert (loader.registry.get("demo") is not None) is enabled


@pytest.mark.asyncio
async def test_default_disabled_skill_is_enabled_without_enabling_other_defaults(installation):
    source, _ = installation
    skills = source.parent / "skills"
    for slug in ("ordinary", "algorithmic-art"):
        target = skills / slug
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes((source / "SKILL.md").read_bytes())
    enabled, restart = await MarketplaceInstallManager._install_skill(source, "code-review", None)
    assert enabled and not restart
    assert allowlist_io.read_allowlist()[1] == {"ordinary", "code-review"}


@pytest.mark.asyncio
async def test_activation_write_failure_does_not_report_success(installation, monkeypatch):
    source, _ = installation
    allowlist_io.overwrite_allowlist({"other-skill"})

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(allowlist_io, "_atomic_write_json", fail)
    with pytest.raises(MarketplaceInstallError, match="marketplace_skill_install_failed"):
        await MarketplaceInstallManager._install_skill(source, "demo", None)
    assert not (source.parent / "skills" / "demo").exists()
    assert allowlist_io.read_allowlist()[1] == {"other-skill"}


@pytest.mark.asyncio
async def test_missing_runtime_load_requires_restart(installation, monkeypatch):
    source, _ = installation
    monkeypatch.setattr("openkitsune.api.routes.skills._propagate", AsyncMock())
    enabled, restart = await MarketplaceInstallManager._install_skill(source, "demo", None)
    assert enabled and restart


def test_default_seed_does_not_overwrite_explicit_user_allowlist(installation):
    allowlist_io.overwrite_allowlist({"user-choice"})
    allowlist_io.upsert_skill_ids({"demo"}, default_allowlist={"other-default"})
    assert allowlist_io.read_allowlist()[1] == {"user-choice", "demo"}


@pytest.mark.asyncio
async def test_install_result_survives_job_reload(installation):
    source, _ = installation
    archive = source.parent / "skill.zip"
    with ZipFile(archive, "w") as package:
        package.write(source / "SKILL.md", "SKILL.md")
    root = source.parent / "marketplace"
    manager = MarketplaceInstallManager(root)
    job = {
        "id": "activation-job",
        "resource_type": "skill",
        "resource_slug": "demo",
        "status": "installed",
    }
    job["restart_required"] = await manager._install(job, archive, None)
    manager._write(job)
    restored = await MarketplaceInstallManager(root).get(job["id"])
    assert restored["skill_enabled"] is True
    assert restored["restart_required"] is False
