"""Tool telemetry — logs every tool invocation in production.

Every Telegram message that hits the tool router gets a telemetry
entry: what was asked, which tool fired, result size, and whether
Patrick used the data in his response.

The JSONL file feeds back into the eval corpus — real conversations
become test cases automatically.

Usage:
    from benai_infra.tools.telemetry import log_tool_use, log_tool_skip

    log_tool_use("web_search", message, result, response)
    log_tool_skip(message, response)  # no tool fired
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".delta-orchestrator" / "logs" / "tool_telemetry.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _did_use_data(response: str) -> bool:
    """Heuristic: did Patrick use the tool data or deflect?"""
    deflections = [
        "don't have that data",
        "i cannot",
        "no web access",
        "i don't have",
        "not available",
        "i can't access",
    ]
    rl = response.lower()
    return not any(d in rl for d in deflections)


def log_tool_use(
    tool: str,
    message: str,
    result: str,
    response: str = "",
) -> None:
    """Log a successful tool invocation."""
    entry = {
        "ts": _now_iso(),
        "event": "tool_use",
        "tool": tool,
        "message": message[:200],
        "result_len": len(result),
        "response_len": len(response),
        "data_used": _did_use_data(response) if response else None,
    }
    _write(entry)


def log_tool_skip(
    message: str,
    response: str = "",
) -> None:
    """Log when no tool fired for a message."""
    entry = {
        "ts": _now_iso(),
        "event": "tool_skip",
        "tool": None,
        "message": message[:200],
        "result_len": 0,
        "response_len": len(response),
        "data_used": None,
    }
    _write(entry)


def log_tool_error(
    tool: str,
    message: str,
    error: str,
) -> None:
    """Log a tool that triggered but errored."""
    entry = {
        "ts": _now_iso(),
        "event": "tool_error",
        "tool": tool,
        "message": message[:200],
        "error": error[:200],
    }
    _write(entry)


def _write(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.debug("telemetry write failed", exc_info=True)


def get_summary(hours: int = 24) -> dict:
    """Summarize recent tool usage for the morning briefing."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stats: dict = {"total": 0, "by_tool": {}, "skips": 0, "errors": 0, "data_used": 0, "data_ignored": 0}

    if not LOG_PATH.exists():
        return stats

    for line in open(LOG_PATH):
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e["ts"])
            if ts < cutoff:
                continue
            stats["total"] += 1
            if e["event"] == "tool_use":
                tool = e.get("tool", "unknown")
                stats["by_tool"][tool] = stats["by_tool"].get(tool, 0) + 1
                if e.get("data_used") is True:
                    stats["data_used"] += 1
                elif e.get("data_used") is False:
                    stats["data_ignored"] += 1
            elif e["event"] == "tool_skip":
                stats["skips"] += 1
            elif e["event"] == "tool_error":
                stats["errors"] += 1
        except (json.JSONDecodeError, KeyError):
            continue

    return stats
