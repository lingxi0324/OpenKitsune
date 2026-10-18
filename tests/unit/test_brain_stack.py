"""openkitsune-brain 记忆栈伴随启动测试。

覆盖：
- 环境变量解析（开关 / 端口 / 超时 / 工程目录）；
- fusion-memory 与 brain-bus 的启动命令和环境构造；
- 总开关关闭、二进制/脚本缺失时的降级路径（不拉起子进程）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openkitsune.memory import brain_stack
from openkitsune.memory.brain_stack import (
    BrainStackConfig,
    BrainStackSupervisor,
    build_bus_command,
    build_bus_env,
    build_fusion_command,
    fusion_binary,
    resolve_brain_home,
)


def _config(home: Path, **overrides) -> BrainStackConfig:
    values = {"home": home}
    values.update(overrides)
    return BrainStackConfig(**values)


def test_env_overrides(tmp_path: Path) -> None:
    env = {
        "OPENKITSUNE_BRAIN_HOME": str(tmp_path),
        "OPENKITSUNE_BRAIN_AUTOSTART": "0",
        "OPENKITSUNE_BRAIN_FUSION_AUTOSTART": "false",
        "OPENKITSUNE_BRAIN_BUS_AUTOSTART": "off",
        "OPENKITSUNE_BRAIN_FUSION_PORT": "5014",
        "OPENKITSUNE_BRAIN_BUS_PORT": "9641",
        "OPENKITSUNE_BRAIN_STOP_ON_EXIT": "no",
        "OPENKITSUNE_BRAIN_HEALTH_TIMEOUT": "12.5",
    }
    config = BrainStackConfig.from_env(env)

    assert config.home == tmp_path
    assert config.autostart is False
    assert config.fusion_autostart is False
    assert config.bus_autostart is False
    assert config.fusion_port == 5014
    assert config.bus_port == 9641
    assert config.stop_on_exit is False
    assert config.health_timeout_s == pytest.approx(12.5)


def test_invalid_port_falls_back_to_default() -> None:
    config = BrainStackConfig.from_env(
        {
            "OPENKITSUNE_BRAIN_HOME": os.getcwd(),
            "OPENKITSUNE_BRAIN_FUSION_PORT": "not-a-port",
            "OPENKITSUNE_BRAIN_BUS_PORT": "70000",
        }
    )

    assert config.fusion_port == brain_stack.DEFAULT_FUSION_PORT
    assert config.bus_port == brain_stack.DEFAULT_BUS_PORT


def test_resolve_home_prefers_env(tmp_path: Path) -> None:
    assert resolve_brain_home({"OPENKITSUNE_BRAIN_HOME": str(tmp_path)}) == tmp_path


def test_fusion_command_matches_stack_script(tmp_path: Path) -> None:
    config = _config(tmp_path, fusion_port=4019)
    command = build_fusion_command(config)

    assert command[0] == str(fusion_binary(config))
    assert command[1:5] == ["--root", str(tmp_path), "--port", "4019"]
    assert command[5:7] == ["--data-dir", "data/fusion-memory"]
    assert command[7:] == ["serve", "--no-watch"]


def test_bus_command_uses_current_interpreter(tmp_path: Path) -> None:
    command = build_bus_command(_config(tmp_path))

    assert Path(command[0]).name.startswith("python")
    assert command[1:3] == ["-X", "utf8"]
    assert Path(command[3]) == tmp_path / "services" / "brain-bus" / "server.py"


def test_bus_command_honours_explicit_interpreter(tmp_path: Path) -> None:
    command = build_bus_command(_config(tmp_path), "/opt/venv/bin/python")

    assert command[0] == "/opt/venv/bin/python"


def test_bus_env_sets_pythonpath_and_okmem(tmp_path: Path) -> None:
    env = build_bus_env(
        _config(tmp_path, bus_port=9641),
        base={"PYTHONPATH": "/existing/path", "PYTHONHOME": "/frozen/home"},
    )

    assert "PYTHONHOME" not in env

    parts = env["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path)
    assert "/existing/path" in parts
    assert env["NEURAL_BUS_PORT"] == "9641"
    assert env["NEURAL_BUS_STATE"] == str(tmp_path / "data" / "neural_bus_decider.json")
    assert env["OKMEM_DB"] == str(tmp_path / "data" / "okmem" / "memory.db")


def test_autostart_disabled_never_spawns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when autostart is disabled")

    monkeypatch.setattr(brain_stack.subprocess, "Popen", _fail)
    supervisor = BrainStackSupervisor(_config(tmp_path, autostart=False))

    status = supervisor.start()

    assert status["enabled"] is False
    assert supervisor.status()["services"]["fusion-memory"]["owned"] is False


def test_missing_binaries_degrade_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(brain_stack, "_port_open", lambda *_args, **_kwargs: False)

    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when files are missing")

    monkeypatch.setattr(brain_stack.subprocess, "Popen", _fail)
    supervisor = BrainStackSupervisor(_config(tmp_path))

    status = supervisor.start()

    assert status["enabled"] is True
    assert status["services"]["fusion-memory"]["health"] == "missing-binary"
    assert status["services"]["brain-bus"]["health"] == "missing-script"
    supervisor.stop(force=True)


def test_existing_services_are_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(brain_stack, "_port_open", lambda *_args, **_kwargs: True)

    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when ports are already served")

    monkeypatch.setattr(brain_stack.subprocess, "Popen", _fail)
    supervisor = BrainStackSupervisor(_config(tmp_path, health_timeout_s=0.1))

    status = supervisor.start()

    assert status["services"]["fusion-memory"]["external"] is True
    assert status["services"]["brain-bus"]["external"] is True
    assert status["services"]["fusion-memory"]["owned"] is False
