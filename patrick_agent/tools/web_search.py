"""Web search tool — Gemini Flash with Google Search grounding.

Self-contained: routes through this repo's `gemini_chat` client with the
`google_search` grounding tool. (Previously wrapped a search provider in
local-agent-kit; the kit removed its cloud search in v0.4.0 to stay
zero-cloud-account. Patrick's doctrine differs — local brain, cloud
hands — so the cloud search lives here now.)

Requires GEMINI_API_KEY (or GOOGLE_API_KEY). Free tier: 15 RPM, 1M TPM.

Usage:
    from patrick_agent.tools.web_search import web_search
    result = await web_search("NBA injury report today")
"""
from __future__ import annotations

import logging

from patrick_agent.tools.gemini_chat import gemini_chat

logger = logging.getLogger(__name__)


async def web_search(query: str, max_tokens: int = 800) -> str:
    """Search the web via Gemini Flash + Google Search grounding."""
    try:
        result = await gemini_chat(
            [{"role": "user", "content": query}],
            tools=[{"google_search": {}}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.warning("web_search failed: %s", exc)
        return f"[web search error: {exc}]"

    if result["error"]:
        logger.warning("web_search failed: %s", result["error"])
        return f"[web search error: {result['error']}]"

    text = result["text"].strip()
    if not text:
        return "[web search error: empty response]"
    logger.info("web_search: query=%r, result_len=%d", query[:50], len(text))
    return text
