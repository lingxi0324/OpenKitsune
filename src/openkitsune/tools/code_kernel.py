"""Session-persistent Python kernels for execute_code (OpenKitsune port).

Adapted from Hermes ``tools/code_kernel.py`` with
Hermes-only dependencies removed:

* one child per ``(owner, python, cwd, tool-set)`` key, one code cell per call,
  state survives across calls (variables / imports persist until ``reset=true``);
* wire protocol: one JSON request per stdin line ``{"id", "code"}``; replies are
  framed on stdout as ``<SENTINEL> <byte-length>\\n<json>`` with a per-kernel
  random SENTINEL from the environment.  Bytes outside frames are raw fd output
  attributed to the running cell (calls are serialized per kernel);
* a wedged kernel dies, never hangs the agent: timeout/interrupt kills the
  process tree and drops the registry entry; state loss is deliberate;
* script-side tool calls go through ``kitsune_tools`` stubs (written into the
  kernel staging dir) which RPC back to the host over a loopback socket
  (Windows) / unix socket (POSIX); the host enforces token + allow-list +
  per-cell call budget before dispatching to the OpenKitsune handler registry.

Security envelope: child env scrubbed; cell output ANSI-stripped and
credential-redacted; allow-list defaults to read-only tools only (see
``handlers/code_execution.py``).
"""

from __future__ import annotations

import atexit
import glob
import json
import logging
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Runner-side cap on captured python-level output; the host re-applies its own cap.
_RUNNER_CAPTURE_BYTES = 1_000_000

# Shared by both generated runners: exec one request in the persistent GLOBALS
# namespace, build the payload.  ``__name__`` is ``__main__`` as on the per-call path.
RUNNER_CELL_SOURCE = """\
GLOBALS = {"__name__": "__main__", "__builtins__": __builtins__}


def _clip(text):
    return (text, False) if len(text) <= _CAPTURE_LIMIT else (text[:_CAPTURE_LIMIT], True)


def run_cell(request, execution_count):
    \"\"\"Exec one cell; returns (response payload, FULL stdout text).\"\"\"
    out, err = io.StringIO(), io.StringIO()
    status, trace = "ok", ""
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(request["code"], "<cell>", "exec"), GLOBALS)
    except SystemExit as exc:
        status, trace = "exit", "SystemExit: " + repr(exc.code)
    except BaseException:
        status, trace = "error", traceback.format_exc()
    stdout_text, stdout_clipped = _clip(out.getvalue())
    stderr_text, stderr_clipped = _clip(err.getvalue())
    return {
        "id": request.get("id", ""), "status": status,
        "stdout": stdout_text, "stderr": stderr_text,
        "stdout_clipped": stdout_clipped, "stderr_clipped": stderr_clipped,
        "traceback": trace, "execution_count": execution_count,
    }, out.getvalue()
"""

KERNEL_RUNNER_SOURCE = f'''\
"""Auto-generated OpenKitsune session-kernel runner. One exec cell per request."""
import contextlib
import io
import json
import os
import sys
import threading
import traceback

_SENTINEL = os.environ["KITSUNE_KERNEL_SENTINEL"]
_CAPTURE_LIMIT = {_RUNNER_CAPTURE_BYTES}
_SPILL_DIR = os.environ.get("KITSUNE_KERNEL_SPILL_DIR", "")
_SPILL_CAP = {5_000_000}
_PARENT_PROCESS_HANDLE = os.environ.pop("KITSUNE_KERNEL_PARENT_PROCESS_HANDLE", "")
_PARENT_DEATH_FD = os.environ.pop("KITSUNE_KERNEL_PARENT_DEATH_FD", "")


def _start_parent_death_pipe_watchdog():
    """POSIX twin of the Windows handle watchdog: exit when the parent dies."""
    global _PARENT_DEATH_FD
    raw_fd = _PARENT_DEATH_FD
    _PARENT_DEATH_FD = ""
    if sys.platform == "win32" or not raw_fd:
        return
    try:
        fd = int(raw_fd)
        os.set_inheritable(fd, False)
    except (OSError, ValueError):
        return

    def _wait():
        try:
            while os.read(fd, 1):
                pass
        except OSError:
            pass
        os._exit(0)

    threading.Thread(target=_wait, name="kitsune-parent-watchdog", daemon=True).start()


def _start_parent_process_watchdog():
    """Exit when the exact Windows parent process object is signaled."""
    global _PARENT_PROCESS_HANDLE
    raw_handle = _PARENT_PROCESS_HANDLE
    _PARENT_PROCESS_HANDLE = ""
    if sys.platform != "win32" or not raw_handle:
        return
    try:
        import ctypes
        from ctypes import wintypes

        handle = int(raw_handle)
        if handle <= 0:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.SetHandleInformation.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD
        ]
        kernel32.SetHandleInformation.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        if not kernel32.SetHandleInformation(handle, 0x00000001, 0):
            kernel32.CloseHandle(handle)
            return
    except (ImportError, OSError, TypeError, ValueError):
        return

    def _wait():
        try:
            result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        finally:
            kernel32.CloseHandle(handle)
        if result == 0x00000000:  # WAIT_OBJECT_0: the parent exited
            os._exit(0)

    threading.Thread(target=_wait, name="kitsune-parent-watchdog", daemon=True).start()


_start_parent_process_watchdog()
_start_parent_death_pipe_watchdog()

_real_stdout = sys.stdout

{RUNNER_CELL_SOURCE}

def _spill(text, spill_name):
    \"\"\"Best-effort: write the FULL clipped stdout to disk, return its path or \"\".\"\"\"
    if not _SPILL_DIR:
        return ""
    try:
        spill_path = os.path.join(_SPILL_DIR, spill_name)
        with open(spill_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(text[:_SPILL_CAP])
            if len(text) > _SPILL_CAP:
                f.write("\\n\\n[... spill capped ...]")
        return spill_path
    except Exception:
        return ""


def _reply(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _real_stdout.buffer.write(("\\n" + _SENTINEL + " " + str(len(body)) + "\\n").encode("utf-8"))
    _real_stdout.buffer.write(body)
    _real_stdout.buffer.flush()


def main():
    execution_count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        execution_count += 1
        payload, full_stdout = run_cell(request, execution_count)
        payload["stdout_spill_path"] = (
            _spill(full_stdout, "cell_%06d_stdout.txt" % execution_count)
            if payload["stdout_clipped"] else ""
        )
        _reply(payload)
        if payload["status"] == "exit":
            break


if __name__ == "__main__":
    main()
'''

