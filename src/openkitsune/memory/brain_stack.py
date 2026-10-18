"""随 OpenKitsune 启动的 openkitsune-brain 记忆栈。

``openkitsune-brain`` 是独立工程（默认 ``E:\\agents\\openkitsune-brain``），
记忆能力分两层：

- **进程内层**：``memory/openkitsune_brain.py`` 直接调用 ``okmem`` 读写记忆，
  不依赖任何常驻服务；
- **常驻服务层**：``fusion-memory``（Rust，默认 :4014）负责三速记忆与知识库
  索引，``brain-bus``（Python FastAPI，默认 :8641）暴露 ``/api/memory/*``
  记忆器官接口。

本模块负责第二层的“伴随启动”：宿主启动时在后台拉起两个子进程，宿主退出时
回收本进程拉起的实例；端口已被外部实例占用时直接复用，绝不误杀。所有失败
只记录日志，不阻断 OpenKitsune 主流程。

环境变量::

    OPENKITSUNE_BRAIN_AUTOSTART          1/0，总开关（默认 1）
    OPENKITSUNE_BRAIN_HOME               工程根目录
    OPENKITSUNE_BRAIN_FUSION_AUTOSTART   1/0，是否拉起 fusion-memory（默认 1）
    OPENKITSUNE_BRAIN_BUS_AUTOSTART      1/0，是否拉起 brain-bus（默认 1）
    OPENKITSUNE_BRAIN_FUSION_PORT        fusion-memory 端口（默认 4014）
    OPENKITSUNE_BRAIN_BUS_PORT           brain-bus 端口（默认 8641）
    OPENKITSUNE_BRAIN_STOP_ON_EXIT       宿主退出时停止子进程（默认 1）
    OPENKITSUNE_BRAIN_HEALTH_TIMEOUT     健康探针超时秒数（默认 30）
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

# 4010 是上游 Kitsune fusion-memory 的默认端口；独立部署使用 4014 避免抢占。
DEFAULT_FUSION_PORT = 4014
DEFAULT_BUS_PORT = 8641

_FUSION_BINARY = "fusion-memory.exe" if os.name == "nt" else "fusion-memory"
_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0)
    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if os.name == "nt"
    else 0
)


def _env_flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = str(env.get(name, "")).strip().lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


def _env_port(env: Mapping[str, str], name: str, default: int) -> int:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        logger.warning("[BrainStack] %s=%r is not a valid port, using %d", name, raw, default)
        return default
    if not 1 <= port <= 65535:
        logger.warning("[BrainStack] %s=%r out of range, using %d", name, raw, default)
        return default
    return port


def _env_seconds(env: Mapping[str, str], name: str, default: float) -> float:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _normalize_home(raw: str) -> Path:
    """Windows 盘符路径在非 Windows 平台转换为 WSL 挂载路径。"""
    if os.name != "nt":
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
        if match:
            rest = match.group(2).replace("\\", "/").lstrip("/")
            raw = f"/mnt/{match.group(1).lower()}/{rest}"
    return Path(raw).expanduser()


def resolve_brain_home(env: Mapping[str, str] | None = None) -> Path:
    """解析 openkitsune-brain 工程根目录。

    优先级：环境变量 > WSL 挂载 / Windows 固定路径 > 用户目录。
    """
    source = os.environ if env is None else env
    raw = str(source.get("OPENKITSUNE_BRAIN_HOME", "")).strip()
    if raw:
        return _normalize_home(raw)

    candidates = [
        Path("/mnt/e/agents/openkitsune-brain"),
        Path(r"E:\agents\openkitsune-brain"),
        Path.home() / "openkitsune-brain",
    ]
    for candidate in candidates:
        if (candidate / "okmem").is_dir():
            return candidate
    if os.name == "nt":
        return Path(r"E:\agents\openkitsune-brain")
    return Path.home() / "openkitsune-brain"


@dataclass(frozen=True)
class BrainStackConfig:
    """记忆栈启动配置（全部来自环境变量，可测试注入）。"""

    home: Path
    autostart: bool = True
    fusion_autostart: bool = True
    bus_autostart: bool = True
    fusion_port: int = DEFAULT_FUSION_PORT
    bus_port: int = DEFAULT_BUS_PORT
    stop_on_exit: bool = True
    health_timeout_s: float = 30.0
    fusion_data_dir: str = "data/fusion-memory"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BrainStackConfig:
        env = os.environ if environ is None else environ
        return cls(
            home=resolve_brain_home(env),
            autostart=_env_flag(env, "OPENKITSUNE_BRAIN_AUTOSTART", True),
            fusion_autostart=_env_flag(env, "OPENKITSUNE_BRAIN_FUSION_AUTOSTART", True),
            bus_autostart=_env_flag(env, "OPENKITSUNE_BRAIN_BUS_AUTOSTART", True),
            fusion_port=_env_port(env, "OPENKITSUNE_BRAIN_FUSION_PORT", DEFAULT_FUSION_PORT),
            bus_port=_env_port(env, "OPENKITSUNE_BRAIN_BUS_PORT", DEFAULT_BUS_PORT),
            stop_on_exit=_env_flag(env, "OPENKITSUNE_BRAIN_STOP_ON_EXIT", True),
            health_timeout_s=_env_seconds(env, "OPENKITSUNE_BRAIN_HEALTH_TIMEOUT", 30.0),
        )


def fusion_binary(config: BrainStackConfig) -> Path:
    """fusion-memory 可执行文件路径（``target/release``）。"""
    return config.home / "target" / "release" / _FUSION_BINARY


def build_fusion_command(config: BrainStackConfig) -> list[str]:
    """构造 fusion-memory 启动命令（与 ``scripts/start-memory-stack.ps1`` 对齐）。"""
    return [
        str(fusion_binary(config)),
        "--root",
        str(config.home),
        "--port",
        str(config.fusion_port),
        "--data-dir",
        config.fusion_data_dir,
        "serve",
        "--no-watch",
    ]


def _resolve_python() -> str | None:
    """解析 brain-bus 子进程使用的 Python 解释器。

    PyInstaller 冻结环境下 ``sys.executable`` 是宿主 exe，不能直接执行脚本，
    必须走 ``runtime_env`` 提供的项目解释器。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable or "python"
    try:
        from ..runtime_env import get_python_executable

        return get_python_executable()
    except Exception:  # noqa: BLE001 -- 解析失败由调用方降级
        return None


