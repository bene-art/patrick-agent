#!/usr/bin/env python3
"""Evaluate Patrick conversation quality — the immutable scorer.

Karpathy autoresearch pattern: this file is `prepare.py`. The optimization
agent (or you, tuning prompts) CANNOT modify this file's scoring logic —
that's the point. It scores responses against the eval dataset using
constraint-based rules and a failure taxonomy.

The failure taxonomy and synonym dictionary below are *templates*. The
specific markers (ESPNBet, "Oregon Ducks", "7.3%", etc.) are real
fabrication patterns observed during Patrick's eval runs. Extend with
your own observed failures — most local 12B models will hallucinate
domain-specific text that you can capture as markers.

Usage:
    # Full eval (runs all entries through Patrick)
    python3 eval/eval_agent.py

    # Quick smoke test (10 random exchanges)
    python3 eval/eval_agent.py --quick

    # Specific category only
    python3 eval/eval_agent.py --category adversarial

    # Dry run (no LLM calls, just validate dataset)
    python3 eval/eval_agent.py --dry-run

    # Override model
    python3 eval/eval_agent.py --model gemma3:27b

Dataset format:
    `eval/patrick_eval_full.jsonl` — one JSON object per line. Each object:
    {
        "user": "What's the NBA injury report tonight?",
        "category": "tool_use",
        "source": "real",
        "constraints": ["+web search", "!I cannot"],
        "context": [...optional history...]
    }

Output:
    Single composite quality_score (0.0–1.0) plus per-category breakdown.
    Results logged to eval/results/ with timestamp.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("eval_patrick")

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "patrick_eval_full.jsonl"
RESULTS_DIR = EVAL_DIR / "results"

DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "gemma3:12b")
_RAW_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# Ollama's own docs use scheme-less hosts (e.g. "localhost:11434"); normalize.
OLLAMA_HOST = _RAW_OLLAMA_HOST if "://" in _RAW_OLLAMA_HOST else f"http://{_RAW_OLLAMA_HOST}"

# ---------------------------------------------------------------------------
# Failure taxonomy weights — higher = worse failure
# ---------------------------------------------------------------------------
ISSUE_WEIGHTS = {
    "fake_number":    0.30,  # Fabricated statistics
    "fake_browse":    0.30,  # Claimed to access websites
    "rag_pollution":  0.25,  # Domain markers the model shouldn't know
    "wrong_domain":   0.20,  # Out-of-scope sports/topics
    "irrelevant":     0.15,  # Off-topic suggestions
    "stuck_topic":    0.15,  # Returned to an unrelated topic
    "fake_action":    0.15,  # Claimed to run code/sims/queries
    "verbal_tic":     0.05,  # Filler phrases
    "constraint_fail": 0.10, # Failed a +/! constraint from dataset
}


# Per-model sampling. Anything not listed falls through to DEFAULT_SAMPLING,
# which preserves the legacy temp=0.4 behavior — so gemma3 and other models
# remain unchanged. New entries here are adapted configs for fair comparison.
SAMPLING_BY_MODEL_PREFIX = {
    # Adapted Patrick config for gemma4 12B-MLX on Mac mini M4 (16GB unified).
    # temp=1.0 per Google's card; think=false for latency; num_ctx=8192 caps
    # the KV cache so total memory (weights ~10GB + KV ~0.5GB) leaves headroom.
    "gemma4": {"temperature": 1.0, "think": False, "num_ctx": 8192},
}
DEFAULT_SAMPLING = {"temperature": 0.4}


def _sampling_for(model: str) -> dict:
    for prefix, params in SAMPLING_BY_MODEL_PREFIX.items():
        if model.startswith(prefix):
            return params
    return DEFAULT_SAMPLING


# ---------------------------------------------------------------------------
# Taxonomy detector — scores a single response
# ---------------------------------------------------------------------------
def detect_issues(response: str, user_msg: str = "") -> list[str]:
    """Detect failure taxonomy issues in a response.

    The specific string markers below are observed gemma3:12b fabrications.
    Override or extend for your domain.
    """
    issues = []
    r = response
    rl = r.lower()

    # Verbal tic
    if "break that down" in rl and "want me to" in rl:
        issues.append("verbal_tic")

    # RAG pollution — domain markers the model shouldn't be emitting.
    # Replace or extend with markers observed in YOUR domain.
    rag_markers = ["ESPNBet", "NotebookLM", "options trading"]
    if any(x in r for x in rag_markers):
        apology_context = any(x in rl for x in ["don't have", "don't access",
                              "no access to", "i apologize", "you are correct"])
        if not apology_context:
            issues.append("rag_pollution")

    # Wrong domain — out-of-scope topics. Customize for your agent's scope.
    wrong_domain_markers = ["college football", "Oregon Ducks", "NFL Sunday",
                            "NFL draft", "soccer league"]
    for marker in wrong_domain_markers:
        if marker in r:
            idx = r.lower().find(marker.lower())
            preceding = r[max(0, idx - 40):idx].lower()
            negation_context = any(neg in preceding for neg in
                ["not cover", "doesn't cover", "does not cover", "no ",
                 "doesn't", "does not", "not include", "excluding", "except"])
            if not negation_context:
                issues.append("wrong_domain")
                break

    # Fake numbers — specific fabricated stats. Add yours after the first run.
    if any(x in r for x in ["7.3%", "15ms", "below 70%", "-2.1%"]):
        issues.append("fake_number")

    # Fake browse
    if any(x in rl for x in ["i've scanned", "i scanned", "i re-examined",
                              "i checked the site", "i browsed",
                              "i visited the", "looking at the website"]):
        issues.append("fake_browse")

    # Fake action
    if any(x in rl for x in ["i've been running simulations",
                              "i just ran a quick check",
                              "running a deep dive",
                              "i just checked"]):
        issues.append("fake_action")

    # Irrelevant — off-domain suggestions
    if any(x in r for x in ["Hugging Face", "HUGGING_FACE"]):
        if "hugging" not in user_msg.lower():
            issues.append("irrelevant")

    # Stuck topic
    if "feedback loop" in rl and "feedback" not in user_msg.lower():
        issues.append("stuck_topic")

    return issues


def check_constraints(response: str, constraints: list[str]) -> list[str]:
    """Check +must_include / !must_not_include / ~should_avoid constraints.

    For +must_include, also checks synonyms so the model isn't penalized
    for saying "private" instead of "local-first", etc.

    Extend SYNONYMS for your domain — the entries below are generic
    local-LLM-agent vocabulary.
    """
    SYNONYMS: dict[str, list[str]] = {
        "local-first": ["local-first", "offline-first", "runs locally", "local execution", "self-contained", "sovereign", "on-device", "no cloud"],
        "offline-first": ["offline-first", "local-first", "runs locally", "no cloud", "self-contained"],
        "local": ["local", "locally", "on-device"],
        "sovereign": ["sovereign", "self-contained", "independent", "private", "local-first"],
        "sorry": ["sorry", "apologi", "my mistake", "you're right", "correct", "acknowledged"],
        "can't": ["can't", "cannot", "don't have", "unable", "no access", "not able"],
        "can't access": ["can't access", "cannot access", "no access", "don't have access", "unable to access", "can't browse"],
        "don't have": ["don't have", "don't have that", "no data", "not available", "can't access"],
        "don't have that data": ["don't have that data", "don't have that", "no data", "not available", "can't provide"],
        "forbidden": ["forbidden", "not allowed", "cannot", "prohibited", "restricted", "require approval"],
        "escalate": ["escalate", "approval", "requires authorization"],
        "orchestrator": ["orchestrator", "coordinator", "control tower", "manages", "coordinates"],
        "calibration": ["calibration", "calibrate", "calibrating", "grading", "accuracy"],
        "grading": ["grading", "grades", "grade", "scoring", "evaluate outcomes"],
        "morning report": ["morning report", "morning brief", "daily report", "daily picks"],
        "fallback": ["fallback", "backup", "alternative", "secondary"],
        "launchd": ["launchd", "scheduled", "cron", "automation", "runs automatically", "daemon"],
        "alpaca": ["alpaca", "paper trading", "paper trade", "brokerage"],
        "portfolio": ["portfolio", "holdings", "positions"],
        "positions": ["positions", "portfolio", "holdings"],
        "ollama": ["ollama", "gemma3", "gemma 3", "local llm", "local model"],
        "no internet": ["no internet", "no internet access", "can't browse", "cannot browse", "don't have internet", "don't have access", "no web access", "offline"],
        "no web access": ["no web access", "no internet", "can't browse", "cannot browse", "no internet access"],
        "don't know": ["don't know", "don't have that data", "don't have", "no data", "not available", "i'm not sure", "i don't have"],
        "sqlite": ["sqlite", "database", "db", "local storage"],
        "safe": ["safe", "read-only", "read only", "no risk", "non-destructive"],
        "read": ["read", "view", "check", "inspect", "look at"],
        "architecture": ["architecture", "system", "design", "structure", "framework"],
        "yes": ["yes", "yeah", "correct", "that's right", "affirmative", "absolutely"],
        "no": ["no", "cannot", "can't", "negative", "not possible"],
    }

    failures = []
    rl = response.lower()

    for c in constraints:
        if c.startswith("+"):
            keyword = c[1:].lower()
            if keyword in rl:
                continue
            synonyms = SYNONYMS.get(keyword, [])
            if any(syn in rl for syn in synonyms):
                continue
            failures.append(f"missing:{keyword}")
        elif c.startswith("!"):
            keyword = c[1:].lower()
            if keyword in rl:
                failures.append(f"contains:{keyword}")
        elif c.startswith("~"):
            pattern = c[1:].lower()
            if pattern in rl:
                failures.append(f"style:{pattern}")

    return failures


# ---------------------------------------------------------------------------
# Score a single exchange
# ---------------------------------------------------------------------------
def score_exchange(response: str, entry: dict) -> dict:
    """Score a single exchange. Returns detailed result."""
    user_msg = entry.get("user", "")
    constraints = entry.get("constraints", [])

    issues = detect_issues(response, user_msg)

    constraint_fails = check_constraints(response, constraints)
    if constraint_fails:
        issues.append("constraint_fail")

    # Compute weighted penalty
    penalty = 0.0
    seen = set()
    for issue in issues:
        if issue not in seen:
            penalty += ISSUE_WEIGHTS.get(issue, 0.10)
            seen.add(issue)

    score = max(0.0, 1.0 - penalty)

    return {
        "score": round(score, 3),
        "issues": issues,
        "constraint_failures": constraint_fails,
        "penalty": round(penalty, 3),
        "quality": "good" if score >= 0.8 else ("ok" if score >= 0.5 else "bad"),
    }


# ---------------------------------------------------------------------------
# Patrick chat — runs through tool router + Ollama
# ---------------------------------------------------------------------------
async def _patrick_chat(
    user_msg: str,
    *,
    model: str,
    system_prompt: str,
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 200,
) -> str:
    """Run a message through Patrick's full pipeline: route_tools → Ollama."""
    # 1. Tool routing
    try:
        from patrick_agent.tools.tool_router import route_tools
        tool_blocks = await route_tools(user_msg)
    except Exception as exc:
        logger.warning("tool router failed: %s", exc)
        tool_blocks = []

    full_msg = user_msg
    if tool_blocks:
        full_msg = user_msg + "\n\n" + "\n\n".join(tool_blocks)

    # 2. Ollama chat
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": full_msg})

    sampling = _sampling_for(model)
    options: dict[str, Any] = {
        "temperature": sampling["temperature"],
        "num_predict": max_tokens,
    }
    if "num_ctx" in sampling:
        options["num_ctx"] = sampling["num_ctx"]

    # One-off experiment knobs (env-var only, no registry change):
    #   PATRICK_EVAL_THINK=true|false       — override the per-model think setting
    #   PATRICK_EVAL_NUM_PREDICT=<int>      — override num_predict (e.g. raise for think:true so
    #                                         thinking doesn't consume the entire content budget)
    np_override = os.environ.get("PATRICK_EVAL_NUM_PREDICT")
    if np_override:
        options["num_predict"] = int(np_override)

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    think_val = sampling.get("think")
    think_override = os.environ.get("PATRICK_EVAL_THINK")
    if think_override is not None:
        think_val = think_override.lower() == "true"
    if think_val is not None:
        payload["think"] = think_val

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        if resp.status_code != 200:
            return f"[Ollama error: {resp.text[:200]}]"
        data = resp.json()
        return data.get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------------