# ---------------------------------------------------------------------------
# kitsune_tools stub generator (script-side programmable tool calls)
# ---------------------------------------------------------------------------

_COMMON_HELPERS = '''\

# ---------------------------------------------------------------------------
# Convenience helpers (avoid common scripting pitfalls)
# ---------------------------------------------------------------------------

def json_parse(text: str):
    """Parse JSON tolerant of control characters and UTF-8 BOM (strict=False)."""
    if isinstance(text, str) and text.startswith("\\ufeff"):
        text = text[1:]
    return json.loads(text, strict=False)


def shell_quote(s: str) -> str:
    """Shell-escape a string for safe interpolation into commands."""
    return shlex.quote(s)


def retry(fn, max_attempts=3, delay=2):
    """Retry a function up to max_attempts times with exponential backoff."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_err

'''

_UDS_TRANSPORT_HEADER = '''\
"""Auto-generated OpenKitsune kitsune_tools RPC stubs."""
import json, os, socket, shlex, threading, time

_sock = None
_call_lock = threading.Lock()
''' + _COMMON_HELPERS + '''\

def _connect():
    """Connect to the parent's RPC server (tcp:// on Windows, unix socket otherwise)."""
    global _sock
    if _sock is None:
        endpoint = os.environ["KITSUNE_RPC_SOCKET"]
        if endpoint.startswith("tcp://"):
            _host_port = endpoint[len("tcp://"):]
            _host, _, _port = _host_port.rpartition(":")
            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _sock.connect((_host or "127.0.0.1", int(_port)))
        else:
            _sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _sock.connect(endpoint)
        _sock.settimeout(300)
    return _sock

def _call(tool_name, args):
    """Send a tool call to the parent process and return the parsed result."""
    request = json.dumps({
        "tool": tool_name,
        "args": args,
        "token": os.environ.get("KITSUNE_RPC_TOKEN", ""),
    }) + "\\n"
    _attempts = 2 if os.environ.get("KITSUNE_RPC_PERSISTENT") == "1" else 1
    with _call_lock:
        for _attempt in range(_attempts):
            try:
                conn = _connect()
                conn.sendall(request.encode())
                buf = b""
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        raise RuntimeError("Agent process disconnected")
                    buf += chunk
                    if buf.endswith(b"\\n"):
                        break
                break
            except (OSError, RuntimeError):
                global _sock
                try:
                    if _sock is not None:
                        _sock.close()
                except OSError:
                    pass
                _sock = None
                if _attempt + 1 >= _attempts:
                    raise
    raw = buf.decode().strip()
    result = json.loads(raw)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    return result

'''


def generate_kitsune_tools_module(enabled_tools: list[str]) -> str:
    """Source of the ``kitsune_tools.py`` stub module for *enabled_tools*.

    Stubs are generated from the host tool registry's input schemas, so the
    sandbox always sees current signatures.
    """
    header = _UDS_TRANSPORT_HEADER
    body: list[str] = []
    for name in sorted(enabled_tools):
        body.append(
            f"def {name}(**kwargs):\n"
            f"    \"\"\"Call the host tool '{name}'.\"\"\"\n"
            f"    return _call({name!r}, kwargs)\n"
        )
    return header + "\n".join(body)


# ---------------------------------------------------------------------------
# RPC server (host side) — token check → allow-list → budget → dispatch
# ---------------------------------------------------------------------------

def tool_error(message: str) -> str:
    """A tool result string carrying an error, like Hermes ``tools.registry.tool_error``."""
    try:
        return json.dumps({"error": str(message)}, ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "tool error"})


def _rpc_token_ok(request: dict, rpc_token: str) -> bool:
    """Constant-time token check; an empty server token fails closed."""
    return bool(rpc_token) and secrets.compare_digest(
        str(request.get("token") or "").encode(), rpc_token.encode()
    )


