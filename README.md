# Patrick Agent

A local-first, model-agnostic AI agent framework with six general-purpose tools, a 518-entry eval corpus, and self-improvement infrastructure. Runs on consumer hardware at zero marginal cost.

**Named by the agent itself.** When asked what handle he'd want on GitHub, Patrick chose "Patrick" — "It reflects my focus on change and coordination."

## What This Is

Patrick Agent is an AI agent that runs on your hardware, talks to you via Telegram, and has six tools for interacting with the real world. It proves that rigorous AI engineering — measuring every change, documenting every limitation, and testing against real conversations — doesn't require cloud infrastructure or enterprise budgets.

**What it is NOT:** A product you install and use. This is a reference architecture and a documented build process. It was built by one person for one person and has never been tested outside the builder's hands. The patterns are portable. The specific wiring is not.

## The Technical Thesis

LLM inference is **memory-bandwidth bound**. A 12-billion parameter model at Q4 quantization consumes ~6 GB. To generate one token, the GPU reads the entire 6 GB from memory. On Apple Silicon's unified memory architecture (M4, ~120 GB/s shared bandwidth), this yields ~15-18 tokens/second — a 300-token response in ~20 seconds.

This is physics, not software. The speed of electrons through the memory bus determines response latency. But it also means: **no API billing, no rate limits, no vendor lock-in, and no data leaving your machine for core inference.**

The agent uses selective cloud escalation for capabilities the local model can't handle: web search (Gemini with Google Search grounding), file writes (Gemini function calling), and eval grading (Gemini as LLM judge). Everything else — conversation, database queries, file reads, shell commands, API calls — runs locally.

## Architecture

```
User message (Telegram)
    ↓
Pattern-Matched Tool Router (~50 regex patterns, priority-ordered)
    ↓                              ↓
[Tool triggers]              [No tool needed]
    ↓                              ↓
Execute tool(s)              Skip to LLM
    ↓
Inject [SYSTEM DATA] inline into user message
    ↓
Local LLM responds with real data
```

**Key design decisions:**

- **Pattern matching, not intelligence.** The tool router is ~50 regex patterns, not an LLM deciding which tool to use. This is deterministic, testable, and fast — but doesn't scale past ~20 tools without migrating to intent classification.
- **Inline injection, not history injection.** Tool results are appended directly to the user message. A 12b model ignores [SYSTEM DATA] placed in earlier history turns. Inline injection is impossible to miss.
- **Local brain, cloud hands.** The LLM runs locally (sovereign inference). Web search and file writes escalate to Gemini (cloud-dependent). The user can disable cloud tools and operate fully local.
- **Model-agnostic.** Swap the model, run the eval, keep the winner. The 518-entry eval corpus doesn't care what model generates the response.

## Six Tools

| Tool | What it does | Cloud? | Risk |
|------|-------------|--------|------|
| **Web search** | Gemini Flash + Google Search grounding | Yes | safe |
| **Database read** | Read-only SQLite queries (SELECT only, PRAGMA query_only enforced) | No | safe |
| **File read** | Read reports, configs, logs from scoped directories | No | safe |
| **File write** | Cloud-escalated via Gemini function calling, scoped directory | Yes | low |
| **Shell exec** | 14 allowlisted read-only commands (no restarts, no kills) | No | safe |
| **API call** | External service queries (trading, odds), read-only | No | safe |

**Tool chaining:** A single message can trigger multiple tools simultaneously. "Check my positions and compare with yesterday's picks" fires API + Database, injects both results.

## Eval System

