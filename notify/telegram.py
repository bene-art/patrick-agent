"""Telegram channel — wraps scripts.pat_tg.send_message.

Pilot decision: shares the Patrick bot token (PAT_TG_BOT_TOKEN). Verified
safe because Telegram Bot API's getUpdates does not return the bot's own
outbound messages, so Patrick's pat_tg_loop.py will not see notify_service
alerts in its inbound stream and cannot self-pollute.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from patrick_agent.notify.base import (
    Channel,
    ChannelConfig,
    ChannelFormat,
    DeliveryResult,
    Severity,
)

_logger = logging.getLogger(__name__)


def _load_pat_tg():
    """Lazy import pat_tg from scripts/. Keeps patrick_agent import-time clean."""
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import pat_tg  # type: ignore

    return pat_tg


class TelegramChannel(Channel):
    def __init__(
        self,
        *,
        channel_id: str = "telegram",
        config: ChannelConfig | None = None,
        chat_id: int | None = None,
        _pat_tg_module: object | None = None,  # test injection
    ) -> None:
        super().__init__(channel_id, config)
        self._pat_tg = (
            _pat_tg_module if _pat_tg_module is not None else _load_pat_tg()
        )
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
        # Use First Officer formatter for alerts (Tier 3)
        if severity is not None and severity in (
            Severity.CAPITAL_CRITICAL, Severity.HIGH
        ):
            from patrick_agent.notify.formatter import fmt_alert
            text = fmt_alert(title=title, error=body, severity=severity)
        else:
            text = f"{title}\n\n{body}" if title else body
        # Telegram hard limit 4096; honor configured cap otherwise.
        text = text[: min(self.config.max_message_length, 4096)]
        try:
            ok = self._pat_tg.send_message(text, chat_id=self.chat_id)
            return DeliveryResult(
                success=bool(ok),
                channel_id=self.channel_id,
                timestamp=self._now(),
                message_preview=preview,
                error=None if ok else "pat_tg.send_message returned False",
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("TelegramChannel send failed: %s", exc)
            return DeliveryResult(
                success=False,
                channel_id=self.channel_id,
                timestamp=self._now(),
                message_preview=preview,
                error=str(exc),
            )
