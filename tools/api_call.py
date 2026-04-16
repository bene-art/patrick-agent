"""API call tool — read-only access to external services.

Safe tier only. Read-only endpoints. No trades, no orders, no mutations.
Uses existing BenAi integrations (Alpaca, The Odds API).

Usage:
    from benai_infra.tools.api_call import api_call
    result = await api_call("alpaca_positions")
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Alpaca helpers ────────────────────────────────────────────────────

def _get_alpaca_broker():
    """Lazy-load AlpacaBroker with env credentials."""
    from src.benai_local.agents.finance.stock_market.execution.alpaca_broker import (
        AlpacaBroker,
    )
    return AlpacaBroker(
        api_key=os.getenv("ALPACA_API_KEY", ""),
        api_secret=os.getenv("ALPACA_API_SECRET", ""),
        paper=os.getenv("ALPACA_PAPER", "true").lower() == "true",
    )


def _alpaca_account() -> str:
    try:
        broker = _get_alpaca_broker()
        acct = broker.get_account()
        lines = [
            f"Status: {acct.get('status', '?')}",
            f"Cash: ${float(acct.get('cash', 0)):,.2f}",
            f"Portfolio value: ${float(acct.get('portfolio_value', 0)):,.2f}",
            f"Buying power: ${float(acct.get('buying_power', 0)):,.2f}",
            f"Day P&L: ${float(acct.get('equity', 0)) - float(acct.get('last_equity', 0)):,.2f}",
            f"Paper: {acct.get('account_type', '?') == 'paper' or 'paper' in str(acct.get('id', ''))}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[Alpaca account error: {exc}]"


def _alpaca_positions() -> str:
    try:
        broker = _get_alpaca_broker()
        positions = broker.get_positions()
        if not positions:
            return "No open positions."
        lines = []
        for p in positions:
            symbol = p.get("symbol", "?")
            qty = p.get("qty", "?")
            market_val = float(p.get("market_value", 0))
            unrealized = float(p.get("unrealized_pl", 0))
            pct = float(p.get("unrealized_plpc", 0)) * 100
            lines.append(f"{symbol}: {qty} shares, ${market_val:,.2f} ({unrealized:+,.2f} / {pct:+.1f}%)")
        return "\n".join(lines)
    except Exception as exc:
        return f"[Alpaca positions error: {exc}]"


def _alpaca_quote(symbol: str) -> str:
    try:
        broker = _get_alpaca_broker()
        quote = broker.get_latest_quote(symbol.upper())
        if quote:
            bid = quote.get("bid_price", quote.get("bp", "?"))
            ask = quote.get("ask_price", quote.get("ap", "?"))
            return f"{symbol.upper()}: bid ${bid}, ask ${ask}"
        return f"[no quote for {symbol}]"
    except Exception as exc:
        return f"[Alpaca quote error: {exc}]"


# ── Odds API helpers ──────────────────────────────────────────────────

def _odds_api_games(sport: str = "basketball_nba") -> str:
    """Fetch upcoming games from The Odds API."""
    import requests
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        return "[ODDS_API_KEY not set]"
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
            params={
                "apiKey": api_key,
                "regions": "us",
                "markets": "h2h",
                "oddsFormat": "american",
            },
            timeout=10,
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

ALLOWED_CALLS: dict[str, tuple[Any, str]] = {
    "alpaca_account":    (_alpaca_account,   "Alpaca paper trading account summary"),
    "alpaca_positions":  (_alpaca_positions,  "Current stock positions"),
    "odds_nba":          (lambda: _odds_api_games("basketball_nba"), "Upcoming NBA games with odds"),
    "odds_mlb":          (lambda: _odds_api_games("baseball_mlb"),   "Upcoming MLB games with odds"),
    "odds_nhl":          (lambda: _odds_api_games("icehockey_nhl"),  "Upcoming NHL games with odds"),
}


async def api_call(call_id: str, **kwargs) -> str:
    """Execute a read-only API call.

    Args:
        call_id: Key from ALLOWED_CALLS.

    Returns:
        API response as text or error message.
    """
    if call_id not in ALLOWED_CALLS:
        avail = ", ".join(ALLOWED_CALLS.keys())
        return f"[unknown API call: {call_id}. Available: {avail}]"

    handler, desc = ALLOWED_CALLS[call_id]

    try:
        logger.info("api_call: %s (%s)", call_id, desc)

        if call_id == "alpaca_quote" and "symbol" in kwargs:
            result = await asyncio.to_thread(_alpaca_quote, kwargs["symbol"])
        else:
            result = await asyncio.to_thread(handler)

        logger.info("api_call: %s completed, %d chars", call_id, len(result))
        return result

    except Exception as exc:
        logger.warning("api_call: %s failed: %s", call_id, exc)
        return f"[API call error: {exc}]"