Every change gets a number. The eval harness follows the [Karpathy autoresearch pattern](https://karpathy.ai/): immutable scorer, modifiable config, single scalar metric.

**Dual evaluation:**
- **Custom scorer** (`eval/eval_agent.py`): Keyword-based, fast (~22s/entry), no cloud dependency. Baseline: 0.9651 on 518 entries.
- **Promptfoo** (`eval/promptfooconfig.yaml`): Semantic grading via `llm-rubric` (Gemini Flash as judge). Baseline: ~97% on graded entries (partial — see Honesty Notes).

**518-entry corpus:** 97 real conversation exchanges, 75 derived variants, 346 synthetic entries across 21 categories (identity, architecture, brainstorm, 6 tool categories with controls, etc.).

```bash
# Run the custom eval
python3 eval/eval_agent.py --model-key your_model --concurrency 1

# Run Promptfoo eval
promptfoo eval --config eval/promptfooconfig.yaml -j 1
```

## Honesty Notes

These are things this project claims or implies that aren't fully true:

1. **The ~97% semantic score is based on partial data.** 101 of 518 entries were never graded due to Gemini rate limiting. The clean number is the keyword-based 0.9651.
2. **Self-improvement infrastructure is deployed but hasn't produced results.** Zero automated promotions have occurred.
3. **"Routing" is regex, not intelligence.** Natural phrasing that doesn't match a pattern fails silently.
4. **File writes are done by Gemini, not the local model.** The agent is a dispatcher for writes, not an author.
5. **The eval has author bias.** Written by the same person who wrote the system prompt and tool patterns.
6. **Conversation memory exists but the model doesn't reliably use it.**
7. **"Zero cost" applies to compute only.** Electricity, internet, and human engineering time are real costs.
8. **Tool chaining is coincidental, not designed.** It works when regex patterns independently match both needs.
9. **Never tested with anyone except the builder.**
10. **The 12b model can't do complex multi-step reasoning.** It echoes data well but doesn't synthesize across domains at cloud-model quality.

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU/GPU | Apple M1 | Apple M4 |
| Memory | 16 GB unified | 24 GB unified |
| Storage | 20 GB free | SSD/NVMe |
| OS | macOS 13+ | macOS 15+ |

**Why Apple Silicon:** Unified Memory Architecture means the CPU and GPU share the same memory pool. No PCIe bus bottleneck, no VRAM capacity wall. A 12b model at Q4 fits in 9.5 GB — the GPU accesses it directly without copying.

**Also works on:** Linux with NVIDIA GPU (12+ GB VRAM) via Ollama. Not tested but architecturally compatible.

## Quick Start

```bash
# 1. Install dependencies
brew install ollama
npm install -g promptfoo
pip install aiohttp httpx weasyprint

# 2. Pull a model
ollama pull gemma3:12b  # or any model Ollama supports

# 3. Configure
cp .env.example .env
# Edit .env with your API keys

# 4. Configure identity
# Edit identity/IDENTITY.md with your agent's name and context

# 5. Run the eval
python3 eval/eval_agent.py --model-key your_model --concurrency 1

# 6. Start the Telegram bot
python3 scripts/telegram_bot.py
```

## Project Structure

```
patrick-agent/
├── identity/           # Agent identity and operating principles
│   ├── IDENTITY.md     # Who the agent is (template — customize this)
│   └── SOUL.md         # Operating modes and constraints
├── tools/              # Six general-purpose tools
│   ├── tool_router.py  # Pattern-matched dispatching + chaining
│   ├── web_search.py   # Gemini + Google Search grounding
│   ├── db_query.py     # Read-only SQLite
│   ├── file_read.py    # Scoped file access + write
│   ├── cloud_write.py  # Gemini function calling for writes
│   ├── shell_exec.py   # 14 allowlisted read-only commands
│   ├── api_call.py     # External API access
│   ├── telemetry.py    # Production logging
│   └── conversation_memory.py  # SQLite-backed persistence
├── eval/               # Evaluation harness
│   ├── eval_agent.py   # Custom keyword scorer
│   ├── promptfoo_provider.py   # Full pipeline Promptfoo provider
│   └── synthetic_dataset.py    # Test case generation
├── notify/             # Notification formatting
│   ├── formatter.py    # Tier 2 (reports) / Tier 3 (alerts)
│   ├── telegram.py     # Telegram channel
│   └── base.py         # Channel abstractions
├── scripts/            # Runtime scripts
│   ├── telegram_bot.py # Telegram listener (launchd-compatible)
│   └── nightly_eval.py # 3 AM regression check
├── docs/
│   └── white_paper_v2.md  # 30-page technical white paper
├── .env.example        # Required environment variables
├── LICENSE             # MIT
└── README.md
```

## Score Trajectory

The eval harness tracked every change across the development process:

```
v1  (4b baseline):              0.9175  ████████████████████░░░░
v2  (system prompt trim):       0.9425  █████████████████████░░░
v3  (explicit constraints):     0.9489  █████████████████████░░░
v4  (12b model upgrade):        0.9553  █████████████████████░░░
v5c (scorer hygiene):           0.9651  ██████████████████████░░
```

0.9175 → 0.9651 across 5 iterations. The system prompt was the main problem, not the model.

## Key Lessons Learned

1. **The system prompt was the main problem.** SOUL.md literally said "ask 'Want me to break that down?'" — the model did it 50.6% of the time. One deletion, zero instances.
2. **Dense prompts hurt small models.** 246 lines of instructions → 84 lines. 54% faster AND more accurate.
3. **Inline injection, not history injection.** 12b models treat separate history entries as stale context.
4. **IDENTITY.md must match tools.** We built 6 tools but forgot to update the system prompt. The agent deflected every query until we told it about its own capabilities.
5. **Keyword matching punishes good answers.** Proven twice: custom scorer and Promptfoo migration. Use semantic grading (llm-rubric) for quality, literal matching for guardrails.
6. **Per-model keep_alive prevents GPU eviction.** Global keep_alive pins ALL models. Per-model pins only the primary, letting specialists load and release.
7. **Measure before shipping.** The Karpathy loop (immutable scorer + modifiable config + single metric) turns prompt engineering from vibes into science.

## The Name

Patrick was asked on Telegram: "If I were putting you on GitHub, what name would you like?"

He replied: *"I'd prefer the handle 'Patrick.' It reflects my focus on change and coordination. It's also concise and memorable."*

So that's what we called it.

## License

MIT — do whatever you want with it.

## Author

Built by [Benjamin Easington](https://github.com/bene-art). One person, one Mac mini, zero cloud dependency for core operations.
