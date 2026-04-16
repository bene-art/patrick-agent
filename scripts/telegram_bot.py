"""Patrick Telegram bot — lightweight send/receive via Bot API.

No external deps beyond requests (already in venv).
All Telegram communication goes through this module.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger("pat_tg")

# Config — token and chat ID from env or defaults
TG_BOT_TOKEN = os.environ.get(
    "DELTA_TG_BOT_TOKEN", ""
)
TG_CHAT_ID = int(os.environ.get("PAT_TG_CHAT_ID", "0"))
TG_API = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"

# Max message length for Telegram (4096 chars)
TG_MAX_LEN = 4096


def send_message(text: str, chat_id: int | None = None) -> bool:
    """Send a text message via Telegram Bot API."""
    cid = chat_id or TG_CHAT_ID
    text = text[:TG_MAX_LEN]
    try:
        resp = requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": cid, "text": text},
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.warning("Telegram send failed: %s", resp.text[:200])
        return False
    except Exception as exc:
        logger.warning("Telegram send error: %s", exc)
        return False


def get_updates(offset: int = 0, timeout: int = 30) -> list[dict[str, Any]]:
    """Long-poll for new messages from Telegram.

    Uses long polling — blocks up to `timeout` seconds waiting for messages.
    Returns list of update dicts. Pass the last update_id + 1 as offset
    to acknowledge previous messages.
    """
    try:
        resp = requests.get(
            f"{TG_API}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        return []
    except Exception as exc:
        logger.warning("Telegram getUpdates error: %s", exc)
        return []


def extract_message(update: dict) -> tuple[int, int, str, str] | None:
    """Extract (update_id, chat_id, sender_name, text) from an update.

    Returns None if the update doesn't contain a text message.
    """
    msg = update.get("message")
    if not msg or "text" not in msg:
        return None
    update_id = update.get("update_id", 0)
    chat_id = msg["chat"]["id"]
    sender = msg.get("from", {})
    name = sender.get("first_name", "Unknown")
    text = msg["text"]
    return update_id, chat_id, name, text
