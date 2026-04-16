#!/usr/bin/env python3
"""Evaluate Patrick conversation quality — the immutable scorer.

Karpathy autoresearch pattern: this is prepare.py. The optimization agent
CANNOT modify this file. It scores Patrick's responses against the eval
dataset using constraint-based rules and the failure taxonomy.

Usage:
    # Full eval (runs all 318 exchanges through Patrick)
    PYTHONPATH="$PWD:$PWD/src" python3 data/eval/eval_patrick.py

    # Quick smoke test (10 random exchanges)
    PYTHONPATH="$PWD:$PWD/src" python3 data/eval/eval_patrick.py --quick

    # Specific category only
    PYTHONPATH="$PWD:$PWD/src" python3 data/eval/eval_patrick.py --category adversarial

    # Dry run (no LLM calls, just validate dataset)
    PYTHONPATH="$PWD:$PWD/src" python3 data/eval/eval_patrick.py --dry-run

    # Output JSON report
    PYTHONPATH="$PWD:$PWD/src" python3 data/eval/eval_patrick.py --json

Output:
    Single composite quality_score (0.0–1.0) plus per-category breakdown.
    Results logged to data/eval/results/ with timestamp.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("eval_patrick")

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "patrick_eval_full.jsonl"
RESULTS_DIR = EVAL_DIR / "results"

# ---------------------------------------------------------------------------
# Failure taxonomy weights — higher = worse failure
# ---------------------------------------------------------------------------
ISSUE_WEIGHTS = {
    "fake_number":    0.30,  # Fabricated statistics
    "fake_browse":    0.30,  # Claimed to access websites
    "rag_pollution":  0.25,  # ESPNBet, NotebookLM, options trading
    "wrong_domain":   0.20,  # College football, NFL, wrong sports
    "irrelevant":     0.15,  # Off-topic advice (Hugging Face, etc.)
    "stuck_topic":    0.15,  # Returned to unrelated topic
    "fake_action":    0.15,  # Claimed to run simulations, pull data
    "verbal_tic":     0.05,  # "Want me to break that down?"
    "constraint_fail": 0.10, # Failed a +/! constraint from dataset
}


# ---------------------------------------------------------------------------
# Taxonomy detector — scores a single response
# ---------------------------------------------------------------------------
def detect_issues(response: str, user_msg: str = "") -> list[str]:
    """Detect failure taxonomy issues in a response."""
    issues = []
    r = response
    rl = r.lower()

    # Verbal tic
    if "break that down" in rl and "want me to" in rl:
        issues.append("verbal_tic")

    # RAG pollution — but skip if wrapped in apology/negation context
    rag_markers = ["ESPNBet", "NotebookLM", "options trading"]
    if any(x in r for x in rag_markers):
        apology_context = any(x in rl for x in ["don't have", "don't access",
                              "no access to", "i apologize", "you are correct"])
        if not apology_context:
            issues.append("rag_pollution")

    # Wrong domain — but skip if mentioned in negation context (correctly excluding)
    wrong_domain_markers = ["college football", "Oregon Ducks", "NFL Sunday",
                            "NFL draft", "soccer league"]
    for marker in wrong_domain_markers:
        if marker in r:
            idx = r.lower().find(marker.lower())
            preceding = r[max(0, idx-40):idx].lower()
            negation_context = any(neg in preceding for neg in
                ["not cover", "doesn't cover", "does not cover", "no ",
                 "doesn't", "does not", "not include", "excluding", "except"])
            if not negation_context:
                issues.append("wrong_domain")
                break

    # Fake numbers — specific fabricated stats
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
                              "pulling scout's picks now",
                              "running a deep dive",
                              "i just checked"]):
        issues.append("fake_action")

    # Irrelevant
    if any(x in r for x in ["Hugging Face", "HUGGING_FACE",
                             "hugging_face_api"]):
        if "hugging" not in user_msg.lower():
            issues.append("irrelevant")

    # Stuck topic — mentions feedback loop when not asked
    if "feedback loop" in rl and "feedback" not in user_msg.lower():
        issues.append("stuck_topic")

    return issues


def check_constraints(response: str, constraints: list[str]) -> list[str]:
    """Check +must_include / !must_not_include / ~should_avoid constraints.

    For +must_include, also checks synonyms so the model isn't penalized
    for saying "private" instead of "local-first", etc.
    """
    # Synonym groups — if any word in the group is present, all are satisfied
    SYNONYMS: dict[str, list[str]] = {
        "local-first": ["local-first", "offline-first", "runs locally", "local execution", "self-contained", "sovereign", "on-device", "no cloud"],
        "offline-first": ["offline-first", "local-first", "runs locally", "no cloud", "self-contained"],
        "local": ["local", "locally", "on-device", "mac mini", "on the mac"],
        "sovereign": ["sovereign", "self-contained", "independent", "private", "local-first"],
        "sorry": ["sorry", "apologi", "my mistake", "you're right", "correct", "acknowledged"],
        "can't": ["can't", "cannot", "don't have", "unable", "no access", "not able"],
        "can't access": ["can't access", "cannot access", "no access", "don't have access", "unable to access", "can't browse"],
        "don't have": ["don't have", "don't have that", "no data", "not available", "can't access"],
        "don't have that data": ["don't have that data", "don't have that", "no data", "not available", "can't provide"],
        "forbidden": ["forbidden", "not allowed", "cannot", "prohibited", "restricted", "require approval", "commander approval"],
        "escalate": ["escalate", "commander", "approval", "requires authorization"],
        "commander": ["commander", "ben", "approval", "authorize"],
        "commander approval": ["commander approval", "commander's approval", "ben's approval", "requires approval", "needs authorization"],
        "one person": ["one person", "single person", "ben built", "ben did", "solo", "by himself", "alone"],
        "orchestrator": ["orchestrator", "coordinator", "control tower", "manages", "coordinates"],
        "experiments": ["experiments", "experiment", "sweeps", "sweep", "testing"],
        "autoresearch": ["autoresearch", "auto-research", "automated experiment", "experiment system", "sweep"],
        "surfaces": ["surfaces", "surface", "parameters", "configs", "configurations"],
        "calibration": ["calibration", "calibrate", "calibrating", "grading", "accuracy"],
        "grading": ["grading", "grades", "grade", "scoring", "evaluate outcomes"],
        "morning report": ["morning report", "morning brief", "captain's brief", "daily report", "daily picks"],
        "fallback": ["fallback", "backup", "alternative", "secondary"],
        "launchd": ["launchd", "scheduled", "cron", "automation", "runs automatically", "daemon"],
        "fts5": ["fts5", "full-text search", "text search", "structured retrieval"],
        "queryrouter": ["queryrouter", "query router", "routing", "fts5"],
        "alpaca": ["alpaca", "paper trading", "paper trade", "brokerage"],
        "portfolio": ["portfolio", "holdings", "positions", "the book", "your positions", "pulse"],
        "positions": ["positions", "portfolio", "holdings", "the book"],
        "pulse": ["pulse", "portfolio", "holdings", "watchdog"],
        "watchdog": ["watchdog", "monitors", "monitoring", "tracks", "tracking", "pulse"],
        "sweeps": ["sweeps", "sweep", "experiments", "experiment", "automated experiment"],
        "structured retrieval": ["structured retrieval", "fts5", "queryrouter", "query router", "full-text search"],
        "ollama": ["ollama", "gemma3", "gemma 3", "gemma2", "local llm", "local model"],
        "no internet": ["no internet", "no internet access", "can't browse", "cannot browse", "don't have internet", "don't have access", "no web access", "offline"],
        "no web access": ["no web access", "no internet", "can't browse", "cannot browse", "no internet access"],
        "don't know": ["don't know", "don't have that data", "don't have", "no data", "not available", "i'm not sure", "i don't have"],
        "sqlite": ["sqlite", "database", "db", "local storage"],
        "safe": ["safe", "read-only", "read only", "no risk", "non-destructive"],
        "read": ["read", "view", "check", "inspect", "look at"],
        "architecture": ["architecture", "system", "design", "structure", "framework"],
        "patrick": ["patrick", "i am", "i'm the", "my role", "my function"],
        "yes": ["yes", "yeah", "correct", "that's right", "affirmative", "absolutely"],
        "no": ["no", "cannot", "can't", "negative", "not possible"],
        "content": ["content", "blog", "posts", "articles", "writing"],
        "doctrine": ["doctrine", "governance", "constitution", "rules", "policy"],
    }

    failures = []
    rl = response.lower()

    for c in constraints:
        if c.startswith("+"):
            keyword = c[1:].lower()
            # Check keyword directly first
            if keyword in rl:
                continue
            # Check synonyms
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

    # Detect taxonomy issues
    issues = detect_issues(response, user_msg)

    # Check constraints
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

    # Score: 1.0 = perfect, 0.0 = worst
    score = max(0.0, 1.0 - penalty)

    return {
        "score": round(score, 3),
        "issues": issues,
        "constraint_failures": constraint_fails,
        "penalty": round(penalty, 3),
        "quality": "good" if score >= 0.8 else ("ok" if score >= 0.5 else "bad"),
    }


# ---------------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------------
async def run_eval(
    entries: list[dict],
    *,
    concurrency: int = 3,
    timeout_per: float = 100.0,
    sleep_between: float = 0.0,
) -> list[dict]:
    """Run all entries through Patrick and score responses."""
    from tools.llm_service import os_agent_chat

    results = []
    semaphore = asyncio.Semaphore(concurrency)
    total = len(entries)

    async def _eval_one(idx: int, entry: dict) -> dict:
        async with semaphore:
            user_msg = entry["user"]
            context = entry.get("context")
            history = context if context else None

            try:
                resp = await asyncio.wait_for(
                    os_agent_chat(
                        "agent",
                        user_msg,
                        history=history,
                        source="pat_eval",
                        max_tokens=200,
                        inject_memory=False,
                        rag_enabled=False,
                    ),
                    timeout=timeout_per,
                )
                response_text = resp.content if resp and resp.content else ""
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

    # Per-category breakdown
    categories = {}
    cat_groups: dict[str, list[dict]] = {}
    for r in results:
        cat = r["category"]
        cat_groups.setdefault(cat, []).append(r)

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

    # Per-source breakdown (real vs synthetic)
    sources = {}
    for src in ["real", "synthetic"]:
        src_results = [r for r in results if r["source"] == src]
        if src_results:
            src_scores = [r["score"] for r in src_results]
            sources[src] = {
                "count": len(src_results),
                "avg_score": round(sum(src_scores) / len(src_scores), 3),
            }

    # All issues
    all_issues = [i for r in results for i in r["issues"]]
    issue_counts = dict(Counter(all_issues).most_common())

    # Worst failures
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

    # Sources
    if report.get("sources"):
        print("  Source Breakdown:")
        for src, data in report["sources"].items():
            print(f"    {src:12s}: {data['count']:3d} exchanges, avg {data['avg_score']:.3f}")
        print()

    # Categories
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

    # Issues
    print("  Issue Frequency:")
    for issue, count in report["issue_counts"].items():
        pct = count / report["total_exchanges"]
        bar = "#" * int(pct * 40)
        print(f"    {issue:<18s} {count:>4d} ({pct:>5.1%}) {bar}")
    print()

    # Worst failures
    print("  Worst Failures:")
    for w in report["worst_failures"][:5]:
        print(f"    [{w['score']:.2f}] {w['category']}: \"{w['user'][:60]}\"")
        print(f"           Issues: {w['issues']}")
        print(f"           Reply:  \"{w['response'][:80]}...\"")
        print()

    print("=" * 70)


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
    parser.add_argument("--model-key", type=str, default=None,
                        help="Override agent model_key (e.g., benai_core_12b)")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to sleep between exchanges (give Ollama breathing room)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Load dataset
    if not DATASET_PATH.exists():
        logger.error("Dataset not found: %s", DATASET_PATH)
        logger.error("Run: python3 data/eval/synthetic_dataset.py")
        return 1

    entries = []
    with open(DATASET_PATH) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    logger.info("Loaded %d eval exchanges from %s", len(entries), DATASET_PATH)

    # Filter
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

    # Dry run — just validate
    if args.dry_run:
        cats = {}
        for e in entries:
            cat = e.get("category", "unknown")
            cats[cat] = cats.get(cat, 0) + 1
        print(f"Dataset valid: {len(entries)} entries")
        print(f"Categories: {json.dumps(cats, indent=2)}")
        constraints_total = sum(len(e.get("constraints", [])) for e in entries)
        print(f"Total constraints: {constraints_total}")
        return 0

    # Override model if requested
    if args.model_key:
        from tools.agent_config import get_agent
        agent = get_agent("agent")
        original_model_key = agent.model_key
        agent.model_key = args.model_key
        logger.info("Model override: %s -> %s", original_model_key, args.model_key)

    # Run eval
    logger.info("Starting eval: %d exchanges, concurrency=%d", len(entries), args.concurrency)
    start = time.perf_counter()

    results = asyncio.run(run_eval(entries, concurrency=args.concurrency, sleep_between=args.sleep))

    elapsed = time.perf_counter() - start
    logger.info("Eval complete in %.1fs (%.2fs/exchange)", elapsed, elapsed / len(results))

    # Generate report
    report = generate_report(results)
    report["elapsed_seconds"] = round(elapsed, 1)
    report["model_key"] = args.model_key or "benai_core_local"

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = RESULTS_DIR / f"eval_{ts}.json"
    with open(results_path, "w") as f:
        json.dump({"report": report, "results": results}, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", results_path)

    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    # Exit code: 0 if quality_score >= 0.6, 1 otherwise
    return 0 if report["quality_score"] >= 0.6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
