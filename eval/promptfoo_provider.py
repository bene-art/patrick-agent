"""Custom Promptfoo provider — tests the full Patrick pipeline.

Runs messages through the complete stack:
  tool_router → [SYSTEM DATA] injection → os_agent_chat (12b)

This ensures Promptfoo tests what Commander actually experiences,
not just raw Ollama output.

Usage in promptfooconfig.yaml:
  providers:
    - id: python:data/eval/promptfoo_provider.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure BenAi imports work
BENAI_ROOT = Path(__file__).resolve().parents[2]
for p in [str(BENAI_ROOT), str(BENAI_ROOT / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Disable circuit breaker for eval
os.environ.setdefault("BENAI_CIRCUIT_ENABLED", "false")


def _get_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """Promptfoo calls this for each test case.

    Args:
        prompt: The rendered prompt (user message).
        options: Provider config from promptfooconfig.yaml.
        context: Test context (vars, etc).

    Returns:
        {"output": "response text"} or {"error": "message"}
    """
    loop = _get_loop()

    try:
        # Run through the full tool pipeline
        from tools.tools.tool_router import route_tools
        tool_blocks = loop.run_until_complete(route_tools(prompt))

        # Build the message with tool context (same as pat_imsg_loop)
        tool_context = ""
        if tool_blocks:
            tool_context = "\n\n" + "\n\n".join(tool_blocks)

        user_msg = prompt + tool_context

        # Call Patrick via the LLM service
        from tools.llm_service import os_agent_chat
        resp = loop.run_until_complete(
            os_agent_chat(
                "agent",
                user_msg,
                source="promptfoo_eval",
                max_tokens=350,
                inject_memory=False,
                rag_enabled=False,
            )
        )

        output = resp.content if resp and resp.content else ""
        return {"output": output}

    except Exception as exc:
        return {"error": str(exc)}
