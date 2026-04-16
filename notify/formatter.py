"""Telegram message formatter — First Officer Protocol.

Standardized message shapes for Patrick's Telegram output.
Three tiers, each with a distinct visual signature so Commander
can identify message type before reading content.

Tier 1 — Chat:     No formatting. Natural conversation.
                    Handled by pat_tg_loop.py, NOT this module.

Tier 2 — Report:   Structured, scannable. Morning brief, health
                    summaries, overnight digests. Emoji header +
                    bullet structure.

Tier 3 — Alert:    Urgent interrupt. Capital-critical failures,
                    high-severity watchdog triggers. Bold title +
                    error context + action line.

Usage:
    from delta_orchestrator.notify.formatter import fmt_report, fmt_alert

    # Tier 2 — structured report
    text = fmt_report(
        title="Captain's Brief — Apr 10",
        sections=[
            ("Scout", "3 picks today (NBA 2, NHL 1). CLV +0.8u MTD"),
            ("Pulse", "Portfolio stable. No thesis violations."),
            ("Mkt", "2 drafts queued, awaiting approval."),
        ],
        footer="All 13 jobs green",
    )

    # Tier 3 — urgent alert
    text = fmt_alert(
        title="Stock Trading — FAILURE",
        error="Alpaca API connection refused",
        job="com.benai.stock-trading",
        time="09:35 CT",
        action="Check Alpaca credentials",
    )
"""
from __future__ import annotations

from datetime import datetime, timezone

from delta_orchestrator.notify.base import Severity

# ── Severity → emoji mapping ──────────────────────────────────────────
_ALERT_ICON: dict[Severity, str] = {
    Severity.CAPITAL_CRITICAL: "\u2757\u2757",    # ❗❗
    Severity.HIGH:             "\U0001f6a8",       # 🚨
    Severity.MEDIUM:           "\u26a0\ufe0f",     # ⚠️
    Severity.LOW:              "\u2139\ufe0f",      # ℹ️
    Severity.SAFE:             "\u2705",            # ✅
}

_REPORT_ICON = "\U0001f4ca"  # 📊


# ── Tier 2: Reports ───────────────────────────────────────────────────

def fmt_report(
    title: str,
    sections: list[tuple[str, str]],
    footer: str = "",
) -> str:
    """Format a structured report (Tier 2).

    Args:
        title: Report header (e.g. "Captain's Brief — Apr 10")
        sections: List of (label, content) pairs
        footer: Optional one-liner at bottom (e.g. job health summary)
    """
    lines = [f"{_REPORT_ICON} *{title}*", ""]

    for label, content in sections:
        if content:
            lines.append(f"*{label}:* {content}")

    if footer:
        lines.append("")
        lines.append(footer)

    return "\n".join(lines)


def fmt_job_health(
    green: int,
    failed: list[tuple[str, str]],
    skipped: list[str] | None = None,
) -> str:
    """Format overnight job health for the morning brief.

    If all green: returns a single line.
    If failures: returns a structured failure summary.
    """
    if not failed:
        return f"\u2705 All {green} jobs green"

    lines = [f"\u26a0\ufe0f *Job Health* — {len(failed)} failed / {green + len(failed)} total", ""]
    for job, error in failed:
        err_preview = error[:80] if error else "unknown error"
        lines.append(f"\u274c *{job}:* {err_preview}")

    if skipped:
        lines.append("")
        lines.append(f"\u23ed\ufe0f Skipped: {', '.join(skipped)}")

    return "\n".join(lines)


# ── Tier 3: Alerts ────────────────────────────────────────────────────

def fmt_alert(
    title: str,
    error: str,
    severity: Severity = Severity.HIGH,
    job: str = "",
    time: str = "",
    action: str = "",
) -> str:
    """Format an urgent alert (Tier 3).

    Args:
        title: What broke (e.g. "Stock Trading — FAILURE")
        error: Error message/description
        severity: Controls the icon
        job: Launchd job label if applicable
        time: When it happened
        action: What Commander should do
    """
    icon = _ALERT_ICON.get(severity, "\U0001f6a8")
    lines = [f"{icon} *{title}*", ""]

    if job:
        lines.append(f"Job: `{job}`")
    if time:
        lines.append(f"Time: {time}")

    lines.append(f"Error: {error}")

    if action:
        lines.append("")
        lines.append(f"*Action:* {action}")

    return "\n".join(lines)


# ── First Officer routing logic ───────────────────────────────────────

def should_interrupt(severity: Severity) -> bool:
    """Should this severity interrupt Commander via Telegram immediately?

    First Officer protocol:
    - CAPITAL_CRITICAL: always interrupt
    - HIGH: interrupt during waking hours (7 AM - 11 PM CT)
    - MEDIUM and below: fold into morning brief, never interrupt
    """
    if severity is Severity.CAPITAL_CRITICAL:
        return True

    if severity is Severity.HIGH:
        # Check waking hours (CT = UTC-5 / UTC-6)
        now_utc = datetime.now(timezone.utc)
        ct_hour = (now_utc.hour - 5) % 24  # approximate CT
        return 7 <= ct_hour <= 23

    return False
