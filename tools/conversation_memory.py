"""Persistent conversation memory — SQLite-backed, survives restarts.

Replaces the JSON-based ContextStore for the Telegram chat path.
Stores the last N exchanges per thread_id so Patrick remembers
what was discussed.

Usage:
    from benai_infra.tools.conversation_memory import ConversationMemory
    mem = ConversationMemory()
    mem.add("tg_123", "What's the weather?", "It's sunny in Chicago.")
    history = mem.get_history("tg_123", limit=10)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".patrick-agent" / "conversation_memory.db"
MAX_HISTORY = 20  # 20 entries = 10 exchanges (user + assistant each)


class ConversationMemory:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path), timeout=5)

    def _ensure_schema(self) -> None:
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_thread_ts
            ON messages (thread_id, ts DESC)
        """)
        conn.commit()
        conn.close()

    def add(self, thread_id: str, user_msg: str, assistant_msg: str) -> None:
        """Store a user/assistant exchange."""
        ts = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        conn.execute(
            "INSERT INTO messages (thread_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (thread_id, "user", user_msg[:500], ts),
        )
        conn.execute(
            "INSERT INTO messages (thread_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (thread_id, "assistant", assistant_msg[:500], ts),
        )
        # Prune old messages beyond MAX_HISTORY
        conn.execute("""
            DELETE FROM messages WHERE id NOT IN (
                SELECT id FROM messages WHERE thread_id = ?
                ORDER BY ts DESC, id DESC LIMIT ?
            ) AND thread_id = ?
        """, (thread_id, MAX_HISTORY, thread_id))
        conn.commit()
        conn.close()

    def get_history(self, thread_id: str, limit: int = MAX_HISTORY) -> list[dict[str, str]]:
        """Return recent messages as [{"role": "user", "content": "..."}, ...]."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = ? "
            "ORDER BY ts ASC, id ASC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
        conn.close()
        return [{"role": r[0], "content": r[1]} for r in rows]

    def count(self, thread_id: str) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0