def _result_error(result) -> str:
    """The ``error`` text of a JSON-object tool result, else ``""``."""
    if not isinstance(result, str) or not result.startswith("{") or '"error"' not in result:
        return ""
    try:
        body = json.loads(result)
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    return str(error)[:300] if error else ""


def tool_errors_since(tool_call_log: list, start: int = 0) -> list:
    """Failed in-script tool calls since *start*, for the execute_code result."""
    return [{"tool": e["tool"], "error": e["error"]} for e in tool_call_log[start:] if e.get("error")][:5]


def _handle_rpc_request(request: dict, *, allowed_tools: frozenset, tool_call_counter: list,
                        max_tool_calls: int, dispatch, tool_call_log: list,
                        call_start: float, where: str) -> str:
    """Enforce allow-list + budget, then dispatch one authenticated request."""
    tool_name = request.get("tool", "")
    tool_args = request.get("args", {})
    if tool_name not in allowed_tools:
        return tool_error(
            f"Tool '{tool_name}' is not available in execute_code. "
            f"Available: {', '.join(sorted(allowed_tools)) or '(none)'}"
        )
    if tool_call_counter[0] >= max_tool_calls:
        return tool_error(f"Tool call limit reached ({max_tool_calls}). "
                          "No more tool calls allowed in this execution.")
    try:
        result = dispatch(tool_name, tool_args)
    except Exception as exc:
        logger.error("Tool call failed in %s: %s", where, exc, exc_info=True)
        result = tool_error(str(exc))
    tool_call_counter[0] += 1
    entry = {"tool": tool_name, "args_preview": str(tool_args)[:80],
             "duration": round(time.monotonic() - call_start, 2)}
    error = _result_error(result)
    if error:
        entry["error"] = error
    tool_call_log.append(entry)
    return result if isinstance(result, str) else str(result)


def _rpc_server_loop(server_sock: socket.socket, tool_call_log: list,
                     tool_call_counter: list, max_tool_calls: int, allowed_tools: frozenset,
                     stop_event: threading.Event, rpc_token: str, dispatch=None):
    """Accept one client and serve newline-delimited JSON requests until it
    disconnects, idles 300s, or the call limit is reached."""
    conn = None
    try:
        server_sock.settimeout(0.05)
        while not stop_event.is_set():
            try:
                conn, _ = server_sock.accept()
                break
            except TimeoutError:
                continue
        if conn is None:
            return
        conn.settimeout(300)
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                call_start = time.monotonic()
                try:
                    request = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    resp = tool_error(f"Invalid RPC request: {exc}")
                else:
                    resp = (
                        _handle_rpc_request(
                            request, allowed_tools=allowed_tools,
                            tool_call_counter=tool_call_counter, max_tool_calls=max_tool_calls,
                            dispatch=dispatch, tool_call_log=tool_call_log,
                            call_start=call_start, where="execute_code sandbox",
                        )
                        if _rpc_token_ok(request, rpc_token)
                        else tool_error("Unauthorized RPC request")
                    )
                try:
                    conn.sendall((resp + "\n").encode())
                except OSError:
                    break
    except TimeoutError:
        logger.debug("RPC listener socket timeout")
    except OSError as e:
        logger.debug("RPC listener socket error: %s", e, exc_info=True)
    finally:
        if conn:
            try:
                conn.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Cell authority: rebind RPC dispatches to the CURRENT cell's dispatch fn
# ---------------------------------------------------------------------------

class CellAuthority:
    """The tool-dispatch identity of exactly one execute_code cell.

    A fresh authority is captured per cell and retired when the cell settles,
    so a late tool call (leaked background thread) is refused instead of
    running under a stale identity.
    """

    def __init__(self, dispatch: Callable[[str, dict], str] | None):
        self.dispatch_fn = dispatch
        self.active = True

    def retire(self) -> None:
        self.active = False

    def dispatch(self, tool_name: str, tool_args: dict) -> str:
        if not self.active:
            return tool_error(
                "No active execute_code cell: the cell this kernel call "
                "belonged to has settled, so its tool authority is retired."
            )
        if self.dispatch_fn is None:
            return tool_error(
                "Tool calls are not enabled for this execute_code session "
                "(the host configured an empty sandbox allow-list)."
            )
        try:
            result = self.dispatch_fn(tool_name, tool_args)
        except Exception as exc:
            logger.error("execute_code script tool dispatch failed: %s", exc, exc_info=True)
            return tool_error(str(exc))
        return result if isinstance(result, str) else str(result)


class _BoundedBuffer:
    """Byte chunks capped at a total size; ``drain`` returns text and resets."""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.total = 0

    def append(self, data: bytes, cap: int) -> None:
        keep = data[: max(0, cap - self.total)]
        if keep:
            self.chunks.append(keep)
            self.total += len(keep)

    def drain(self) -> str:
        chunks, self.chunks, self.total = self.chunks, [], 0
        return b"".join(chunks).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Session kernel + registry
# ---------------------------------------------------------------------------

