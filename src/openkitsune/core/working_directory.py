"""Session-scoped working-directory helpers.

The configuration workspace (``settings.project_root``) owns OpenKitsune state.
User file operations use the working directory carried by the current
``PolicyContext`` so concurrent conversations never need process-wide chdir.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


class WorkingDirectoryError(ValueError):
    """Raised when a requested conversation working directory is unusable."""


def working_directory_feature_enabled() -> bool:
    """Return whether per-conversation directories are active."""
    try:
        from .feature_flags import is_enabled

        return is_enabled("session_working_directory_v1")
    except Exception:
        return True


def config_workspace() -> Path:
    """Return the process-level configuration workspace."""
    try:
        from ..config import settings

        return Path(settings.project_root).expanduser().resolve(strict=False)
    except Exception:
        return Path.cwd().resolve(strict=False)


def normalize_working_directory(
    value: str | os.PathLike[str] | None,
    *,
    default: str | os.PathLike[str] | None = None,
    must_exist: bool = True,
) -> Path:
    """Validate and canonicalize a working directory.

    API callers must supply absolute paths. Internal callers may pass a
    resolved ``default`` for legacy sessions. UNC paths are intentionally
    rejected in the first version because the existing path guard cannot
    provide reliable link and share-boundary guarantees for them.
    """
    raw = str(value or default or "").strip()
    if not raw:
        raise WorkingDirectoryError("working_directory is required")
    if len(raw) > 4096:
        raise WorkingDirectoryError("working_directory is too long")
    if any(ord(ch) < 32 for ch in raw):
        raise WorkingDirectoryError("working_directory contains control characters")
    if raw.startswith("\\\\"):
        raise WorkingDirectoryError("UNC working directories are not supported")

    # WSL / 非 Windows 平台兼容：历史会话遗留的 Windows 绝对路径
    # （如 C:\Users\...）在 POSIX 语义下 is_absolute() 为 False，会把
    # sessions.json 里所有旧会话的 history/消息接口打成 500。
    # 此处将其映射为 /mnt/<drive>/...，仅 os.name != "nt" 时生效，
    # Windows 侧行为完全不变。
    if os.name != "nt" and len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        drive = raw[0].lower()
        rest = raw[2:].lstrip("\\/").replace("\\", "/")
        raw = f"/mnt/{drive}/{rest}"

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise WorkingDirectoryError("working_directory must be an absolute path")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkingDirectoryError(f"working_directory cannot be resolved: {exc}") from exc
    if must_exist and not resolved.is_dir():
        raise WorkingDirectoryError("working_directory does not exist or is not a directory")
    return resolved


def session_working_directory(session: Any | None, *, require_available: bool = False) -> Path:
    """Return a session's immutable directory, with legacy config fallback."""
    if not working_directory_feature_enabled():
        return normalize_working_directory(config_workspace(), must_exist=require_available)
    raw = getattr(session, "working_directory", None) if session is not None else None
    if raw is not None and not isinstance(raw, (str, Path)):
        raw = None
    fallback = config_workspace()
    try:
        return normalize_working_directory(
            raw,
            default=fallback,
            must_exist=require_available,
        )
    except WorkingDirectoryError:
        if raw:
            raise
        return fallback


def current_working_directory(*, require_available: bool = False) -> Path:
    """Resolve the current task's directory from the PolicyContext."""
    if not working_directory_feature_enabled():
        return normalize_working_directory(config_workspace(), must_exist=require_available)
    raw: str | Path | None = None
    try:
        from .policy_v2.context import get_current_context

        ctx = get_current_context()
        if ctx is not None:
            raw = getattr(ctx, "working_directory", None)
    except Exception:
        raw = None
    return normalize_working_directory(
        raw,
        default=config_workspace(),
        must_exist=require_available,
    )


def resolve_working_path(
    value: str | os.PathLike[str],
    *,
    base: str | os.PathLike[str] | None = None,
    strict: bool = False,
) -> Path:
    """Resolve an absolute or task-relative path without changing process cwd."""
    raw = str(value or "")
    if not raw:
        raise WorkingDirectoryError("path is required")
    if len(raw) > 4096 or any(ord(ch) < 32 for ch in raw):
        raise WorkingDirectoryError("invalid path")
    if raw.startswith("\\\\"):
        raise WorkingDirectoryError("UNC paths are not supported")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        root = (
            normalize_working_directory(base, must_exist=True)
            if base is not None
            else current_working_directory(require_available=True)
        )
        candidate = root / candidate
    try:
        return candidate.resolve(strict=strict)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkingDirectoryError(f"path cannot be resolved: {exc}") from exc


def is_within(path: Path, root: Path) -> bool:
    """Cross-platform containment check on canonical paths."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        if os.name != "nt":
            return False
        try:
            path_s = os.path.normcase(str(path.resolve(strict=False)))
            root_s = os.path.normcase(str(root.resolve(strict=False)))
            return path_s == root_s or path_s.startswith(root_s + os.sep)
        except (OSError, RuntimeError, ValueError):
            return False


_FILE_MENTION_RE = re.compile(r'@(?:"([^"]+)"|([^\s]+))')


def resolve_text_file_mentions(text: str, session: Any | None) -> list[tuple[str, Path]]:
    """Resolve CLI/IM ``@path`` mentions without treating normal @names as files."""
    if not text or session is None:
        return []
    try:
        root = session_working_directory(session, require_available=True)
    except WorkingDirectoryError:
        return []
    resolved_mentions: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for match in _FILE_MENTION_RE.finditer(text):
        raw = (match.group(1) or match.group(2) or "").rstrip(".,;:!?，。；：！？")
        if not raw or raw.lower().startswith("org:") or Path(raw).is_absolute():
            continue
        try:
            candidate = (root / raw).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if not candidate.is_file() or not is_within(candidate, root):
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        resolved_mentions.append((raw, candidate))
        if len(resolved_mentions) >= 20:
            break
    return resolved_mentions
