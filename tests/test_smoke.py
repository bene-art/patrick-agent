"""Smoke tests — verify the package is wired correctly.

These don't hit Ollama or any external API. They check that imports
resolve, dataclasses construct, and the tool router routes without
exploding when its dependencies are missing (graceful degradation).
"""
from __future__ import annotations

import asyncio


def test_package_imports():
    import patrick_agent
    assert patrick_agent.__version__


def test_tool_router_imports():
    from patrick_agent.tools.tool_router import route_tools  # noqa: F401


def test_notify_imports():
    from patrick_agent.notify.base import Channel, Severity, ChannelConfig  # noqa: F401
    from patrick_agent.notify.formatter import fmt_report, fmt_alert, should_interrupt  # noqa: F401
    assert Severity.HIGH.value == "high"


def test_formatter_produces_expected_shape():
    from patrick_agent.notify.formatter import fmt_report, fmt_alert
    from patrick_agent.notify.base import Severity

    report = fmt_report(
        title="Morning Brief",
        sections=[("Markets", "S&P +0.4%"), ("Tasks", "All clear")],
        footer="OK",
    )
    assert "Morning Brief" in report
    assert "Markets" in report
    assert "S&P" in report

    alert = fmt_alert(
        title="Outage",
        error="Connection refused",
        severity=Severity.HIGH,
        job="com.example.job",
        action="Restart service",
    )
    assert "Outage" in alert
    assert "Connection refused" in alert
    assert "Restart service" in alert


def test_repo_paths_resolve_to_repo_root():
    """Regression: PATRICK_REPO pointed at the package dir, not the repo
    root, so identity/ and config/ reads always got access-denied."""
    from patrick_agent.tools.file_read import PATRICK_REPO, file_read

    identity = PATRICK_REPO / "identity" / "IDENTITY.md"
    assert identity.exists(), f"repo-root resolution broken: {identity}"
    result = asyncio.run(file_read("identity/IDENTITY.md"))
    assert not result.startswith("[access denied"), result
    assert not result.startswith("[file not found"), result


def test_vendored_channel_requires_token(monkeypatch):
    from patrick_agent.channels.telegram_channel import TelegramListenerChannel

    monkeypatch.delenv("PAT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    try:
        TelegramListenerChannel()
        raise AssertionError("expected ValueError without a bot token")
    except ValueError:
        pass
    ch = TelegramListenerChannel(bot_token="fake", chat_id=123)
    assert ch.chat_id == 123


def test_vendored_web_search_fails_loudly_without_key(monkeypatch):
    """Self-contained since kit v0.4.0 — must return an error envelope,
    not raise, when no Gemini key is configured."""
    from patrick_agent.tools.web_search import web_search

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = asyncio.run(web_search("test query"))
    assert result.startswith("[web search error:")


def test_route_tools_handles_empty_message():
    """The router must not crash on innocuous input even when no API keys are set."""
    from patrick_agent.tools.tool_router import route_tools
    result = asyncio.run(route_tools("hello"))
    assert isinstance(result, list)


def test_route_tools_returns_list_for_internal_question():
    """Internal questions about the agent should not trigger web search."""
    from patrick_agent.tools.tool_router import route_tools
    result = asyncio.run(route_tools("what is your identity"))
    # Should hit the file_read branch or no-op; in either case returns a list.
    assert isinstance(result, list)
