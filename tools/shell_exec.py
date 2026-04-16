"""Shell exec tool — read-only system commands for Patrick.

SAFE TIER ONLY. No writes, no restarts, no kills. Allowlist-enforced.
Every execution is logged. If the command isn't on the list, it doesn't run.

Future: medium-risk commands (restarts, service control) will require
Commander approval via Telegram before execution.

Usage:
    from benai_infra.tools.shell_exec import shell_exec
    result = await shell_exec("ollama_ps")
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

# ── Allowlist: command_id → (actual command, description, timeout_sec) ──
# These are the ONLY commands Patrick can run. Period.
SAFE_COMMANDS: dict[str, tuple[str, str, int]] = {
    "ollama_ps":       ("ollama ps",                "Show loaded Ollama models",          10),
    "ollama_list":     ("ollama list",              "List available Ollama models",        10),
    "disk_space":      ("df -h",                    "Check disk space",                    10),
    "memory":          ("vm_stat",                  "Check memory pressure",               10),
    "uptime":          ("uptime",                   "System uptime and load",              10),
    "top_mem":         ("top -l 1 -o mem -n 10 -stats pid,command,mem",
                                                    "Top 10 memory consumers",             15),
    "top_cpu":         ("top -l 1 -o cpu -n 10 -stats pid,command,cpu",
                                                    "Top 10 CPU consumers",                15),
    "launchd_benai":   ("launchctl list | grep benai",
                                                    "List BenAi launchd jobs",             10),
    "ports":           ("lsof -iTCP -sTCP:LISTEN -P -n | grep -E '8000|8089|11434|59809|3333|5174'",
                                                    "Check BenAi service ports",           10),
    "git_status":      ("git -C ~/BenAi_Local status --short",
                                                    "Git working tree status",             10),
    "git_log":         ("git -C ~/BenAi_Local log --oneline -10",
                                                    "Last 10 commits",                     10),
    "python_procs":    ("ps aux | grep python | grep -v grep | head -15",
                                                    "Running Python processes",            10),
    "health_ledger":   ("sqlite3 ~/.benai_local/health_ledger.db \"SELECT job, status, ts FROM runs ORDER BY ts DESC LIMIT 10;\"",
                                                    "Recent job health entries",           10),
}


def list_available_commands() -> str:
    """List all commands Patrick can run."""
    lines = ["Available system commands:"]
    for cmd_id, (_, desc, _) in SAFE_COMMANDS.items():
        lines.append(f"  {cmd_id}: {desc}")
    return "\n".join(lines)


async def shell_exec(command_id: str) -> str:
    """Execute a safe, allowlisted command.

    Args:
        command_id: Key from SAFE_COMMANDS.

    Returns:
        Command output or error message.
    """
    if command_id not in SAFE_COMMANDS:
        return f"[command not allowed: {command_id}. {list_available_commands()}]"

    cmd, desc, timeout = SAFE_COMMANDS[command_id]

    try:
        logger.info("shell_exec: running %s (%s)", command_id, cmd[:40])
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[stderr: {result.stderr.strip()[:200]}]"

        if not output:
            output = "[command produced no output]"

        # Cap output
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"

        logger.info("shell_exec: %s completed, %d chars output", command_id, len(output))
        return output

    except subprocess.TimeoutExpired:
        logger.warning("shell_exec: %s timed out after %ds", command_id, timeout)
        return f"[command timed out after {timeout}s]"
    except Exception as exc:
        logger.warning("shell_exec: %s failed: %s", command_id, exc)
        return f"[command error: {exc}]"
