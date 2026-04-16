"""Database read tool — gives Patrick access to his own data.

Read-only SQLite queries against known BenAi databases.
No writes, no DDL, no PRAGMA — SELECT only.

Usage:
    from benai_infra.tools.db_query import db_query
    result = await db_query("picks", "SELECT COUNT(*) FROM picks WHERE date = date('now')")
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Known databases Patrick is allowed to query (read-only)
ALLOWED_DBS: dict[str, Path] = {
    "picks": Path("data/picks.db"),
    "calibration": Path("data/calibration.db"),
    "sports_betting": Path("data/sports_betting.db"),
    "memory": Path("data/memory.db"),
    "marketing": Path("data/marketing.db"),
    "discovery": Path("data/discovery.db"),
    "health": Path("data/health_ledger.db"),
}

# Hard blocklist — never allow these
_BLOCKED_KEYWORDS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
                     "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX"}


def _is_safe_query(sql: str) -> bool:
    """Check if query is read-only SELECT."""
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return False
    return not any(kw in normalized for kw in _BLOCKED_KEYWORDS)


async def db_query(db_name: str, sql: str, max_rows: int = 20) -> str:
    """Execute a read-only query against a known database.

    Args:
        db_name: Key from ALLOWED_DBS (e.g. "picks", "calibration")
        sql: SELECT query to execute
        max_rows: Maximum rows to return

    Returns:
        Query results as formatted text, or error message.
    """
    if db_name not in ALLOWED_DBS:
        return f"[unknown database: {db_name}. Known: {', '.join(ALLOWED_DBS)}]"

    if not _is_safe_query(sql):
        return "[query blocked — read-only SELECT queries only]"

    db_path = ALLOWED_DBS[db_name]
    if not db_path.exists():
        return f"[database not found: {db_path}]"

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        conn.close()

        if not rows:
            return "[no results]"

        # Format as readable text
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))

        if len(rows) == max_rows:
            lines.append(f"... (capped at {max_rows} rows)")

        result = "\n".join(lines)
        logger.info("db_query: db=%s, rows=%d, sql=%r", db_name, len(rows), sql[:60])
        return result

    except Exception as exc:
        logger.warning("db_query failed: %s", exc)
        return f"[db query error: {exc}]"
