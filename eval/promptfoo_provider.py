"""Custom Promptfoo provider — tests the full Patrick pipeline.

Runs messages through the complete stack:
  tool_router → [SYSTEM DATA] injection → Ollama (local LLM)

This ensures Promptfoo tests what the operator actually experiences,
not just raw Ollama output.

Usage in promptfooconfig.yaml:
  providers:
    - id: python:eval/promptfoo_provider.py

Environment:
    AGENT_MODEL    Ollama model name. Default: gemma3:12b.
    OLLAMA_HOST    Ollama base URL. Default: http://localhost:11434.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make patrick_agent importable when promptfoo runs from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
    from eval.eval_agent import _patrick_chat, _load_system_prompt, DEFAULT_MODEL

    loop = _get_loop()
    system_prompt = _load_system_prompt()
    model = (options or {}).get("model", DEFAULT_MODEL)

    try:
        output = loop.run_until_complete(
            _patrick_chat(
                prompt,
                model=model,
                system_prompt=system_prompt,
                history=None,
                max_tokens=350,
            )
        )
        return {"output": output}
    except Exception as exc:
        return {"error": str(exc)}
