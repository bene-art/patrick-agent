"""Web search tool — gives Patrick eyes beyond the Mac mini.

Thin wrapper around `local_agent_kit.search.gemini_search.GeminiSearch`.
Uses Gemini Flash with Google Search grounding. No extra API key needed
beyond GEMINI_API_KEY. Free tier: 15 RPM, 1M TPM.

Usage:
    from patrick_agent.tools.web_search import web_search
    result = await web_search("NBA injury report today")
"""
from __future__ import annotations

import logging

from local_agent_kit.search.gemini_search import GeminiSearch

logger = logging.getLogger(__name__)

_provider: GeminiSearch | None = None


def _get_provider() -> GeminiSearch:
    global _provider
    if _provider is None:
        _provider = GeminiSearch()
    return _provider


async def web_search(query: str, max_tokens: int = 400) -> str:
    """Search the web via Gemini Flash + Google Search grounding."""
    try:
        result = await _get_provider().search(query)
        logger.info("web_search: query=%r, result_len=%d", query[:50], len(result))
        return result
    except Exception as exc:
        logger.warning("web_search failed: %s", exc)
        return f"[web search error: {exc}]"