class SessionKernel:
    """One live kernel process plus its RPC server and reader threads."""

    def __init__(self, key: tuple):
        self.key, self.owner, self.lock = key, key[0], threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.tmpdir = self.rpc_token = self.sentinel = ""
        self.sock_path: str | None = None
        self.server_sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.death_pipe_w: int | None = None
        self.tool_call_log: list = []
        self.cell_log_start = 0
        self.tool_call_counter: list[int] = [0]
        self.attached: int = 0
        self.response_q: queue.Queue[dict] = queue.Queue()
        self.raw, self.stderr = _BoundedBuffer(), _BoundedBuffer()
        self.execution_count, self.last_used = 0, time.monotonic()
        self.cell_authority: CellAuthority | None = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def dead(self) -> bool:
        return self.proc is not None and self.proc.poll() is not None

    def teardown(self) -> None:
        self.stop_event.set()
        if self.death_pipe_w is not None:
            try:
                os.close(self.death_pipe_w)
            except OSError:
                pass
            self.death_pipe_w = None
        if self.alive():
            _kill_process_group(self.proc, escalate=True)
        sock, self.server_sock = self.server_sock, None
        try:
            if sock is not None:
                sock.close()
            if self.sock_path:
                os.unlink(self.sock_path)
        except OSError:
            pass
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class KernelRegistry:
    """Owner -> kernel bookkeeping; lifetime caps enforced under one lock."""

    def __init__(self, teardown: Callable[[Any], None]):
        self.lock = threading.Lock()
        self.kernels: dict = {}
        self._teardown = teardown

    def shutdown(self, owner: str | None = None,
                 *, owner_matches: Callable[[str], bool] | None = None) -> None:
        doomed = []
        with self.lock:
            for key, _kernel in list(self.kernels.items()):
                if owner is not None and key[0] != owner:
                    continue
                if owner_matches is not None and not owner_matches(key[0]):
                    continue
                doomed.append(self.kernels.pop(key))
        for kernel in doomed:
            self._teardown(kernel)

    def discard(self, key: tuple, kernel: Any) -> None:
        with self.lock:
            if self.kernels.get(key) is kernel:
                self.kernels.pop(key, None)
        self._teardown(kernel)


_KERNEL_CAP = 8
_KERNEL_IDLE_TIMEOUT = 1800.0
_STALE_STAGING_DIR_AGE = 7 * 86400
_REAPER_INTERVAL_FLOOR, _REAPER_INTERVAL_CEIL = 30.0, 300.0
_REAPER_STARTED = False
_STAGING_PREFIX = "kitsune_kernel_"

_REGISTRY = KernelRegistry(lambda k: k.teardown())
_KERNELS = _REGISTRY.kernels


def shutdown_all_kernels() -> None:
    _REGISTRY.shutdown()


def shutdown_kernels_for_owner(owner: str) -> None:
    _REGISTRY.shutdown(owner=owner)


atexit.register(shutdown_all_kernels)


# ---------------------------------------------------------------------------
# Process group kill (no external dependency)
# ---------------------------------------------------------------------------

def _kill_process_group(proc: subprocess.Popen, escalate: bool = False) -> None:
    """Terminate *proc* and its process tree. On Windows, terminate the tree via
    ``taskkill /T`` (escalate) falling back to plain terminate."""
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        if _IS_WINDOWS and escalate:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass
        else:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover
        logger.debug("process group kill failed: %s", exc)


# ---------------------------------------------------------------------------
# Child environment + spawn
# ---------------------------------------------------------------------------

def _build_child_env(rpc_endpoint: str, rpc_token: str, tmpdir: str,
                     child_python: str) -> dict:
    env = dict(os.environ)
    # Strip anything that could leak or break the kernel.
    for key in list(env):
        if key.startswith("KITSUNE_") or key.startswith("HERMES_"):
            env.pop(key, None)
    env.pop("PYTHONSTARTUP", None)
    env.pop("PYTHONINSPECT", None)
    env.pop("PYTHONBREAKPOINT", None)
    env["KITSUNE_RPC_SOCKET"] = rpc_endpoint
    env["KITSUNE_RPC_TOKEN"] = rpc_token
    env["KITSUNE_RPC_PERSISTENT"] = "1"
    # Runner + kitsune_tools live in the staging dir; make them importable.
    env["PYTHONPATH"] = tmpdir
    if child_python:
        venv_scripts = str(Path(child_python).parent)
        env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
    return env


def _parent_process_handle(child_env: dict[str, str]):
    """Windows: open an inheritable SYNCHRONIZE handle to this process for the
    kernel's parent-death watchdog. Returns (handle, CloseHandle, startupinfo)
    or (None, None, None); fails open."""
    handle = close = startupinfo = None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcessId.argtypes = []
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        close = kernel32.CloseHandle
        handle = kernel32.OpenProcess(0x00100000, True, kernel32.GetCurrentProcessId())
        if handle:
            child_env["KITSUNE_KERNEL_PARENT_PROCESS_HANDLE"] = str(int(handle))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {"handle_list": [int(handle)]}
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        if handle and close is not None:
            close(handle)
        child_env.pop("KITSUNE_KERNEL_PARENT_PROCESS_HANDLE", None)
        handle = close = startupinfo = None
    return handle, close, startupinfo


