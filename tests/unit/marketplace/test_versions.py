import json
import shutil
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from openkitsune.config import settings
from openkitsune.integrations.marketplace.installed import inspect_installation
from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
)
from openkitsune.skills import allowlist_io


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "project_root", tmp_path / "project")
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path / "custom-home"))
    manager = MarketplaceInstallManager(tmp_path)
    payload = {
        "id": "instruction",
        "resource_id": "resource-resume",
        "resource_name": "Resume",
        "resource_slug": "resume",
        "resource_type": "skill",
        "version_id": "version-2",
        "version": "2.0.0",
        "digest_sha256": "a" * 64,
        "signature": "signature",
        "size_bytes": 10,
        "download_url": "https://marketplace.openkitsune.cn/package.zip",
        "verification": {"algorithm": "Ed25519", "digest_algorithm": "SHA-256"},
    }
    manager._authorize = AsyncMock(side_effect=lambda *a, **kw: dict(payload))
    manager._report = AsyncMock(return_value=True)
    return manager, payload


def put_skill(version="1.0.0", *, resource_id="resource-resume", root=None):
    target = (root or settings.skills_path) / "resume"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        "---\nname: resume\ndescription: Resume helper\n---\nOriginal content",
        encoding="utf-8",
    )
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "resource_id": resource_id,
                "resource_type": "skill",
                "version": version,
            }
        ),
        encoding="utf-8",
    )
    return target


async def prepare(manager):
    return await manager.prepare("a" * 64, "https://marketplace.openkitsune.cn", account=object())


@pytest.mark.parametrize(
    "current,requested,action",
    [
        ("1.0.0", "1.0.0", "already_installed"),
        ("1.0.0", "2.0.0", "upgrade"),
        ("1.10.0", "1.9.0", "downgrade"),
        ("1.0.0rc1", "1.0.0", "upgrade"),
        ("unknown", "1.0.0", "replace"),
    ],
)
async def test_preview_uses_installed_identity_and_semantic_version(
    env, current, requested, action
):
    manager, payload = env
    target = put_skill(current)
    payload["version"] = requested
    before = (target / "SKILL.md").read_bytes()
    allowlist_io.overwrite_allowlist({"other"})
    result = await prepare(manager)
    assert result["install_action"] == action
    assert result["installed_version"] == current
    assert not any(key.startswith("_installation_") for key in result)
    assert result["status"] == ("installed" if action == "already_installed" else "ready")
    assert (target / "SKILL.md").read_bytes() == before
    assert allowlist_io.read_allowlist()[1] == {"other"}
    assert not manager._tasks


async def test_same_version_never_downloads_and_reports_idempotently(env):
    manager, payload = env
    put_skill(payload["version"])
    state = "claimed"

    async def report(job, status, **extra):
        nonlocal state
        if state == "claimed" and status == "installed":
            return False
        state = status
        return True

    manager._report = AsyncMock(side_effect=report)
    manager._run = AsyncMock()
    result = await prepare(manager)
    assert result["already_installed"] is True
    assert state == "installed"
    assert [call.args[1] for call in manager._report.await_args_list] == [
        "installed",
        "installing",
        "installed",
    ]
    await manager.confirm(result["id"], None, account=object())
    manager._run.assert_not_awaited()


async def test_upgrade_requires_confirmation(env):
    manager, _ = env
    put_skill()
    manager._run = AsyncMock()
    preview = await prepare(manager)
    manager._run.assert_not_awaited()
    result = await manager.confirm(preview["id"], None, account=object())
    assert result["status"] == "downloading"
    await manager._tasks[preview["id"]]
    manager._run.assert_awaited_once()


async def test_downgrade_cannot_be_forced_by_calling_confirm(env):
    manager, _ = env
    put_skill("3.0.0")
    manager._run = AsyncMock()
    preview = await prepare(manager)
    result = await manager.confirm(preview["id"], None, account=object())
    assert result["install_action"] == "downgrade"
    assert result["status"] == "ready"
    manager._run.assert_not_awaited()


async def test_changed_preview_requires_another_confirmation(env):
    manager, _ = env
    put_skill()
    preview = await prepare(manager)
    put_skill("1.5.0")
    manager._run = AsyncMock()
    result = await manager.confirm(preview["id"], None, account=object())
    assert result["status"] == "ready"
    assert result["installed_version"] == "1.5.0"
    manager._run.assert_not_awaited()


async def test_uninstall_and_other_workspace_do_not_leave_false_installed_state(env):
    manager, payload = env
    target = put_skill(payload["version"])
    shutil.rmtree(target)
    put_skill(payload["version"], root=settings.project_root / "skills")
    result = await prepare(manager)
    assert result["install_action"] == "install"


async def test_same_folder_with_different_identity_needs_explicit_replacement(env):
    manager, _ = env
    put_skill("9.0.0", resource_id="unrelated")
    result = await prepare(manager)
    assert result["install_action"] == "replace"
    assert result["installed_version"] is None


