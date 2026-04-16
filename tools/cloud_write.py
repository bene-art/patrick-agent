"""Cloud-escalated file write — Gemini does the thinking, system does the writing.

When Patrick needs to update a file, he can't generate content AND call a write
tool in one pass (gemma3:12b doesn't support tool calling). So we escalate to
Gemini Flash which CAN do function calling:

1. Read the current file
2. Send to Gemini with context + write_file tool
3. Gemini generates new content and calls write_file
4. We execute the write
5. Return confirmation for Patrick to relay

Scoped to BenAi Master Plan directory only.

Usage:
    from benai_infra.tools.cloud_write import cloud_write_file
    result = await cloud_write_file(
        path="07_Agents/Patrick/STATUS.md",
        instruction="Update with current state: 12b model, Telegram, 4 tools",
        context="Patrick's current IDENTITY.md contents..."
    )
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MASTER_PLAN = Path.home() / "Desktop" / "project-docs"


async def cloud_write_file(
    path: str,
    instruction: str,
    context: str = "",
) -> str:
    """Escalate to Gemini Flash to generate and write file content.

    Args:
        path: Relative path within Master Plan directory.
        instruction: What to do (e.g. "Update with current state").
        context: Additional context (e.g. Patrick's IDENTITY.md).

    Returns:
        Confirmation message or error.
    """
    from benai_infra.llm.cloud_providers import route_to_gemini
    from benai_infra.model_registry import MODEL_REGISTRY
    from benai_infra.tools.file_read import file_read, file_write, _is_writable_path

    cfg = MODEL_REGISTRY.get("gemini_flash")
    if not cfg:
        return "[cloud write unavailable — gemini_flash not in registry]"

    # Resolve path within master plan
    full_path = MASTER_PLAN / path
    if not _is_writable_path(full_path):
        return f"[write denied: {path} is not in the Master Plan directory]"

    # Read current file if it exists
    current_content = ""
    if full_path.exists():
        current_content = await file_read(str(full_path))

    # Build the Gemini request with function calling
    system_prompt = (
        "You are Patrick, BenAi's operations officer. You are updating a documentation file "
        "in the BenAi Master Plan. Write accurate, current content based on the context provided. "
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

    # Gemini function calling tool definition
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
        result = await route_to_gemini(
            cfg, messages, temperature=0.3, max_tokens=2000, tools=tools
        )

        if not result:
            return "[Gemini returned empty response]"

        # Parse the function call from the response
        if "<tool_call>" in result:
            # Extract the tool call JSON
            start = result.index("<tool_call>") + len("<tool_call>")
            end = result.index("</tool_call>")
            call_json = json.loads(result[start:end])

            if call_json.get("tool") == "write_file":
                content = call_json["params"].get("content", "")
                if content:
                    write_result = await file_write(str(full_path), content)
                    logger.info(
                        "cloud_write: path=%s, chars=%d",
                        full_path, len(content),
                    )
                    return f"[file updated: {path} ({len(content)} chars)]"

        # Gemini might return text without a function call — use the text as content
        if result.strip() and "<tool_call>" not in result:
            write_result = await file_write(str(full_path), result)
            logger.info("cloud_write (text fallback): path=%s, chars=%d", full_path, len(result))
            return f"[file updated: {path} ({len(result)} chars)]"

        return "[Gemini did not generate file content]"

    except Exception as exc:
        logger.warning("cloud_write failed: %s", exc)
        return f"[cloud write error: {exc}]"
