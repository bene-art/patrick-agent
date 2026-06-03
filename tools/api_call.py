"""API call tool — read-only access to external services.

Safe tier only. Read-only endpoints. No trades, no orders, no mutations.
Direct REST calls to Alpaca (paper/live brokerage) and The Odds API.

Usage:
    from patrick_agent.tools.api_call import api_call
    result = await api_call("alpaca_positions")
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


# ── Alpaca helpers ────────────────────────────────────────────────────

def _alpaca_base() -> str:
    paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    return "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"


def _alpaca_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_API_SECRET", ""),
    }


def _have_alpaca_creds() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"))


async def _alpaca_get(path: str, base: str | None = None) -> Any:
    url = f"{base or _alpaca_base()}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=_alpaca_headers())
        resp.raise_for_status()
        return resp.json()


async def _alpaca_account() -> str:
    if not _have_alpaca_creds():
        return "[ALPACA_API_KEY / ALPACA_API_SECRET not set]"
    try:
        acct = await _alpaca_get("/v2/account")
        equity = float(acct.get("equity", 0))
        last_equity = float(acct.get("last_equity", 0))
        lines = [
            f"Status: {acct.get('status', '?')}",
            f"Cash: ${float(acct.get('cash', 0)):,.2f}",
            f"Portfolio value: ${float(acct.get('portfolio_value', 0)):,.2f}",
            f"Buying power: ${float(acct.get('buying_power', 0)):,.2f}",
            f"Day P&L: ${equity - last_equity:,.2f}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[Alpaca account error: {exc}]"


async def _alpaca_positions() -> str:
    if not _have_alpaca_creds():
        return "[ALPACA_API_KEY / ALPACA_API_SECRET not set]"
    try:
        positions = await _alpaca_get("/v2/positions")
        if not positions:
            return "No open positions."
        lines = []
        for p in positions:
            symbol = p.get("symbol", "?")
            qty = p.get("qty", "?")
            market_val = float(p.get("market_value", 0))
            unrealized = float(p.get("unrealized_pl", 0))
            pct = float(p.get("unrealized_plpc", 0)) * 100
            lines.append(
                f"{symbol}: {qty} shares, ${market_val:,.2f} ({unrealized:+,.2f} / {pct:+.1f}%)"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"[Alpaca positions error: {exc}]"


async def _alpaca_quote(symbol: str) -> str:
    if not _have_alpaca_creds():
        return "[ALPACA_API_KEY / ALPACA_API_SECRET not set]"
    try:
        data = await _alpaca_get(
            f"/v2/stocks/{symbol.upper()}/quotes/latest",
            base="https://data.alpaca.markets",
        )
        quote = data.get("quote", {}) if isinstance(data, dict) else {}
        bid = quote.get("bp", "?")
        ask = quote.get("ap", "?")
        return f"{symbol.upper()}: bid ${bid}, ask ${ask}"
    except Exception as exc:
        return f"[Alpaca quote error: {exc}]"


# ── Odds API helpers ──────────────────────────────────────────────────

async def _odds_api_games(sport: str = "basketball_nba") -> str:
    """Fetch upcoming games from The Odds API."""
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        return "[ODDS_API_KEY not set]"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "us",
                    "markets": "h2h",
                    "oddsFormat": "american",
                },
            )
            resp.raise_for_status()
            games = resp.json()
        if not games:
            return f"No upcoming {sport} games with odds."
        lines = []
        for g in games[:10]:
            home = g.get("home_team", "?")
            away = g.get("away_team", "?")
            start = g.get("commence_time", "?")[:16]
            lines.append(f"{away} @ {home} — {start}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[Odds API error: {exc}]"


# ── Dispatch ──────────────────────────────────────────────────────────

ALLOWED_CALLS: dict[str, tuple[Callable, str]] = {
    "alpaca_account":   (_alpaca_account,    "Alpaca brokerage account summary"),
    "alpaca_positions": (_alpaca_positions,  "Current stock positions"),
    "odds_nba":         (lambda: _odds_api_games("basketball_nba"), "Upcoming NBA games with odds"),
    "odds_mlb":         (lambda: _odds_api_games("baseball_mlb"),   "Upcoming MLB games with odds"),
    "odds_nhl":         (lambda: _odds_api_games("icehockey_nhl"),  "Upcoming NHL games with odds"),
}


async def api_call(call_id: str, **kwargs) -> str:
    """Execute a read-only API call.

    Args:
        call_id: Key from ALLOWED_CALLS (or "alpaca_quote" with symbol kwarg).

    Returns:
        API response as text or error message.
    """
    if call_id == "alpaca_quote" and "symbol" in kwargs:
        return await _alpaca_quote(kwargs["symbol"])

    if call_id not in ALLOWED_CALLS:
        avail = ", ".join(ALLOWED_CALLS.keys())
        return f"[unknown API call: {call_id}. Available: {avail}]"

    handler, desc = ALLOWED_CALLS[call_id]

    try:
        logger.info("api_call: %s (%s)", call_id, desc)
        result = await handler()
        logger.info("api_call: %s completed, %d chars", call_id, len(result))
        return result
    except Exception as exc:
        logger.warning("api_call: %s failed: %s", call_id, exc)
        return f"[API call error: {exc}]"
