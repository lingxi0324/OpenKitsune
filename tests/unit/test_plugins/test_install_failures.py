import json
import subprocess

import pytest

from openkitsune.plugins import installer


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(installer, "_resolve_pip_runner", lambda: ("python", []))
    monkeypatch.setattr(installer, "_pip_subprocess_env", lambda _: {})
    calls = []
    results = []

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(cmd, result[0], result[1], "")

    monkeypatch.setattr(installer, "_run_pip_with_progress", run)
    monkeypatch.setattr(installer.subprocess, "run", run)
    return calls, results


@pytest.mark.parametrize("streaming", [True, False])
def test_interrupted_download_retries_once_without_cache(tmp_path, runner, streaming):
    calls, results = runner
    results.extend([(1, "ERROR: Connection broken: IncompleteRead(428516, 46522)"), (0, "ok")])
    assert installer.install_pip_deps(
        tmp_path, {"pip": ["docxtpl"]},
        progress=installer.InstallProgress() if streaming else None, raise_on_error=True,
    )
    assert len(calls) == 2
    assert "--no-cache-dir" not in calls[0]
    assert "--no-cache-dir" in calls[1]


def test_final_failure_retains_cause_after_bounded_retry(tmp_path, runner):
    calls, results = runner
    results.extend([(1, "IncompleteRead(1, 2)"), (1, "IncompleteRead(3, 4)")])
    with pytest.raises(installer.PluginInstallError, match="IncompleteRead\\(3, 4\\)") as caught:
        installer.install_pip_deps(tmp_path, {"pip": ["docxtpl"]}, raise_on_error=True)
    assert caught.value.reason == "dependency_network"
    assert len(calls) == 2


def test_dependency_conflicts_are_not_retried(tmp_path, runner):
    calls, results = runner
    results.append((1, "ERROR: ResolutionImpossible: conflicting dependencies"))
    with pytest.raises(installer.PluginInstallError, match="ResolutionImpossible") as caught:
        installer.install_pip_deps(tmp_path, {"pip": ["docxtpl"]}, raise_on_error=True)
    assert caught.value.reason == "dependency_install"
    assert len(calls) == 1


@pytest.mark.parametrize("exc,reason", [
    (subprocess.TimeoutExpired("pip", 600), "dependency_timeout"),
    (FileNotFoundError("Python executable missing"), "dependency_runtime"),
])
def test_runtime_failures_have_specific_reasons(tmp_path, runner, exc, reason):
    _, results = runner
    results.append(exc)
    with pytest.raises(installer.PluginInstallError) as caught:
        installer.install_pip_deps(tmp_path, {"pip": ["docxtpl"]}, raise_on_error=True)
    assert caught.value.reason == reason


def test_runtime_callers_keep_boolean_failure_contract(tmp_path, runner):
    _, results = runner
    results.append((1, "ERROR: incompatible packages"))
    assert installer.install_pip_deps(tmp_path, {"pip": ["docxtpl"]}) is False


def test_failure_cleanup_does_not_discard_pip_error(tmp_path, runner):
    _, results = runner
    results.append((1, "ERROR: No matching distribution found for missing-package"))
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "id": "demo", "name": "Demo", "version": "1.0.0", "type": "python",
        "entry": "plugin.py", "permissions": [], "requires": {"pip": ["missing-package"]},
    }))
    with pytest.raises(installer.PluginInstallError, match="No matching distribution"):
        installer._finalize_install(plugin_dir)
    assert not plugin_dir.exists()


def test_diagnostics_redact_credentials_before_truncation():
    raw = "x" * 5000 + "\nhttps://user:password123@example.test/package?token=private123\nAuthorization: Bearer abc.def\nERROR: IncompleteRead(1, 2)"
    error = installer.PluginInstallError(raw)
    assert len(str(error)) <= 4000
    assert "password123" not in str(error)
    assert "private123" not in str(error)
    assert "abc.def" not in str(error)
    assert "IncompleteRead" in str(error)