def build_bus_command(config: BrainStackConfig, python: str | None = None) -> list[str]:
    """构造 brain-bus 启动命令，复用项目解释器（保证依赖一致）。"""
    script = config.home / "services" / "brain-bus" / "server.py"
    interpreter = python or _resolve_python() or "python"
    return [interpreter, "-X", "utf8", str(script)]


def build_bus_env(
    config: BrainStackConfig, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """构造 brain-bus 子进程环境：把工程根目录加入 ``PYTHONPATH``。"""
    env = dict(os.environ if base is None else base)
    # 冻结宿主可能设置了 PYTHONHOME；带进另一个解释器会破坏其标准库查找。
    env.pop("PYTHONHOME", None)
    home = str(config.home)
    parts = [home]
    for part in env.get("PYTHONPATH", "").split(os.pathsep):
        if part and part != home:
            parts.append(part)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["NEURAL_BUS_PORT"] = str(config.bus_port)
    env.setdefault("NEURAL_BUS_STATE", str(config.home / "data" / "neural_bus_decider.json"))
    env.setdefault("OKMEM_DB", str(config.home / "data" / "okmem" / "memory.db"))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except Exception:  # noqa: BLE001 -- 探针失败只代表未就绪
        return False


@dataclass
class _Service:
    name: str
    port: int
    autostart: bool
    process: subprocess.Popen | None = None
    log_files: list[Any] = field(default_factory=list)
    external: bool = False
    health: str = "unknown"


class BrainStackSupervisor:
    """管理 fusion-memory / brain-bus 两个伴随子进程的生命周期。"""

    def __init__(self, config: BrainStackConfig | None = None) -> None:
        self.config = config or BrainStackConfig.from_env()
        self._lock = threading.Lock()
        self._started = False
        self._atexit_registered = False
        self._probe: threading.Thread | None = None
        self._services: dict[str, _Service] = {
            "fusion-memory": _Service(
                "fusion-memory", self.config.fusion_port, self.config.fusion_autostart
            ),
            "brain-bus": _Service("brain-bus", self.config.bus_port, self.config.bus_autostart),
        }

    # ------------------------------------------------------------------
    # 启动 / 状态
    # ------------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """拉起记忆栈（幂等、非阻塞）。返回当前状态快照。"""
        with self._lock:
            if self._started:
                return self.status()
            self._started = True

            if not self.config.autostart:
                logger.debug("[BrainStack] autostart disabled by OPENKITSUNE_BRAIN_AUTOSTART")
                return self.status()
            if not self.config.home.is_dir():
                logger.warning(
                    "[BrainStack] home not found: %s (记忆栈未启动)", self.config.home
                )
                return self.status()

            self._start_fusion()
            self._start_bus()

            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True

        self._start_health_probe()
        return self.status()

    def _start_fusion(self) -> None:
        service = self._services["fusion-memory"]
        if not service.autostart:
            service.health = "disabled"
            return
        if _port_open(service.port):
            service.external = True
            service.health = "external"
            logger.info(
                "[BrainStack] fusion-memory already listening on :%d (reuse)", service.port
            )
            return
        binary = fusion_binary(self.config)
        if not binary.exists():
            service.health = "missing-binary"
            logger.warning(
                "[BrainStack] fusion-memory binary missing: %s "
                "(run `cargo build --release -p openkitsune-memory` in %s)",
                binary,
                self.config.home,
            )
            return
        self._spawn(service, build_fusion_command(self.config), env=None)

    def _start_bus(self) -> None:
        service = self._services["brain-bus"]
        if not service.autostart:
            service.health = "disabled"
            return
        if _port_open(service.port):
            service.external = True
            service.health = "external"
            logger.info("[BrainStack] brain-bus already listening on :%d (reuse)", service.port)
            return
        script = self.config.home / "services" / "brain-bus" / "server.py"
        if not script.exists():
            service.health = "missing-script"
            logger.warning("[BrainStack] brain-bus script missing: %s", script)
            return
        python = _resolve_python()
        if python is None:
            service.health = "no-python"
            logger.warning(
                "[BrainStack] no usable Python interpreter for brain-bus "
                "(frozen build without project venv)"
            )
            return
        self._spawn(
            service,
            build_bus_command(self.config, python),
            env=build_bus_env(self.config),
        )

    def _spawn(
        self,
        service: _Service,
        command: list[str],
        *,
        env: dict[str, str] | None,
    ) -> None:
        stdout = stderr = subprocess.DEVNULL
        log_files: list[Any] = []
        try:
            log_dir = self.config.home / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            # 句柄需要活到子进程结束，由 _Service.log_files 统一关闭。
            stdout = open(log_dir / f"host-{service.name}.out.log", "ab")  # noqa: SIM115
            stderr = open(log_dir / f"host-{service.name}.err.log", "ab")  # noqa: SIM115
            log_files = [stdout, stderr]
        except OSError:
            stdout = stderr = subprocess.DEVNULL

        kwargs: dict[str, Any] = {
            "cwd": str(self.config.home),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = _CREATION_FLAGS
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command, **kwargs)  # noqa: S603 -- 固定本机工程路径
        except Exception as exc:  # noqa: BLE001 -- 拉起失败不能阻断宿主
            for handle in log_files:
                handle.close()
            service.health = f"spawn-failed: {exc}"
            logger.warning("[BrainStack] %s spawn failed: %s", service.name, exc)
            return

        service.process = process
        service.log_files = log_files
        service.health = "starting"
        logger.info(
            "[BrainStack] %s started on :%d (pid=%s)",
            service.name,
            service.port,
            process.pid,
        )

    def _start_health_probe(self) -> None:
        if self._probe is not None and self._probe.is_alive():
            return
        if not any(
            service.process is not None or service.external
            for service in self._services.values()
        ):
            return
        self._probe = threading.Thread(
            target=self._probe_health,
            name="openkitsune-brain-health",
            daemon=True,
        )
        self._probe.start()

    def _probe_health(self) -> None:
        pending = {
            name
            for name, service in self._services.items()
            if service.process is not None or service.external
        }
        deadline = time.monotonic() + self.config.health_timeout_s
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                service = self._services[name]
                if _http_ok(f"http://127.0.0.1:{service.port}/health", timeout=1.0):
                    service.health = "ok"
                    pending.discard(name)
                    continue
                process = service.process
                if process is not None and process.poll() is not None:
                    service.health = f"exited({process.returncode})"
                    pending.discard(name)
                    logger.warning(
                        "[BrainStack] %s exited with code %s; see %s",
                        name,
                        process.returncode,
                        self.config.home / "logs" / f"host-{name}.err.log",
                    )
            if pending:
                time.sleep(0.5)
        for name in pending:
            service = self._services[name]
            if service.health == "starting":
                service.health = "timeout"
        logger.info("[BrainStack] health: %s", {name: s.health for name, s in self._services.items()})

    def status(self) -> dict[str, Any]:
        services: dict[str, dict[str, Any]] = {}
        for name, service in self._services.items():
            process = service.process
            alive = process is not None and process.poll() is None
            services[name] = {
                "port": service.port,
                "autostart": service.autostart,
                "owned": process is not None,
                "pid": process.pid if alive else None,
                "external": service.external,
                "health": service.health,
            }
        return {
            "enabled": self.config.autostart,
            "home": str(self.config.home),
            "services": services,
        }

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------

    def stop(self, *, force: bool = False) -> None:
        """回收本进程拉起的子进程；外部实例不受影响。"""
        with self._lock:
            self._started = False
            services = list(self._services.values())

        if not force and not self.config.stop_on_exit:
            return

        owned = [service for service in services if service.process is not None]
        for service in owned:
            process = service.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        deadline = time.monotonic() + 5.0
        for service in owned:
            process = service.process
            if process is None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for handle in service.log_files:
                try:
                    handle.close()
                except OSError:
                    pass
            service.log_files = []
            service.health = "stopped"
            service.process = None


_supervisor: BrainStackSupervisor | None = None
_supervisor_lock = threading.Lock()


def get_brain_stack_supervisor() -> BrainStackSupervisor:
    global _supervisor
    with _supervisor_lock:
        if _supervisor is None:
            _supervisor = BrainStackSupervisor()
        return _supervisor


def start_brain_stack() -> dict[str, Any]:
    """启动记忆栈；任何异常都降级为日志，不阻断宿主启动。"""
    try:
        return get_brain_stack_supervisor().start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[BrainStack] autostart failed: %s", exc, exc_info=True)
        return {"enabled": False, "error": str(exc)}


def stop_brain_stack(*, force: bool = False) -> None:
    """停止本进程拉起的记忆栈子进程。"""
    try:
        get_brain_stack_supervisor().stop(force=force)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[BrainStack] stop failed: %s", exc)
