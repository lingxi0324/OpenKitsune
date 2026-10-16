import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
DRY_RUN = ROOT / ".github" / "workflows" / "release-dryrun.yml"
MOBILE = ROOT / ".github" / "workflows" / "mobile.yml"
PREPARE = ROOT / ".github" / "actions" / "desktop-build-prepare" / "action.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH = ROOT / ".github" / "workflows" / "publish-release.yml"
TAURI_CONFIG = ROOT / "apps" / "setup-center" / "src-tauri" / "tauri.conf.json"
LOCAL_TAURI_CONFIG = (
    ROOT / "apps" / "setup-center" / "src-tauri" / "tauri.local-build.conf.json"
)
LOCAL_FULL_TAURI_CONFIG = (
    ROOT / "apps" / "setup-center" / "src-tauri" / "tauri.local-full-build.conf.json"
)
LOCAL_PARALLEL_TAURI_CONFIG = (
    ROOT / "apps" / "setup-center" / "src-tauri" / "tauri.local-parallel-build.conf.json"
)
FULL_BUILD_SCRIPTS = (ROOT / "build" / "build_full.ps1", ROOT / "build" / "build_full.sh")
WINDOWS_BUILD_SCRIPTS = (
    ROOT / "build" / "build_core.ps1",
    ROOT / "build" / "build_full.ps1",
    ROOT / "build" / "build_parallel.ps1",
)
POSIX_BUILD_SCRIPTS = (ROOT / "build" / "build_core.sh", ROOT / "build" / "build_full.sh")


def test_release_workflows_never_clobber_existing_assets() -> None:
    for path in (RELEASE, MOBILE):
        source = path.read_text(encoding="utf-8")
        assert "gh release upload" in source
        assert "--clobber" not in source


def test_release_workflows_enforce_release_contract() -> None:
    release_source = RELEASE.read_text(encoding="utf-8")
    mobile_source = MOBILE.read_text(encoding="utf-8")

    assert "scripts/release_contract.py" in release_source
    assert "scripts/release_contract.py" in mobile_source
    assert "--require-release" in mobile_source
    assert "--expected-commit" in release_source
    assert "--expected-commit" in mobile_source