def _bind_rpc_socket(kernel: SessionKernel) -> str:
    """Bind the tool-RPC listener: loopback TCP on Windows, UDS elsewhere."""
    if _IS_WINDOWS:
        kernel.sock_path = None
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        host, port = server_sock.getsockname()[:2]
        rpc_endpoint = f"tcp://{host}:{port}"
    else:
        sock_tmpdir = tempfile.gettempdir()
        rpc_endpoint = kernel.sock_path = os.path.join(
            sock_tmpdir, f"kitsune_rpc_{uuid.uuid4().hex}.sock"
        )
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(kernel.sock_path)
        os.chmod(kernel.sock_path, 0o600)
    server_sock.listen(1)
    kernel.server_sock = server_sock
    return rpc_endpoint


def _spawn(kernel: SessionKernel, *, child_python: str, child_cwd: str,
           sandbox_tools: frozenset, max_tool_calls: int) -> None:
    kernel.tmpdir = tempfile.mkdtemp(prefix=_STAGING_PREFIX)
    kernel.rpc_token = secrets.token_urlsafe(32)
    kernel.sentinel = "@@KITSUNE-KERNEL-" + secrets.token_urlsafe(16) + "@@"
    rpc_endpoint = _bind_rpc_socket(kernel)
    for name, src in (
        ("kitsune_tools.py", generate_kitsune_tools_module(list(sandbox_tools))),
        ("kitsune_kernel_runner.py", KERNEL_RUNNER_SOURCE),
    ):
        Path(kernel.tmpdir, name).write_text(src, encoding="utf-8")
    child_env = _build_child_env(
        rpc_endpoint=rpc_endpoint, rpc_token=kernel.rpc_token,
        tmpdir=kernel.tmpdir, child_python=child_python,
    )
    child_env["KITSUNE_KERNEL_SENTINEL"] = kernel.sentinel
    child_env["KITSUNE_KERNEL_SPILL_DIR"] = kernel.tmpdir
    child_env["KITSUNE_RPC_PERSISTENT"] = "1"
    parent_handle, close_handle, startupinfo = (
        _parent_process_handle(child_env) if _IS_WINDOWS else (None, None, None)
    )
    death_r: int | None = None
    pass_fds: tuple = ()
    if not _IS_WINDOWS:
        death_r, kernel.death_pipe_w = os.pipe()
        child_env["KITSUNE_KERNEL_PARENT_DEATH_FD"] = str(death_r)
        pass_fds = (death_r,)
    try:
        kernel.proc = subprocess.Popen(
            [child_python, os.path.join(kernel.tmpdir, "kitsune_kernel_runner.py")],
            cwd=child_cwd or kernel.tmpdir, env=child_env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
            close_fds=True, pass_fds=pass_fds, startupinfo=startupinfo,
        )
    finally:
        if parent_handle and close_handle is not None:
            close_handle(parent_handle)
        if death_r is not None:
            os.close(death_r)
    for target, args in (
        (_rpc_forever, (kernel, max_tool_calls, sandbox_tools)),
        (_stdout_reader, (kernel,)),
        (_stderr_reader, (kernel,)),
    ):
        threading.Thread(target=target, args=args, daemon=True).start()
    _ensure_background_reaper()


def _rpc_forever(kernel: SessionKernel, max_tool_calls: int,
                 sandbox_tools: frozenset) -> None:
    """Serve tool RPC for the kernel's whole life; re-accept until teardown."""
    def _dispatch(tool_name: str, tool_args: dict) -> str:
        authority = kernel.cell_authority
        if authority is None:
            return tool_error(
                "No active execute_code cell: this kernel has no cell authority installed."
            )
        return authority.dispatch(tool_name, tool_args)
    while not kernel.stop_event.is_set():
        _rpc_server_loop(kernel.server_sock, kernel.tool_call_log, kernel.tool_call_counter,
                         max_tool_calls, sandbox_tools, kernel.stop_event, kernel.rpc_token,
                         dispatch=_dispatch)


MAX_STDOUT_BYTES = 50_000    # 50 KB
MAX_STDERR_BYTES = 10_000    # 10 KB
_MAX_SPILLED_STDOUT_BYTES = 5_000_000


def _stdout_reader(kernel: SessionKernel) -> None:
    """Split the child's stdout into protocol frames and raw passthrough."""
    assert kernel.proc is not None and kernel.proc.stdout is not None
    stream = kernel.proc.stdout
    marker = ("\n" + kernel.sentinel + " ").encode("utf-8")

    def raw(data: bytes) -> None:
        kernel.raw.append(data, MAX_STDOUT_BYTES)

    buf = b""
    while True:
        chunk = stream.read1(4096)
        if not chunk:
            if buf:
                raw(buf)
            kernel.response_q.put({"status": "kernel-eof"})
            return
        buf += chunk
        while True:
            index = buf.find(marker)
            if index < 0:
                spill = buf[: -len(marker)] if len(buf) > len(marker) else b""
                if spill:
                    raw(spill)
                    buf = buf[len(spill):]
                break
            if index:
                raw(buf[:index])
            rest = buf[index + len(marker):]
            newline = rest.find(b"\n")
            if newline < 0:
                buf = buf[index:]
                break
            try:
                length = int(rest[:newline])
            except ValueError:
                raw(marker)
                buf = rest
                continue
            body = rest[newline + 1:]
            while len(body) < length:
                more = stream.read1(length - len(body))
                if not more:
                    kernel.response_q.put({"status": "kernel-eof"})
                    return
                body += more
            try:
                kernel.response_q.put(json.loads(body[:length].decode("utf-8", errors="replace")))
            except ValueError:
                kernel.response_q.put({"status": "protocol-error"})
            buf = body[length:]


