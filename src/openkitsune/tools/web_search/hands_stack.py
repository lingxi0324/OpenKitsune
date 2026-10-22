"""随 OpenKitsune 启动 openkitsune-hands 网络爪牙服务。

``openkitsune-hands`` 是独立的 Rust 服务（默认 ``E:\\agents\\openkitsune-hands``），
对外提供：::

    POST /api/search/web       多引擎搜索（SearXNG / Bing / Baidu / DuckDuckGo ...）
    POST /api/search/fetch     URL 抓取（请求 / 浏览器渲染 / 视觉兜底）
    GET  /health               存活探针

本模块在宿主启动时拉起 ``kitsune-hands(.exe)``，退出时回收本进程拉起的实例；
端口已被外部实例占用时直接复用，绝不误杀。任何失败只记录日志，不阻断宿主。

环境变量::

    OPENKITSUNE_HANDS_AUTOSTART       1/0，总开关（默认 1）
    OPENKITSUNE_HANDS_HOME            工程根目录
    OPENKITSUNE_HANDS_URL             服务地址（默认 http://127.0.0.1:8320）
    OPENKITSUNE_HANDS_STOP_ON_EXIT    宿主退出时停止子进程（默认 1）
    OPENKITSUNE_HANDS_HEALTH_TIMEOUT  健康探针超时秒数（默认 20）
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_HANDS_URL = "http://127.0.0.1:8320"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

_BINARY_NAMES = ("kitsune-hands.exe", "kitsune_hands.exe") if os.name == "nt" else (
    "kitsune-hands",
    "kitsune_hands",
)
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


def _env_seconds(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        value = float(str(env.get(name, "")).strip())
    except ValueError:
        return default
    return value if value > 0 else default


def resolve_hands_home(env: Mapping[str, str] | None = None) -> Path:
    """解析 openkitsune-hands 工程根目录。"""
    source = os.environ if env is None else env
    raw = str(source.get("OPENKITSUNE_HANDS_HOME", "")).strip()
    if raw:
        return Path(raw).expanduser()
    candidates = [Path(r"E:\agents\openkitsune-hands"), Path("/mnt/e/agents/openkitsune-hands")]
    for candidate in candidates:
        if (candidate / "Cargo.toml").is_file():
            return candidate
    if os.name == "nt":
        return Path(r"E:\agents\openkitsune-hands")
    return Path.home() / "openkitsune-hands"


def resolve_hands_url(env: Mapping[str, str] | None = None) -> str:
    """解析 kitsune-hands 服务地址（去掉尾部斜杠）。"""
    source = os.environ if env is None else env
    raw = str(source.get("OPENKITSUNE_HANDS_URL", "")).strip() or DEFAULT_HANDS_URL
    return raw.rstrip("/")


def _host_port(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return host, port


def service_reachable(url: str, timeout: float = 0.2) -> bool:
    """TCP 探测服务地址是否可达（供 Provider 的 ``is_available`` 使用）。"""
    host, port = _host_port(url)
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


@dataclass(frozen=True)
class HandsConfig:
    home: Path
    url: str = DEFAULT_HANDS_URL
    autostart: bool = True
    stop_on_exit: bool = True
    health_timeout_s: float = 20.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> HandsConfig:
        env = os.environ if environ is None else environ
        return cls(
            home=resolve_hands_home(env),
            url=resolve_hands_url(env),
            autostart=_env_flag(env, "OPENKITSUNE_HANDS_AUTOSTART", True),
            stop_on_exit=_env_flag(env, "OPENKITSUNE_HANDS_STOP_ON_EXIT", True),
            health_timeout_s=_env_seconds(env, "OPENKITSUNE_HANDS_HEALTH_TIMEOUT", 20.0),
        )

    @property
    def host(self) -> str:
        return _host_port(self.url)[0]

    @property
    def port(self) -> int:
        return _host_port(self.url)[1]


def resolve_hands_binary(config: HandsConfig) -> Path | None:
    """优先 release，其次 debug（开发机常见）。"""
    for profile in ("release", "debug"):
        for name in _BINARY_NAMES:
            candidate = config.home / "target" / profile / name
            if candidate.is_file():
                return candidate
    return None


def build_hands_command(config: HandsConfig, binary: Path) -> list[str]:
    """构造 kitsune-hands 启动命令（无参数，配置经环境变量注入）。"""
    return [str(binary)]


def build_hands_env(
    config: HandsConfig, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """构造子进程环境：显式指定配置文件与监听地址。"""
    env = dict(os.environ if base is None else base)
    env["NX_CONFIG"] = str(config.home / "config.yaml")
    env["NX_BIND"] = f"{config.host}:{config.port}"
    env.setdefault("RUST_LOG", "info")
    return env


@dataclass
class _Service:
    process: subprocess.Popen | None = None
    log_files: list[Any] = field(default_factory=list)
    external: bool = False
    health: str = "unknown"


class HandsSupervisor:
    """管理 kitsune-hands 子进程的生命周期。"""

    def __init__(self, config: HandsConfig | None = None) -> None:
        self.config = config or HandsConfig.from_env()
        self._lock = threading.Lock()
        self._started = False
        self._atexit_registered = False
        self._probe: threading.Thread | None = None
        self._service = _Service()

    def start(self) -> dict[str, Any]:
        """拉起网络服务（幂等、非阻塞）。返回当前状态快照。"""
        with self._lock:
            if self._started:
                return self.status()
            self._started = True

            if not self.config.autostart:
                logger.debug("[HandsStack] autostart disabled by OPENKITSUNE_HANDS_AUTOSTART")
                return self.status()
            if self.config.host not in _LOCAL_HOSTS:
                self._service.external = True
                self._service.health = "remote"
                logger.info("[HandsStack] using remote service %s (no local spawn)", self.config.url)
                return self.status()
            if service_reachable(self.config.url):
                self._service.external = True
                self._service.health = "external"
                logger.info("[HandsStack] kitsune-hands already listening on %s", self.config.url)
                return self.status()
            if not self.config.home.is_dir():
                logger.warning("[HandsStack] home not found: %s", self.config.home)
                return self.status()

            binary = resolve_hands_binary(self.config)
            if binary is None:
                self._service.health = "missing-binary"
                logger.warning(
                    "[HandsStack] kitsune-hands binary missing under %s "
                    "(run `cargo build --release` in that project)",
                    self.config.home / "target",
                )
                return self.status()

            self._spawn(binary)
            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True

        self._start_health_probe()
        return self.status()

    def _spawn(self, binary: Path) -> None:
        stdout = stderr = subprocess.DEVNULL
        log_files: list[Any] = []
        try:
            log_dir = self.config.home / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            # 句柄需要活到子进程结束，由 _Service.log_files 统一关闭。
            stdout = open(log_dir / "host-kitsune-hands.out.log", "ab")  # noqa: SIM115
            stderr = open(log_dir / "host-kitsune-hands.err.log", "ab")  # noqa: SIM115
            log_files = [stdout, stderr]
        except OSError:
            stdout = stderr = subprocess.DEVNULL

        kwargs: dict[str, Any] = {
            "cwd": str(self.config.home),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "env": build_hands_env(self.config),
        }
        if os.name == "nt":
            kwargs["creationflags"] = _CREATION_FLAGS
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(  # noqa: S603 -- 固定本机工程路径
                build_hands_command(self.config, binary), **kwargs
            )
        except Exception as exc:  # noqa: BLE001 -- 拉起失败不能阻断宿主
            for handle in log_files:
                handle.close()
            self._service.health = f"spawn-failed: {exc}"
            logger.warning("[HandsStack] spawn failed: %s", exc)
            return

        self._service.process = process
        self._service.log_files = log_files
        self._service.health = "starting"
        logger.info(
            "[HandsStack] kitsune-hands started on %s (pid=%s, binary=%s)",
            self.config.url,
            process.pid,
            binary,
        )

    def _start_health_probe(self) -> None:
        if self._probe is not None and self._probe.is_alive():
            return
        if self._service.process is None and not self._service.external:
            return
        self._probe = threading.Thread(
            target=self._probe_health,
            name="openkitsune-hands-health",
            daemon=True,
        )
        self._probe.start()

    def _probe_health(self) -> None:
        deadline = time.monotonic() + self.config.health_timeout_s
        while time.monotonic() < deadline:
            if _http_ok(f"{self.config.url}/health", timeout=1.0):
                self._service.health = "ok"
                logger.info("[HandsStack] health ok (%s)", self.config.url)
                return
            process = self._service.process
            if process is not None and process.poll() is not None:
                self._service.health = f"exited({process.returncode})"
                logger.warning(
                    "[HandsStack] kitsune-hands exited with code %s; see %s",
                    process.returncode,
                    self.config.home / "logs" / "host-kitsune-hands.err.log",
                )
                return
            time.sleep(0.5)
        if self._service.health == "starting":
            self._service.health = "timeout"
        logger.warning("[HandsStack] health timeout (%s)", self.config.url)

    def status(self) -> dict[str, Any]:
        process = self._service.process
        alive = process is not None and process.poll() is None
        return {
            "enabled": self.config.autostart,
            "home": str(self.config.home),
            "url": self.config.url,
            "owned": process is not None,
            "pid": process.pid if alive else None,
            "external": self._service.external,
            "health": self._service.health,
        }

    def stop(self, *, force: bool = False) -> None:
        """回收本进程拉起的子进程；外部实例不受影响。"""
        with self._lock:
            self._started = False
            process = self._service.process
            log_files = list(self._service.log_files)

        if not force and not self.config.stop_on_exit:
            return
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for handle in log_files:
            try:
                handle.close()
            except OSError:
                pass
        self._service.log_files = []
        self._service.process = None
        self._service.health = "stopped"


_supervisor: HandsSupervisor | None = None
_supervisor_lock = threading.Lock()


def get_hands_supervisor() -> HandsSupervisor:
    global _supervisor
    with _supervisor_lock:
        if _supervisor is None:
            _supervisor = HandsSupervisor()
        return _supervisor


def start_hands_stack() -> dict[str, Any]:
    """启动网络爪牙服务；任何异常都降级为日志，不阻断宿主启动。"""
    try:
        return get_hands_supervisor().start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[HandsStack] autostart failed: %s", exc, exc_info=True)
        return {"enabled": False, "error": str(exc)}


def stop_hands_stack(*, force: bool = False) -> None:
    """停止本进程拉起的网络爪牙服务。"""
    try:
        get_hands_supervisor().stop(force=force)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[HandsStack] stop failed: %s", exc)
