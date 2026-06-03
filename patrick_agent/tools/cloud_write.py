"""Cloud-escalated file write — Gemini does the thinking, the system does the writing.

When the local agent needs to update a file, it can't generate content AND
call a write tool in one pass (gemma3:12b doesn't support tool calling).
So we escalate to Gemini Flash which CAN do function calling:

1. Read the current file
2. Send to Gemini with context + write_file function declaration
3. Gemini generates new content and calls write_file
4. We execute the write locally
5. Return confirmation for the local agent to relay

Scoped to AGENT_DATA_DIR (default ~/.patrick-agent). The path you pass is
resolved relative to that directory.

Usage:
    from patrick_agent.tools.cloud_write import cloud_write_file
    result = await cloud_write_file(
        path="STATUS.md",
        instruction="Update with current state: 12B model, Telegram, 9 tools",
        context="Patrick's current IDENTITY.md contents...",
    )
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", str(Path.home() / ".patrick-agent")))


async def cloud_write_file(
    path: str,
    instruction: str,
    context: str = "",
) -> str:
    """Escalate to Gemini Flash to generate and write file content.

    Args:
        path: Relative path within AGENT_DATA_DIR (e.g. "STATUS.md").
        instruction: What to do (e.g. "Update with current state").
        context: Additional context (e.g. IDENTITY.md contents).

    Returns:
        Confirmation message or error.
    """
    from patrick_agent.tools.file_read import file_read, file_write, _is_writable_path
    from patrick_agent.tools.gemini_chat import gemini_chat

    full_path = AGENT_DATA_DIR / path
    if not _is_writable_path(full_path):
        return f"[write denied: {path} is not in a writable directory under AGENT_DATA_DIR]"

    # Read current file if it exists
    current_content = ""
    if full_path.exists():
        current_content = await file_read(str(full_path))

    # Build the Gemini request with function calling
    system_prompt = (
        "You are updating a documentation file for a local-first AI agent. "
        "Write accurate, current content based on the context provided. "
        "Use markdown formatting. Be concise and factual. "
        "Call the write_file function with the COMPLETE updated file content."
    )

    user_message = f"Instruction: {instruction}\n\n"
    if current_content:
        user_message += f"Current file contents:\n```\n{current_content[:2000]}\n```\n\n"
    if context:
        user_message += f"Current system context:\n{context[:2000]}\n"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    # Gemini function-call tool declaration
    tools = [{
        "function_declarations": [{
            "name": "write_file",
            "description": "Write the complete updated file content",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The complete markdown file content to write",
                    }
                },
                "required": ["content"],
            },
        }]
    }]

    try:
        resp = await gemini_chat(
            messages,
            temperature=0.3,
            max_tokens=2000,
            tools=tools,
        )

        if resp.get("error"):
            return f"[Gemini error: {resp['error']}]"

        fc = resp.get("function_call")
        if fc and fc.get("name") == "write_file":
            content = fc.get("args", {}).get("content", "")
            if content:
                await file_write(str(full_path), content)
                logger.info("cloud_write: path=%s, chars=%d", full_path, len(content))
                return f"[file updated: {path} ({len(content)} chars)]"

        # Fallback: Gemini returned text instead of a function call
        text = resp.get("text", "").strip()
        if text:
            await file_write(str(full_path), text)
            logger.info("cloud_write (text fallback): path=%s, chars=%d", full_path, len(text))
            return f"[file updated: {path} ({len(text)} chars)]"

        return "[Gemini did not generate file content]"

    except Exception as exc:
        logger.warning("cloud_write failed: %s", exc)
        return f"[cloud write error: {exc}]"