def _stderr_reader(kernel: SessionKernel) -> None:
    assert kernel.proc is not None and kernel.proc.stderr is not None
    while chunk := kernel.proc.stderr.read1(4096):
        kernel.stderr.append(chunk, MAX_STDERR_BYTES)


# ---------------------------------------------------------------------------
# Lifecycle: idle sweep + process-wide cap + stale staging dir reaper
# ---------------------------------------------------------------------------

def _pop_idle_expired(now: float, idle_timeout: float) -> list[SessionKernel]:
    return [_KERNELS.pop(k) for k in list(_KERNELS)
            if _KERNELS[k].attached == 0 and now - _KERNELS[k].last_used > idle_timeout]


def _acquire_kernel(key: tuple, reset: bool) -> tuple[SessionKernel, bool]:
    """Look up or register the kernel for *key*; returns (kernel, state_reset)."""
    with _REGISTRY.lock:
        expired = _pop_idle_expired(time.monotonic(), _KERNEL_IDLE_TIMEOUT)
        kernel = _KERNELS.get(key)
        state_reset = kernel is not None and (reset or kernel.dead())
        if state_reset:
            dropped = _KERNELS.pop(key)
            if dropped.attached == 0:
                expired.append(dropped)
            kernel = None
        if kernel is None:
            kernel = _KERNELS[key] = SessionKernel(key)
        kernel.last_used = time.monotonic()
        kernel.attached += 1
        unpinned = list(_KERNELS)
        by_age = sorted((k for k in unpinned if k != key and _KERNELS[k].attached == 0),
                        key=lambda k: _KERNELS[k].last_used)
        expired.extend(_KERNELS.pop(k) for k in by_age[: max(0, len(unpinned) - _KERNEL_CAP)])
    for doomed in expired:
        doomed.teardown()
    return kernel, state_reset


def _sweep_stale_staging_dirs(now: float | None = None) -> int:
    now = time.time() if now is None else now
    removed = 0
    for path in glob.glob(os.path.join(tempfile.gettempdir(), _STAGING_PREFIX + "*")):
        try:
            if now - os.path.getmtime(path) > _STALE_STAGING_DIR_AGE:
                shutil.rmtree(path)
                removed += 1
        except OSError:
            continue
    return removed


def _reap_once() -> None:
    with _REGISTRY.lock:
        expired = _pop_idle_expired(time.monotonic(), _KERNEL_IDLE_TIMEOUT)
    for doomed in expired:
        doomed.teardown()
    _sweep_stale_staging_dirs()


def _ensure_background_reaper() -> None:
    global _REAPER_STARTED
    with _REGISTRY.lock:
        if _REAPER_STARTED:
            return
        _REAPER_STARTED = True
    threading.Thread(target=_background_reaper, daemon=True,
                     name="kitsune-kernel-idle-reaper").start()


def _background_reaper() -> None:
    while True:
        time.sleep(min(_REAPER_INTERVAL_CEIL,
                       max(_REAPER_INTERVAL_FLOOR, _KERNEL_IDLE_TIMEOUT / 6.0)))
        try:
            _reap_once()
        except Exception:
            logger.exception("kernel idle reaper pass failed; retrying next interval")


# ---------------------------------------------------------------------------
# Cell execution + result assembly
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_CREDENTIAL_RE = re.compile(
    r"(?i)(sk-[a-zA-Z0-9]{16,}|(?:api[_-]?key|access[_-]?token|authorization|bearer)"
    r"['\"]?\s*[:=]\s*['\"]?[a-zA-Z0-9_\-./]{16,})"
)


