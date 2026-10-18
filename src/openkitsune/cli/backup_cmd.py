"""``openkitsune backup ...`` Typer sub-app — source-code backup & restore.

Archives are named with the creation timestamp so a working tree can be
rolled back to a known point::

    openkitsune-source-<project>-20261018_153000.zip
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..workspace.source_backup import (
    DEFAULT_MAX_BACKUPS,
    create_source_backup,
    default_output_dir,
    list_source_backups,
    restore_source_backup,
)

backup_app = typer.Typer(
    name="backup",
    help="Source-code backup & restore (timestamped zip archives).",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _resolve_project(project: Path | None) -> Path:
    """Resolve the project root lazily so ``--help`` stays cheap."""
    if project is not None:
        return project.resolve()
    from ..config import settings

    return Path(settings.project_root).resolve()


def _format_local_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value[:19].replace("T", " ")


@backup_app.command("create")
def create(
    project: Path | None = typer.Option(
        None, "--project", "-p", help="Project root (default: configured project root)."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Archive directory (default: <project>/backups/source)."
    ),
    label: str = typer.Option("", "--label", "-l", help="Optional tag appended to the filename."),
    include_env: bool = typer.Option(
        False, "--include-env", help="Include the .env file (may contain secrets)."
    ),
    max_backups: int = typer.Option(
        DEFAULT_MAX_BACKUPS, "--max-backups", help="Keep at most N archives (0 = unlimited)."
    ),
) -> None:
    """Create a timestamped zip archive of the project's source and config."""
    root = _resolve_project(project)
    try:
        archive = create_source_backup(
            root,
            output,
            label=label,
            include_env=include_env,
            max_backups=max_backups,
        )
    except Exception as exc:
        console.print(f"[red]备份失败: {exc}[/red]")
        raise typer.Exit(1) from exc

    size_mb = archive.stat().st_size / 1024 / 1024
    console.print(f"[green]✓[/green] 源码备份完成: [bold]{archive}[/bold] ({size_mb:.1f} MB)")


@backup_app.command("list")
def list_cmd(
    project: Path | None = typer.Option(
        None, "--project", "-p", help="Project root (default: configured project root)."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Archive directory (default: <project>/backups/source)."
    ),
) -> None:
    """List source-code backup archives, newest first."""
    root = _resolve_project(project)
    directory = output.resolve() if output else default_output_dir(root)
    backups = list_source_backups(directory, project_id=root.name)

    if not backups:
        console.print(f"[yellow]未找到源码备份: {directory}[/yellow]")
        return

    table = Table(title=f"源码备份 · {directory}")
    table.add_column("时间", style="cyan")
    table.add_column("文件数", justify="right")
    table.add_column("大小", justify="right")
    table.add_column("归档", style="green")
    for item in backups:
        manifest = item.get("manifest") or {}
        table.add_row(
            _format_local_time(str(manifest.get("created_at", item["created_at"]))),
            str(manifest.get("file_count", "-")),
            f"{item['size_bytes'] / 1024 / 1024:.1f} MB",
            item["filename"],
        )
    console.print(table)


@backup_app.command("restore")
def restore(
    archive: Path = typer.Argument(..., help="Path to the .zip archive to restore."),
    project: Path | None = typer.Option(
        None, "--project", "-p", help="Project root (default: configured project root)."
    ),
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", "-b", help="Where to store the pre-restore safety backup."
    ),
    no_safety: bool = typer.Option(
        False, "--no-safety", help="Skip the automatic backup of the current tree."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Restore source files from an archive (overwrites matching files)."""
    root = _resolve_project(project)
    if not yes and not typer.confirm(f"将用 {archive.name} 覆盖 {root} 下的同名源码文件，继续？"):
        raise typer.Exit(1)

    try:
        result = restore_source_backup(
            archive,
            root,
            backup_dir=backup_dir,
            safety_backup=not no_safety,
        )
    except Exception as exc:
        console.print(f"[red]还原失败: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(
        f"[green]✓[/green] 已还原 {result['restored_count']} 个文件，"
        f"跳过 {result['skipped_count']} 个"
    )
    if result.get("safety_backup"):
        console.print(f"[dim]还原前快照: {result['safety_backup']}[/dim]")
