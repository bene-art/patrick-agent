"""Telegram notification channel — direct Bot API send.

For one-shot notifications (alerts, morning briefs). For full
conversational message loops, use
`patrick_agent.channels.telegram_channel.TelegramListenerChannel`.

Requires:
    PAT_TG_BOT_TOKEN  Telegram bot token (from @BotFather).
    PAT_TG_CHAT_ID    Default chat ID to send to.
"""
from __future__ import annotations

import logging
import os

import requests

from patrick_agent.notify.base import (
    Channel,
    ChannelConfig,
    ChannelFormat,
    DeliveryResult,
    Severity,
)

_logger = logging.getLogger(__name__)

_TG_API_BASE = "https://api.telegram.org/bot"


def _send_message(
    text: str,
    chat_id: int | str | None = None,
    parse_mode: str | None = None,
) -> bool:
    """Send a text message via the Telegram Bot API.

    If Telegram rejects the message with a parse_mode set (unbalanced
    markup entities), retry once as plain text — delivery beats styling.
    """
    token = os.environ.get("PAT_TG_BOT_TOKEN", "")
    cid = chat_id if chat_id is not None else os.environ.get("PAT_TG_CHAT_ID", "")
    if not token or not cid:
        _logger.warning("Telegram credentials missing (PAT_TG_BOT_TOKEN/PAT_TG_CHAT_ID)")
        return False

    payload: dict = {"chat_id": cid, "text": text[:4096]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(
            f"{_TG_API_BASE}{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        if parse_mode:
            _logger.warning(
                "Telegram send with parse_mode=%s failed (%s); retrying plain",
                parse_mode, resp.text[:200],
            )
            return _send_message(text, chat_id=chat_id, parse_mode=None)
        _logger.warning("Telegram send failed: %s", resp.text[:200])
        return False
    except Exception as exc:
        _logger.warning("Telegram send error: %s", exc)
        return False


class TelegramChannel(Channel):
    def __init__(
        self,
        *,
        channel_id: str = "telegram",
        config: ChannelConfig | None = None,
        chat_id: int | str | None = None,
    ) -> None:
        super().__init__(channel_id, config)
        self.chat_id = chat_id

    def send(
        self,
        title: str,
        body: str,
        fmt: ChannelFormat = ChannelFormat.PLAIN,
        severity: "Severity | None" = None,
    ) -> DeliveryResult:
        preview = self._preview(body)
        if not self.config.enabled:
            return DeliveryResult(
                success=False,
                channel_id=self.channel_id,
                timestamp=self._now(),
                message_preview=preview,
                error="channel disabled",
            )
        # Use the First Officer formatter for alerts (Tier 3)
        if severity is not None and severity in (
            Severity.CAPITAL_CRITICAL, Severity.HIGH
        ):
            from patrick_agent.notify.formatter import fmt_alert
            text = fmt_alert(title=title, error=body, severity=severity)
        else:
            text = f"{title}\n\n{body}" if title else body
        # Telegram hard limit 4096; honor configured cap otherwise.
        text = text[: min(self.config.max_message_length, 4096)]
        # Honor the requested format — the tier formatter emits *bold*
        # Markdown; without parse_mode Telegram renders literal asterisks.
        parse_mode = {
            ChannelFormat.MARKDOWN: "Markdown",
            ChannelFormat.HTML: "HTML",
        }.get(fmt)
        ok = _send_message(text, chat_id=self.chat_id, parse_mode=parse_mode)
        return DeliveryResult(
            success=bool(ok),
            channel_id=self.channel_id,
            timestamp=self._now(),
            message_preview=preview,
            error=None if ok else "Telegram send failed",
        )