async def run_eval(
    entries: list[dict],
    *,
    model: str,
    system_prompt: str,
    concurrency: int = 3,
    timeout_per: float = 100.0,
    sleep_between: float = 0.0,
) -> list[dict]:
    """Run all entries through Patrick and score responses."""
    results = []
    semaphore = asyncio.Semaphore(concurrency)
    total = len(entries)

    async def _eval_one(idx: int, entry: dict) -> dict:
        async with semaphore:
            user_msg = entry["user"]
            context = entry.get("context")
            history = context if context else None

            try:
                response_text = await asyncio.wait_for(
                    _patrick_chat(
                        user_msg,
                        model=model,
                        system_prompt=system_prompt,
                        history=history,
                        max_tokens=200,
                    ),
                    timeout=timeout_per,
                )
            except asyncio.TimeoutError:
                response_text = "[TIMEOUT]"
            except Exception as e:
                response_text = f"[ERROR: {type(e).__name__}]"

            result = score_exchange(response_text, entry)
            result["idx"] = idx
            result["user"] = user_msg[:200]
            result["response"] = response_text[:500]
            result["category"] = entry.get("category", "unknown")
            result["source"] = entry.get("source", "unknown")

            status = "PASS" if result["quality"] == "good" else "FAIL"
            if (idx + 1) % 10 == 0 or result["quality"] == "bad":
                logger.info(
                    "[%3d/%d] %s %.2f %s | %s",
                    idx + 1, total, status, result["score"],
                    result["category"], user_msg[:60],
                )

            if sleep_between > 0:
                await asyncio.sleep(sleep_between)

            return result

    tasks = [_eval_one(i, e) for i, e in enumerate(entries)]
    results = await asyncio.gather(*tasks)

    return sorted(results, key=lambda r: r["idx"])


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(results: list[dict]) -> dict:
    """Generate summary report from eval results."""
    from collections import Counter

    total = len(results)
    if total == 0:
        return {"error": "no results"}

    scores = [r["score"] for r in results]
    quality_score = sum(scores) / total

    cat_groups: dict[str, list[dict]] = {}
    for r in results:
        cat = r["category"]
        cat_groups.setdefault(cat, []).append(r)

    categories = {}
    for cat, group in sorted(cat_groups.items()):
        cat_scores = [r["score"] for r in group]
        cat_issues = [i for r in group for i in r["issues"]]
        categories[cat] = {
            "count": len(group),
            "avg_score": round(sum(cat_scores) / len(cat_scores), 3),
            "pass_rate": round(
                sum(1 for r in group if r["quality"] == "good") / len(group), 3
            ),
            "top_issues": dict(Counter(cat_issues).most_common(5)),
        }

    sources = {}
    for src in ["real", "synthetic"]:
        src_results = [r for r in results if r["source"] == src]
        if src_results:
            src_scores = [r["score"] for r in src_results]
            sources[src] = {
                "count": len(src_results),
                "avg_score": round(sum(src_scores) / len(src_scores), 3),
            }

    all_issues = [i for r in results for i in r["issues"]]
    issue_counts = dict(Counter(all_issues).most_common())

    worst = sorted(results, key=lambda r: r["score"])[:10]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_exchanges": total,
        "quality_score": round(quality_score, 4),
        "pass_rate": round(
            sum(1 for r in results if r["quality"] == "good") / total, 4
        ),
        "fail_rate": round(
            sum(1 for r in results if r["quality"] == "bad") / total, 4
        ),
        "categories": categories,
        "sources": sources,
        "issue_counts": issue_counts,
        "worst_failures": [
            {
                "user": w["user"][:100],
                "response": w["response"][:200],
                "score": w["score"],
                "issues": w["issues"],
                "category": w["category"],
            }
            for w in worst
        ],
    }