def test_mobile_release_waits_for_draft_creation_without_an_independent_tag_trigger() -> None:
    release_workflow = yaml.load(RELEASE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    mobile_workflow = yaml.load(MOBILE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    mobile_triggers = mobile_workflow["on"]
    assert "workflow_call" in mobile_triggers
    assert "workflow_dispatch" in mobile_triggers
    assert "push" not in mobile_triggers

    mobile_job = release_workflow["jobs"]["mobile_release"]
    assert mobile_job["needs"] == ["create_release"]
    assert mobile_job["permissions"] == {"contents": "write"}
    assert mobile_job["uses"] == "./.github/workflows/mobile.yml"
    assert mobile_job["secrets"] == "inherit"
    assert "github.event_name == 'push'" in mobile_job["if"]
    assert mobile_job["with"]["release_id"] == "${{ needs.create_release.outputs.release_id }}"

    create_release_job = release_workflow["jobs"]["create_release"]
    assert create_release_job["outputs"]["release_id"] == (
        "${{ steps.resolve_release.outputs.release_id }}"
    )

    release_contract_job = mobile_workflow["jobs"]["release_contract"]
    assert release_contract_job["permissions"] == {"contents": "write"}
    workflow_call_inputs = mobile_workflow["on"]["workflow_call"]["inputs"]
    assert workflow_call_inputs["release_id"] == {
        "description": ("Numeric GitHub Release ID to validate and receive mobile assets."),
        "required": "true",
        "type": "string",
    }

    release_contract_run = next(
        step["run"]
        for step in release_contract_job["steps"]
        if step.get("name") == "Verify immutable mobile assets and tag provenance"
    )
    assert '--release-id "${{ inputs.release_id }}"' in release_contract_run
    assert "--wait-seconds" not in release_contract_run


def test_desktop_packaging_uses_bootstrap_runtime_without_pyinstaller() -> None:
    workflow_sources = [
        path.read_text(encoding="utf-8")
        for path in (
            RELEASE,
            ROOT / ".github" / "workflows" / "release-dryrun.yml",
            ROOT / ".github" / "workflows" / "ci.yml",
        )
    ]
    prepare_source = PREPARE.read_text(encoding="utf-8")

    for source in (*workflow_sources, prepare_source):
        assert "build_backend.py" not in source
        assert "verify_bundled_python_contract.py" not in source
        assert "dist/openkitsune-server" not in source
    assert "prepare_bootstrap_resources.py" in prepare_source


def test_full_builds_compile_each_frontend_target_once() -> None:
    tauri_config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    assert tauri_config["build"]["beforeBuildCommand"] == "npm run build"

    prepare_source = PREPARE.read_text(encoding="utf-8")
    assert prepare_source.count("npm run build:web") == 1
    assert "build_backend.py" not in prepare_source

    ci_source = CI.read_text(encoding="utf-8")
    full_build_job = ci_source.index("tauri_full_build_check:")
    web_build = ci_source.index("npm run build:web", full_build_job)
    bootstrap_build = ci_source.index("prepare_bootstrap_resources.py", web_build)
    assert web_build < bootstrap_build

    for path in FULL_BUILD_SCRIPTS:
        source = path.read_text(encoding="utf-8")
        assert source.count("npm run build:web") == 1
        assert "prepare_bootstrap_resources.py" in source
        assert "build_backend.py" not in source


def test_local_builds_package_a_required_python_seed() -> None:
    for path in WINDOWS_BUILD_SCRIPTS:
        source = path.read_text(encoding="utf-8")
        assert "--commit-resources" in source
        assert "--target-platform win-x64" in source
        assert "--require-python-seed" in source
        assert "--bundles nsis" in source

    core_config = json.loads(LOCAL_TAURI_CONFIG.read_text(encoding="utf-8"))
    full_config = json.loads(LOCAL_FULL_TAURI_CONFIG.read_text(encoding="utf-8"))
    parallel_config = json.loads(LOCAL_PARALLEL_TAURI_CONFIG.read_text(encoding="utf-8"))
    assert core_config["bundle"]["createUpdaterArtifacts"] is False
    assert full_config["bundle"]["createUpdaterArtifacts"] is False
    assert parallel_config["bundle"]["createUpdaterArtifacts"] is False
    assert parallel_config["build"]["beforeBuildCommand"] == ""
    assert full_config["bundle"]["resources"] == [
        "resources/bootstrap/",
        "resources/modules/",
    ]

    for path in POSIX_BUILD_SCRIPTS:
        source = path.read_text(encoding="utf-8")
        assert "--commit-resources" in source
        assert "--auto-detect-target-platform" in source
        assert "--require-python-seed" in source


def test_ci_full_build_parallelizes_independent_packagers() -> None:
    workflow = yaml.load(CI.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["tauri_full_build_check"]["steps"]
    steps_by_name = {step.get("name"): step for step in steps}

    frontend_run = steps_by_name["Build web and desktop frontend assets"]["run"]
    assert "npm run build:web" in frontend_run.splitlines()
    assert "npm run build" in frontend_run.splitlines()

    parallel_run = steps_by_name["Build Rust and docs in parallel"]["run"]
    assert "cargo build --release --features tauri/custom-protocol" in parallel_run
    assert "wait_for_build" in parallel_run
    assert all(
        f'wait_for_build "${name}_pid" {name}' in parallel_run
        for name in ("rust", "docs")
    )
    assert "backend_pid" not in parallel_run
    assert "frontend_pid" not in parallel_run

    tauri_run = steps_by_name["Build Tauri bundles (full build)"]["run"]
    assert "npx tauri bundle" in tauri_run
    assert "npx tauri build" not in tauri_run


def test_desktop_workflows_cache_only_rust_binary() -> None:
    prepare_source = PREPARE.read_text(encoding="utf-8")
    ci_source = CI.read_text(encoding="utf-8")

    for source in (prepare_source, ci_source):
        assert "scripts/build_cache_key.py backend" not in source
        assert "desktop-backend-v2-" not in source
        assert "dist/openkitsune-server" not in source
    assert "python scripts/build_cache_key.py rust" in prepare_source
    assert "desktop-rust-binary-v2-" in prepare_source


def test_release_workflows_compile_then_bundle_without_destroying_rust_cache() -> None:
    for path, job_name in ((RELEASE, "desktop_release"), (DRY_RUN, "dryrun_build")):
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        steps = workflow["jobs"][job_name]["steps"]
        steps_by_name = {step.get("name"): step for step in steps}

        compile_step = steps_by_name["Compile Rust desktop binary"]
        assert "cargo build --release --features tauri/custom-protocol" in compile_step["run"]
        assert "rust_binary_cache_hit != 'true'" in compile_step["if"]

        bundle_run = steps_by_name["Bundle Tauri installers"]["run"]
        assert "npx tauri bundle" in bundle_run
        assert "npx tauri build" not in bundle_run
        assert "Clean Rust release intermediates for current target" not in steps_by_name
        assert "Preflight Rust dependency check" not in steps_by_name
        assert "cargo clean" in compile_step["run"]
        prepare_run = steps_by_name["Prepare Cargo binary for Tauri bundler"]["run"]
        assert "scripts/prepare_tauri_binary.py" in prepare_run


def test_intel_macos_dmg_bypasses_create_dmg() -> None:
    for path in (RELEASE, DRY_RUN):
        source = path.read_text(encoding="utf-8")
        assert 'if [ "${{ matrix.suffix }}" = "macos-x64" ]; then' in source
        assert "Intel runner: using hdiutil directly" in source


def test_desktop_workflows_do_not_upload_pyinstaller_reports() -> None:
    for source in (PREPARE.read_text(encoding="utf-8"), CI.read_text(encoding="utf-8")):
        assert "warn-*.txt" not in source
        assert "xref-*.html" not in source


def test_publish_release_mirrors_optional_assets_before_publishing() -> None:
    source = PUBLISH.read_text(encoding="utf-8")
    mirror_step = source.index("Mirror optional feature assets to Aliyun OSS")
    publish_step = source.index("- name: Publish release")

    assert mirror_step < publish_step
    assert "scripts/prepare_optional_assets.py" in source
    assert "ossutil stat" in source
    assert "optional-assets-inventory.json" in source
    assert "api/optional-assets.json" in source
    assert '"playwright==${PLAYWRIGHT_VERSION}"' in source
    assert "sha256sum --check" in source
    assert "--existing-manifest" in source

    catalog = (ROOT / ".github" / "optional-assets.json").read_text(encoding="utf-8")
    assert '"browser.playwright-runtime"' in catalog


def test_changed_workflow_yaml_is_valid() -> None:
    paths = (
        RELEASE,
        MOBILE,
        DRY_RUN,
        ROOT / ".github" / "workflows" / "ci.yml",
        PREPARE,
        PUBLISH,
    )
    for path in paths:
        assert yaml.safe_load(path.read_text(encoding="utf-8"))
