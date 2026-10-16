from __future__ import annotations

from pathlib import Path

from openkitsune import optional_assets
from scripts.prepare_optional_assets import _python_wheel_artifacts, parse_playwright_dry_run


def test_optional_asset_mirror_override_joins_feature_path(monkeypatch) -> None:
    monkeypatch.setenv("OPENKITSUNE_OPTIONAL_ASSET_MIRROR", "https://mirror.example/root/")

    mirror = optional_assets.resolve_optional_asset_mirror(
        "browser.chromium",
        strategy="playwright_download_host",
        mirror_path="optional/playwright",
    )

    assert mirror is not None
    assert mirror.base_url == "https://mirror.example/root/optional/playwright"


def test_optional_asset_mirror_uses_matching_manifest_entry(monkeypatch) -> None:
    monkeypatch.delenv("OPENKITSUNE_OPTIONAL_ASSET_MIRROR", raising=False)
    monkeypatch.setenv("OPENKITSUNE_OPTIONAL_ASSET_MANIFEST", "https://assets.example/api.json")
    monkeypatch.setattr(
        optional_assets,
        "_fetch_manifest",
        lambda url: {
            "features": {
                "browser.chromium": {
                    "strategy": "playwright_download_host",
                    "mirror_base_url": "https://cdn.example/optional/playwright/",
                }
            }
        },
    )

    mirror = optional_assets.resolve_optional_asset_mirror(
        "browser.chromium",
        strategy="playwright_download_host",
        mirror_path="unused",
    )

    assert mirror is not None
    assert mirror.base_url == "https://cdn.example/optional/playwright"


def test_parse_playwright_dry_run_collects_primary_and_fallback_urls() -> None:
    output = """Chrome for Testing 148.0 (playwright chromium v1223)
  Install location: /tmp/chromium-1223
  Download url:        https://cdn.playwright.dev/builds/cft/148.0/linux64/chrome.zip

FFmpeg (playwright ffmpeg v1011)
  Install location: /tmp/ffmpeg-1011
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1011/ffmpeg-linux.zip
  Download fallback 1: https://playwright.download.prss.microsoft.com/dbazure/download/playwright/builds/ffmpeg/1011/ffmpeg-linux.zip

Winldd (playwright winldd v1007)
  Install location: /tmp/winldd-1007
"""

    artifacts = parse_playwright_dry_run(output)

    assert [item["component"] for item in artifacts] == ["chromium", "ffmpeg"]
    assert len(artifacts[1]["sources"]) == 2
    assert artifacts[1]["revision"] == "1011"


def test_python_wheel_provider_resolves_all_configured_platforms() -> None:
    feature = {
        "package": "playwright",
        "mirror_path": "optional/python/playwright",
        "platforms": {
            "windows-x64": "win_amd64.whl",
            "macos-arm64": "macosx_11_0_arm64.whl",
            "linux-arm64": "manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
        },
    }

    provider_version, artifacts = _python_wheel_artifacts(
        feature, Path(__file__).parents[2] / "uv.lock"
    )

    assert provider_version == "1.60.0"
    assert {item["platform"] for item in artifacts} == set(feature["platforms"])
    assert all(len(item["sha256"]) == 64 for item in artifacts)