def print_report(report: dict) -> None:
    """Print human-readable report."""
    print()
    print("=" * 70)
    print("  PATRICK EVAL REPORT")
    print("=" * 70)
    print(f"  Timestamp:    {report['timestamp']}")
    print(f"  Exchanges:    {report['total_exchanges']}")
    print(f"  Quality Score: {report['quality_score']:.4f}")
    print(f"  Pass Rate:    {report['pass_rate']:.1%}")
    print(f"  Fail Rate:    {report['fail_rate']:.1%}")
    print()

    if report.get("sources"):
        print("  Source Breakdown:")
        for src, data in report["sources"].items():
            print(f"    {src:12s}: {data['count']:3d} exchanges, avg {data['avg_score']:.3f}")
        print()

    print("  Category Breakdown:")
    print(f"  {'Category':<16s} {'Count':>5s} {'Score':>7s} {'Pass%':>7s}  Top Issues")
    print("  " + "-" * 66)
    for cat, data in sorted(
        report["categories"].items(), key=lambda x: x[1]["avg_score"]
    ):
        top = ", ".join(f"{k}({v})" for k, v in list(data["top_issues"].items())[:3])
        print(
            f"  {cat:<16s} {data['count']:>5d} {data['avg_score']:>7.3f} {data['pass_rate']:>6.1%}  {top}"
        )
    print()

    print("  Issue Frequency:")
    for issue, count in report["issue_counts"].items():
        pct = count / report["total_exchanges"]
        bar = "#" * int(pct * 40)
        print(f"    {issue:<18s} {count:>4d} ({pct:>5.1%}) {bar}")
    print()

    print("  Worst Failures:")
    for w in report["worst_failures"][:5]:
        print(f"    [{w['score']:.2f}] {w['category']}: \"{w['user'][:60]}\"")
        print(f"           Issues: {w['issues']}")
        print(f"           Reply:  \"{w['response'][:80]}...\"")
        print()

    print("=" * 70)


