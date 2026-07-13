"""Minimal Gemini Flash chat client.

Used for cloud-escalated tasks where the local 12B model can't help:
function calling for file writes, semantic eval grading, etc.

For pure web search use `local_agent_kit.search.gemini_search.GeminiSearch`
instead — this module is for chat + function-call workflows.

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"


def _api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


async def gemini_chat(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call Gemini Flash and return the raw response dict.

    Args:
        messages: OpenAI-style [{"role": "system"|"user"|"assistant", "content": "..."}].
        model: Gemini model name.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        tools: Optional Gemini tool declarations (e.g. function_declarations).

    Returns:
        {"text": str, "function_call": dict | None, "error": str | None}
    """
    api_key = _api_key()
    if not api_key:
        return {"text": "", "function_call": None, "error": "GEMINI_API_KEY not set"}

    system_text = ""
    contents = []
    for m in messages:
        role = m["role"]
        if role == "system":
            system_text += m["content"] + "\n"
            continue
        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": m["content"]}]})

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_text:
        body["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
    if tools:
        body["tools"] = tools

    # Key goes in a header, not the URL — httpx error messages embed the
    # full URL, so a query-string key leaks into logs and returned errors.
    url = f"{GEMINI_API_URL}/{model}:generateContent"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("gemini_chat failed: %s", exc)
        return {"text": "", "function_call": None, "error": str(exc)}

    candidates = data.get("candidates", [])
    if not candidates:
        return {"text": "", "function_call": None, "error": "no candidates"}

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts: list[str] = []
    function_call: dict[str, Any] | None = None
    for p in parts:
        if "text" in p:
            text_parts.append(p["text"])
        elif "functionCall" in p and function_call is None:
            function_call = p["functionCall"]

    return {
        "text": "".join(text_parts),
        "function_call": function_call,
        "error": None,
    }
