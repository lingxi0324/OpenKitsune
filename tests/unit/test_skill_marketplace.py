from __future__ import annotations

import json

import pytest

from openkitsune.skills.marketplace import (
    MARKETPLACE_INSTALL_RECORD,
    build_skillhub_download_url,
    installed_marketplace_names,
    installed_marketplace_resource_id,
    normalize_skillhub_response,
    normalize_skillhub_source,
    parse_skillhub_locator,
    resolve_marketplace_install_source,
)


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        "broken json",
        [],
        {},
        {"resource_type": "plugin", "resource_id": "other"},
        {"resource_type": "skill", "resource_id": 123},
        {"resource_type": "skill", "resource_id": ""},
    ],
)
def test_unrelated_or_invalid_manifest_is_not_a_marketplace_install(tmp_path, manifest):
    skill = tmp_path / "SKILL.md"
    skill.write_text("A skill", encoding="utf-8")
    if manifest is not None:
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert installed_marketplace_resource_id(skill) is None


def test_marketplace_identity_survives_skill_directory_rename(tmp_path):
    directory = tmp_path / "renamed-local-skill"
    directory.mkdir()
    (directory / "SKILL.md").write_text("A skill", encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "resource_type": "skill",
                "resource_id": "resource_original",
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    assert installed_marketplace_resource_id(directory / "SKILL.md") == "resource_original"


def test_official_name_prefers_receipt_and_recovers_old_installs_from_matching_history(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    manifest = {"resource_type": "skill", "resource_id": "resource_anki", "version": "1.0.0"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    def job(filename, **overrides):
        data = {
            **manifest,
            "resource_name": "Anki 记忆卡片助手",
            "status": "installed",
            "created_at": 1,
            **overrides,
        }
        (jobs / filename).write_text(json.dumps(data), encoding="utf-8")

    job("success.json")
    job("failed.json", status="failed", resource_name="Wrong failed name", created_at=10)
    job("other-version.json", version="2.0.0", resource_name="Wrong version", created_at=20)
    job("other-resource.json", resource_id="other", resource_name="Wrong resource", created_at=30)
    assert installed_marketplace_names([skill_path], jobs)[str(skill_path)] == "Anki 记忆卡片助手"
    receipt = tmp_path / MARKETPLACE_INSTALL_RECORD
    receipt.write_text(
        json.dumps({**manifest, "resource_name": "Updated formal name"}), encoding="utf-8"
    )
    assert installed_marketplace_names([skill_path], jobs)[str(skill_path)] == "Updated formal name"
    receipt.write_text(
        json.dumps({**manifest, "resource_id": "other", "resource_name": "Wrong receipt"}),
        encoding="utf-8",
    )
    assert installed_marketplace_names([skill_path], jobs)[str(skill_path)] == "Anki 记忆卡片助手"
    (tmp_path / "manifest.json").unlink()
    assert installed_marketplace_names([skill_path], jobs) == {}


def test_skillhub_payload_is_normalized_to_provider_neutral_model() -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "total": 1,
            "skills": [
                {
                    "slug": "demo-skill",
                    "name": "Demo Skill",
                    "description": "Default description",
                    "description_zh": "中文描述",
                    "version": "1.2.3",
                    "ownerName": "Demo Author",
                    "namespace": {
                        "handle": "community_demo",
                        "displayName": "Demo Author",
                    },
                    "category": "dev-programming",
                    "subCategories": [{"key": "testing", "name": "测试"}],
                    "tags": ["python", "testing"],
                    "downloads": 42,
                    "installs": 7,
                    "stars": 3,
                    "verified": True,
                    "labels": {"requires_api_key": "true"},
                    "upstream_url": "https://github.com/example/demo",
                    "homepage": "https://skillhub.cn/skills/community_demo/demo-skill",
                }
            ],
        },
    }

    result = normalize_skillhub_response(payload, page=2, page_size=10)

    assert result["schemaVersion"] == 1
    assert result["provider"] == "skillhub"
    assert result["pagination"] == {"page": 2, "pageSize": 10, "total": 1}
    skill = result["skills"][0]
    assert skill["canonicalId"] == "skillhub:@community_demo/demo-skill"
    assert skill["coordinate"] == {"namespace": "community_demo", "slug": "demo-skill"}
    assert skill["display"]["description"] == "中文描述"
    assert skill["publisher"]["name"] == "Demo Author"
    assert skill["metrics"] == {"downloads": 42, "installs": 7, "stars": 3}
    assert skill["trust"] == {"verified": True, "level": "verified"}
    assert skill["requirements"] == {"requiresApiKey": True}
    assert skill["install"] == {
        "strategy": "registry-zip",
        "locator": "skillhub:@community_demo/demo-skill",
        "version": "1.2.3",
    }
    assert "slug" not in skill
    assert "upstream_url" not in skill


def test_invalid_skillhub_payload_is_not_exposed_to_callers() -> None:
    with pytest.raises(ValueError, match="upstream unavailable"):
        normalize_skillhub_response({"code": 503, "message": "upstream unavailable"})


def test_marketplace_install_descriptor_resolves_to_versioned_locator() -> None:
    source = resolve_marketplace_install_source(
        {
            "strategy": "registry-zip",
            "locator": "skillhub:@community_demo/demo-skill",
            "version": "1.2.3",
        }
    )

    assert source == "skillhub:@community_demo/demo-skill?version=1.2.3"
    locator = parse_skillhub_locator(source)
    assert build_skillhub_download_url(locator) == (
        "https://api.skillhub.cn/api/v1/download"
        "?slug=demo-skill&namespace=community_demo&version=1.2.3"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://skillhub.cn/skills/community_demo/demo-skill",
            "skillhub:@community_demo/demo-skill",
        ),
        ("https://skillhub.cn/skills/demo-skill", "skillhub:demo-skill"),
        (
            "https://api.skillhub.cn/community_demo/demo-skill?v=1.2.3",
            "skillhub:@community_demo/demo-skill?version=1.2.3",
        ),
        (
            "https://api.skillhub.cn/api/v1/download"
            "?slug=demo-skill&namespace=community_demo&version=1.2.3",
            "skillhub:@community_demo/demo-skill?version=1.2.3",
        ),
    ],
)
def test_skillhub_public_urls_normalize_to_canonical_locator(source: str, expected: str) -> None:
    assert normalize_skillhub_source(source) == expected


def test_non_skillhub_url_is_left_for_other_install_providers() -> None:
    assert normalize_skillhub_source("https://github.com/example/demo") is None


@pytest.mark.parametrize(
    "value",
    [
        "skillhub:@missing-slug",
        "skillhub:namespace/slug",
        "skillhub:@namespace/../slug",
        "skillhub:bad slug",
    ],
)
def test_skillhub_locator_rejects_ambiguous_or_unsafe_coordinates(value: str) -> None:
    with pytest.raises(ValueError):
        parse_skillhub_locator(value)