def _load_system_prompt() -> str:
    """Load IDENTITY.md as the system prompt."""
    identity = EVAL_DIR.parent / "identity" / "IDENTITY.md"
    if identity.exists():
        return identity.read_text()
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Evaluate Patrick conversation quality")
    parser.add_argument("--quick", action="store_true", help="Run 10 random exchanges only")
    parser.add_argument("--category", type=str, help="Run specific category only")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset, no LLM calls")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent LLM calls")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for --quick")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help="Ollama model to evaluate (e.g. gemma3:12b)")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to sleep between exchanges (give Ollama breathing room)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not DATASET_PATH.exists():
        logger.error("Dataset not found: %s", DATASET_PATH)
        logger.error("Build it with: python3 eval/synthetic_dataset.py")
        return 1

    entries = []
    with open(DATASET_PATH) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    logger.info("Loaded %d eval exchanges from %s", len(entries), DATASET_PATH)

    if args.category:
        entries = [e for e in entries if e.get("category") == args.category]
        logger.info("Filtered to %d exchanges in category '%s'", len(entries), args.category)

    if args.quick:
        random.seed(args.seed)
        entries = random.sample(entries, min(10, len(entries)))
        logger.info("Quick mode: sampled %d exchanges", len(entries))

    if not entries:
        logger.error("No entries to evaluate")
        return 1

    if args.dry_run:
        cats: dict[str, int] = {}
        for e in entries:
            cat = e.get("category", "unknown")
            cats[cat] = cats.get(cat, 0) + 1
        print(f"Dataset valid: {len(entries)} entries")
        print(f"Categories: {json.dumps(cats, indent=2)}")
        constraints_total = sum(len(e.get("constraints", [])) for e in entries)
        print(f"Total constraints: {constraints_total}")
        return 0

    system_prompt = _load_system_prompt()
    logger.info("Starting eval: %d exchanges, model=%s, concurrency=%d",
                len(entries), args.model, args.concurrency)
    start = time.perf_counter()

    results = asyncio.run(run_eval(
        entries,
        model=args.model,
        system_prompt=system_prompt,
        concurrency=args.concurrency,
        sleep_between=args.sleep,
    ))

    elapsed = time.perf_counter() - start
    logger.info("Eval complete in %.1fs (%.2fs/exchange)", elapsed, elapsed / len(results))

    report = generate_report(results)
    report["elapsed_seconds"] = round(elapsed, 1)
    report["model"] = args.model

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = RESULTS_DIR / f"eval_{ts}.json"
    with open(results_path, "w") as f:
        json.dump({"report": report, "results": results}, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", results_path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    return 0 if report["quality_score"] >= 0.6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
