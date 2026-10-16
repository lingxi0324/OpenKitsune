from __future__ import annotations

import sys

from openkitsune.runtime_channel_deps import (
    _parse_pip_progress_line,
    _purge_incompatible_websockets,
    _run_pip_command,
    ensure_channel_dependencies,
)


def test_channel_deps_no_enabled_channels_is_ok(monkeypatch):
    monkeypatch.setattr("openkitsune.runtime_channel_deps.inject_module_paths_runtime", lambda: None)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.patch_simplejson_jsondecodeerror", lambda logger=None: False
    )

    result = ensure_channel_dependencies(workspace_env={})

    assert result["status"] == "ok"
    assert result["installed"] == []


def test_channel_deps_packaged_mode_rejects_frozen_sys_executable(monkeypatch):
    monkeypatch.setattr("openkitsune.runtime_channel_deps.inject_module_paths_runtime", lambda: None)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.patch_simplejson_jsondecodeerror", lambda logger=None: False
    )
    monkeypatch.setattr("openkitsune.runtime_channel_deps.IS_FROZEN", True)
    monkeypatch.setattr("openkitsune.runtime_channel_deps.get_app_python_executable", lambda: None)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.get_python_executable", lambda: sys.executable
    )
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.CHANNEL_DEPS",
        {"feishu": [("definitely_missing_openkitsune_dep", "definitely-missing-openkitsune-dep")]},
    )

    result = ensure_channel_dependencies(workspace_env={"FEISHU_ENABLED": "true"})

    assert result["status"] == "error"
    assert "托管 Python" in result["message"]
    assert result["missing"] == ["definitely-missing-openkitsune-dep"]


def test_purge_incompatible_websockets_removes_16_keeps_15(tmp_path):
    """``_purge_incompatible_websockets`` 只清 ``websockets-1[6-9]/2x.dist-info``，
    保留 15.x dist-info、保留 websockets 真实包目录、绝不动其它无关 dist-info。
    """
    (tmp_path / "websockets-16.0.dist-info").mkdir()
    (tmp_path / "websockets-15.0.1.dist-info").mkdir()
    (tmp_path / "websockets-17.5.2.dist-info").mkdir()
    (tmp_path / "websockets").mkdir()
    (tmp_path / "websockets" / "__init__.py").write_text("# package", encoding="utf-8")
    (tmp_path / "lark_oapi-1.6.5.dist-info").mkdir()
    (tmp_path / "dingtalk_stream-0.24.3.dist-info").mkdir()

    removed = _purge_incompatible_websockets(tmp_path)

    assert sorted(removed) == ["websockets-16.0.dist-info", "websockets-17.5.2.dist-info"]
    assert not (tmp_path / "websockets-16.0.dist-info").exists()
    assert not (tmp_path / "websockets-17.5.2.dist-info").exists()
    assert (tmp_path / "websockets-15.0.1.dist-info").exists()
    assert (tmp_path / "websockets" / "__init__.py").exists()
    assert (tmp_path / "lark_oapi-1.6.5.dist-info").exists()
    assert (tmp_path / "dingtalk_stream-0.24.3.dist-info").exists()


def test_purge_incompatible_websockets_missing_dir_is_noop(tmp_path):
    """目标目录不存在时不应抛错，返回空列表。"""
    removed = _purge_incompatible_websockets(tmp_path / "does-not-exist")
    assert removed == []


def test_pip_raw_progress_exposes_current_download_eta(monkeypatch):
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.time.monotonic", lambda: next(clock)
    )
    state: dict = {"current_package": "lark-oapi"}

    started = _parse_pip_progress_line(
        "Downloading https://example.test/lark_oapi.whl (10 MB)", state
    )
    progress = _parse_pip_progress_line("Progress 50 of 100", state)

    assert started == {
        "phase": "downloading",
        "current_package": "lark-oapi",
        "current_artifact": "lark_oapi.whl",
    }
    assert progress is not None
    assert progress["percent"] == 50.0
    assert progress["eta_seconds"] == 2
    assert progress["percent_scope"] == "current_download"


def test_pip_installing_phase_clears_stale_package_and_reports_batch_size():
    state = {"current_package": "typing_extensions"}

    progress = _parse_pip_progress_line(
        "Installing collected packages: certifi, typing_extensions, lark-oapi",
        state,
    )

    assert progress == {
        "phase": "installing",
        "current_package": None,
        "package_count": 3,
        "installing_packages": ["certifi", "typing_extensions", "lark-oapi"],
    }
    assert state["current_package"] is None


def test_streaming_pip_runner_reports_intermediate_phases():
    updates: list[dict] = []
    command = [
        sys.executable,
        "-c",
        (
            "print('Collecting lark-oapi', flush=True); "
            "print('Downloading https://example.test/lark.whl (100 bytes)', flush=True); "
            "print('Progress 100 of 100', flush=True); "
            "print('Installing collected packages: lark-oapi', flush=True); "
            "print('Successfully installed lark-oapi', flush=True)"
        ),
    ]

    result = _run_pip_command(
        command,
        env={},
        timeout=10,
        extra={},
        progress_fn=updates.append,
        packages=["lark-oapi"],
        source_label="test source",
    )

    assert result.returncode == 0
    assert {update["phase"] for update in updates} >= {
        "resolving",
        "downloading",
        "installing",
        "complete",
    }
    installing = next(update for update in updates if update["phase"] == "installing")
    assert installing["current_package"] is None
    assert installing["package_count"] == 1


def test_ensure_channel_deps_returns_install_errors(monkeypatch, tmp_path):
    """模拟 pip 始终失败的场景，验证返回值中 ``errors`` 透传逐包错误尾巴。"""

    monkeypatch.setattr("openkitsune.runtime_channel_deps.inject_module_paths_runtime", lambda: None)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.patch_simplejson_jsondecodeerror",
        lambda logger=None: False,
    )
    monkeypatch.setattr("openkitsune.runtime_channel_deps.IS_FROZEN", False)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.get_app_python_executable", lambda: sys.executable
    )
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.get_python_executable", lambda: sys.executable
    )
    monkeypatch.setattr("openkitsune.runtime_channel_deps.get_channel_deps_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.apply_runtime_pip_environment",
        lambda **_: {},
    )
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.resolve_pip_index",
        lambda: {"url": "https://example.invalid/simple/", "trusted_host": "example.invalid"},
    )
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps._probe_python_runtime",
        lambda *a, **kw: (True, ""),
    )
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.CHANNEL_DEPS",
        {
            "feishu": [
                (
                    "definitely_missing_openkitsune_dep_for_test",
                    "definitely-missing-openkitsune-dep-for-test",
                )
            ]
        },
    )

    import subprocess as _sp

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not find a version that satisfies the requirement xyz"

    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.subprocess.run",
        lambda *a, **kw: _Result(),
    )
    # 让 TimeoutExpired 仍可被 except 捕获
    monkeypatch.setattr(
        "openkitsune.runtime_channel_deps.subprocess.TimeoutExpired", _sp.TimeoutExpired
    )

    result = ensure_channel_dependencies(workspace_env={"FEISHU_ENABLED": "true"})

    assert result["status"] == "error"
    assert result["missing"] == ["definitely-missing-openkitsune-dep-for-test"]
    assert "errors" in result
    assert "definitely-missing-openkitsune-dep-for-test" in result["errors"]
    assert (
        "Could not find a version" in result["errors"]["definitely-missing-openkitsune-dep-for-test"]
    )
