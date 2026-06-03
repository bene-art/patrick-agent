#!/usr/bin/env python3
"""Nightly Patrick eval — catches drift before you notice.

Runs the eval and logs the score. If regression > REGRESSION_THRESHOLD
from baseline, sends a Telegram alert.

Designed for launchd / cron at a quiet hour (e.g. 3:00 AM).

Environment variables:
    AGENT_DATA_DIR        Where to write the eval history JSONL.
                          Default: ~/.patrick-agent
    EVAL_BASELINE         Baseline quality score to compare against.
                          Default: 0.85 (override per your last good run).
    REGRESSION_THRESHOLD  Alert threshold (delta from baseline).
                          Default: 0.01
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("patrick_eval_nightly")

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", str(Path.home() / ".patrick-agent")))
HISTORY_PATH = AGENT_DATA_DIR / "logs" / "patrick_eval_history.jsonl"
BASELINE = float(os.environ.get("EVAL_BASELINE", "0.85"))
REGRESSION_THRESHOLD = float(os.environ.get("REGRESSION_THRESHOLD", "0.01"))


def run_eval() -> dict | None:
    """Run the eval and parse the result."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "eval" / "eval_agent.py"),
        "--concurrency", "1",
        "--json",
    ]

    # Inherit only the env vars Patrick actually needs.
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    for key in [
        "HOME", "USER", "PYTHONPATH",
        "AGENT_DATA_DIR", "AGENT_MODEL", "OLLAMA_HOST",
        "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_PAPER",
        "ODDS_API_KEY",
        "PAT_TG_BOT_TOKEN", "PAT_TG_CHAT_ID",
    ]:
        val = os.environ.get(key)
        if val:
            env[key] = val

    logger.info("Starting eval...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=7200,  # 2h max
            cwd=str(REPO_ROOT), env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error("Eval timed out after 2h")
        return None

    if result.returncode != 0:
        logger.error("Eval failed: %s", result.stderr[-500:])
        return None

    # Find the most recent result file
    results_dir = REPO_ROOT / "eval" / "results"
    result_files = sorted(results_dir.glob("eval_*.json"), reverse=True)
    if not result_files:
        logger.error("No result files found")
        return None

    with open(result_files[0]) as f:
        return json.load(f)


def log_result(report: dict) -> None:
    """Append score to history JSONL."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "quality_score": report.get("report", {}).get("quality_score"),
        "exchanges": report.get("report", {}).get("total_exchanges"),
        "pass_rate": report.get("report", {}).get("pass_rate"),
        "baseline": BASELINE,
    }
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    logger.info("Logged: score=%.4f, baseline=%.4f",
                entry["quality_score"] or 0, BASELINE)


def check_regression(report: dict) -> bool:
    """Check if score regressed and alert if so."""
    score = report.get("report", {}).get("quality_score")
    if score is None:
        return False

    delta = score - BASELINE
    if delta < -REGRESSION_THRESHOLD:
        logger.warning("REGRESSION: %.4f (baseline %.4f, delta %.4f)",
                       score, BASELINE, delta)
        try:
            from patrick_agent.notify.telegram import _send_message
            from patrick_agent.notify.formatter import fmt_alert
            from patrick_agent.notify.base import Severity
            msg = fmt_alert(
                title="Patrick Eval — Regression Detected",
                error=f"Score dropped to {score:.4f} (baseline {BASELINE:.4f}, delta {delta:+.4f})",
                severity=Severity.MEDIUM,
                action="Check recent changes to IDENTITY.md, SOUL.md, or tool router",
            )
            _send_message(msg)
        except Exception as exc:
            logger.warning("Failed to send alert: %s", exc)
        return True

    logger.info("Score %.4f — no regression (baseline %.4f, delta %+.4f)",
                score, BASELINE, delta)
    return False


def main():
    result = run_eval()
    if result is None:
        logger.error("Eval produced no results")
        return 1

    log_result(result)
    check_regression(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
