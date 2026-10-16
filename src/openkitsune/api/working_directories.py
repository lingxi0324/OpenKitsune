"""Authorization and file-reference helpers for conversation directories."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from ..core.working_directory import (
    WorkingDirectoryError,
    config_workspace,
    is_within,
    normalize_working_directory,
    session_working_directory,
)


def configured_working_roots() -> tuple[Path, ...]:
    roots: list[Path] = [config_workspace()]
    try:
        from ..core.policy_v2 import get_config_v2

        roots.extend(Path(p).expanduser().resolve(strict=False) for p in get_config_v2().workspace.paths)
    except Exception:
        pass
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return tuple(deduped)


def _is_loopback_request(request: Request) -> bool:
    """Return whether the request is a direct IPv4/IPv6 loopback connection."""
    try:
        from .auth import _is_local_request

        return _is_local_request(request)
    except Exception:
        return False


def authorize_working_directory(request: Request, raw_path: str) -> Path:
    """Allow arbitrary loopback roots and constrain all remote callers."""
    try:
        resolved = normalize_working_directory(raw_path, must_exist=True)
    except WorkingDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if _is_loopback_request(request):
        return resolved
    if any(is_within(resolved, root) for root in configured_working_roots()):
        return resolved
    raise HTTPException(
        status_code=403,
        detail="working_directory is outside administrator-configured roots",
    )


def resolve_session_file(session: Any, relative_path: str, *, must_exist: bool = True) -> Path:
    """Resolve a user file while preventing traversal and symlink escape."""
    root = session_working_directory(session, require_available=True)
    raw = str(relative_path or "").strip()
    if not raw or Path(raw).is_absolute() or raw.startswith("\\\\"):
        raise HTTPException(status_code=422, detail="relativePath must be a relative path")
    try:
        resolved = (root / raw).resolve(strict=must_exist)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid working-directory file: {exc}") from exc
    if not is_within(resolved, root):
        raise HTTPException(status_code=403, detail="file escapes the conversation directory")
    if must_exist and not resolved.is_file():
        raise HTTPException(status_code=404, detail="working-directory file not found")
    return resolved


def resolve_chat_attachments(attachments: list[Any] | None, session: Any) -> list[Any] | None:
    """Resolve structured workspace refs and reject forged uploaded paths."""
    if not attachments:
        return attachments
    from .routes.upload import resolve_upload_path

    for attachment in attachments:
        source = str(getattr(attachment, "source", "upload") or "upload")
        if source == "working_directory":
            relative_path = str(getattr(attachment, "relative_path", "") or "")
            resolved = resolve_session_file(session, relative_path)
            if resolved.stat().st_size > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="referenced file exceeds 50 MB")
            attachment.local_path = str(resolved)
            attachment.url = None
            attachment.upload_id = None
            continue

        supplied_local = str(getattr(attachment, "local_path", "") or "")
        upload_id = str(getattr(attachment, "upload_id", "") or "")
        url = str(getattr(attachment, "url", "") or "")
        resolved_upload = resolve_upload_path(upload_id or url) if (upload_id or url) else None
        if supplied_local:
            if resolved_upload is None:
                raise HTTPException(status_code=403, detail="unverified attachment local_path")
            try:
                if Path(supplied_local).resolve(strict=True) != resolved_upload.resolve(strict=True):
                    raise HTTPException(status_code=403, detail="attachment local_path mismatch")
            except OSError as exc:
                raise HTTPException(status_code=422, detail="attachment local_path is invalid") from exc
        if resolved_upload is not None:
            attachment.local_path = str(resolved_upload)
    return attachments
