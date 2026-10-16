"""
Workspace import/export routes: backup settings, create backup, restore backup, list backups.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openkitsune.api.runtime_response import runtime_operation_response

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ───────────────────────────────────────────────────────────


def _project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root)
    except Exception:
        return Path.cwd()


# ─── Pydantic models ──────────────────────────────────────────────────


class BackupSettingsRequest(BaseModel):
    enabled: bool = False
    cron: str = "0 2 * * *"
    backup_path: str = ""
    max_backups: int = 5
    include_userdata: bool = True
    include_media: bool = False


class ExportRequest(BaseModel):
    output_dir: str
    include_userdata: bool = True
    include_media: bool = False


class ImportRequest(BaseModel):
    zip_path: str


# ─── Routes ────────────────────────────────────────────────────────────


@router.get("/api/workspace/backup-settings")
async def get_backup_settings():
    """Read backup settings from data/backup_settings.json."""
    from openkitsune.workspace.backup import read_backup_settings

    root = _project_root()
    settings = read_backup_settings(root)
    return {"settings": settings}


@router.post("/api/workspace/backup-settings")
async def save_backup_settings(body: BackupSettingsRequest, request: Request):
    """Save backup settings and sync the scheduler task."""
    from openkitsune.workspace.backup import (
        write_backup_settings,
    )

    root = _project_root()
    new_settings = body.model_dump()
    write_backup_settings(root, new_settings)
    logger.info(f"[Workspace IO] Backup settings updated: enabled={body.enabled}")

    from openkitsune.runtime_config_coordinator import get_runtime_config_coordinator

    runtime = await get_runtime_config_coordinator(request).sync_scheduler(
        lambda: _sync_backup_scheduler_task(new_settings)
    )

    return runtime_operation_response(runtime, {"settings": new_settings})


@router.post("/api/workspace/export")
async def export_backup(body: ExportRequest):
    """Create a workspace backup zip at the specified output directory."""
    from openkitsune.workspace.backup import create_backup, read_backup_settings

    root = _project_root()

    if not body.output_dir or not body.output_dir.strip():
        raise HTTPException(status_code=400, detail="output_dir is required")

    settings = read_backup_settings(root)
    max_backups = settings.get("max_backups", 5)

    try:
        zip_path = create_backup(
            workspace_path=root,
            output_dir=body.output_dir,
            include_userdata=body.include_userdata,
            include_media=body.include_media,
            max_backups=max_backups,
        )
        return {
            "status": "ok",
            "path": str(zip_path),
            "filename": zip_path.name,
            "size_bytes": zip_path.stat().st_size,
        }
    except Exception as exc:
        logger.error(f"[Workspace IO] Export failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/workspace/import")
async def import_backup(body: ImportRequest):
    """Restore workspace from a backup zip file."""
    from openkitsune.workspace.backup import restore_backup

    root = _project_root()

    if not body.zip_path or not body.zip_path.strip():
        raise HTTPException(status_code=400, detail="zip_path is required")

    if not Path(body.zip_path).exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    try:
        result = restore_backup(zip_path=body.zip_path, workspace_path=root)
        skipped = result.get("skipped_count", 0)
        resp: dict = {
            "status": "ok" if skipped == 0 else "partial",
            "restored_count": result["restored_count"],
            "skipped_count": skipped,
            "manifest": result.get("manifest"),
        }
        if skipped:
            resp["skipped_files"] = result.get("skipped_files", [])
            resp["message"] = f"{skipped} 个文件因被占用而跳过，建议重启后重新还原"
        return resp
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"[Workspace IO] Import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/workspace/backups")
async def get_backup_list():
    """List existing backup files in the configured backup directory."""
    from openkitsune.workspace.backup import list_backups, read_backup_settings

    root = _project_root()
    settings = read_backup_settings(root)
    backup_path = settings.get("backup_path", "")

    if not backup_path:
        return {"backups": [], "backup_path": ""}

    backups = list_backups(backup_path)
    return {"backups": backups, "backup_path": backup_path}


# ─── Scheduler sync helper ────────────────────────────────────────────


async def _sync_backup_scheduler_task(settings: dict) -> None:
    """Create, update, or disable the system:workspace_backup scheduler task."""
    from openkitsune.scheduler import get_active_scheduler

    scheduler = get_active_scheduler()
    if scheduler is None:
        return

    task_id = "system_workspace_backup"
    existing = scheduler.get_task(task_id)
    enabled = settings.get("enabled", False) and bool(settings.get("backup_path"))

    if existing:
        from openkitsune.scheduler.task import TaskDeliveryPolicy, TaskSource

        updates: dict = {}
        cron = settings.get("cron", "0 2 * * *")
        if existing.trigger_config.get("cron") != cron:
            updates["trigger_config"] = {"cron": cron}
            updates["trigger_type"] = _get_cron_trigger_type()
        if getattr(existing, "task_source", None) != TaskSource.SYSTEM:
            updates["task_source"] = TaskSource.SYSTEM
        if getattr(existing, "delivery_policy", None) != TaskDeliveryPolicy.FALLBACK_ALLOWED:
            updates["delivery_policy"] = TaskDeliveryPolicy.FALLBACK_ALLOWED

        if updates:
            await scheduler.update_task(task_id, updates)
        if existing.enabled != enabled:
            if enabled:
                await scheduler.enable_task(task_id)
            else:
                await scheduler.disable_task(task_id)
        if updates or existing.enabled != enabled:
            logger.info(f"[Workspace IO] Updated backup task: enabled={enabled}")
    elif enabled:
        await _register_backup_task(scheduler, settings)


async def _register_backup_task(scheduler: object, settings: dict) -> None:
    """Register the workspace backup system task."""
    from openkitsune.scheduler.task import (
        ScheduledTask,
        TaskDeliveryPolicy,
        TaskSource,
        TaskType,
        TriggerType,
    )

    cron = settings.get("cron", "0 2 * * *")
    task = ScheduledTask(
        id="system_workspace_backup",
        name="工作区备份",
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": cron},
        action="system:workspace_backup",
        prompt="执行工作区数据备份",
        description="定时备份工作区配置和用户数据",
        task_type=TaskType.TASK,
        task_source=TaskSource.SYSTEM,
        delivery_policy=TaskDeliveryPolicy.FALLBACK_ALLOWED,
        enabled=True,
        deletable=False,
    )
    await scheduler.add_task(task)
    logger.info("[Workspace IO] Registered backup scheduler task")


def _get_cron_trigger_type():
    from openkitsune.scheduler.task import TriggerType

    return TriggerType.CRON
