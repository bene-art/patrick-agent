"""Minimal Telegram conversational channel — Bot API long polling.

Implements local-agent-kit's `Channel` ABC (the kit removed its own
Telegram channel in v0.4.0 to stay zero-cloud-account; Patrick keeps the
pattern alive here). One bot, one chat: getUpdates long-poll in,
sendMessage out.

Requires:
    PAT_TG_BOT_TOKEN (or TG_BOT_TOKEN)  bot token from @BotFather
    PAT_TG_CHAT_ID   (or TG_CHAT_ID)    chat to accept messages from;
                                        if unset, all chats are accepted
                                        and replies go to the sender.
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import httpx

from local_agent_kit.channels.base import Channel, Message

logger = logging.getLogger(__name__)

_TG_API_BASE = "https://api.telegram.org/bot"
_POLL_TIMEOUT_S = 50


class TelegramListenerChannel(Channel):
    """Long-polling conversational Telegram channel."""

    def __init__(self, bot_token: str | None = None, chat_id: int | str | None = None):
        self.bot_token = (
            bot_token
            or os.environ.get("PAT_TG_BOT_TOKEN")
            or os.environ.get("TG_BOT_TOKEN", "")
        )
        if not self.bot_token:
            raise ValueError(
                "Telegram bot token required — set PAT_TG_BOT_TOKEN (or pass bot_token=)"
            )
        self.chat_id = (
            chat_id
            if chat_id is not None
            else os.environ.get("PAT_TG_CHAT_ID") or os.environ.get("TG_CHAT_ID") or None
        )
        self._base = f"{_TG_API_BASE}{self.bot_token}"
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_POLL_TIMEOUT_S + 10)
        return self._client

    async def listen(self) -> AsyncIterator[Message]:
        client = self._get_client()
        offset: int | None = None
        while True:
            try:
                params: dict = {"timeout": _POLL_TIMEOUT_S}
                if offset is not None:
                    params["offset"] = offset
                resp = await client.get(f"{self._base}/getUpdates", params=params)
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except Exception as exc:
                logger.warning("Telegram poll failed: %s", exc)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message") or {}
                text = msg.get("text")
                chat = msg.get("chat", {}).get("id")
                if not text or chat is None:
                    continue
                # If a chat_id is configured, ignore everything else.
                if self.chat_id is not None and str(chat) != str(self.chat_id):
                    logger.info("Telegram: ignoring message from chat %s", chat)
                    continue
                yield Message(
                    text=text,
                    sender=str(msg.get("from", {}).get("id", "")),
                    channel_id="telegram",
                    thread_id=str(chat),
                )

    async def send(self, text: str, thread_id: str | None = None) -> bool:
        target = thread_id or self.chat_id
        if target is None:
            logger.warning("Telegram send skipped: no chat_id configured")
            return False
        try:
            resp = await self._get_client().post(
                f"{self._base}/sendMessage",
                json={"chat_id": target, "text": text[:4096]},
            )
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

    async def stop(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
