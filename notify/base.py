"""Notification channel base types.

Mirrors ops_clawd/communication/channels.py enums and ABC so Phase 3 can
absorb the existing channels without behavioral change. During Phase 2 these
classes live in parallel with channels.py; channels.py is not touched.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Notification severity levels (CLAUDE.md risk taxonomy).

    Intentionally mirrors the six-level risk taxonomy from CLAUDE.md rather
    than inventing a new one. DOCTRINE_TOUCHING is defined but forbidden at
    send time per notify_service contract.
    """

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CAPITAL_CRITICAL = "capital-critical"
    DOCTRINE_TOUCHING = "doctrine-touching"


class ChannelFormat(str, Enum):
    MARKDOWN = "markdown"
    PLAIN = "plain"
    HTML = "html"


@dataclass(frozen=True)
class ChannelConfig:
    enabled: bool = True
    quiet_hours: tuple[int, int] | None = None
    max_message_length: int = 4000
    rate_limit_per_minute: int = 10


@dataclass
class DeliveryResult:
    success: bool
    channel_id: str
    timestamp: datetime
    message_preview: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Channel(ABC):
    """Abstract notification channel."""

    def __init__(self, channel_id: str, config: ChannelConfig | None = None):
        self.channel_id = channel_id
        self.config = config or ChannelConfig()

    @abstractmethod
    def send(
        self,
        title: str,
        body: str,
        fmt: ChannelFormat = ChannelFormat.PLAIN,
        severity: "Severity | None" = None,
    ) -> DeliveryResult:
        ...

    def _now(self) -> datetime:
        return datetime.now()

    def _preview(self, body: str, n: int = 80) -> str:
        b = body.strip().replace("\n", " ")
        return b[:n] + ("…" if len(b) > n else "")


class ForbiddenSeverityError(RuntimeError):
    """Raised when notify() is called with a severity not permitted to emit
    (currently DOCTRINE_TOUCHING per CLAUDE.md constitutional rules)."""
