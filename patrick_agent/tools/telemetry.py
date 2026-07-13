"""Tool telemetry — logs every tool invocation in production.

Every message that hits the tool router gets a telemetry entry: what
was asked, which tool fired, and the result size. The JSONL file is the
raw material for growing the eval corpus — review it and promote real
misses into test cases (curation is manual by design).

Usage:
    from patrick_agent.tools.telemetry import log_tool_use, log_tool_skip

    log_tool_use("web_search", message, result)
    log_tool_skip(message)  # no tool fired
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".patrick-agent" / "logs" / "tool_telemetry.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_tool_use(tool: str, message: str, result: str) -> None:
    """Log a successful tool invocation."""
    _write({
        "ts": _now_iso(),
        "event": "tool_use",
        "tool": tool,
        "message": message[:200],
        "result_len": len(result),
    })


def log_tool_skip(message: str) -> None:
    """Log when no tool fired for a message."""
    _write({
        "ts": _now_iso(),
        "event": "tool_skip",
        "tool": None,
        "message": message[:200],
        "result_len": 0,
    })


def _write(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.debug("telemetry write failed", exc_info=True)
