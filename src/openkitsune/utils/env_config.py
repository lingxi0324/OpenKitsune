"""Shared transactional updates for ``.env`` and RuntimeState configuration."""

from __future__ import annotations

import locale
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openkitsune.utils import atomic_io

logger = logging.getLogger(__name__)


def strip_utf8_bom(raw: bytes) -> bytes:
    """Remove a UTF-8 BOM without altering other encodings."""
    return raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw


def read_text_robust(path: Path) -> str:
    """Read text with UTF-8 BOM handling and a platform-encoding fallback."""
    path = Path(path)
    if not path.exists():
        return ""
    raw = strip_utf8_bom(path.read_bytes())
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Failed to decode %s as UTF-8, falling back to system encoding", path)
        try:
            return raw.decode(locale.getpreferredencoding(False), errors="replace")
        except Exception:
            return raw.decode("utf-8", errors="replace")


def parse_env_content(content: str) -> dict[str, str]:
    """Parse dotenv content using the same escaping rules as the shared writer."""
    content = content.removeprefix("\ufeff")
    env: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            inner = value[1:-1]
            if "\\" in inner:
                inner = inner.replace("\\\\", "\x00").replace('\\"', '"').replace("\x00", "\\")
            value = inner
        else:
            for separator in (" #", "\t#"):
                index = value.find(separator)
                if index != -1:
                    value = value[:index].rstrip()
                    break
        env[key] = value
    return env


def read_env_file(path: Path) -> dict[str, str]:
    """Read a dotenv file without mutating ``os.environ``."""
    return parse_env_content(read_text_robust(path))


def _needs_quoting(value: str) -> bool:
    if not value:
        return False
    if value[0] in (" ", "\t") or value[-1] in (" ", "\t"):
        return True
    if value[0] in ('"', "'"):
        return True
    return any(ch in value for ch in (" ", "#", '"', "'", "\\"))


def quote_env_value(value: str) -> str:
    """Quote values that would not survive a dotenv round trip unchanged."""
    if not _needs_quoting(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env_content(
    existing: str,
    entries: dict[str, str],
    *,
    delete_keys: set[str] | None = None,
) -> str:
    """Merge non-empty entries and explicit deletions into dotenv content."""
    delete_keys = delete_keys or set()
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in delete_keys:
            updated_keys.add(key)
            continue
        if key not in entries:
            new_lines.append(line)
            continue
        value = entries[key]
        new_lines.append(line if value == "" else f"{key}={quote_env_value(value)}")
        updated_keys.add(key)

    for key, value in entries.items():
        if key not in updated_keys and value != "":
            new_lines.append(f"{key}={quote_env_value(value)}")

    return "\n".join(new_lines) + "\n"


def update_env_file(
    env_path: Path,
    *,
    entries: dict[str, str],
    delete_keys: set[str] | None = None,
) -> bool:
    """Apply one serialized read-modify-write transaction to a dotenv file.

    All runtime writers that share an ``.env`` file must use this entry point
    (or hold ``path_transaction_lock`` themselves) so unrelated concurrent
    updates cannot overwrite each other.
    """
    env_path = Path(env_path)
    delete_keys = set(delete_keys or ())
    written_entries = {key: value for key, value in entries.items() if value != ""}

    with atomic_io.path_transaction_lock(env_path):
        env_existed = env_path.is_file()
        if not written_entries and not (delete_keys and env_existed):
            return False
        existing = env_path.read_text(encoding="utf-8", errors="replace") if env_existed else ""
        content = update_env_content(
            existing,
            written_entries,
            delete_keys=delete_keys,
        )
        atomic_io.safe_write(env_path, content)
        return True


@dataclass(frozen=True)
class EnvConfigCommit:
    settings_changed: list[str]


def commit_env_config(
    env_path: Path,
    *,
    entries: dict[str, str],
    delete_keys: set[str] | None = None,
    settings: Any,
    runtime_state: Any,
    runtime_updates: dict[str, Any] | None = None,
    persist_runtime: bool = False,
) -> EnvConfigCommit:
    """Commit dotenv and RuntimeState changes as one compensating transaction.

    RuntimeState is committed last. Before that point, any dotenv or Settings
    failure can be rolled back without another durable store having advanced.
    """
    env_path = Path(env_path)
    delete_keys = set(delete_keys or ())
    runtime_updates = dict(runtime_updates or {})
    written_entries = {key: value for key, value in entries.items() if value != ""}
    touched_env_keys = set(written_entries) | delete_keys

    with atomic_io.path_transaction_lock(env_path):
        env_existed = env_path.is_file()
        existing = env_path.read_text(encoding="utf-8", errors="replace") if env_existed else ""
        environment_previous = {key: os.environ.get(key) for key in touched_env_keys}
        env_mutated = False

        try:
            if written_entries or (delete_keys and env_existed):
                content = update_env_content(
                    existing,
                    written_entries,
                    delete_keys=delete_keys,
                )
                atomic_io.safe_write(env_path, content)
                env_mutated = True

            for key, value in written_entries.items():
                os.environ[key] = value
            for key in delete_keys:
                os.environ.pop(key, None)

            settings_changed = settings.reload() if touched_env_keys else []
            if runtime_updates or persist_runtime:
                runtime_state.save_updates(**runtime_updates)
            return EnvConfigCommit(settings_changed=list(settings_changed))
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                if env_existed:
                    atomic_io.safe_write(env_path, existing)
                elif env_mutated or env_path.exists():
                    env_path.unlink(missing_ok=True)
            except Exception as rollback_exc:
                rollback_errors.append(f".env: {rollback_exc}")

            for key, previous_value in environment_previous.items():
                if previous_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous_value

            if touched_env_keys:
                try:
                    settings.reload()
                except Exception as rollback_exc:
                    rollback_errors.append(f"settings: {rollback_exc}")

            if rollback_errors:
                raise RuntimeError(
                    f"Configuration write failed ({exc}); rollback also failed: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise
