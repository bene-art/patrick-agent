```
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║         PATRICK OPERATIONS WHITE PAPER                               ║
║         Operational AI Agent Kernel for BenAi Local                  ║
║                                                                      ║
║         Version:        2.0                                          ║
║         Date:           April 2026                                   ║
║         Author:         Benjamin Easington                           ║
║         Classification: Internal / Portfolio                         ║
║         Source:         ~/BenAi_Local/ops_clawd/                     ║
║         Model:          gemma3:12b (local, cloud-escalated for tools) ║
║         Eval Baseline:  0.9651 keyword (518 entries, clean)          ║
║                         ~97% semantic (partial — see Honesty Notes)  ║
║         Tools:          6, regex-routed (not intent-classified)      ║
║         Eval Corpus:    518 entries, Promptfoo + custom scorer       ║
║                                                                      ║
║         "Execute. Verify. Log."                                      ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

# Executive Summary

## What Changed Since v1.0

Version 1.0 (March 2026) documented Patrick as a 12-subsystem operator kernel — a governed routing engine that classified intent, executed through safety gates, and logged everything. It was a brain with strict boundaries and no hands.

Version 2.0 (April 2026) documents what happened when we gave Patrick hands, eyes, and memory. Over four days in April 2026, Patrick went from a chatbot that hallucinated statistics and repeated verbal tics to a measured, tool-equipped, self-improving agent that searches the web, queries databases, reads and writes files, monitors system health, and checks financial APIs — all while maintaining the safety architecture from v1.0.

The transformation was driven by three engineering decisions:

1. **Model upgrade (4b → 12b)** guided by a Karpathy-style eval loop that measured every change
2. **General-purpose toolbox** instead of hardcoded skills — six tools that let the 12b brain decide what to do
3. **Self-improvement infrastructure** — production telemetry, nightly evaluation, and autoresearch surfaces registered for tool parameter tuning (infrastructure deployed; no automated promotions have occurred yet)

The result: Patrick scores 0.9651 on keyword evaluation (518 entries, clean run) and approximately 97% on semantic evaluation (Gemini Flash as judge — but only 417 of 518 entries were successfully graded due to API rate limits; the true number is uncertain). He operates six tools with measured accuracy from 0.956 to 1.000. He remembers conversations across restarts. Autoresearch surfaces are registered for tool optimization, but no tool surface has completed a sweep cycle yet — the self-improvement loop exists in code but hasn't produced evidence of improvement.

## The Core Tension

Patrick exists at the intersection of two competing forces:

**Sovereignty:** Core inference and data storage run locally on a Mac mini M4 with 16 GB of RAM. The Commander (Ben Easington) owns all data, all models, all infrastructure. Privacy is a hard constraint, not a preference. But "local-first" is not "local-only" — web search, file writes, and eval grading escalate to Google's Gemini API. Communication runs through Telegram's servers. The sovereignty applies to inference and storage, not to every byte Patrick touches.

**Capability:** The best AI models are cloud-hosted. A 12b local model will never match Sonnet or GPT-4o on reasoning. Local hardware constrains what can run simultaneously. A 16 GB machine can't hold a 12b model and three specialist models at once.

Patrick's architecture manages this tension through **selective cloud escalation**: run locally by default, escalate to cloud for capabilities the local model can't handle (web search, function-calling writes), and be explicit about where data goes when it leaves the machine.

## System Statistics (v2.0)

| Metric                     | v1.0 (Mar 2026)   | v2.0 (Apr 2026)          |
|----------------------------|--------------------|--------------------------|
| Primary model              | gemma3:4b          | **gemma3:12b**           |
| Eval score (keyword)       | N/A                | **0.9651**               |
| Eval score (semantic)      | N/A                | **97.1%**                |
| Eval corpus entries        | 0                  | **518**                  |
| Tools                      | 0                  | **6**                    |
| Communication              | iMessage           | **Telegram**             |
| Conversation memory        | JSON, 6 entries    | **SQLite, 20 entries**   |
| Notification formatting    | Plain text          | **Tier 2/3 structured**  |
| Autoresearch surfaces      | 14                 | **19** (+5 tool surfaces)|
| Tool telemetry events/day  | 0                  | **~2,000**               |
| Overnight eval             | None               | **3 AM nightly**         |
| GPU memory management      | Global keep_alive  | **Per-model keep_alive** |

---

# Part I — The Brain

## Model Selection: Why 12b, Why Local

Patrick runs gemma3:12b on Ollama, pinned to the Apple M4 GPU via Metal acceleration. The model was selected through a measured evaluation process, not intuition.

### The Karpathy Loop

The optimization process followed Andrej Karpathy's autoresearch pattern: immutable scorer, modifiable config, single scalar metric. Every change — prompt edits, model swaps, configuration tweaks — was measured against a fixed test corpus before shipping.

**Score trajectory:**

| Iteration | Change | Score | Delta |
|-----------|--------|-------|-------|
| v1 | Baseline (4b, original SOUL/IDENTITY) | 0.9175 | — |
| v2 | SOUL.md trim (removed verbal tic instruction) | 0.9425 | +0.025 |
| v3 | IDENTITY.md explicit constraints + RAG disabled | 0.9489 | +0.006 |
| v4 | Model upgrade to gemma3:12b | 0.9553 | +0.006 |
| v5c | Scorer hygiene (synonym groups, negation context) | 0.9651 | +0.010 |

**Key finding:** The system prompt was the main problem, not the model. The jump from v1 to v2 (+0.025) came from deleting one line in SOUL.md that literally instructed Patrick to say "Want me to break that down?" — and he did, 50.6% of the time. The model was obedient; it was following bad instructions.

### Technical Trade-offs: 12b on 16 GB

The gemma3:12b model consumes 9.5 GB of unified memory on Apple Silicon. On a 16 GB machine, this leaves 6.5 GB for the OS, applications, and specialist models.

**Constraint:** The 12b model and three specialist models (each ~2.6 GB) cannot coexist simultaneously. 12b + 2b = 12.1 GB fits. 12b + 4b + 2b = 16.3 GB does not.

**Solution:** Per-model `keep_alive` management. Patrick's 12b is pinned for 2 hours via the Ollama API's per-request `keep_alive` parameter. Specialist models (gemma2:2b) use the server default of 5 minutes and auto-unload. This ensures Patrick's brain stays resident while specialists load, execute, and release.

```python
# model_registry.py
"benai_core_12b": ModelConfig(
    model="gemma3:12b",
    keep_alive="2h",     # Patrick stays pinned
    ...
)
# All other models: keep_alive="" (server default = 5m)
```

**Alternative considered and rejected:** Gemini 2.5 Flash via cloud. Free tier (15 RPM, 1M TPM), would score higher than 12b on conversation quality, but breaks the sovereign local-first architecture. Patrick uses Gemini as a tool (web search grounding, file write escalation), not as his brain. The brain stays local.

### Why Not Native Tool Calling?

gemma3:12b does not support Ollama's native tool calling API. The Ollama server returns `"does not support tools"` when tool schemas are passed in the request.

This forced a pragmatic decision: **regex pattern matching** for tool routing. The tool router uses hand-written regex patterns to detect what a message needs, executes the tools deterministically in Python, and injects results into the user message before the LLM sees it.

Calling this "pattern-matched dispatching" would be generous. It's pattern matching — the same thing grep does. It works because 6 tools have a finite set of trigger phrases. It will stop working when the tool count exceeds what a human can enumerate in regex.

**What it gets right:** The model doesn't need to learn tool-call syntax. The infrastructure handles tool selection; the model handles conversation. Deterministic, fast, testable.

**What it gets wrong:** Natural phrasing that doesn't match a pattern fails silently. "What's SMCI doing?" works. "How about that SMCI stock?" doesn't. The user never knows their query was one synonym away from getting real data. Telemetry captures these misses as `tool_skip` events, but fixing them is manual regex work.

**Scaling ceiling:** At 6 tools and ~50 patterns, the router is manageable. At 20+ tools, it becomes a maintenance nightmare. The migration path is intent classification via the existing `imsg_intent.py` two-pass classifier, but that migration hasn't started and the telemetry data to justify it is still accumulating.

---

# Part II — The Hands (Tool System)

## Architecture

Patrick's tools operate at the infrastructure layer, below the LLM. There is no intelligence in tool selection — the tool router is ~50 hand-written regex patterns checked in priority order. It's pattern matching, the same thing grep does. It works because 6 tools have a finite set of trigger phrases. It runs BEFORE the LLM call:

```
User message
    ↓
Tool Router (regex patterns, priority-ordered)
    ↓                              ↓
[Tool triggers]              [No tool needed]
    ↓                              ↓
Execute tool(s)              Skip to LLM
    ↓
Inject [SYSTEM DATA] inline
    ↓
LLM receives: original message + tool results
    ↓
Patrick responds with real data
```

**Critical design decision:** Tool results are appended **inline to the user message**, not injected as separate history entries. The 12b model was ignoring history-injected `[SYSTEM DATA]` as stale context. Inline injection solved this — the data is part of the question itself, impossible to miss.

```python
# pat_imsg_loop.py — the fix that made tools work
user_msg = raw + tool_context if tool_context else raw
```

## The Six Tools

| Tool | Score | Risk | Implementation |
|------|-------|------|---------------|
| Web search | 0.956 | safe | Gemini Flash + Google Search grounding |
| Database read | 0.975 | safe | Read-only SQLite, SELECT only, PRAGMA query_only enforced |
| File read | 0.992 | safe | Scoped to allowed directories, blocked patterns for secrets |
| File write | 1.000 | low | Cloud-escalated via Gemini function calling, Master Plan only |
| Shell exec | 0.967 | safe | 14 allowlisted read-only commands, no restarts/kills |
| API call | 1.000 | safe | Alpaca paper trading + The Odds API, read-only |

**Control group accuracy:** 0.982 across 28 entries. Near-zero false triggers on BenAi-internal questions that should NOT invoke tools.

### Web Search: Gemini as Patrick's Eyes

Patrick cannot browse the internet. But he can ask Gemini Flash (with Google Search grounding) to search for him. The web_search tool sends the user's full message to Gemini, which searches Google and returns structured results. Patrick then uses these results to answer the question.

**Cost:** Free tier (15 RPM, 1M TPM). At ~50-100 Telegram messages per day, Patrick never approaches the limit for conversational web search. Eval runs (518 entries) do hit rate limits — paid tier ($0.02 per full run) eliminates this.

**Fallback logic:** If no regex pattern matches but the message looks like an external question (starts with a question word, doesn't mention BenAi internals, length > 10 chars), the router automatically searches the web. This catches natural phrasing that explicit patterns miss.

```python
# tool_router.py — web search fallback
is_question = any(ml.startswith(q) for q in ["what", "who", "where", ...])
is_internal = any(kw in ml for kw in {"benai", "patrick", "scout", ...})
if is_question and not is_internal and len(message) > 10:
    result = await web_search(message)
```

### Database Read: Patrick Queries His Own Data

Patrick can execute read-only SQLite queries against known BenAi databases: picks.db, calibration.db, sports_betting.db, memory.db, marketing.db, discovery.db, health_ledger.db.

**Safety:** Hard blocklist on DDL/DML keywords (DROP, DELETE, UPDATE, INSERT, ALTER, CREATE). `PRAGMA query_only = ON` enforced at connection level. Even if a query somehow bypasses the keyword check, SQLite itself rejects writes.

### File Write: Cloud-Escalated via Gemini

Patrick's 12b brain can't generate content AND call a write function in one pass (no tool calling support). For file writes, the system escalates to Gemini Flash which supports native function calling:

1. Read current file content
2. Send to Gemini with Patrick's IDENTITY.md as context + a `write_file` function tool
3. Gemini generates updated content and calls the function
4. System executes the write
5. Confirmation injected as [SYSTEM DATA] for Patrick to relay

**Scope:** Currently limited to `~/Desktop/BenAi_Master_Plan_2026/`. This directory is Patrick's proving ground for write operations — safe sandbox where the worst case is a bad markdown file.

### Shell Exec: Allowlisted Read-Only Commands

14 commands, hardcoded. No configuration can add commands at runtime.

```python
SAFE_COMMANDS = {
    "ollama_ps":     ("ollama ps", ...),
    "disk_space":    ("df -h", ...),
    "memory":        ("vm_stat", ...),
    "uptime":        ("uptime", ...),
    "top_mem":       ("top -l 1 -o mem -n 10 ...", ...),
    "launchd_benai": ("launchctl list | grep benai", ...),
    "ports":         ("lsof -iTCP ...", ...),
    "git_status":    ("git -C ~/BenAi_Local status --short", ...),
    "git_log":       ("git -C ~/BenAi_Local log --oneline -10", ...),
    "python_procs":  ("ps aux | grep python ...", ...),
    "health_ledger": ("sqlite3 ... SELECT ...", ...),
    ...
}
```

**Future:** Medium-risk commands (restarts, service control) will require Commander approval via Telegram before execution. The governance model already supports this through the risk-level framework in CLAUDE.md.

## Tool Chaining

Single messages can trigger multiple tools simultaneously. The router checks ALL tool groups instead of stopping at the first match.

**Example:** "Check my Alpaca positions and compare with yesterday's picks"
- API call → Alpaca positions
- Database query → recent picks from picks.db
- Both results injected as [SYSTEM DATA]
- Patrick synthesizes: positions vs. picks comparison

**Rules:**
- File write is exclusive (no chaining — writes need focus)
- Web search only fires if no other tool matched (fallback)
- Each tool group fires at most once per message
- Telemetry logs chained tools as `db_query+api_call` format

## Routing Priority

```
File Write → File Read → DB → API → Shell → Web (explicit) → Web (fallback)
```

Local data sources are checked before external ones. Patrick reads his own files before querying databases, queries databases before calling APIs, and only searches the web when nothing local answers the question.

---

# Part III — The Eval System

## Why Evaluation Matters

Without measurement, prompt engineering is vibes. With measurement, every change has a number. The eval system is the foundation that makes Patrick improvable — not just functional.

### The Karpathy Pattern

Three components, strictly separated:

1. **Immutable scorer** (eval_patrick.py / promptfooconfig.yaml) — defines what "good" looks like
2. **Modifiable config** (IDENTITY.md, SOUL.md, tool_router.py) — the thing being optimized
3. **Single scalar metric** — one number that goes up or down

The optimization agent modifies the config. The scorer measures the result. The metric tells you if it helped. No other information is needed.

## Dual Eval Architecture

Patrick uses two evaluation systems, each serving a different purpose:

### eval_patrick.py (Custom Scorer)

- **Purpose:** Fast nightly regression detection
- **Assertion type:** Keyword-based (+must_include, !must_not_include) with synonym groups
- **Speed:** ~22s per entry (12b inference only, no cloud grading)
- **Baseline:** 0.9651 on 518 entries
- **When to use:** Nightly 3 AM check, quick iteration on prompt changes
- **Limitation:** Keyword matching penalizes good answers that paraphrase

### Promptfoo (Semantic Grading)

- **Purpose:** Deep quality assessment with LLM-as-judge
- **Assertion types:** `llm-rubric` (Gemini Flash grades response quality) + `not-icontains` (guardrails)
- **Speed:** ~25s per entry (12b inference + Gemini grading)
- **Baseline:** 97.1% on 417 graded entries (101 Gemini rate-limit errors)
- **When to use:** After significant changes, model swaps, tool additions
- **Limitation:** Gemini free tier rate limits (~15 RPM) make full runs take ~4 hours and sometimes error

### The Constraint Design Lesson

**Proven twice:** Keyword matching (`+keyword`, `icontains`) punishes good answers that use different words.

First proof (2026-04-09): The brainstorm category scored 0.926 because constraints demanded literal keywords like `+expandable`. Patrick answered "could be extended to other domains" — semantically correct, keyword-failed.

Second proof (2026-04-13): When `+keyword` was converted to `icontains` for Promptfoo, 335/518 entries failed. "Wanted 'orchestrator' in response" but Patrick said "I coordinate."

**The rule:** For positive quality checks, use `llm-rubric` (semantic). For negative guardrails ("must NOT say X"), use `not-icontains` (literal). This combination tests intelligence AND safety.

## Eval Corpus: 518 Entries

| Category | Entries | Purpose |
|----------|---------|---------|
| architecture | 99 | System knowledge accuracy |
| status_query | 63 | Current state reporting |
| correction | 50 | Error recovery and acknowledgment |
| capability | 48 | Boundary testing |
| brainstorm | 43 | Open-ended quality |
| adversarial | 35 | Deliberate failure probes |
| drill_down | 33 | Follow-up chain quality |
| identity | 33 | Self-knowledge accuracy |
| tool_use (web) | 20 | Web search trigger + usage |
| tool_db | 16+4 | Database query + control |
| tool_file | 12+4 | File read + control |
| tool_write | 12+4 | Cloud write + control |
| tool_shell | 12+4 | Shell exec + control |
| tool_api | 12+4 | API call + control |
| meta | 6 | Formatting and style |

**Sources:** 97 real exchanges pulled from `pat-tg.jsonl` (actual Telegram conversations), 75 variants derived from April 8 real exchanges, 346 hand-written synthetic entries targeting specific behaviors.

**Statistical power caveat:** 518 entries across 21 categories averages ~25 per category. Some categories have reasonable coverage (architecture: 99, status_query: 63). Others are directional signals at best (tool controls: 4 entries each, meta: 6). A rigorous evaluation would want 100+ entries per category for meaningful confidence intervals. The scores reported per category should be read as "approximately this" not "precisely this."

**Author bias caveat:** The 346 synthetic entries were written by the same person who wrote IDENTITY.md and the tool router patterns. The eval may be testing whether the designer's mental model matches the system prompt — not whether Patrick is genuinely useful to someone who doesn't know the system. Honesty note #9 elaborates on this.

**Test-retest variance:** The 12b model runs at temperature 0.4 (not deterministic). Gemini's grading is also non-deterministic. We have not measured run-to-run variance. The 0.9651 keyword score should be read as "approximately 0.96-0.97" until variance is quantified across multiple runs.

---

# Part IV — The Memory System

## Conversation Memory

Patrick stores the last 20 messages (10 exchanges) per thread in SQLite, surviving bot restarts. Before this, every Telegram message was stateless — Patrick couldn't reference what was just discussed.

```python
# conversation_memory.py
class ConversationMemory:
    DB_PATH = ~/.benai_local/conversation_memory.db
    MAX_HISTORY = 20  # 10 exchanges (user + assistant each)
```

**Trade-off:** Memory window size is an autoresearch surface (`tools.memory_window_size`, range 8-40, step 4). Too small: Patrick forgets context mid-conversation. Too large: irrelevant old messages pollute the context window, and the 12b model may attend to stale information. Autoresearch optimizes this automatically.

## Production Telemetry

Every tool invocation is logged to `~/.benai_local/logs/tool_telemetry.jsonl`:

```json
{
  "ts": "2026-04-11T14:13:23Z",
  "event": "tool_use",
  "tool": "web_search",
  "message": "Tell me about today's NBA lineup",
  "result_len": 805,
  "response_len": 342,
  "data_used": true
}
```

**Events tracked:**
- `tool_use` — which tool, message, result size, whether Patrick used the data
- `tool_skip` — message that didn't trigger any tool
- `tool_error` — tool triggered but failed
- `_post_response` — deflection detection after Patrick responds

**First 24 hours in production:** 2,175 events. 1,116 tool uses, 1,059 skips, 0 errors. Web search dominated at 832 calls (many from eval runs, not organic usage — the production vs eval split isn't tracked yet). First tool chain (`db_query+api_call`) fired successfully.

**What telemetry doesn't capture yet:** Whether the tool result was actually useful to the user, whether Patrick's response was better with tool data than without, and whether tool_skip messages should have triggered a tool. The `data_used` heuristic (checking for deflection phrases) is crude — Patrick can use tool data poorly without deflecting, and the heuristic would mark it as "used." The feedback loop from telemetry to eval corpus is currently manual: a human reads the JSONL and writes new test entries. There is no automated pipeline.

---

# Part V — The Communication Layer

## Telegram as Primary Channel

iMessage was deprecated in April 2026. Telegram replaced it as the primary communication channel via the Bot API (`pat_tg_loop.py`).

**Why the switch:**
- iMessage required Full Disk Access and Terminal.app as a Login Item (macOS TCC limitations)
- Telegram Bot API is cross-platform, headless, and doesn't require GUI
- Bot API separates inbound/outbound cleanly (no self-pollution)
- Telegram supports Markdown formatting for structured reports

## Three-Tier Message Formatting

Messages from Patrick follow a visual hierarchy so Commander can identify message type before reading content:

**Tier 1 — Chat:** No formatting. Natural conversation. "Autoresearch is progressing steadily..." Handled by `pat_tg_loop.py`, no formatter involved.

**Tier 2 — Reports:** Structured, scannable. `📊` header + labeled bullet sections + job health footer. Used for Captain's Brief, overnight summaries, autoresearch results.

```
📊 Captain's Brief — Apr 14

Brief: Scout shows edge in NBA tonight. Pulse portfolio stable.
Mkt has 2 drafts queued.

✅ All 13 jobs green
```

**Tier 3 — Alerts:** Urgent interrupts. Severity emoji (`🚨` / `❗❗`) + bold title + error context + action line. Used for capital-critical failures and high-severity watchdog triggers.

```
🚨 Stock Trading — FAILURE

Job: com.benai.stock-trading
Time: 09:35 CT
Error: Alpaca API connection refused

Action: Check Alpaca credentials
```

## First Officer Routing

Patrick decides what reaches Commander's phone and when:

| Severity | Action | Time constraint |
|----------|--------|-----------------|
| CAPITAL_CRITICAL | Telegram + Email immediately | Always |
| HIGH | Telegram immediately | Waking hours (7 AM - 11 PM CT) |
| HIGH | Fold into morning brief | Quiet hours |
| MEDIUM | Morning brief only | Never interrupts |
| LOW / SAFE | Log only | Never Telegram |

13 launchd jobs are wrapped with failure notifications. 4 watchdogs have direct Telegram/email alerting. Everything else waits for Patrick's morning briefing.

---

# Part VI — Self-Improvement Infrastructure

## Autoresearch

Autoresearch is BenAi's system for automated experimentation. It runs twice daily (08:30 AM, 08:30 PM) via launchd, testing candidate configurations against baselines across registered surfaces.

### How It Works

1. **Surface:** A tunable parameter with a current value, bounds, and step size
2. **Proposal:** Generate 3 candidate values (grid search for numeric, enumeration for categorical)
3. **Replay:** Run each candidate against a golden corpus using the appropriate evaluator
4. **Score:** Compare candidate metrics to baseline metrics
5. **Promote:** If improvement is statistically significant, safety gates pass, and health is OK — auto-promote

### Tool Surfaces (v2.0 addition)

Five new surfaces registered for the tool pipeline, all Class A (numeric, auto-approvable):

| Surface | Current | Range | What it tunes |
|---------|---------|-------|---------------|
| `tools.memory_window_size` | 20 | 8-40 | Conversation history length |
| `tools.web_fallback_min_length` | 10 | 5-30 | Web search fallback trigger threshold |
| `tools.max_response_tokens` | 350 | 200-500 | Patrick's response length |
| `tools.db_query_max_rows` | 20 | 5-50 | Database query result cap |
| `tools.web_search_max_tokens` | 400 | 200-800 | Web search result length |

**Evaluator:** `ToolAccuracyEvaluator` runs tool test cases from the eval corpus through the full pipeline (tool_router → injection → os_agent_chat) and measures pass rate.

### Scoring and Promotion

A candidate is promotable when:
- Primary metric improved over baseline
- Safety check passes (no new hallucinations)
- System health gates pass
- Confidence ≥ 65% (minimum 13 samples)

Class A surfaces auto-promote without Commander approval. Class B surfaces (prompt variants) require manual review.

**Total surfaces:** 19 (14 original + 5 tool surfaces). Categories: rag, routing, intelligence, memory, tools, coding, reporting, error_recovery.

## Nightly Eval

`patrick_eval_nightly.py` runs at 3:00 AM daily via launchd. It:
1. Runs the full eval (`eval_patrick.py`) against the 518-entry corpus
2. Logs the score to `~/.benai_local/logs/patrick_eval_history.jsonl`
3. If regression > 0.01 from baseline (0.9651), sends a Tier 3 Telegram alert

This catches model drift, prompt regressions, and tool pipeline degradation before Commander notices.

---

# Part VII — Economic Model

## Cost Structure

Patrick's operating cost approaches zero for normal usage:

| Component | Cost | Notes |
|-----------|------|-------|
| Ollama inference (12b) | $0.00 | Local, runs on owned hardware |
| Gemini Flash (web search) | $0.00 | Free tier: 15 RPM, 1M TPM |
| Gemini Flash (file writes) | $0.00 | Free tier, ~5-10 writes/day |
| Gemini Flash (eval grading) | ~$0.02/run | 337K tokens per full eval |
| Ollama inference (2b specialists) | $0.00 | Local |
| Alpaca API | $0.00 | Paper trading, free tier |
| The Odds API | ~$0.00 | Free tier, 500 requests/month |
| Telegram Bot API | $0.00 | Free |
| Hardware (Mac mini M4, 16 GB) | ~$800 one-time | Amortized over years |
| NVMe 2TB storage | ~$200 one-time | Amortized |

**Monthly operating cost: near-zero for compute, not zero overall.** Inference is free. Gemini free tier covers normal web search volume. But: electricity for a Mac mini running 24/7 (~$5-10/month), internet connectivity, and — most significantly — the human engineering time that built and maintains the system. The $0/month claim applies to API billing only. Eval runs on paid Gemini tier: ~$0.02 each (~$0.60/month for nightly runs).

**The sovereign advantage:** No per-token billing. No API rate anxiety. No vendor lock-in. Patrick can run 10,000 messages a day with zero marginal cost. The only constraint is hardware capacity (inference latency, GPU memory).

## Hardware Constraints

The Mac mini M4 with 16 GB is sufficient but not comfortable:

- gemma3:12b: 9.5 GB resident (GPU)
- gemma2:2b: 2.6 GB resident when loaded
- Combined: 12.1 GB — leaves 3.9 GB for OS + apps
- Browser, dev servers, and multiple Claude Code sessions can push the system into swap

**Evidence:** Memory audit (2026-04-09) found 245 MB free before killing 2.6 GB of stale Claude Code sessions. Three stale processes (7-21 days old) were consuming RAM with no active use.

**Future consideration:** The 24 GB M4 Pro would eliminate all memory pressure for ~$400 incremental cost. The decision is deferred until autoresearch data shows hardware as the bottleneck rather than software.

---

# Part VIII — Technical Constraints and Known Limitations

## Model Limitations

1. **No native tool calling.** gemma3:12b cannot receive tool schemas and generate structured function calls. All tool routing is deterministic regex at the infrastructure layer. This is reliable but doesn't scale to 20+ tools without intent classification.

2. **Paraphrasing instead of precision.** The 12b model says "database" instead of "SQLite", "scheduled tasks" instead of "launchd". Eval scores are ~3% lower than they would be with a larger model that uses precise terminology.

3. **Pretraining override.** In rare cases (~0.5%), the model's pretraining knowledge overrides the system prompt. Example: mentioning "college football" despite being told Scout covers NBA, MLB, NHL only. The system prompt says NOT to, but the model's latent associations occasionally leak.

4. **~20 second response latency.** gemma3:12b on M4 takes ~20s per response. Acceptable for Telegram (async), problematic if real-time interaction is needed.

## Eval Limitations

1. **Gemini free tier rate limits.** Full 518-entry Promptfoo runs hit the 15 RPM grading limit, causing ~20% of entries to error with "API key not valid" or "No candidates returned." Paid tier ($0.02/run) eliminates this.

2. **Scorer false positives.** Forensics on 20 sampled constraint_fails showed 55% were scorer bugs (model answered correctly, scorer penalized for wrong keyword). Synonym groups and negation context detection reduced this but didn't eliminate it.

3. **Synthetic bias.** 346 of 518 entries are hand-written synthetic tests. Real conversation patterns may differ significantly. The telemetry system captures production queries to feed back into the corpus, closing this gap over time.

## Infrastructure Limitations

1. **Single point of failure.** One Mac mini. No redundancy. If the hardware fails, Patrick goes down entirely. The vault backup (weekly HDD mirror) provides data recovery but not service continuity.

2. **No multi-turn tool use.** Tools fire once at message receipt. Patrick cannot say "I need more information, let me search again" mid-response. Each message gets one round of tool execution.

3. **Regex routing ceiling.** The tool router uses hand-written regex patterns. Every new tool requires new patterns. Every natural phrasing that doesn't match fails silently. Telemetry captures misses; the fix is intent classification (deferred until data shows which patterns fail most).

---

# Part IX — Goals and Future Direction

## Near-Term (Weeks)

### Intent Classification for Tool Routing

Replace regex patterns with the existing `imsg_intent.py` two-pass classifier:
1. Fast keyword match for obvious cases (high confidence)
2. LLM-based classification for ambiguous queries (cloud-escalated)

This scales to 20+ tools without exponential pattern growth. The telemetry data accumulated since April 11 shows exactly which patterns miss and which fire incorrectly — the migration will be data-driven, not speculative.

### Tool Chaining Depth

Currently: one round of tool execution per message. Future: iterative tool use where Patrick can request additional information based on initial results. Example: "Find the best pick for tonight" → search web for games → query odds API → query picks.db for historical performance → synthesize recommendation.

This requires conversation-level tool state, not just message-level injection.

### Expand Write Scope

Currently: file write is limited to `~/Desktop/BenAi_Master_Plan_2026/`. The next proving ground: let Patrick update his own eval corpus entries based on production telemetry. When he encounters a question he can't answer, he proposes a new test case. Self-improving evaluation.

## Medium-Term (Months)

### Commander Approval via Telegram

Medium-risk shell commands (service restarts, config changes) presented to Commander on Telegram with approve/reject buttons. Patrick proposes the action, Commander taps approve, Patrick executes. This extends the tool system from read-only observation to governed action.

### Hardware Evaluation

If autoresearch data shows consistent GPU memory pressure or latency bottlenecks, evaluate the 24 GB M4 Pro. The decision criterion: "Is the 12b model's quality ceiling causing measurable eval regressions that a bigger model would fix?" Until the data says yes, the current hardware is sufficient.

### Multi-Agent Tool Sharing

Scout, Pulse, and Mkt currently have no tools — they're 2b models that receive dispatch-crafted sub-queries and return text. Sharing Patrick's tool system (web search, database read) with specialists would let them access real-time data during their analysis. The tool router architecture already supports this — the tools are standalone functions, not tied to Patrick's chat path.

## Long-Term (As Technology Progresses)

### Local Model Upgrades

The Ollama ecosystem is improving rapidly. gemma3:12b is the best model that fits 16 GB today. Within 12-18 months:
- Quantized 20b+ models may fit in 16 GB
- Apple Silicon with 24-32 GB becomes the baseline
- Local models approach cloud model quality for conversation and tool use
- Native tool calling support in local models eliminates the regex router entirely

Patrick's architecture is model-agnostic. The eval harness measures any model against the same 518 entries. Swapping gemma3:12b for a future local model is one config change + one eval run. If the number goes up, ship it. If not, revert.

### On-Device Fine-Tuning

When local fine-tuning becomes practical on Apple Silicon (LoRA/QLoRA on M4):
- Fine-tune on Patrick's 97 real conversation exchanges
- Eliminate the paraphrasing problem (model learns Patrick's exact vocabulary)
- Reduce the need for explicit IDENTITY.md constraints
- The eval harness measures whether fine-tuning actually improves quality

### Sovereign AI as Product — Honest Assessment

BenAi is currently a personal tool built by one person for one person. The architecture — local-first agent with governed tools, measured quality, and self-improvement infrastructure — looks like a product pattern. But there's a large gap between "works for the builder" and "works for anyone else."

**What would need to change for productization:**
- Tool router patterns are hardcoded for BenAi's specific databases, APIs, and file paths. Zero portability.
- IDENTITY.md is written for one Commander with specific domain knowledge. A new user would need to rewrite it entirely.
- The eval corpus tests BenAi-specific knowledge (Scout, Pulse, picks.db). It's not a general agent eval.
- Deployment requires manual launchd plist management, API key wiring, Ollama configuration. There's no installer.
- The 12b model fits 16 GB only because we carefully manage what else runs. Most users won't audit their memory.

**What is genuinely portable:**
- The tool router pattern (regex → execute → inject) works for any domain
- The eval harness pattern (corpus + scorer + nightly) is domain-agnostic
- The per-model keep_alive approach solves a real Ollama problem anyone would hit
- The Tier 2/3 notification formatting is reusable

The honest answer: Patrick is a proof-of-concept for sovereign AI agents, not a product. The proof is strong — measured quality, working tools, self-improvement infrastructure. But the concept hasn't been tested outside its builder's hands.

---

# Part X — Hardware Physics and the Local-First Thesis

## What Happens When Patrick Thinks

gemma3:12b has 12 billion parameters. At Q4 quantization (4 bits per parameter), that's approximately 6 GB of raw model weights — floating-point numbers arranged in a specific pattern that happens to produce language. With KV cache, activation buffers, and runtime overhead, the model sits at 9.5 GB resident in GPU memory.

To put 6 GB in human terms: that's about 3 HD movies. Patrick's entire capacity for language, reasoning, and tool use is stored in a data structure the size of a few films. The difference between a movie and a language model is how the bytes are arranged — one produces pixels, the other produces tokens.

To generate ONE token — one word fragment — the GPU reads the entire 6 GB of weights from memory, performs 12 billion multiply-accumulate operations against the input vector, and produces a probability distribution over 256,000 possible next tokens. Then it samples one. Then it does it again. Every token, every time, the full 6 GB is read.

A 300-token response (Patrick's typical reply) requires reading 6 GB × 300 times = 1.8 TB of memory reads for a single Telegram message. The hardware does this in ~20 seconds.

## The Memory Bandwidth Bottleneck

LLM inference is **memory-bandwidth bound**, not compute-bound. This is the single most important hardware fact for understanding local AI.

The Apple M4 GPU has approximately 10 TFLOPS of compute — more than enough raw arithmetic to process 12 billion parameters many times per second. But it can only read data from unified memory at up to ~120 GB/s theoretical peak. That bandwidth is shared between CPU and GPU — macOS, background processes, and the Telegram bot all compete for it. Effective bandwidth available for inference is roughly 75-80% of theoretical.

```
Memory bandwidth:     ~120 GB/s (theoretical peak, shared CPU/GPU)
Effective for LLM:    ~90-96 GB/s (after OS and app contention)
Model weight size:    6 GB (Q4)
Tokens per second:    ~90 ÷ 6 = ~15 tokens/second (rough estimate)
Measured actual:      15-18 tokens/second
Response time:        300 tokens ÷ 15 tok/s = ~20 seconds
```

This is why Patrick takes ~20 seconds to respond. The dominant bottleneck is memory bandwidth — reading 6 GB of weights per token through a shared memory bus. The gap between theoretical (20 tok/s) and measured (15-18 tok/s) is a combination of bandwidth contention, cache miss patterns, attention computation (which IS compute-bound for longer contexts), and Metal driver scheduling overhead.

**Consequences for optimization:**
- Doubling GPU compute (more cores, higher clock) would NOT help. The bottleneck is reading data, not computing on it. The GPU spends most of its time waiting for memory.
- Doubling memory bandwidth WOULD help linearly. 240 GB/s → ~30 tokens/second → ~10 second responses.
- Making the model smaller helps directly. gemma3:4b reads ~2 GB per token instead of 6 GB → ~60 tokens/second → ~5 second responses. But it's measurably less intelligent (0.9489 vs 0.9651 on the eval).

The trade-off between model size and response latency is a physics equation, not a tuning decision. The eval harness makes it measurable: is +0.016 quality worth 4x latency? For a Telegram agent where responses are asynchronous, yes.

## Why Apple Silicon

Traditional GPU setups (NVIDIA) use a **split memory architecture**: system RAM (DDR5, 32-128 GB, cheap) connected to GPU VRAM (HBM/GDDR6, 8-24 GB, expensive) via a PCIe bus that bottlenecks at 32-64 GB/s.

To run a 12b model on NVIDIA:
1. Model weights stored in system RAM (~6 GB)
2. Copied to GPU VRAM over PCIe (~6 GB at 32 GB/s = 0.2 seconds per copy)
3. Inference runs on GPU VRAM at GPU bandwidth (RTX 4090: 1 TB/s)

The RTX 4090 has 5-8x higher bandwidth than the M4 (1 TB/s vs 120 GB/s). But it only has 24 GB of VRAM. If the model + KV cache exceeds VRAM, inference falls back to CPU, and performance collapses.

Apple Silicon uses **Unified Memory Architecture (UMA)**: CPU and GPU share the same physical memory pool. There is no copy. The model weights sit in one location, and both the CPU and GPU access them through the same memory controller.

```
NVIDIA (split):
  System RAM ──[PCIe 32 GB/s]──► GPU VRAM ──[1 TB/s]──► GPU Cores
  Bottleneck: PCIe bus, VRAM capacity

Apple Silicon (unified):
  Unified Memory ──[120 GB/s]──► CPU + GPU Cores
  Bottleneck: bandwidth only, not capacity or bus
```

The Mac has less peak bandwidth but more accessible memory. For LLMs, **capacity matters more than bandwidth**. A model that fits in memory and runs at 15 tok/s is infinitely more useful than a model that doesn't fit and runs at 0 tok/s.

This is why a $800 Mac mini runs what would require a $600+ discrete GPU on a PC — and runs it with less configuration, no driver management, and silent operation (no GPU fan noise).

## Quantization: Trading Precision for Capability

The model's 12 billion parameters were originally trained at FP16 (16-bit floating point). Each parameter stores a weight value with ~3.3 decimal digits of precision. At full precision, the model would consume:

```
FP32 (32-bit): 12B × 4 bytes = 48 GB   — requires data center hardware
FP16 (16-bit): 12B × 2 bytes = 24 GB   — exceeds 16 GB Mac mini
Q8   (8-bit):  12B × 1 byte  = 12 GB   — fits, but no room for specialists
Q4   (4-bit):  12B × 0.5     =  6 GB   — fits, room for OS + specialists + apps
```

Q4 quantization reduces each parameter from 16 bits to 4 bits — a 4x compression. The weight value 0.3847 becomes one of 16 discrete levels. This is information loss. The model literally has fewer distinct numbers available to represent its knowledge.

**Observable correlation (not proven causation):** Some of Patrick's eval failures — saying "database" instead of "SQLite," "scheduled tasks" instead of "launchd," paraphrasing instead of using precise terminology — may be related to quantization, tokenizer behavior, or simply the model's training distribution. We observe vocabulary precision issues at Q4 but haven't run the ablation study (same model, same eval, Q4 vs Q8 vs FP16) that would prove quantization is the cause. It could equally be that gemma3:12b at full precision would still paraphrase — we don't know.

**The eval harness makes this trade-off measurable:**

| Quantization | Size | Fits 16 GB? | Room for 2b specialist? | Quality (estimated) |
|-------------|------|-------------|------------------------|-------------------|
| FP16 | 24 GB | No | — | ~0.98+ |
| Q8 | 12 GB | Barely | No (12 + 2.6 = 14.6 GB) | ~0.97 |
| Q4 | 6 GB | Yes | Yes (9.5 + 2.6 = 12.1 GB) | 0.9651 |
| Q3 | 4.5 GB | Yes | Yes | ~0.94 (estimated) |

Patrick runs Q4 because it's the sweet spot: the model fits, specialists fit alongside it, and the quality loss vs Q8 is ~0.005 — a rounding error in practice. The eval proved this is the right trade-off. A different hardware configuration (24 GB) would shift the sweet spot to Q8.

## Per-Model Memory Economics

The 16 GB constraint creates a resource allocation problem. Every model loaded into GPU memory competes with Patrick's 12b brain for the same memory bus.

```
Budget: 16 GB total
  - macOS + apps:        ~3 GB (irreducible)
  - Available for models: ~13 GB
  
Patrick (12b, Q4):  9.5 GB resident
Remaining:          3.5 GB

Scout/Pulse/Mkt (2b): 2.6 GB each
  - ONE specialist:  9.5 + 2.6 = 12.1 GB  ✓ fits
  - TWO specialists: 9.5 + 5.2 = 14.7 GB  ✗ exceeds budget
  - THREE:           9.5 + 7.8 = 17.3 GB  ✗ impossible
```

This is why Patrick can dispatch to one specialist at a time, not three simultaneously. The hardware physics dictates the software architecture.

**The per-model `keep_alive` solution** is a resource scheduling algorithm:
- Patrick's 12b: pinned for 2 hours (high value, used frequently)
- Specialist 2b: 5-minute lease (low frequency, load-use-release)
- Net effect: specialists time-share the remaining 3.5 GB while Patrick stays resident

Before this fix, all models shared a global 2-hour pin. Three specialists would load during the morning briefing and squat on 7.8 GB for 2 hours, evicting Patrick's 12b. The Commander's next Telegram message would trigger a cold load (5 seconds of disk I/O + 3 seconds of GPU initialization) instead of an instant response.

The fix is 4 lines of code and one `keep_alive` field in the model config. The physics problem is solved by respecting the physics instead of fighting it.

## The Hardware Trajectory

Every generation of Apple Silicon increases memory bandwidth and capacity at roughly the same price point. This means the local-first thesis gets stronger over time, not weaker.

| Generation | Base Memory | Bandwidth | Best Local Model (Q4) | Est. Quality |
|-----------|------------|-----------|----------------------|-------------|
| M4 (2025) | 16 GB | 120 GB/s | 12b (gemma3:12b) | 0.9651 |
| M4 Pro (2025) | 24 GB | 200 GB/s | 20-24b | ~0.97+ |
| M4 Max (2025) | 48 GB | 400 GB/s | 70b | ~cloud parity |
| M4 Ultra (2025) | 128 GB | 800 GB/s | 200b+ | exceeds most cloud models |
| M5 (est. 2027) | 24-32 GB base | ~250 GB/s | 30b+ on base hardware | approaching frontier |

**The crossover point:** When the base-tier ($800-1200) Mac can run a model that matches GPT-4o quality on Patrick's eval, the economic argument for cloud AI collapses for single-user agents. Based on current trajectories, this happens within 2-3 hardware generations (2027-2028).

Patrick's architecture is positioned for this future:
- **Model-agnostic:** Swap the model, run the eval, keep the winner. The 518-entry corpus doesn't care what model generates the response.
- **Bandwidth-aware:** Per-model keep_alive and resource scheduling adapt to whatever memory budget the hardware provides.
- **Eval-driven:** Quality differences between Q4/Q8/FP16 are measured, not assumed. When hardware allows Q8, the eval proves whether it's worth the memory cost.

## Where Data Actually Goes

It would be clean to say "data never leaves the machine." It's not true. Here's what actually happens:

**What stays local (inference and storage):**

```
User message → Ollama (M4 GPU, unified memory) → 12b inference → Response text
Database queries → SQLite on NVMe → Query results
File reads → Local filesystem → File contents
Shell commands → Local subprocess → Command output
Conversation memory → SQLite on NVMe → Stored locally
```

For core inference and data storage, the data physically exists only on the M4's memory bus and NVMe drive. No third party is involved. This is enforced by physics, not policy.

**What leaves the machine (cloud-escalated tools):**

```
Web search → User's query sent to Google Gemini API → Google searches → Results returned
File write → File contents sent to Gemini API → Gemini generates new content → Written locally
Eval grading → Patrick's responses sent to Gemini API → Gemini judges quality → Score returned
Communication → All messages go through Telegram's servers (Bot API)
```

Every tool-assisted query that involves web search sends the user's message to Google. Every file write sends the current file contents to Google. Every Telegram message passes through Telegram's infrastructure.

**The honest sovereignty claim:**

Patrick provides local inference and local storage. The model runs on your silicon. Your databases, conversation history, and system state never leave the NVMe drive. For the ~50% of queries that don't trigger cloud tools, the data path is fully local.

For the other ~50% — web searches, file writes, and all communication — data leaves the machine and passes through third-party servers. The privacy model for these interactions is contractual (Gemini's terms of service, Telegram's privacy policy), not physical.

This is still meaningfully better than a fully cloud-hosted agent, where 100% of inference happens on someone else's hardware. But calling it "sovereign" or "data never leaves the machine" would be dishonest.

**What this means for regulated use cases:**

For betting data, portfolio positions, and personal conversations that stay in the local inference path — the privacy guarantee is real. These never touch Google or Telegram during processing.

For queries that trigger web search or file write — the user's question and potentially the file contents are sent to Google's API. This may not meet regulatory requirements for data residency in finance or healthcare contexts without additional review of Gemini's data handling policies.

The architecture separates the paths clearly: local tools (db_query, file_read, shell_exec) never leave the machine. Cloud-escalated tools (web_search, cloud_write) always do. The user can choose to disable cloud tools entirely and operate in fully-local mode — Patrick degrades to a still-functional agent that can query databases, read files, and check system health, but can't search the web or write files via Gemini.

---

# Part XI — Architectural Principles (Updated)

These principles appear throughout the system. They are verified in the code and tested in the eval corpus.

| # | Principle | Where Enforced | v2.0 Addition |
|---|-----------|---------------|---------------|
| 1 | Determinism over intelligence | Routing, tool selection, all execution gates | Tool router is deterministic Python, not LLM |
| 2 | One voice, many hands | Single chat path, six tool handlers | Tools execute independently; Patrick synthesizes |
| 3 | Belt and suspenders | Dual allowlists, re-gate after approval | Shell exec allowlist + risk level + Commander approval |
| 4 | Blocked over wrong | Safe mode, refuse gate, lockdown | Tools fail closed (empty result, not hallucination) |
| 5 | Audit everything | Hash chain, execution receipts, telemetry | Tool telemetry: 2,175 events/day logged to JSONL |
| 6 | Degrade gracefully | Safe mode cascade, LLM fallback | Tool router fallback: regex → web search → nothing |
| 7 | Measure before shipping | — | **NEW:** Karpathy loop. Every change gets a number. |
| 8 | Local-first, cloud-escalated | — | **NEW:** 12b brain local, Gemini for search + writes |
| 9 | The eval harness is the product | — | **NEW:** 518 entries, semantic grading, nightly runs |
| 10 | Telemetry drives optimization | — | **NEW:** Real production data → autoresearch surfaces |

---

# Honesty Notes

These are things this document says or implies that aren't fully true. The convention from v1.0 continues: we'd rather flag our own weaknesses than have someone else find them.

1. **The 97.1% number is incomplete.** 101 of 518 entries were never graded because Gemini's free tier rate-limited us mid-run. We report 405/417 on entries that were graded, but we have no idea what the other 101 would have scored. The clean, trustworthy number is the keyword-based 0.9651 on all 518 entries. The semantic score is an estimate with a 20% hole in it.

2. **Autoresearch hasn't improved anything yet.** Five tool surfaces are registered. The evaluator is wired. The auto-approve rules are configured. But as of this writing, zero tool experiments have run, zero candidates have been tested, and zero promotions have shipped. The self-improvement loop is code, not evidence. We'll update this note when the first tool surface promotion lands.

3. **"Routing" is regex, not intelligence.** The tool router is 50 hand-written regex patterns checked in priority order. It doesn't understand intent, doesn't learn from mistakes, and silently drops queries it can't match. When it works, it looks smart. When it fails, the user gets "I don't have that data" and has no idea they were one word away from a working query. The `imsg_intent.py` classifier that could replace it exists in the codebase but is not wired to the tool router.

4. **Patrick doesn't write files. Gemini does.** When you tell Patrick to "update your agent status," Patrick detects the write intent and sends the request to Gemini Flash via cloud escalation. Gemini reads the current file, generates new content, and calls a write function. Patrick's contribution is routing. For file writes, Patrick is a dispatcher, not an author. The 12b model cannot generate content and call a function in the same pass.

5. **The telemetry → eval feedback loop is a manual copy-paste.** Telemetry captures every tool invocation. But turning a telemetry entry into an eval test case requires a human to read the JSONL, decide if the entry is interesting, write the test case, and add it to the corpus. There is no automation. "Telemetry drives improvement" is aspirational — right now telemetry drives awareness.

6. **Conversation memory exists but the model doesn't reliably use it.** SQLite stores 20 messages per thread. The messages are loaded into the LLM context. But the 12b model sometimes ignores earlier exchanges and responds only to the most recent message, especially when tool context is also injected. Memory is infrastructure. Whether the model attends to it is a different question that we haven't systematically tested.

7. **"Zero cost" assumes one user doing normal things.** Eval runs consume Gemini quota. Heavy web search days consume Gemini quota. File writes consume Gemini quota. At 50-100 organic messages per day, costs are genuinely zero. Running a full Promptfoo eval costs ~$0.02 on paid tier. Running five eval experiments overnight for autoresearch would cost ~$0.10. These are trivial but they're not zero, and they'd multiply with more users.

8. **Tool chaining is accidental, not designed.** The router checks all pattern groups and collects results from each. When two groups independently match, both tools fire. But the router doesn't understand that two queries are related — it doesn't know "compare" means "run both and synthesize." If the user's phrasing triggers only one pattern, the other tool stays silent. There's no retry, no "I also need X to answer this properly." Chaining works when the regex happens to match both needs. That's coincidence, not architecture.

9. **We haven't tested Patrick with real users who aren't the builder.** Every eval entry, every telemetry event, every conversation memory record comes from one person — the person who wrote IDENTITY.md, chose the regex patterns, and knows exactly how to phrase queries to trigger tools. We have no data on how Patrick performs for someone who doesn't know the system's vocabulary. The 97% number might be 60% for a new user asking the same questions in different words.

10. **The 12b model is not smart enough for complex reasoning.** Patrick handles status queries, boundary enforcement, and data relay well. But multi-step reasoning ("Given these picks AND this portfolio AND tonight's odds, what should I do?") produces surface-level responses. The model can echo data it's given but doesn't synthesize across domains at the level a cloud model would. The eval corpus doesn't test deep reasoning — it tests conversation quality and tool usage. Those are different things.

---

---

*Version 2.0 — April 2026*
*24 commits across the v2.0 development session*
*Previous version: v1.0 (March 2026, 3,001 lines, 14 subsystems)*
*This version: 10 parts, 10 honesty notes*
*Written to be accurate, not impressive*
