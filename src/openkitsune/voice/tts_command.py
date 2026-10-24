"""用户自定义 shell 命令 TTS 引擎 —— 迁移自 hermes-agent ``tools/tts_command_provider.py``（瘦身版）。

``tts.providers.<name>`` 声明命令型 provider：:

    {"tts": {"providers": {"piper-local": {
        "type": "command",
        "command": "piper -f {output_path} < {input_path}",
        "voice": "zh_CN-huayan-medium",
        "timeout": 120
    }}}}

占位符（``{name}``）按所在引号上下文做 shell 安全转义，``{{``/``}}`` 保持字面。
TTS 占位符：``{input_path}``/``{text_path}``、``{output_path}``、``{format}``、
``{voice}``、``{model}``、``{speed}``。内置 provider 名（edge/openai/...）永远优先于
同名 ``providers`` 条目，不允许被命令 provider 顶替。
"""
from __future__ import annotations

import os
import queue
import re
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .config import BUILTIN_TTS_PROVIDERS

DEFAULT_COMMAND_TTS_TIMEOUT_SECONDS = 120
DEFAULT_COMMAND_TTS_OUTPUT_FORMAT = "mp3"
COMMAND_TTS_OUTPUT_FORMATS = frozenset({"mp3", "wav", "ogg", "flac", "m4a", "aac", "amr", "opus"})
DEFAULT_COMMAND_TTS_MAX_TEXT_LENGTH = 5000


# ---- 占位符渲染 ----
def shell_quote_context(command_template: str, position: int) -> str | None:
    """返回 *position* 前生效的 shell 引号字符（'/"）或 None。"""
    quote: str | None = None
    escaped = False
    i = 0
    while i < position:
        char = command_template[i]
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "\\":
            i += 1
        i += 1
    return quote


def quote_command_placeholder(value: str, quote_context: str | None) -> str:
    """按模板中的引号上下文转义占位符值。"""
    if quote_context == "'":
        return value.replace("'", r"'\''")
    if quote_context == '"':
        return value.replace("\\", "\\\\").replace('"', r'\"').replace("$", r"\$").replace("`", r"\`")
    return subprocess.list2cmdline([value]) if os.name == "nt" else shlex.quote(value)


def render_command_template(command_template: str, placeholders: dict[str, str]) -> str:
    """替换 ``{name}`` 占位符（引号感知），保留 ``{{``/``}}``。"""
    names = "|".join(re.escape(name) for name in placeholders)
    pattern = re.compile(rf"(?<!\$)(?:\{{\{{(?P<double>{names})\}}\}}|\{{(?P<single>{names})\}})")
    replacements: list[tuple[str, str]] = []

    def replace_match(match: re.Match[str]) -> str:
        name = match.group("double") or match.group("single")
        token = f"__OK_CMD_PLACEHOLDER_{len(replacements)}__"
        quoted = quote_command_placeholder(placeholders[name], shell_quote_context(command_template, match.start()))
        replacements.append((token, quoted))
        return token

    rendered = pattern.sub(replace_match, command_template).replace("{{", "{").replace("}}", "}")
    for token, value in replacements:
        rendered = rendered.replace(token, value)
    return rendered


# ---- 进程执行（空闲超时 + 进程树清理）----
def _windows_hide_flags() -> int:
    """CREATE_NO_WINDOW（0x08000000）| CREATE_NEW_PROCESS_GROUP（0x200）：隐藏控制台窗口。"""
    return 0x08000000 | 0x00000200