def _clean_output(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    return _CREDENTIAL_RE.sub("***", text)


def _head_tail_split(total: int, *, head_frac: float = 0.4) -> tuple[int, int]:
    head = max(1, int(total * head_frac))
    tail = max(1, total - head)
    return head, tail


def _truncate_stdout_text(stdout_text: str) -> tuple[str, dict[str, Any]]:
    """Cap stdout by bytes (40% head / 60% tail) with explicit truncation metadata."""
    stdout_bytes = stdout_text.encode("utf-8", errors="replace")
    total = len(stdout_bytes)
    captured = min(total, MAX_STDOUT_BYTES)
    metadata: dict[str, Any] = {"stdout_truncated": total > captured,
                                "stdout_bytes_captured": captured,
                                "stdout_bytes_total": total,
                                "stdout_bytes_omitted": total - captured}
    if total <= MAX_STDOUT_BYTES:
        return stdout_bytes.decode("utf-8", errors="replace"), metadata
    head_bytes, tail_bytes = _head_tail_split(MAX_STDOUT_BYTES)
    notice = f"\n\n[... stdout truncated: {total - captured} of {total} bytes omitted ...]\n\n"
    text = (stdout_bytes[:head_bytes].decode("utf-8", errors="replace")
            + notice
            + stdout_bytes[-tail_bytes:].decode("utf-8", errors="replace"))
    metadata["warning"] = (
        "execute_code stdout was truncated (head/tail shown); the script did run. "
        "Re-run only with narrower output if the omitted data is required."
    )
    spill_path = _spill_full_stdout(stdout_text)
    if spill_path:
        metadata["stdout_spill_path"] = spill_path
        metadata["warning"] = (
            f"execute_code stdout was truncated (head/tail shown); the script did run. "
            f"FULL output saved to {spill_path} — page it with read_file("
            f'path="{spill_path}", offset=...) instead of re-running.'
        )
    return text, metadata


def _spill_full_stdout(stdout_text: str) -> str | None:
    """Best-effort: write full stdout next to the kernel staging area and return
    its path (None on failure — the truncated inline output is still returned)."""
    try:
        import hashlib
        spill_root = Path(tempfile.gettempdir()) / "kitsune_exec_spill"
        spill_root.mkdir(parents=True, exist_ok=True)
        if len(stdout_text) > _MAX_SPILLED_STDOUT_BYTES:
            stdout_text = (stdout_text[:_MAX_SPILLED_STDOUT_BYTES]
                           + f"\n\n[... spill capped at {_MAX_SPILLED_STDOUT_BYTES:,} bytes ...]")
        digest = hashlib.sha256(stdout_text.encode("utf-8", errors="replace")).hexdigest()[:12]
        path = spill_root / f"stdout-{digest}.txt"
        path.write_text(stdout_text, encoding="utf-8", errors="replace")
        return str(path)
    except Exception as exc:
        logger.debug("Failed to spill execute_code stdout: %s", exc)
        return None


def _await_cell(kernel: SessionKernel, timeout: int, is_interrupted) -> tuple[str, dict[str, Any]]:
    """Wait for the cell's reply; returns (host status, payload)."""
    deadline = time.monotonic() + timeout if timeout else None
    while True:
        if is_interrupted():
            return "interrupted", {}
        if deadline is not None and time.monotonic() > deadline:
            return "timeout", {}
        try:
            payload = kernel.response_q.get(timeout=0.05)
        except queue.Empty:
            continue
        if payload.get("status") in ("kernel-eof", "protocol-error"):
            return "error", payload
        return "success", payload


def _with_stderr(stdout_text: str, stderr_text: str) -> str:
    return stdout_text + "\n--- stderr ---\n" + stderr_text


def _format_interrupted_output(stdout_text: str) -> str:
    return stdout_text + "\n\n\u23f3 Interrupted; the session kernel was killed and its state was lost."


def _error_result(error: str, *, tool_calls_made: int = 0, duration: float = 0) -> str:
    body = {
        "status": "error", "exit_code": -1, "error": str(error),
        "output": str(error), "tool_calls_made": tool_calls_made,
        "duration_seconds": round(duration, 2),
        "kernel": {"mode": "session"},
    }
    return json.dumps(body, ensure_ascii=False)


def _sandbox_failure_hint(stderr_text: str, enabled_tools) -> str | None:
    """Map well-known sandbox script failures to one actionable recovery hint."""
    if not stderr_text:
        return None
    window = stderr_text[:4000]
    rules = (
        (r"cannot import name '(\w+)' from 'kitsune_tools'", "import kitsune_tools"),
        (r"NameError: name '(json_parse|shell_quote|retry)' is not defined",
         "Import the helper first: from kitsune_tools import {1}"),
        (r"ModuleNotFoundError: No module named '([\w.]+)'",
         "'{1}' is not installed in the kernel interpreter. Use Python stdlib inside "
         "execute_code, or run the code through run_powershell with the project venv."),
        (r"TypeError: string indices must be integers|AttributeError: 'str' object has no attribute 'get'",
         "Tool functions in the kernel return DICTS (already parsed) — do not json.loads() them."),
    )
    try:
        for pattern, template in rules:
            m = re.search(pattern, window)
            if m:
                if "{1}" in template and m.lastindex and m.lastindex >= 1:
                    return template.format(m.group(0), m.group(1))
                return template.format(m.group(0))
    except Exception:
        return None
    return None


def _cell_result(kernel: SessionKernel, key: tuple, status: str, payload: dict[str, Any], *,
                 timeout: int, sandbox_tools: frozenset, reused: bool,
                 state_reset: bool, exec_start: float) -> dict[str, Any]:
    """Assemble the tool result for one settled cell."""
    if status in ("timeout", "interrupted"):
        _REGISTRY.discard(key, kernel)
    duration = round(time.monotonic() - exec_start, 2)
    kernel.execution_count = int(payload.get("execution_count", kernel.execution_count + 1))
    stderr_raw = kernel.stderr.drain()
    clean = _clean_output
    stdout_text, stdout_metadata = _truncate_stdout_text(
        clean(str(payload.get("stdout", "")) + kernel.raw.drain())
    )
    cell_stderr = clean(str(payload.get("stderr", "")) + stderr_raw)
    cell_status = payload.get("status", "")
    result: dict[str, Any] = {
        "status": status, "output": stdout_text, "exit_code": 0,
        "tool_calls_made": kernel.tool_call_counter[0], "duration_seconds": duration,
        "kernel": {"mode": "session", "reused": reused,
                   "execution_count": kernel.execution_count, "state_reset": state_reset},
    }
    result.update(stdout_metadata)
    tool_errors = tool_errors_since(kernel.tool_call_log, kernel.cell_log_start)
    if tool_errors:
        result["tool_errors"] = tool_errors
    cell_spill = str(payload.get("stdout_spill_path", "") or "")
    if cell_spill and payload.get("stdout_clipped"):
        result["stdout_spill_path"] = cell_spill
        result["warning"] = (
            f"Cell stdout exceeded the inline cap; head shown. FULL output saved to {cell_spill} "
            f'— page it with read_file(path="{cell_spill}", offset=...) instead of re-running. '
            "(Kernel state persists: printing a narrower slice next call is often cheaper.)"
        )
    if status == "timeout":
        message = (f"Cell timed out after {timeout}s; the session kernel was killed and its "
                   "state was lost. The next execute_code call starts a fresh kernel.")
        result.update(exit_code=-1, error=message,
                      output=(stdout_text + "\n\n\u23f0 " + message) if stdout_text else ("\u23f0 " + message))
    elif status == "interrupted":
        result.update(exit_code=-1, output=_format_interrupted_output(stdout_text),
                      error="Interrupted; the session kernel was killed and its state was lost.")
    elif cell_status == "error":
        trace = clean(str(payload.get("traceback", "")))
        result.update(status="error", exit_code=1, error=trace or "Cell raised an exception.",
                      output=_with_stderr(stdout_text, cell_stderr + trace) if (cell_stderr or trace) else stdout_text)
        hint = _sandbox_failure_hint(trace, enabled_tools=sandbox_tools)
        if hint:
            result["hint"] = hint
    elif cell_status == "exit":
        _REGISTRY.discard(key, kernel)
        result["kernel"]["ended"] = True
        if cell_stderr:
            result["output"] = _with_stderr(stdout_text, cell_stderr)
    elif status == "error":
        _REGISTRY.discard(key, kernel)
        result.update(exit_code=-1, error="The session kernel died while running the cell"
                      + (": " + stderr_raw.strip() if stderr_raw.strip() else "."))
    elif cell_stderr:
        result["output"] = _with_stderr(stdout_text, cell_stderr)
    return result


def execute_in_session_kernel(
    code: str, *, owner: str, child_python: str, child_cwd: str,
    sandbox_tools: frozenset, timeout: int, max_tool_calls: int, reset: bool,
    is_interrupted, dispatch: Callable[[str, dict], str] | None = None,
) -> str:
    """Run one cell in the (owner, python, cwd, tools) session kernel.

    ``owner`` keys the kernel (pass the session/agent id so state survives across
    turns). ``dispatch`` is the script-side tool executor (e.g. the agent handler
    registry); ``None`` disables script-side tool calls. Returns a JSON string.
    """
    key = (owner or "", child_python, child_cwd, tuple(sorted(sandbox_tools)))
    exec_start = time.monotonic()
    kernel, state_reset = _acquire_kernel(key, reset)
    try:
        return _run_cell(kernel, key, code, owner=owner, child_python=child_python,
                         child_cwd=child_cwd, sandbox_tools=sandbox_tools,
                         timeout=timeout, max_tool_calls=max_tool_calls,
                         is_interrupted=is_interrupted, exec_start=exec_start,
                         state_reset=state_reset, dispatch=dispatch)
    finally:
        with _REGISTRY.lock:
            kernel.attached -= 1
            kernel.last_used = time.monotonic()
            orphaned = kernel.attached == 0 and _KERNELS.get(key) is not kernel
        if orphaned:
            kernel.teardown()


def _run_cell(kernel: SessionKernel, key: tuple, code: str, *, owner: str,
              child_python: str, child_cwd: str, sandbox_tools: frozenset,
              timeout: int, max_tool_calls: int, is_interrupted,
              exec_start: float, state_reset: bool,
              dispatch: Callable[[str, dict], str] | None) -> str:
    reused = kernel.proc is not None
    authority = CellAuthority(dispatch)
    with kernel.lock:
        try:
            if kernel.proc is None:
                _spawn(kernel, child_python=child_python, child_cwd=child_cwd,
                       sandbox_tools=sandbox_tools, max_tool_calls=max_tool_calls)
            assert kernel.proc is not None and kernel.proc.stdin is not None
            kernel.tool_call_counter[0] = 0
            kernel.cell_log_start = len(kernel.tool_call_log)
            kernel.raw.drain(), kernel.stderr.drain()
            kernel.cell_authority = authority
            kernel.proc.stdin.write(
                (json.dumps({"id": uuid.uuid4().hex, "code": code}) + "\n").encode("utf-8")
            )
            kernel.proc.stdin.flush()
            status, payload = _await_cell(kernel, timeout, is_interrupted)
            result = _cell_result(
                kernel, key, status, payload,
                timeout=timeout, sandbox_tools=sandbox_tools, reused=reused,
                state_reset=state_reset, exec_start=exec_start,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover
            logger.error("session kernel failed: %s: %s", type(exc).__name__, exc, exc_info=True)
            _REGISTRY.discard(key, kernel)
            return _error_result(str(exc), tool_calls_made=kernel.tool_call_counter[0],
                                 duration=round(time.monotonic() - exec_start, 2))
        finally:
            authority.retire()
