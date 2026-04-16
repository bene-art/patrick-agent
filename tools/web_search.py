"""Web search tool — gives Patrick eyes beyond the Mac mini.

Uses Gemini Flash with Google Search grounding. No extra API key
needed beyond GEMINI_API_KEY. Free tier: 15 RPM, 1M TPM.

Usage:
    from benai_infra.tools.web_search import web_search
    result = await web_search("NBA injury report today")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def web_search(query: str, max_tokens: int = 400) -> str:
    """Search the web via Gemini Flash + Google Search grounding.

    Args:
        query: The search query.
        max_tokens: Max response tokens.

    Returns:
        Search results as text, or error message on failure.
    """
    try:
        from benai_infra.llm.cloud_providers import route_to_gemini
        from benai_infra.model_registry import MODEL_REGISTRY

        cfg = MODEL_REGISTRY.get("gemini_flash")
        if not cfg:
            return "[web search unavailable — gemini_flash not in registry]"

        messages = [
            {"role": "user", "content": query},
        ]
        tools = [{"google_search": {}}]

        result = await route_to_gemini(
            cfg,
            messages,
            temperature=0.2,
            max_tokens=max_tokens,
            tools=tools,
        )

        if result and isinstance(result, str):
            logger.info("web_search: query=%r, result_len=%d", query[:50], len(result))
            return result

        return "[web search returned empty]"

    except Exception as exc:
        logger.warning("web_search failed: %s", exc)
        return f"[web search error: {exc}]"