def _terminate_tree(proc: subprocess.Popen) -> None:
    """尽力终止命令进程及其子进程树（Windows 用 taskkill /T，POSIX 用进程组信号）。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, stdin=subprocess.DEVNULL, creationflags=_windows_hide_flags(), check=False)
            return
        except Exception:
            proc.kill()
            return
    import signal
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def run_command_provider(command: str, timeout: float) -> subprocess.CompletedProcess:
    """执行命令型 provider 的 shell 命令，带进程树空闲清理。

    *timeout* 是空闲超时：命令持续产出输出则重置计时（慢但活的 provider 存活，
    静默卡死的被杀）。Windows 下子进程隐藏控制台窗口。
    """
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = _windows_hide_flags()
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, **kwargs)
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}
    open_streams = {"stdout", "stderr"}

    def read_stream(name: str, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                output_queue.put((name, chunk))
        finally:
            output_queue.put((name, None))

    readers = [
        threading.Thread(target=read_stream, args=(name, stream), daemon=True)
        for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while open_streams:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            name, chunk = output_queue.get(timeout=min(0.05, remaining))
        except queue.Empty:
            continue
        if chunk is None:
            open_streams.discard(name)
            continue
        chunks[name].append(chunk)
        deadline = time.monotonic() + timeout
    if not timed_out:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
    if timed_out:
        _terminate_tree(proc)
        for reader in readers:
            reader.join(timeout=0.5)
    stdout, stderr = "".join(chunks["stdout"]), "".join(chunks["stderr"])
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, command, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def command_failure_detail(exc: subprocess.CalledProcessError) -> str:
    """``stderr: ...; stdout: ...`` 或 ``no command output``。"""
    parts = [f"{stream}: {text.strip()}" for stream, text in (("stderr", exc.stderr), ("stdout", exc.stdout)) if text]
    return "; ".join(parts) or "no command output"


# ---- 配置层 ----
def _get_provider_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    section_cfg = config.get(name) if isinstance(config, dict) else None
    return section_cfg if isinstance(section_cfg, dict) else {}


def _named_provider_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    """``tts.providers.<name>``（规范位置）；对非内置名兼容 ``tts.<name>``。"""
    section_cfg = _get_provider_section(config, "providers").get(name)
    if isinstance(section_cfg, dict):
        return section_cfg
    return _get_provider_section(config, name) if name.lower() not in BUILTIN_TTS_PROVIDERS else {}


def is_command_provider_config(config: dict[str, Any]) -> bool:
    """*config* 是否声明命令型 provider（有非空 ``command``）。"""
    if not isinstance(config, dict):
        return False
    ptype = str(config.get("type") or "").strip().lower()
    command = config.get("command")
    return ptype in ("", "command") and isinstance(command, str) and bool(command.strip())


def resolve_command_provider_config(provider: str, tts_config: dict[str, Any]) -> dict[str, Any] | None:
    """解析命令型 provider 配置；内置名/未知/非命令返回 None。"""
    key = (provider or "").lower().strip()
    if not key or key in BUILTIN_TTS_PROVIDERS:
        return None
    named = _named_provider_config(tts_config, key)
    return named if is_command_provider_config(named) else None


def iter_command_providers(tts_config: dict[str, Any]):
    """产出每个已声明的命令型 provider 的 (name, config)。"""
    for name, cfg in _get_provider_section(tts_config, "providers").items():
        if isinstance(name, str) and name.lower() not in BUILTIN_TTS_PROVIDERS and is_command_provider_config(cfg):
            yield name, cfg


def command_tts_timeout(config: dict[str, Any]) -> float:
    """命令超时（秒）：``timeout`` 优先，坏值回退默认。"""
    raw = config.get("timeout", config.get("timeout_seconds", DEFAULT_COMMAND_TTS_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_COMMAND_TTS_TIMEOUT_SECONDS)
    return value if value > 0 else float(DEFAULT_COMMAND_TTS_TIMEOUT_SECONDS)


def command_tts_output_format(config: dict[str, Any], output_path: str | None = None) -> str:
    """输出格式：输出路径后缀 > ``format``/``output_format`` > mp3。"""
    suffix = Path(output_path).suffix.lower().strip().lstrip(".") if output_path else ""
    if suffix in COMMAND_TTS_OUTPUT_FORMATS:
        return suffix
    raw = config.get("format") or config.get("output_format") or DEFAULT_COMMAND_TTS_OUTPUT_FORMAT
    fmt = str(raw).lower().strip().lstrip(".")
    return fmt if fmt in COMMAND_TTS_OUTPUT_FORMATS else DEFAULT_COMMAND_TTS_OUTPUT_FORMAT


# ---- 执行 ----
def generate_command_tts(
    text: str, output_path: str, provider_name: str, config: dict[str, Any], tts_config: dict[str, Any],
) -> str:
    """运行用户配置的 shell 命令合成语音，返回其写出的音频路径。

    异常：``ValueError``（配置缺失）、``RuntimeError``（超时 / 非零退出 / 无输出）。
    """
    command_template = str(config.get("command") or "").strip()
    if not command_template:
        raise ValueError(f"tts.providers.{provider_name}.command is not configured")
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    timeout = command_tts_timeout(config)
    fmt = command_tts_output_format(config, str(output))
    if output.suffix.lower().lstrip(".") not in COMMAND_TTS_OUTPUT_FORMATS:
        output = output.with_suffix(f".{fmt}")
    with tempfile.TemporaryDirectory() as tmpdir:
        text_path = Path(tmpdir) / "input.txt"
        text_path.write_text(text, encoding="utf-8")
        placeholders = {
            "input_path": str(text_path), "text_path": str(text_path), "output_path": str(output),
            "format": fmt,
            "voice": str(config.get("voice", "")),
            "model": str(config.get("model", "")),
            "speed": str(config.get("speed", tts_config.get("speed", ""))),
        }
        command = render_command_template(command_template, placeholders)
        try:
            run_command_provider(command, timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"TTS provider '{provider_name}' timed out after {timeout:g}s") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"TTS provider '{provider_name}' exited with code {exc.returncode}: {command_failure_detail(exc)}"
            ) from exc
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError(f"TTS provider '{provider_name}' produced no output at {output}")
    return str(output)