async def test_file_change_during_download_cannot_be_silently_overwritten(env):
    manager, _ = env
    put_skill()
    preview = await prepare(manager)
    manager._download = AsyncMock(side_effect=lambda *args: put_skill("3.0.0"))
    manager._verify = lambda *args: None
    manager._install = AsyncMock()
    await manager.confirm(preview["id"], None, account=object())
    task = manager._tasks[preview["id"]]
    await task
    result = await manager.get(preview["id"])
    assert result["failure_code"] == "marketplace_install_state_changed"
    manager._install.assert_not_awaited()


async def test_parallel_install_of_same_resource_is_rejected(env):
    manager, payload = env
    put_skill()
    first = await prepare(manager)
    manager._jobs[first["id"]]["status"] = "downloading"
    payload["id"] = "second-instruction"
    second = await manager.prepare("b" * 64, "https://marketplace.openkitsune.cn", account=object())
    with pytest.raises(MarketplaceInstallError, match="marketplace_install_busy"):
        await manager.confirm(second["id"], None, account=object())


async def test_nested_skill_package_keeps_marketplace_manifest(env, tmp_path, monkeypatch):
    manager, payload = env
    archive = tmp_path / "nested.zip"
    manifest = {"resource_id": payload["resource_id"], "resource_type": "skill", "version": "2.0.0"}
    with ZipFile(archive, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        package.writestr("content/SKILL.md", "---\nname: resume\ndescription: Resume\n---\nBody")
    monkeypatch.setattr("openkitsune.api.routes.skills._propagate", AsyncMock())
    monkeypatch.setattr("openkitsune.api.routes.skills._resolve_agent", lambda request: None)
    await manager._install(payload, archive, None)
    assert inspect_installation(payload)["install_action"] == "already_installed"


@pytest.mark.parametrize(
    "kind,marker", [("plugin", "plugin.json"), ("mcp", "SERVER_METADATA.json")]
)
def test_other_resource_kinds_are_identified_by_resource_id(env, kind, marker):
    _, payload = env
    payload["resource_type"] = kind
    root = (
        settings.project_root / "data" / "plugins" if kind == "plugin" else settings.mcp_config_path
    )
    target = root / "actual-runtime-id"
    target.mkdir(parents=True)
    (target / marker).write_text(json.dumps({"id": "actual-runtime-id"}))
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "resource_id": payload["resource_id"],
                "resource_type": kind,
                "version": "1.0.0",
            }
        )
    )
    assert inspect_installation(payload)["install_action"] == "upgrade"
    if kind == "plugin":
        assert inspect_installation(payload)["plugin_id"] == "actual-runtime-id"


def test_pending_plugin_version_takes_precedence_over_running_version(env):
    _, payload = env
    payload["resource_type"] = "plugin"
    active = settings.project_root / "data" / "plugins" / "resume"
    staged = settings.project_root / "data" / "plugin-updates" / "resume" / "revision"
    for target, version in [(active, "1.0.0"), (staged, "2.0.0")]:
        target.mkdir(parents=True)
        (target / "plugin.json").write_text("{}")
        (target / "manifest.json").write_text(
            json.dumps(
                {
                    "resource_id": payload["resource_id"],
                    "resource_type": "plugin",
                    "version": version,
                }
            )
        )
    (settings.project_root / "data" / "plugin_state.json").write_text(
        json.dumps(
            {
                "plugins": {"resume": {"pending_update_path": str(staged)}},
            }
        )
    )
    result = inspect_installation(payload)
    assert result["install_action"] == "already_installed"
    assert result["installed_pending_restart"] is True


def test_named_workspace_does_not_use_default_workspace_installation(env, monkeypatch):
    _, payload = env
    put_skill(payload["version"])
    monkeypatch.setattr(
        settings, "project_root", settings.openkitsune_home / "workspaces" / "research"
    )
    assert inspect_installation(payload)["install_action"] == "install"


async def test_upgrade_keeps_disabled_choice_and_is_detected_afterward(env, tmp_path, monkeypatch):
    manager, payload = env
    put_skill("1.0.0")
    allowlist_io.overwrite_allowlist({"other"})
    archive = tmp_path / "upgrade.zip"
    with ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                {
                    "resource_id": payload["resource_id"],
                    "resource_type": "skill",
                    "version": "2.0.0",
                }
            ),
        )
        package.writestr("SKILL.md", "---\nname: resume\ndescription: Resume\n---\nNew body")
    monkeypatch.setattr("openkitsune.api.routes.skills._propagate", AsyncMock())
    monkeypatch.setattr("openkitsune.api.routes.skills._resolve_agent", lambda request: None)
    await manager._install(payload, archive, None)
    assert allowlist_io.read_allowlist()[1] == {"other"}
    assert payload["skill_enabled"] is False
    assert inspect_installation(payload)["installed_version"] == "2.0.0"
