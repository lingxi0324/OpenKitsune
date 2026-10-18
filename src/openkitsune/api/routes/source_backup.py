"""Source-code backup & restore routes.

Packs the project's source tree and configuration into timestamped zip
archives and restores from them. Runtime data backups live in
``workspace_io.py``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from openkitsune.workspace.source_backup import (
    DEFAULT_MAX_BACKUPS,
    create_source_backup,
    default_output_dir,
    list_source_backups,
    restore_source_backup,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root).resolve()
    except Exception:
        return Path.cwd().resolve()


class SourceBackupCreateRequest(BaseModel):
    output_dir: str = ""
    label: str = ""
    include_env: bool = False
    max_backups: int = DEFAULT_MAX_BACKUPS


class SourceBackupRestoreRequest(BaseModel):
    zip_path: str
    safety_backup: bool = True


@router.get("/api/workspace/source-backups")
async def get_source_backup_list(dir: str = ""):
    """List source backups, newest first. Defaults to <project>/backups/source."""
    root = _project_root()
    directory = Path(dir).expanduser().resolve() if dir.strip() else default_output_dir(root)

    backups = await asyncio.to_thread(list_source_backups, directory, project_id=root.name)
    return {"backups": backups, "backup_dir": str(directory)}


@router.post("/api/workspace/source-backups")
async def create_source_backup_route(body: SourceBackupCreateRequest):
    """Create a timestamped source backup archive."""
    root = _project_root()
    output_dir = body.output_dir.strip() or None

    try:
        archive = await asyncio.to_thread(
            create_source_backup,
            root,
            output_dir,
            label=body.label,
            include_env=body.include_env,
            max_backups=body.max_backups,
        )
    except Exception as exc:
        logger.error(f"[SourceBackup] Create failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "ok",
        "path": str(archive),
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
    }


@router.post("/api/workspace/source-backups/restore")
async def restore_source_backup_route(body: SourceBackupRestoreRequest):
    """Restore source files from a backup archive."""
    root = _project_root()

    if not body.zip_path.strip():
        raise HTTPException(status_code=400, detail="zip_path is required")
    if not Path(body.zip_path).exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    try:
        result = await asyncio.to_thread(
            restore_source_backup,
            body.zip_path,
            root,
            safety_backup=body.safety_backup,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"[SourceBackup] Restore failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    skipped = result.get("skipped_count", 0)
    response: dict = {
        "status": "ok" if skipped == 0 else "partial",
        "restored_count": result["restored_count"],
        "skipped_count": skipped,
        "safety_backup": result.get("safety_backup"),
    }
    if skipped:
        response["skipped_files"] = result.get("skipped_files", [])
        response["message"] = f"{skipped} 个文件因被占用而跳过，建议关闭服务后重新还原"
    return response
