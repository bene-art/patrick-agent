"""Conversational channels for the Patrick reference agent.

Distinct from `patrick_agent.notify` (one-shot outbound notifications):
these implement local-agent-kit's `Channel` ABC for full message loops.
"""
from patrick_agent.channels.telegram_channel import TelegramListenerChannel

__all__ = ["TelegramListenerChannel"]
