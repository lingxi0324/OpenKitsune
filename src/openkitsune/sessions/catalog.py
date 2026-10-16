"""SQLite-backed random-access catalog for the canonical sessions.json store."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openkitsune.utils.atomic_io import path_transaction_lock

logger = logging.getLogger(__name__)

CATALOG_VERSION = 3

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS catalog_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_key  TEXT PRIMARY KEY,
    byte_offset  INTEGER NOT NULL,
    byte_length  INTEGER NOT NULL,
    session_id   TEXT NOT NULL,
    channel      TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    state        TEXT NOT NULL,
    chat_id      TEXT NOT NULL,
    pinned       INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    title        TEXT NOT NULL,
    last_message TEXT NOT NULL,
    search_text  TEXT NOT NULL,
    summary_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS session_search USING fts5(
    session_key UNINDEXED,
    search_text,
    tokenize='trigram'
);

CREATE INDEX IF NOT EXISTS idx_session_catalog_session_id
    ON sessions (session_id);
CREATE INDEX IF NOT EXISTS idx_session_catalog_listing
    ON sessions (channel, pinned DESC, timestamp_ms DESC, chat_id DESC);
CREATE INDEX IF NOT EXISTS idx_session_catalog_state_listing
    ON sessions (channel, state, pinned DESC, timestamp_ms DESC, chat_id DESC);
CREATE INDEX IF NOT EXISTS idx_session_catalog_user_listing
    ON sessions (user_id, pinned DESC, timestamp_ms DESC, chat_id DESC);
CREATE INDEX IF NOT EXISTS idx_session_catalog_user_state_listing
    ON sessions (user_id, state, pinned DESC, timestamp_ms DESC, chat_id DESC);
"""


@dataclass(frozen=True)
class SessionCatalogEntry:
    session_key: str
    offset: int
    length: int
    summary: dict[str, Any]


@dataclass(frozen=True)
class SessionCatalogPage:
    summaries: list[dict[str, Any]]
    total: int


class SessionCatalogIndexWriteError(OSError):
    """The session store was replaced but its SQLite catalog was not."""


