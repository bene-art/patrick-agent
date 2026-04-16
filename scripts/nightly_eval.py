#!/usr/bin/env python3
"""Nightly Patrick eval — catches drift before Commander notices.

Runs eval_patrick.py on the tool_use categories only (fast, ~10 min)
and logs the score. If regression > 0.01 from baseline, sends a
Telegram alert.

Designed for launchd: com.benai.patrick-eval at 3:00 AM daily.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("patrick_eval_nightly")

BENAI_ROOT = Path.home() / "patrick-agent"
HISTORY_PATH = Path.home() / ".benai_local" / "logs" / "patrick_eval_history.jsonl"
BASELINE = 0.9651  # v5c + scorer hygiene (2026-04-09)
REGRESSION_THRESHOLD = 0.01


def run_eval() -> dict | None:
    """Run the eval and parse the result."""
    cmd = [
        sys.executable,
        str(BENAI_ROOT / "data" / "eval" / "eval_patrick.py"),
        "--model-key", "benai_core_12b",
        "--concurrency", "1",
    ]
    env = {
        "PYTHONPATH": f"{BENAI_ROOT}:{BENAI_ROOT / 'src'}",
        "BENAI_CIRCUIT_ENABLED": "false",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    }

    # Inherit needed env vars
    import os
    for key in ["HOME", "USER", "GEMINI_API_KEY", "OLLAMA_HOST",
                 "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_PAPER",
                 "ODDS_API_KEY"]:
        val = os.environ.get(key)
        if val:
            env[key] = val

    logger.info("Starting eval...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=7200,  # 2h max
            cwd=str(BENAI_ROOT), env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error("Eval timed out after 2h")
        return None

    if result.returncode != 0:
        logger.error("Eval failed: %s", result.stderr[-500:])
        return None

    # Find the most recent result file
    results_dir = BENAI_ROOT / "data" / "eval" / "results"
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
            sys.path.insert(0, str(BENAI_ROOT / "scripts"))
            from pat_tg import send_message
            from tools.notify.formatter import fmt_alert
            from tools.notify.base import Severity
            msg = fmt_alert(
                title="Patrick Eval — Regression Detected",
                error=f"Score dropped to {score:.4f} (baseline {BASELINE:.4f}, delta {delta:+.4f})",
                severity=Severity.MEDIUM,
                action="Check recent changes to IDENTITY.md, SOUL.md, or tool router",
            )
            send_message(msg)
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
