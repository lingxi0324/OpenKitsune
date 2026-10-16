"""Repair the historical default/desktop_user split in local desktop databases.

This is an owner rename, not a memory review: IDs, content, timestamps, expiry,
supersession and graph edges are preserved. Run before serving requests, only
on a desktop-launched main manager. Shared/ambiguous databases require the
existing explicit owner-merge workflow instead.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .storage import MemoryStorage


def align_desktop_owner(storage: MemoryStorage) -> dict[str, Any]:
    """Back up and atomically rename the local owner's default-workspace data.

    A write reservation protects detection, backup and migration from concurrent
    SQLite writers. Repeated runs are harmless; no completion flag suppresses
    detection of records subsequently imported from an older installation.
    """
    conn = storage._conn
    if conn is None:
        return {"status": "skipped", "reason": "storage_unavailable"}

    with storage._lock:
        if conn.in_transaction:
            return {"status": "skipped", "reason": "transaction_in_progress"}
        conn.execute("BEGIN IMMEDIATE")
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            # These names/predicates are constants, never caller-supplied SQL.
            targets = [
                ("memories", "id", "scope IN ('user', 'session')", "scope"),
                ("session_tenants", "session_id", "1=1", "'session'"),
            ]
            if "mdrm_nodes" in tables:
                targets.append(("mdrm_nodes", "id", "1=1", "'graph'"))

            # A default identity can also be explicitly supplied by an IM
            # adapter. A known non-desktop session namespace makes that bucket
            # ambiguous even when no named IM user has written memories yet.
            default_sessions = conn.execute(
                "SELECT session_id FROM session_tenants WHERE user_id='default'"
            ).fetchall()
            if any("__" in sid and not sid.startswith("desktop__") for (sid,) in default_sessions):
                conn.rollback()
                return {"status": "skipped", "reason": "non_desktop_default_sessions"}

            # Inspect all workspaces, not just the one being renamed. Another
            # real/unknown user anywhere in this DB makes automatic attribution
            # unsafe, including users with sessions but no semantic memories.
            for table, _, predicate, _ in targets:
                ambiguous = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {predicate} "
                    "AND COALESCE(user_id, '') NOT IN ('default', 'desktop_user') LIMIT 1"
                ).fetchone()
                if ambiguous:
                    conn.rollback()
                    return {"status": "skipped", "reason": "ambiguous_owners", "table": table}

            counts = {}
            for table, _, predicate, _ in targets:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {predicate} "
                    "AND user_id='default' AND workspace_id='default'"
                ).fetchone()[0]
            if not any(counts.values()):
                conn.rollback()
                return {"status": "clean"}

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = storage._db_path.with_name(
                f"{storage._db_path.name}.bak.desktop_owner.{stamp}"
            )
            pending_backup = storage._db_path.with_name(f".desktop_owner_backup.{stamp}.tmp")
            # Use a separate reader: backing up the connection holding a write
            # transaction can hang. BEGIN IMMEDIATE still allows this reader,
            # and prevents other writers changing the committed snapshot.
            try:
                with (
                    closing(sqlite3.connect(str(storage._db_path))) as source,
                    closing(sqlite3.connect(str(pending_backup))) as dest,
                ):
                    source.backup(dest)
                    dest.execute("PRAGMA journal_mode=DELETE")
                    if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("Desktop owner migration backup failed integrity check")
                pending_backup.replace(backup)
            finally:
                pending_backup.unlink(missing_ok=True)

            now = datetime.now().isoformat()
            for table, key, predicate, scope_expr in targets:
                if not counts[table]:
                    continue
                conn.execute(
                    "INSERT INTO _memory_scope_audit "
                    "(memory_id, old_scope, new_scope, old_user_id, new_user_id, "
                    "reason, migrated_at, migration_version) "
                    f"SELECT {key}, {scope_expr}, {scope_expr}, user_id, 'desktop_user', "
                    f"?, ?, 'desktop_owner_alignment' FROM {table} WHERE {predicate} "
                    "AND user_id='default' AND workspace_id='default'",
                    (f"desktop_owner_alignment:{table}", now),
                )
                conn.execute(
                    f"UPDATE {table} SET user_id='desktop_user' WHERE {predicate} "
                    "AND user_id='default' AND workspace_id='default'"
                )
            report = {"status": "migrated", "counts": counts, "backup": str(backup)}
            conn.execute(
                "INSERT OR REPLACE INTO _schema_meta (key, value) VALUES (?, ?)",
                ("desktop_owner_alignment", json.dumps(report)),
            )
            conn.commit()
            return report
        except Exception:
            conn.rollback()
            raise
