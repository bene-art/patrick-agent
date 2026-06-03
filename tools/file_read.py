"""File read tool — gives Patrick access to reports, configs, and logs.

Read-only. Scoped to known safe directories. No secrets, no credentials,
no files outside the allowlist.

Configure the data directory via the AGENT_DATA_DIR environment variable
(defaults to ~/.patrick-agent). Reports, status snapshots, and logs live
under that directory.

Usage:
    from patrick_agent.tools.file_read import file_read
    result = await file_read("reports/latest.md")
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", str(Path.home() / ".patrick-agent")))
PATRICK_REPO = Path(__file__).resolve().parent.parent

# Allowed directory roots — Patrick can read these
ALLOWED_ROOTS: list[Path] = [
    AGENT_DATA_DIR,                              # reports, status snapshots, logs, plan docs
    PATRICK_REPO / "identity",                   # IDENTITY.md, SOUL.md
    PATRICK_REPO / "config",                     # YAML configs (non-secret)
]

# Directories Patrick can WRITE to (subset of readable)
WRITABLE_ROOTS: list[Path] = [
    AGENT_DATA_DIR / "reports",                  # Generated reports
    AGENT_DATA_DIR / "logs",                     # Activity logs
]

# Blocked patterns — never read these
_BLOCKED_PATTERNS = {"api_key", "secret", "credential", "token", ".env", "password", "auth.yaml"}

MAX_CHARS = 3000  # Cap output to fit in context


def _is_safe_path(path: Path) -> bool:
    """Check if path is within allowed roots and not blocked."""
    resolved = path.resolve()

    # Check blocked patterns
    name_lower = resolved.name.lower()
    if any(b in name_lower for b in _BLOCKED_PATTERNS):
        return False

    # Check if under an allowed root
    for root in ALLOWED_ROOTS:
        root_resolved = root.resolve()
        if root_resolved.is_file():
            # Exact file match (e.g. IDENTITY.md)
            if resolved == root_resolved:
                return True
        elif str(resolved).startswith(str(root_resolved)):
            return True

    return False


async def file_read(path_str: str) -> str:
    """Read a file from an allowed location.

    Args:
        path_str: Relative path from AGENT_DATA_DIR, or absolute path
                  (must be in allowed roots).

    Returns:
        File contents (capped at MAX_CHARS) or error message.
    """
    # Resolve the path — try multiple bases. ~/-prefixed paths are
    # expanded first so absolute and tilde-form requests share a path.
    path = Path(path_str).expanduser()
    candidates = [
        path,
        AGENT_DATA_DIR / path,
        PATRICK_REPO / path,
    ]

    resolved = None
    for candidate in candidates:
        if candidate.exists():
            resolved = candidate
            break

    if resolved is None:
        return f"[file not found: {path_str}]"

    if not _is_safe_path(resolved):
        return f"[access denied: {path_str} is outside allowed directories]"

    try:
        content = resolved.read_text(errors="replace")
        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS] + f"\n\n... (truncated at {MAX_CHARS} chars)"

        logger.info("file_read: path=%s, chars=%d", resolved, len(content))
        return content

    except Exception as exc:
        logger.warning("file_read failed: %s", exc)
        return f"[file read error: {exc}]"


async def list_files(directory: str) -> str:
    """List files in an allowed directory.

    Args:
        directory: Relative or absolute path to a directory.

    Returns:
        File listing or error message.
    """
    path = Path(directory).expanduser()
    candidates = [path, AGENT_DATA_DIR / path, PATRICK_REPO / path]

    resolved = None
    for candidate in candidates:
        if candidate.is_dir():
            resolved = candidate
            break

    if resolved is None:
        return f"[directory not found: {directory}]"

    if not _is_safe_path(resolved):
        return f"[access denied: {directory}]"

    try:
        files = sorted(resolved.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        lines = [f.name for f in files[:20]]
        if len(files) > 20:
            lines.append(f"... ({len(files)} total)")
        return "\n".join(lines)
    except Exception as exc:
        return f"[list error: {exc}]"


def _is_writable_path(path: Path) -> bool:
    """Check if path is within writable roots."""
    resolved = path.resolve()
    name_lower = resolved.name.lower()
    if any(b in name_lower for b in _BLOCKED_PATTERNS):
        return False
    for root in WRITABLE_ROOTS:
        root_resolved = root.resolve()
        if str(resolved).startswith(str(root_resolved)):
            return True
    return False


async def file_write(path_str: str, content: str) -> str:
    """Write content to a file in an allowed writable directory.

    Args:
        path_str: Path to write to (relative or absolute).
        content: Text content to write.

    Returns:
        Success message or error.
    """
    path = Path(path_str).expanduser()
    candidates = [path, AGENT_DATA_DIR / path, PATRICK_REPO / path]

    # For new files, use the first candidate whose parent exists
    resolved = None
    for candidate in candidates:
        if candidate.exists() or candidate.parent.exists():
            resolved = candidate
            break

    if resolved is None:
        return f"[cannot resolve path: {path_str}]"

    if not _is_writable_path(resolved):
        return f"[write denied: {path_str} is not in a writable directory]"

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
        logger.info("file_write: path=%s, chars=%d", resolved, len(content))
        return f"[written: {resolved.name} ({len(content)} chars)]"
    except Exception as exc:
        logger.warning("file_write failed: %s", exc)
        return f"[write error: {exc}]"
