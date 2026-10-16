from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.integrations.marketplace.installer import (
    MarketplaceInstallError,
    MarketplaceInstallManager,
)
from openkitsune.skills.categories import CategoryRegistry
from openkitsune.skills.category_store import CategoryStore
from openkitsune.skills.loader import SkillLoader


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "openkitsune.skills.allowlist_io._skills_json_path",
        lambda: tmp_path / "data" / "skills.json",
    )
    source = tmp_path / "package"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: build-game\ndescription: Build browser games.\n---\nGame instructions.",
        encoding="utf-8",
    )
    store = CategoryStore(tmp_path / "data" / "skills" / "skill_categories.json")
    registry = CategoryRegistry()
    registry.set_store(store)
    agent = SimpleNamespace(skill_category_registry=registry)
    monkeypatch.setattr("openkitsune.api.routes.skills._resolve_agent", lambda request: agent)
    propagate = AsyncMock()
    monkeypatch.setattr("openkitsune.api.routes.skills._propagate", propagate)
    monkeypatch.setattr(
        "openkitsune.integrations.marketplace.installer.settings",
        SimpleNamespace(skills_path=tmp_path / "skills", project_root=tmp_path),
    )
    return source, store, registry, propagate


@pytest.mark.asyncio
async def test_first_install_imports_category_and_upgrade_preserves_local_choices(installation):
    source, store, registry, propagate = installation
    install = MarketplaceInstallManager._install_skill
    await install(source, "build-game", None, resource_category="test")
    target = source.parent / "skills" / "build-game"
    assert store.get_binding("build-game") == "test"
    assert CategoryStore(store.path).get_binding("build-game") == "test"
    loaded = SkillLoader(category_registry=registry).load_skill(target)
    assert loaded is not None and loaded.metadata.category == "test"
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert propagate.await_count == 1

    store.bind_skill("build-game", "我的创作")
    await install(source, "build-game", None, resource_category="New market category")
    assert store.get_binding("build-game") == "我的创作"
    assert not store.has_category("New market category")

    store.unbind_skill("build-game")
    await install(source, "build-game", None, resource_category="test")
    assert store.get_binding("build-game") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category", [None, "", {}, "system", "Uncategorized", "bad\nlabel", "中" * 41]
)
async def test_optional_or_invalid_category_does_not_break_install(installation, category):
    source, store, _, _ = installation
    await MarketplaceInstallManager._install_skill(
        source,
        "build-game",
        None,
        resource_category=category,
    )
    assert (source.parent / "skills/build-game/SKILL.md").is_file()
    assert store.get_bindings() == {}


@pytest.mark.asyncio
async def test_first_install_does_not_replace_existing_binding(installation):
    source, store, _, _ = installation
    store.bind_skill("build-game", "保留分类")
    await MarketplaceInstallManager._install_skill(
        source, "build-game", None, resource_category="test"
    )
    assert store.get_binding("build-game") == "保留分类"
    assert not store.has_category("test")


@pytest.mark.asyncio
async def test_market_category_cannot_claim_system_category(installation):
    source, store, registry, _ = installation
    registry.upsert("Core", system_readonly=True)
    await MarketplaceInstallManager._install_skill(
        source, "build-game", None, resource_category="Core"
    )
    assert not store.has_category("Core")


@pytest.mark.asyncio
async def test_category_write_failure_rolls_back_first_install(installation, monkeypatch):
    source, store, _, propagate = installation
    store.create_category("Keep")
    before = store.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("openkitsune.utils.atomic_io.atomic_json_write", fail)
    with pytest.raises(MarketplaceInstallError, match="marketplace_skill_install_failed"):
        await MarketplaceInstallManager._install_skill(
            source,
            "build-game",
            None,
            resource_category="test",
        )
    assert not (source.parent / "skills/build-game").exists()
    assert store.path.read_bytes() == before
    assert not store.has_category("test")
    propagate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", [None, "test"])
async def test_category_survives_preparation_and_job_reload(tmp_path, category):
    manager = MarketplaceInstallManager(tmp_path)
    payload = {
        "id": "category-job",
        "resource_id": "resource-game",
        "resource_name": "Game",
        "resource_slug": "build-game",
        "resource_type": "skill",
        "version_id": "version-game",
        "version": "1.0.0",
        "digest_sha256": "a" * 64,
        "signature": "signature",
        "size_bytes": 1,
        "download_url": "https://marketplace.openkitsune.cn/file",
        "verification": {"algorithm": "Ed25519", "digest_algorithm": "SHA-256"},
    }
    if category is not None:
        payload["resource_category"] = category
    manager._authorize = AsyncMock(return_value=payload)
    prepared = await manager.prepare("b" * 64, "https://marketplace.openkitsune.cn", account=object())
    assert prepared["resource_category"] == category
    assert (
        MarketplaceInstallManager(tmp_path)._jobs["category-job"]["resource_category"] == category
    )
