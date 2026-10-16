"""
计划看板（Kanban）数据层 — SQLite 持久化

对标 Hermes ``kanban.db`` 的轻量实现，落在 OpenKitsune 架构内：
- 三张表：``boards`` / ``cards`` / ``comments`` + 活动流 ``card_events``
- 状态列：todo → in_progress → blocked → done（``archived`` 为归档过滤，不作为列）
- WAL 并发安全 + busy_timeout，跨进程共享同一份看板数据
- 默认看板 ``default``，数据库位于 ``<data_dir>/kanban/kanban.db``
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 工作流（对标 Hermes kanban_workflow，精简为核心四列 + 归档） ─────────
ARCHIVED = "archived"

WORKFLOW_COLUMNS: list[dict[str, str]] = [
    {"key": "todo", "label": "待办", "icon": "◻"},
    {"key": "in_progress", "label": "进行中", "icon": "●"},
    {"key": "blocked", "label": "阻塞", "icon": "⊘"},
    {"key": "done", "label": "已完成", "icon": "✓"},
]

VALID_STATUSES: set[str] = {c["key"] for c in WORKFLOW_COLUMNS} | {ARCHIVED}

# 手动拖拽允许矩阵（src -> {dst}），归档/恢复任意可走
MANUAL_MOVES: dict[str, set[str]] = {
    "todo": {"in_progress", "blocked", "done"},
    "in_progress": {"todo", "blocked", "done"},
    "blocked": {"todo", "in_progress", "done"},
    "done": {"todo", "in_progress"},
    ARCHIVED: {"todo", "in_progress", "blocked", "done"},
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS boards (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    id          TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL REFERENCES boards(id),
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    assignee    TEXT,
    priority    INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cards_board_status ON cards(board_id, status);

CREATE TABLE IF NOT EXISTS comments (
    id         TEXT PRIMARY KEY,
    card_id    TEXT NOT NULL REFERENCES cards(id),
    author     TEXT NOT NULL DEFAULT 'user',
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_card ON comments(card_id, created_at);

CREATE TABLE IF NOT EXISTS card_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    TEXT NOT NULL REFERENCES cards(id),
    kind       TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_card ON card_events(card_id, id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return secrets.token_hex(4)


class KanbanStore:
    """计划看板 SQLite 数据层（线程安全单例）"""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = self._resolve_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self.init_db()

    # ── 路径解析 ────────────────────────────────────────────────

    @staticmethod
    def _resolve_db_path() -> Path:
        try:
            from openkitsune.config import settings

            return Path(settings.data_dir) / "kanban" / "kanban.db"
        except Exception:
            return Path("data/kanban/kanban.db")

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── 连接管理 ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """每线程独立连接：WAL + busy_timeout，避免跨线程共享连接。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        self._local.conn = conn
        return conn

    def init_db(self) -> None:
        with self._init_lock:
            conn = self._connect()
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            self._ensure_default_board(conn)

    @staticmethod
    def _ensure_default_board(conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT id FROM boards WHERE id = ?", ("default",)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO boards (id, name, created_at) VALUES (?, ?, ?)",
                ("default", "默认看板", _now()),
            )
            conn.commit()

    def _rows(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(r) for r in rows]

    # ── 看板 ────────────────────────────────────────────────────

    def list_boards(self) -> list[dict[str, Any]]:
        conn = self._connect()
        return self._rows(conn.execute(
            "SELECT id, name, created_at FROM boards ORDER BY created_at ASC"
        ).fetchall())

    def create_board(self, name: str) -> dict[str, Any]:
        board_id = name.strip().lower().replace(" ", "-") or _new_id()
        if not name or not name.strip():
            raise ValueError("看板名称不能为空")
        conn = self._connect()
        conn.execute(
            "INSERT OR IGNORE INTO boards (id, name, created_at) VALUES (?, ?, ?)",
            (board_id, name.strip(), _now()),
        )
        conn.commit()
        row = conn.execute("SELECT id, name, created_at FROM boards WHERE id = ?", (board_id,)).fetchone()
        return dict(row)

    def get_board(self, board_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute("SELECT id, name, created_at FROM boards WHERE id = ?", (board_id,)).fetchone()
        return dict(row) if row else None

    # ── 卡片 ────────────────────────────────────────────────────

    def list_cards(
        self,
        board_id: str = "default",
        status: str | None = None,
        assignee: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        where = ["board_id = ?"]
        params: list[Any] = [board_id]
        if status:
            if status not in VALID_STATUSES:
                raise ValueError(f"未知状态: {status}")
            where.append("status = ?")
            params.append(status)
        elif not include_archived:
            where.append("status != ?")
            params.append(ARCHIVED)
        if assignee:
            where.append("assignee = ?")
            params.append(assignee)
        params.append(max(1, min(int(limit), 500)))
        sql = (
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM comments m WHERE m.card_id = c.id) AS comment_count "
            "FROM cards c WHERE " + " AND ".join(where) +
            " ORDER BY c.status ASC, c.priority DESC, c.sort_order ASC, c.created_at DESC LIMIT ?"
        )
        return self._rows(conn.execute(sql, params).fetchall())

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM comments m WHERE m.card_id = c.id) AS comment_count "
            "FROM cards c WHERE c.id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        card = dict(row)
        card["comments"] = self._rows(conn.execute(
            "SELECT id, author, body, created_at FROM comments WHERE card_id = ? ORDER BY created_at ASC",
            (card_id,),
        ).fetchall())
        card["events"] = self._rows(conn.execute(
            "SELECT id, kind, payload, created_at FROM card_events WHERE card_id = ? ORDER BY id DESC LIMIT 20",
            (card_id,),
        ).fetchall())
        return card

    def create_card(
        self,
        title: str,
        description: str = "",
        board_id: str = "default",
        status: str = "todo",
        assignee: str | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValueError("卡片标题不能为空")
        if status not in VALID_STATUSES:
            raise ValueError(f"未知状态: {status}")
        if status == ARCHIVED:
            raise ValueError("创建时不能直接归档，请使用 todo/in_progress/blocked/done")
        if self.get_board(board_id) is None:
            raise ValueError(f"看板不存在: {board_id}")
        card_id = _new_id()
        now = _now()
        conn = self._connect()
        conn.execute(
            "INSERT INTO cards (id, board_id, title, description, status, assignee, priority, sort_order, created_at, updated_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL)",
            (card_id, board_id, title, description or "", status, assignee or None, int(priority or 0), now, now),
        )
        self._log_event(conn, card_id, "created", {"title": title, "status": status})
        conn.commit()
        card = self.get_card(card_id)
        assert card is not None
        return card

    def update_card(self, card_id: str, **fields: Any) -> dict[str, Any]:
        """白名单字段更新：title / description / assignee / priority。"""
        conn = self._connect()
        row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise KeyError(f"卡片不存在: {card_id}")
        allowed = {"title", "description", "assignee", "priority"}
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "title":
                value = (value or "").strip()
                if not value:
                    raise ValueError("卡片标题不能为空")
            if key == "assignee":
                value = (value or "").strip() or None
            if key == "priority":
                value = int(value or 0)
            updates[key] = value
        if not updates:
            return self.get_card(card_id) or {}
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE cards SET {sets}, updated_at = ? WHERE id = ?",
            (*updates.values(), _now(), card_id),
        )
        self._log_event(conn, card_id, "updated", {"fields": list(updates)})
        conn.commit()
        return self.get_card(card_id) or {}

    def move_card(self, card_id: str, status: str, note: str | None = None) -> dict[str, Any]:
        """状态流转：校验目标列 + 手动移动矩阵；归档/恢复不受矩阵限制。"""
        if status not in VALID_STATUSES:
            raise ValueError(f"未知状态: {status}")
        conn = self._connect()
        row = conn.execute("SELECT id, status FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise KeyError(f"卡片不存在: {card_id}")
        src = row["status"]
        if src == status:
            return self.get_card(card_id) or {}
        if status != ARCHIVED and src != ARCHIVED:
            allowed = MANUAL_MOVES.get(src, set())
            if status not in allowed:
                raise ValueError(f"不允许从 {src} 移动到 {status}")
        archived_at = _now() if status == ARCHIVED else None
        conn.execute(
            "UPDATE cards SET status = ?, archived_at = ?, updated_at = ? WHERE id = ?",
            (status, archived_at, _now(), card_id),
        )
        self._log_event(conn, card_id, "moved", {"from": src, "to": status, "note": note})
        conn.commit()
        return self.get_card(card_id) or {}

    def delete_card(self, card_id: str) -> bool:
        """物理删除（含评论与事件）。归档请用 move_card(archived)。"""
        conn = self._connect()
        row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM card_events WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM comments WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()
        return True

    # ── 评论 ────────────────────────────────────────────────────

    def add_comment(self, card_id: str, body: str, author: str = "user") -> dict[str, Any]:
        body = (body or "").strip()
        if not body:
            raise ValueError("评论内容不能为空")
        conn = self._connect()
        row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise KeyError(f"卡片不存在: {card_id}")
        comment_id = _new_id()
        now = _now()
        conn.execute(
            "INSERT INTO comments (id, card_id, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (comment_id, card_id, (author or "user").strip() or "user", body, now),
        )
        self._log_event(conn, card_id, "commented", {"author": author})
        conn.commit()
        return {
            "id": comment_id,
            "card_id": card_id,
            "author": (author or "user").strip() or "user",
            "body": body,
            "created_at": now,
        }

    # ── 统计 ────────────────────────────────────────────────────

    def stats(self, board_id: str = "default") -> dict[str, Any]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM cards WHERE board_id = ? GROUP BY status",
            (board_id,),
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        by_column = {c["key"]: counts.get(c["key"], 0) for c in WORKFLOW_COLUMNS}
        return {
            "board_id": board_id,
            "total": sum(by_column.values()),
            "archived": counts.get(ARCHIVED, 0),
            "by_column": by_column,
        }

    def workflow(self) -> dict[str, Any]:
        """前端渲染列定义 + 手动移动矩阵（对标 Hermes GET /workflow）。"""
        return {
            "columns": WORKFLOW_COLUMNS,
            "manual": {src: sorted(dsts) for src, dsts in MANUAL_MOVES.items()},
            "archived": ARCHIVED,
        }

    # ── 内部 ────────────────────────────────────────────────────

    @staticmethod
    def _log_event(conn: sqlite3.Connection, card_id: str, kind: str, payload: dict | None = None) -> None:
        import json

        conn.execute(
            "INSERT INTO card_events (card_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (card_id, kind, json.dumps(payload, ensure_ascii=False) if payload else None, _now()),
        )


# 模块级单例：API 与 Agent 工具共享同一份数据
_store: KanbanStore | None = None
_store_lock = threading.Lock()


def get_kanban_store() -> KanbanStore:
    """获取全局看板数据层单例（幂等初始化）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = KanbanStore()
    return _store


__all__ = [
    "ARCHIVED",
    "WORKFLOW_COLUMNS",
    "VALID_STATUSES",
    "MANUAL_MOVES",
    "KanbanStore",
    "get_kanban_store",
]
