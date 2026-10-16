import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from openkitsune.plugins import installer


def test_pip_output_arrives_before_process_exit():
    received = threading.Event()

    class Progress(installer.InstallProgress):
        def update(self, *args, **kwargs):
            super().update(*args, **kwargs)
            if kwargs.get("dependency") == "python_docx":
                received.set()

    progress = Progress()
    command = [
        sys.executable,
        "-u",
        "-c",
        "import time; print('Downloading python_docx-1.2.0-py3-none-any.whl (1 MB)'); "
        "time.sleep(1); print('Installing collected packages: python-docx')",
    ]
    with ThreadPoolExecutor() as pool:
        future = pool.submit(installer._run_pip_with_progress, command, os.environ.copy(), progress)
        assert received.wait(5)
        assert not future.done(), "Progress must arrive while pip is still running"
        result = future.result(timeout=5)
    assert result.returncode == 0
    assert progress.snapshot()["stage"] == "dependency_installing"
    assert progress.snapshot()["dependency"] == "python-docx"


def test_silent_process_times_out_and_is_reaped(monkeypatch):
    processes = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        proc = original(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    with pytest.raises(subprocess.TimeoutExpired):
        installer._run_pip_with_progress(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            os.environ.copy(),
            installer.InstallProgress(),
            timeout=0.1,
        )
    assert processes[0].poll() is not None


def test_timeout_also_stops_dependency_build_children(tmp_path):
    psutil = pytest.importorskip("psutil")
    pid_path = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        installer._run_pip_with_progress(
            [sys.executable, "-c", script],
            os.environ.copy(),
            installer.InstallProgress(),
            timeout=1,
        )
    child_pid = int(pid_path.read_text())
    assert (
        not psutil.pid_exists(child_pid)
        or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    )


@pytest.mark.parametrize(
    "line",
    [
        "Downloading https://user:secret@example.test/private.whl",
        "Collecting https://user:secret@example.test/private.whl",
        "ERROR: token=secret at C:/Users/private/name",
        "Installing collected packages: name, https://example.test?token=secret",
    ],
)
def test_progress_never_forwards_raw_pip_output(line):
    progress = installer.InstallProgress()
    installer._pip_progress_line(line, progress)
    assert progress.snapshot()["dependency"] == ""
    assert "secret" not in str(progress.snapshot())


def test_dependency_failure_is_reported_and_preserves_output():
    result = installer._run_pip_with_progress(
        [sys.executable, "-u", "-c", "import sys; print('ERROR: failed dependency'); sys.exit(7)"],
        os.environ.copy(),
        installer.InstallProgress(),
    )
    assert result.returncode == 7
    assert "failed dependency" in installer._pip_output_excerpt(result)


def test_local_install_passes_progress_into_dependency_runner(tmp_path, monkeypatch):
    import json

    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "progress-demo",
                "name": "Demo",
                "version": "1.0.0",
                "type": "python",
                "entry": "plugin.py",
                "requires": {"pip": ["docxtpl"]},
            }
        )
    )
    (source / "plugin.py").write_text("pass")
    progress = installer.InstallProgress()

    def run(cmd, env, received, *, timeout):
        assert received is progress
        assert 0 < timeout <= 600
        assert "docxtpl" in cmd and env["PYTHONUNBUFFERED"] == "1"
        installer._pip_progress_line("Collecting docxtpl", received)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "_run_pip_with_progress", run)
    result = installer.install_from_path(source, tmp_path / "plugins", progress=progress)
    assert result == "progress-demo"
    assert progress.snapshot()["dependency"] == "docxtpl"