class SessionCatalogStore:
    """Keep queryable summaries separate from full session documents.

    ``sessions.json`` remains the canonical, backwards-compatible array. The
    adjacent SQLite database stores byte ranges and compact projections, so
    startup and list requests do not deserialize every conversation.
    """

    def __init__(self, sessions_file: Path):
        self.sessions_file = Path(sessions_file)
        self.index_file = self.sessions_file.with_name("sessions.index.sqlite3")
        self.pending_index_file = self.index_file.with_suffix(self.index_file.suffix + ".next")
        self.building_index_file = self.index_file.with_suffix(self.index_file.suffix + ".building")
        self.legacy_index_file = self.sessions_file.with_name("sessions.index.json")
        self._lock = threading.RLock()

    def load(self) -> bool:
        """Return whether a catalog matching the current sessions file exists."""
        with self._lock:
            return self._valid_index_path_unlocked() is not None

    def get_entry(self, session_key: str) -> SessionCatalogEntry | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = conn.execute(
                """
                SELECT session_key, byte_offset, byte_length, summary_json
                FROM sessions WHERE session_key = ?
                """,
                (session_key,),
            ).fetchone()
        return self._entry_from_row(row)

    def get_entry_by_session_id(self, session_id: str) -> SessionCatalogEntry | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = conn.execute(
                """
                SELECT session_key, byte_offset, byte_length, summary_json
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._entry_from_row(row)

    def get_summaries(self, session_keys: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not session_keys:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self._read_connection() as conn:
            if conn is None:
                return result
            for start in range(0, len(session_keys), 500):
                batch = session_keys[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT session_key, summary_json FROM sessions "
                    f"WHERE session_key IN ({placeholders})",
                    tuple(batch),
                ).fetchall()
                for session_key, raw_summary in rows:
                    summary = self._decode_summary(raw_summary)
                    if summary is not None:
                        result[str(session_key)] = summary
        return result

    def iter_entries(self, *, include_closed: bool = True) -> Iterator[SessionCatalogEntry]:
        where = "" if include_closed else "WHERE state <> 'closed'"
        with self._read_connection() as conn:
            if conn is None:
                return
            cursor = conn.execute(
                f"""
                SELECT session_key, byte_offset, byte_length, summary_json
                FROM sessions {where} ORDER BY rowid
                """
            )
            while True:
                rows = cursor.fetchmany(128)
                if not rows:
                    break
                for row in rows:
                    entry = self._entry_from_row(row)
                    if entry is not None:
                        yield entry

    def list_summaries(
        self,
        *,
        channel: str | None = None,
        user_id: str | None = None,
        state: str | None = None,
        query: str = "",
        exclude_org_chats: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> SessionCatalogPage:
        where, params = self._summary_filters(
            channel=channel,
            user_id=user_id,
            state=state,
            query=query,
            exclude_org_chats=exclude_org_chats,
        )
        with self._read_connection() as conn:
            if conn is None:
                return SessionCatalogPage([], 0)
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM sessions {where}", tuple(params)).fetchone()[0]
            )
            sql = (
                "SELECT summary_json FROM sessions "
                f"{where} ORDER BY pinned DESC, timestamp_ms DESC, chat_id DESC"
            )
            page_params = list(params)
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                page_params.extend((max(0, int(limit)), max(0, int(offset))))
            rows = conn.execute(sql, tuple(page_params)).fetchall()

        summaries: list[dict[str, Any]] = []
        for (raw_summary,) in rows:
            summary = self._decode_summary(raw_summary)
            if summary is not None:
                summaries.append(summary)
        return SessionCatalogPage(summaries, total)

    def counts(self) -> dict[str, Any]:
        stats: dict[str, Any] = {"total": 0, "active": 0, "idle": 0, "by_channel": {}}
        with self._read_connection() as conn:
            if conn is None:
                return stats
            rows = conn.execute(
                """
                SELECT channel, state, COUNT(*)
                FROM sessions
                WHERE state <> 'closed'
                GROUP BY channel, state
                """
            ).fetchall()
        for channel, state, raw_count in rows:
            count = int(raw_count)
            stats["total"] += count
            stats["by_channel"][str(channel)] = stats["by_channel"].get(str(channel), 0) + count
            if state == "active":
                stats["active"] += count
            elif state in {"idle", "expired"}:
                stats["idle"] += count
        return stats

    def contains_many(self, session_keys: Sequence[str]) -> set[str]:
        return set(self.get_summaries(session_keys))

    def keys_for_channel(self, channel: str) -> list[str]:
        with self._read_connection() as conn:
            if conn is None:
                return []
            rows = conn.execute(
                "SELECT session_key FROM sessions WHERE channel = ?",
                (channel,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def delete(self, session_key: str) -> bool:
        return self.delete_many([session_key]) > 0

    def delete_many(self, session_keys: Sequence[str]) -> int:
        if not session_keys:
            return 0
        deleted = 0
        with self._write_connection() as conn:
            if conn is None:
                return 0
            for start in range(0, len(session_keys), 500):
                batch = session_keys[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                cursor = conn.execute(
                    f"DELETE FROM sessions WHERE session_key IN ({placeholders})",
                    tuple(batch),
                )
                deleted += max(0, int(cursor.rowcount or 0))
                conn.execute(
                    f"DELETE FROM session_search WHERE session_key IN ({placeholders})",
                    tuple(batch),
                )
            conn.commit()
        return deleted

    def update_summary(self, session_key: str, summary: dict[str, Any]) -> bool:
        """Update one catalog projection without changing the JSON document offsets."""
        with self._write_connection() as conn:
            if conn is None:
                return False
            row = conn.execute(
                "SELECT byte_offset, byte_length FROM sessions WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            if row is None:
                return False

            values = self._summary_row(session_key, int(row[0]), int(row[1]), summary)
            conn.execute(
                """
                UPDATE sessions SET
                    session_id = ?, channel = ?, user_id = ?, state = ?, chat_id = ?,
                    pinned = ?, timestamp_ms = ?, title = ?, last_message = ?,
                    search_text = ?, summary_json = ?
                WHERE session_key = ?
                """,
                (*values[3:], session_key),
            )
            conn.execute("DELETE FROM session_search WHERE session_key = ?", (session_key,))
            conn.execute(
                "INSERT INTO session_search (session_key, search_text) VALUES (?, ?)",
                (session_key, self._summary_search_text(summary)),
            )
            conn.commit()
        return True

    def read_document(self, entry: SessionCatalogEntry) -> dict[str, Any] | None:
        try:
            with open(self.sessions_file, "rb") as handle:
                handle.seek(entry.offset)
                raw = handle.read(entry.length)
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def read_raw_document(self, entry: SessionCatalogEntry) -> str | None:
        try:
            with open(self.sessions_file, "rb") as handle:
                handle.seek(entry.offset)
                raw = handle.read(entry.length)
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def write(
        self,
        documents: Iterable[tuple[str, str | dict[str, Any], dict[str, Any]]],
    ) -> int:
        """Atomically replace the JSON store and rebuild its SQLite catalog."""
        self.sessions_file.parent.mkdir(parents=True, exist_ok=True)
        sessions_tmp = self.sessions_file.with_suffix(self.sessions_file.suffix + ".tmp")
        source_replaced = False

        with self._lock, path_transaction_lock(self.sessions_file):
            self._remove_sqlite_file(self.building_index_file)
            source_index = self._valid_index_path_unlocked()
            conn = sqlite3.connect(str(self.building_index_file))
            try:
                if source_index is None:
                    self._initialize_schema(conn)
                else:
                    with closing(sqlite3.connect(str(source_index))) as source_conn:
                        source_conn.backup(conn)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM session_search")
                conn.execute("DELETE FROM sessions")
                count = 0
                byte_offset = 1
                with open(sessions_tmp, "wb") as handle:
                    handle.write(b"[")
                    for session_key, document, summary in documents:
                        raw = (
                            document.strip()
                            if isinstance(document, str)
                            else json.dumps(document, ensure_ascii=False, separators=(",", ":"))
                        )
                        if not raw.startswith("{") or not raw.endswith("}"):
                            raise ValueError(f"invalid session document: {session_key}")
                        encoded = raw.encode("utf-8")
                        if count:
                            handle.write(b",")
                            byte_offset += 1
                        conn.execute(
                            """
                            INSERT INTO sessions (
                                session_key, byte_offset, byte_length, session_id,
                                channel, user_id, state, chat_id, pinned, timestamp_ms,
                                title, last_message, search_text, summary_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            self._summary_row(session_key, byte_offset, len(encoded), summary),
                        )
                        search_text = self._summary_search_text(summary)
                        conn.execute(
                            "INSERT INTO session_search (session_key, search_text) VALUES (?, ?)",
                            (session_key, search_text),
                        )
                        handle.write(encoded)
                        byte_offset += len(encoded)
                        count += 1
                    handle.write(b"]\n")
                    handle.flush()
                    os.fsync(handle.fileno())

                source_stat = sessions_tmp.stat()
                conn.executemany(
                    "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES (?, ?)",
                    (
                        ("version", str(CATALOG_VERSION)),
                        ("source_size", str(source_stat.st_size)),
                        ("source_mtime_ns", str(source_stat.st_mtime_ns)),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                sessions_tmp.unlink(missing_ok=True)
                self._remove_sqlite_file(self.building_index_file)
                raise
            finally:
                conn.close()

            try:
                self._backup_sessions_file()
                self._replace_with_retry(sessions_tmp, self.sessions_file)
                source_replaced = True
                self._replace_with_retry(self.building_index_file, self.index_file)
                self._remove_sqlite_file(self.pending_index_file)
                self.legacy_index_file.unlink(missing_ok=True)
                return count
            except Exception as exc:
                if source_replaced and self.building_index_file.exists():
                    try:
                        self._replace_with_retry(
                            self.building_index_file,
                            self.pending_index_file,
                        )
                    except OSError:
                        pass
                if source_replaced:
                    raise SessionCatalogIndexWriteError(
                        f"failed to install SQLite session catalog: {exc}"
                    ) from exc
                raise
            finally:
                sessions_tmp.unlink(missing_ok=True)
                self._remove_sqlite_file(self.building_index_file)

    @staticmethod
    def _initialize_schema(conn: sqlite3.Connection) -> None:
        """Create catalog tables during first-time initialization or migration."""
        conn.executescript(_SCHEMA_SQL)

    @staticmethod
    def summary_matches(
        summary: dict[str, Any],
        *,
        channel: str | None = None,
        user_id: str | None = None,
        state: str | None = None,
        query: str = "",
        exclude_org_chats: bool = False,
    ) -> bool:
        summary_state = str(summary.get("state") or "")
        if summary_state == "expired":
            summary_state = "idle"
        if summary_state == "closed":
            return False
        if channel and summary.get("channel") != channel:
            return False
        if user_id and summary.get("user_id") != user_id:
            return False
        if state and summary_state != state:
            return False
        if exclude_org_chats and str(summary.get("chat_id") or "").startswith("org_"):
            return False
        normalized_query = query.strip().casefold()
        if normalized_query:
            searchable = (
                f"{summary.get('title') or ''}\n{summary.get('last_message') or ''}".casefold()
            )
            if normalized_query not in searchable:
                return False
        return True

    @staticmethod
    def summary_sort_key(summary: dict[str, Any]) -> tuple[bool, int, str]:
        return (
            bool(summary.get("pinned")),
            int(summary.get("timestamp") or 0),
            str(summary.get("chat_id") or ""),
        )

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection | None]:
        with self._lock:
            path = self._valid_index_path_unlocked()
            if path is None:
                yield None
                return
            conn = sqlite3.connect(str(path))
            try:
                yield conn
            finally:
                conn.close()

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection | None]:
        with self._lock:
            path = self._valid_index_path_unlocked()
            if path is None:
                yield None
                return
            conn = sqlite3.connect(str(path))
            try:
                yield conn
            finally:
                conn.close()

    def _valid_index_path_unlocked(self) -> Path | None:
        if self._database_matches_source(self.index_file):
            return self.index_file
        if not self._database_matches_source(self.pending_index_file):
            return None
        try:
            self._replace_with_retry(self.pending_index_file, self.index_file)
            return self.index_file
        except OSError:
            return self.pending_index_file

    def _database_matches_source(self, path: Path) -> bool:
        if not self.sessions_file.exists() or not path.exists():
            return False
        try:
            source_stat = self.sessions_file.stat()
            with closing(sqlite3.connect(str(path))) as conn:
                meta = dict(conn.execute("SELECT key, value FROM catalog_meta").fetchall())
                if meta.get("version") != str(CATALOG_VERSION):
                    return False
                if meta.get("source_size") != str(source_stat.st_size):
                    return False
                if meta.get("source_mtime_ns") != str(source_stat.st_mtime_ns):
                    return False
                invalid = conn.execute(
                    """
                    SELECT 1 FROM sessions
                    WHERE byte_offset < 0 OR byte_length <= 0
                       OR byte_offset + byte_length > ?
                    LIMIT 1
                    """,
                    (source_stat.st_size,),
                ).fetchone()
                return invalid is None
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
            return False

    @staticmethod
    def _entry_from_row(row: tuple[Any, ...] | None) -> SessionCatalogEntry | None:
        if row is None:
            return None
        session_key, offset, length, raw_summary = row
        summary = SessionCatalogStore._decode_summary(raw_summary)
        if summary is None:
            return None
        return SessionCatalogEntry(
            session_key=str(session_key),
            offset=int(offset),
            length=int(length),
            summary=summary,
        )

    @staticmethod
    def _decode_summary(raw_summary: Any) -> dict[str, Any] | None:
        try:
            value = json.loads(str(raw_summary))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _summary_row(
        session_key: str,
        offset: int,
        length: int,
        summary: dict[str, Any],
    ) -> tuple[Any, ...]:
        normalized = dict(summary)
        if normalized.get("state") == "expired":
            normalized["state"] = "idle"
        title = str(normalized.get("title") or "")
        last_message = str(normalized.get("last_message") or "")
        return (
            session_key,
            offset,
            length,
            str(normalized.get("session_id") or ""),
            str(normalized.get("channel") or ""),
            str(normalized.get("user_id") or ""),
            str(normalized.get("state") or ""),
            str(normalized.get("chat_id") or ""),
            int(bool(normalized.get("pinned"))),
            int(normalized.get("timestamp") or 0),
            title,
            last_message,
            SessionCatalogStore._summary_search_text(normalized),
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        )

    @staticmethod
    def _summary_filters(
        *,
        channel: str | None,
        user_id: str | None,
        state: str | None,
        query: str,
        exclude_org_chats: bool,
    ) -> tuple[str, list[Any]]:
        clauses = ["state <> 'closed'"]
        params: list[Any] = []
        if channel:
            clauses.append("channel = ?")
            params.append(channel)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if state:
            clauses.append("CASE WHEN state = 'expired' THEN 'idle' ELSE state END = ?")
            params.append(state)
        if exclude_org_chats:
            clauses.append("chat_id NOT LIKE 'org\\_%' ESCAPE '\\'")
        normalized_query = query.strip().casefold()
        if normalized_query:
            if len(normalized_query) >= 3:
                clauses.append(
                    "session_key IN ("
                    "SELECT session_key FROM session_search WHERE search_text MATCH ?"
                    ")"
                )
                escaped_query = normalized_query.replace('"', '""')
                params.append(f'"{escaped_query}"')
            else:
                clauses.append("instr(search_text, ?) > 0")
                params.append(normalized_query)
        return "WHERE " + " AND ".join(clauses), params

    @staticmethod
    def _summary_search_text(summary: dict[str, Any]) -> str:
        title = str(summary.get("title") or "")
        last_message = str(summary.get("last_message") or "")
        return f"{title}\n{last_message}".casefold()

    def _backup_sessions_file(self) -> None:
        if not self.sessions_file.exists():
            return
        backup_file = self.sessions_file.with_suffix(self.sessions_file.suffix + ".bak")
        try:
            shutil.copy2(self.sessions_file, backup_file)
        except OSError as exc:
            logger.warning("Failed to create backup %s: %s", backup_file, exc)

    @staticmethod
    def _replace_with_retry(source: Path, target: Path, retries: int = 3) -> None:
        last_error: OSError | None = None
        for attempt in range(retries):
            try:
                source.replace(target)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(0.2 * (attempt + 1))
        if last_error is not None:
            raise last_error

    @staticmethod
    def _remove_sqlite_file(path: Path) -> None:
        for candidate in (
            path,
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
            Path(f"{path}-journal"),
        ):
            candidate.unlink(missing_ok=True)
