from pathlib import Path

from scripts.build_cache_key import INPUTS, fingerprint


def test_cache_inputs_track_only_the_desktop_binary() -> None:
    assert set(INPUTS) == {"rust"}
    assert "apps/setup-center/src-tauri/src" in INPUTS["rust"]
    assert "src/openkitsune" not in INPUTS["rust"]
    assert "src/openkitsune/optional_modules.json" in INPUTS["rust"]


def test_rust_cache_tracks_frontend_assets_embedded_by_tauri() -> None:
    assert "apps/setup-center/src" in INPUTS["rust"]
    assert "apps/setup-center/package-lock.json" in INPUTS["rust"]
    assert "apps/setup-center/vite.config.ts" in INPUTS["rust"]


def test_fingerprints_are_stable_sha256_values() -> None:
    for kind in INPUTS:
        value = fingerprint(kind)
        assert len(value) == 64
        assert int(value, 16) >= 0


def test_all_declared_single_file_inputs_exist() -> None:
    root = Path(__file__).parents[2]
    for inputs in INPUTS.values():
        for value in inputs:
            path = root / value
            assert path.exists(), value
