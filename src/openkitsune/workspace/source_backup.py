"""Source-code backup & restore utilities.

Unlike :mod:`openkitsune.workspace.backup` (which packs runtime data), this
module packs the project's *source tree and configuration* into a
timestamped ``.zip`` archive so a working tree can be restored to an
earlier point in time.

Archive layout::

    openkitsune-source-<project>-<YYYYmmdd_HHMMSS>[-<label>].zip
    ├── manifest.json
    ├── src/...
    ├── apps/...
    └── ...

The timestamp in the filename is the restore marker; ``manifest.json``
carries the same timestamp plus file counts for quick inspection.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_FILE = "manifest.json"
SOURCE_BACKUP_FORMAT_VERSION = 1
SOURCE_BACKUP_KIND = "source"
SOURCE_BACKUP_PREFIX = "openkitsune-source"
DEFAULT_MAX_BACKUPS = 10

# ── Inclusion / exclusion rules ──────────────────────────────────────

# ``.env`` holds secrets, so it is opt-in via ``include_env``.
ENV_FILES = (".env", ".env.local")

# Top-level directories that never belong to a source backup (runtime data,
# dependencies, caches, and the archive directory itself).
_EXCLUDE_TOP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "data",
    "logs",
    "tools-tmp",
    "backups",
    "workspaces",
    "htmlcov",
    ".idea",
}

# Directory names skipped at any depth.
_EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".vite",
    "dist",
    "dist-web",
    "dist-cli",
    "target",
    "htmlcov",
    ".idea",
    ".gradle",
    ".cxx",
    ".externalNativeBuild",
    "Pods",
}

# Relative paths skipped even though their parent directory is backed up.
_EXCLUDE_REL_DIRS = {
    "identity/runtime",
    "apps/setup-center/src-tauri/resources",
}

# File extensions that are build output, caches, databases, or binaries.
_EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".db",
    ".db-shm",
    ".db-wal",
    ".db-journal",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".bak",
    ".tsbuildinfo",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
}

_EXCLUDE_FILENAMES = {
    ".DS_Store",
    "Thumbs.db",
    ".coverage",
    "npm-debug.log",
    "yarn-error.log",
}


def default_output_dir(project_root: Path) -> Path:
    """Default archive location: ``<project>/backups/source``."""
    return Path(project_root).resolve() / "backups" / "source"


def _sanitize_label(label: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", (label or "").strip()).strip("-._")
    return cleaned[:48]


def _archive_name(project_id: str, timestamp: str, label: str) -> str:
    suffix = f"-{label}" if label else ""
    return f"{SOURCE_BACKUP_PREFIX}-{project_id}-{timestamp}{suffix}.zip"


def _archive_pattern(project_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(SOURCE_BACKUP_PREFIX)}-{re.escape(project_id)}-"
        rf"\d{{8}}_\d{{6}}(?:-.+)?\.zip$"
    )


def _is_excluded_dir(rel: str, dirname: str) -> bool:
    if dirname in _EXCLUDE_DIR_NAMES:
        return True
    # Any frontend build output (``dist``, ``dist-web``, ``dist-web-new``...).
    if dirname == "dist" or dirname.startswith("dist-"):
        return True
    if not rel and dirname in _EXCLUDE_TOP_DIRS:
        return True
    # Nested ``build/`` directories are toolchain output; the repo-root
    # ``build/`` directory holds source build scripts and stays included.
    if rel and dirname == "build":
        return True
    rel_posix = f"{rel}/{dirname}" if rel else dirname
    return rel_posix in _EXCLUDE_REL_DIRS


def _is_excluded_file(rel_posix: str, filename: str) -> bool:
    if filename in _EXCLUDE_FILENAMES:
        return True
    _, ext = os.path.splitext(filename)
    return ext.lower() in _EXCLUDE_EXTENSIONS


def _iter_files(project_root: Path, include_env: bool) -> list[tuple[Path, str]]:
    """Collect ``(absolute_path, archive_relative_path)`` entries to back up.

    Walks the whole project and prunes runtime/build directories, so new
    source or config files are covered without updating a whitelist.
    """
    entries: list[tuple[Path, str]] = []

    for root, dirs, files in os.walk(project_root):
        root_path = Path(root)
        rel_root = (
            "" if root_path == project_root else root_path.relative_to(project_root).as_posix()
        )
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(rel_root, d))

        for filename in sorted(files):
            if filename in ENV_FILES and not include_env:
                continue
            rel_posix = f"{rel_root}/{filename}" if rel_root else filename
            if _is_excluded_file(rel_posix, filename):
                continue
            full = root_path / filename
            if full.is_file():
                entries.append((full, rel_posix))

    return entries


# ── Backup creation ─────────────────────────────────────────────────


def create_source_backup(
    project_root: Path,
    output_dir: Path | str | None = None,
    *,
    label: str = "",
    include_env: bool = False,
    max_backups: int = DEFAULT_MAX_BACKUPS,
) -> Path:
    """Pack the project's source tree into a timestamped zip archive.

    Returns the path of the created archive.
    """
    project_root = Path(project_root).resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_root}")

    out = Path(output_dir).resolve() if output_dir else default_output_dir(project_root)
    out.mkdir(parents=True, exist_ok=True)

    project_id = project_root.name or "project"
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    archive_label = _sanitize_label(label)
    zip_path = out / _archive_name(project_id, timestamp, archive_label)

    # Avoid overwriting an archive created within the same second.
    counter = 1
    while zip_path.exists():
        zip_path = out / _archive_name(
            project_id, timestamp, f"{archive_label}-{counter}" if archive_label else str(counter)
        )
        counter += 1

    entries = _iter_files(project_root, include_env)
    if not entries:
        raise ValueError(f"No source files found under {project_root}")

    manifest: dict[str, Any] = {
        "format_version": SOURCE_BACKUP_FORMAT_VERSION,
        "kind": SOURCE_BACKUP_KIND,
        "created_at": now.astimezone(UTC).isoformat(),
        "project_id": project_id,
        "project_root": str(project_root),
        "label": archive_label,
        "include_env": include_env,
    }

    total_size = 0
    written_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for full, rel in entries:
            try:
                zf.write(full, rel)
                total_size += full.stat().st_size
                written_count += 1
            except (PermissionError, OSError) as exc:
                logger.warning(f"[SourceBackup] Skipping {rel}: {exc}")

        manifest["file_count"] = written_count
        manifest["total_size_bytes"] = total_size
        zf.writestr(MANIFEST_FILE, json.dumps(manifest, ensure_ascii=False, indent=2))

    logger.info(
        f"[SourceBackup] Created {zip_path} ({written_count} files, "
        f"{total_size / 1024 / 1024:.1f} MB uncompressed)"
    )

    if max_backups > 0:
        _rotate_backups(out, project_id, max_backups)

    return zip_path


def _rotate_backups(backup_dir: Path, project_id: str, max_backups: int) -> None:
    """Remove oldest source backups so at most ``max_backups`` remain."""
    pattern = _archive_pattern(project_id)
    backups = sorted(
        (f for f in backup_dir.iterdir() if f.is_file() and pattern.match(f.name)),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in backups[max_backups:]:
        try:
            old.unlink()
            logger.info(f"[SourceBackup] Rotated old backup: {old.name}")
        except OSError as exc:
            logger.warning(f"[SourceBackup] Failed to remove {old.name}: {exc}")


# ── Listing ─────────────────────────────────────────────────────────


def list_source_backups(
    backup_dir: Path | str,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """List source backup archives in ``backup_dir``, newest first."""
    directory = Path(backup_dir)
    if not directory.is_dir():
        return []

    pattern = (
        _archive_pattern(project_id)
        if project_id
        else re.compile(rf"^{re.escape(SOURCE_BACKUP_PREFIX)}-.+-\d{{8}}_\d{{6}}(?:-.+)?\.zip$")
    )

    result: list[dict[str, Any]] = []
    candidates = sorted(
        (f for f in directory.iterdir() if f.is_file() and pattern.match(f.name)),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for archive in candidates:
        stat = archive.stat()
        info: dict[str, Any] = {
            "filename": archive.name,
            "path": str(archive),
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        }
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                if MANIFEST_FILE in zf.namelist():
                    info["manifest"] = json.loads(zf.read(MANIFEST_FILE).decode("utf-8"))
        except Exception as exc:
            logger.debug(f"[SourceBackup] Cannot read manifest of {archive.name}: {exc}")
        result.append(info)
    return result


# ── Restore ─────────────────────────────────────────────────────────


def _validate_member_name(name: str) -> None:
    normalized = os.path.normpath(name)
    if normalized.startswith("..") or os.path.isabs(normalized):
        raise ValueError(f"Unsafe path in backup: {name}")
    if re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"Unsafe path in backup: {name}")


def restore_source_backup(
    zip_path: Path | str,
    project_root: Path,
    *,
    backup_dir: Path | str | None = None,
    safety_backup: bool = True,
    max_backups: int = DEFAULT_MAX_BACKUPS,
) -> dict[str, Any]:
    """Restore source files from ``zip_path`` into ``project_root``.

    Existing files are overwritten; files absent from the archive are left
    untouched. When ``safety_backup`` is true, the current tree is archived
    first under ``backup_dir`` (defaults to the archive's directory).
    """
    archive = Path(zip_path).resolve()
    project_root = Path(project_root).resolve()

    if not archive.exists():
        raise FileNotFoundError(f"Backup file not found: {archive}")
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_root}")

    with zipfile.ZipFile(archive, "r") as zf:
        if MANIFEST_FILE not in zf.namelist():
            raise ValueError("Invalid source backup: missing manifest.json")

        manifest = json.loads(zf.read(MANIFEST_FILE).decode("utf-8"))
        if manifest.get("kind") != SOURCE_BACKUP_KIND:
            raise ValueError("Invalid source backup: manifest kind mismatch")
        fmt_ver = manifest.get("format_version", 0)
        if fmt_ver > SOURCE_BACKUP_FORMAT_VERSION:
            raise ValueError(
                f"Backup format version {fmt_ver} is newer than supported "
                f"version {SOURCE_BACKUP_FORMAT_VERSION}"
            )

        members = zf.infolist()
        for member in members:
            if member.filename == MANIFEST_FILE or member.is_dir():
                continue
            _validate_member_name(member.filename)

        safety_path: Path | None = None
        if safety_backup:
            target_dir = Path(backup_dir) if backup_dir else archive.parent
            try:
                safety_path = create_source_backup(
                    project_root,
                    target_dir,
                    label="pre-restore",
                    # Mirror the archive's scope so a restore that overwrites
                    # .env can itself be rolled back.
                    include_env=bool(manifest.get("include_env", False)),
                    max_backups=max_backups,
                )
            except Exception as exc:
                logger.warning(f"[SourceBackup] Safety backup failed, aborting restore: {exc}")
                raise

        restored_count = 0
        skipped: list[str] = []
        for member in members:
            if member.filename == MANIFEST_FILE or member.is_dir():
                continue
            target = project_root / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored_count += 1
            except OSError as exc:
                skipped.append(member.filename)
                logger.warning(f"[SourceBackup] Skipping {member.filename}: {exc}")

    if skipped:
        logger.warning(
            f"[SourceBackup] Restored {restored_count} files, skipped {len(skipped)} "
            f"(locked/inaccessible): {skipped[:10]}"
        )
    else:
        logger.info(f"[SourceBackup] Restored {restored_count} files from {archive.name}")

    return {
        "restored_count": restored_count,
        "skipped_count": len(skipped),
        "skipped_files": skipped[:20],
        "manifest": manifest,
        "safety_backup": str(safety_path) if safety_path else None,
    }
