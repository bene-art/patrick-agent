"""Web search tool — gives Patrick eyes beyond the Mac mini.

Thin wrapper around `local_agent_kit.search.gemini_search.GeminiSearch`.
Uses Gemini Flash with Google Search grounding. No extra API key needed
beyond GEMINI_API_KEY. Free tier: 15 RPM, 1M TPM.

The GeminiSearch import is deferred so `patrick_agent` can be imported
in environments where local-agent-kit is not yet installed (the call
fails loudly, but module import does not).

Usage:
    from patrick_agent.tools.web_search import web_search
    result = await web_search("NBA injury report today")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        try:
            from local_agent_kit.search.gemini_search import GeminiSearch
        except ImportError as exc:
            raise RuntimeError(
                "local-agent-kit is not installed. "
                "Run: pip install -e . (or pip install -r requirements.txt)"
            ) from exc
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
