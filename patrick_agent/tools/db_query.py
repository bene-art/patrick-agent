"""Database read tool — gives Patrick access to local SQLite databases.

Read-only SQLite queries. No writes, no DDL, no PRAGMA — SELECT only.

The database allowlist is loaded from `config/databases.yaml` if present,
or from the AGENT_DBS environment variable (JSON object: {"name": "path"}).
If neither is set, this tool returns an empty allowlist.

Example config/databases.yaml:
    picks: ~/data/picks.db
    calibration: ~/data/calibration.db

Usage:
    from patrick_agent.tools.db_query import db_query
    result = await db_query("picks", "SELECT COUNT(*) FROM picks WHERE date = date('now')")
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# parents[2]: tools/ → patrick_agent/ → repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "databases.yaml"

# Hard blocklist — never allow these
_BLOCKED_KEYWORDS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
                     "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX"}


def _load_allowlist() -> dict[str, Path]:
    """Load DB allowlist from config file or env var."""
    # 1. config/databases.yaml
    if _CONFIG_PATH.exists():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
            return {k: Path(v).expanduser() for k, v in data.items()}
        except Exception as exc:
            logger.warning("Failed to load %s: %s", _CONFIG_PATH, exc)

    # 2. AGENT_DBS env var (JSON)
    env_dbs = os.environ.get("AGENT_DBS", "").strip()
    if env_dbs:
        try:
            data = json.loads(env_dbs)
            return {k: Path(v).expanduser() for k, v in data.items()}
        except Exception as exc:
            logger.warning("Invalid AGENT_DBS env var: %s", exc)

    return {}


ALLOWED_DBS: dict[str, Path] = _load_allowlist()


def _is_safe_query(sql: str) -> bool:
    """Check if query is read-only SELECT."""
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return False
    return not any(kw in normalized for kw in _BLOCKED_KEYWORDS)


async def db_query(db_name: str, sql: str, max_rows: int = 20) -> str:
    """Execute a read-only query against a known database.

    Args:
        db_name: Key from ALLOWED_DBS (configured in config/databases.yaml or AGENT_DBS env).
        sql: SELECT query to execute.
        max_rows: Maximum rows to return.

    Returns:
        Query results as formatted text, or error message.
    """
    if not ALLOWED_DBS:
        return (
            "[no databases configured. "
            "Add entries to config/databases.yaml or set AGENT_DBS env var]"
        )

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
