# Patrick Agent

[![CI](https://github.com/bene-art/patrick-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/bene-art/patrick-agent/actions/workflows/ci.yml)

A local-first, model-agnostic AI agent reference implementation. Built on top of [local-agent-kit](https://github.com/bene-art/local-agent-kit). Six general-purpose tools, a pattern-matched tool router, and an eval harness designed around the [Karpathy autoresearch pattern](https://karpathy.ai/) (immutable scorer, modifiable config, single scalar metric). Runs on consumer hardware at zero marginal cost for inference.

**Named by the agent itself.** When asked what handle he'd want on GitHub, Patrick chose "Patrick" — "It reflects my focus on change and coordination."

## What This Is

Patrick is an AI agent that runs on your hardware, talks to you via Telegram or the CLI, and has six tools for interacting with the real world. The repo is a documented build process and reference architecture, not a turn-key product — patterns are portable, specific wiring is not.

The lightweight framework Patrick is built on — hardware detection, Ollama wiring, pluggable channels (CLI / Telegram), pluggable search — lives in [local-agent-kit](https://github.com/bene-art/local-agent-kit). Patrick adds the **tool router**, the **eval framework**, the **notification protocol**, and the **identity scaffolding** on top.

## The Technical Thesis

LLM inference is **memory-bandwidth bound**. A 12B parameter model at Q4 quantization is ~6 GB on disk. To generate one token, the GPU reads the entire 6 GB from memory. On Apple Silicon's unified memory architecture (M4, ~120 GB/s shared bandwidth), this yields ~15-18 tokens/second — a 300-token response in ~20 seconds.

This is physics, not software. The speed of electrons through the memory bus determines response latency. But it also means: **no API billing, no rate limits, no vendor lock-in, and no data leaving your machine for core inference.**

Patrick uses selective cloud escalation for capabilities the local model can't handle: web search (Gemini with Google Search grounding), file writes (Gemini function calling), and eval grading (Gemini as LLM judge). Everything else — conversation, database queries, file reads, shell commands, API calls — runs locally.

## Architecture

```
User message (Telegram or CLI)
    ↓
Pattern-Matched Tool Router (~50 regex patterns, priority-ordered)
    ↓                              ↓
[Tool triggers]              [No tool needed]
    ↓                              ↓
Execute tool(s)              Skip to LLM
    ↓
Inject [SYSTEM DATA] inline into user message
    ↓
Local LLM (Ollama) responds with real data
```

**Key design decisions:**

- **Pattern matching, not intelligence.** The tool router is ~50 regex patterns, not an LLM deciding which tool to use. Deterministic, testable, fast. Doesn't scale past ~20 tools without migrating to intent classification.
- **Inline injection, not history injection.** Tool results are appended directly to the user message. A 12B model treats `[SYSTEM DATA]` placed in earlier history turns as stale context — inline injection is impossible to miss.
- **Local brain, cloud hands.** The LLM runs locally (sovereign inference). Web search and file writes escalate to Gemini (cloud-dependent). You can disable cloud tools and operate fully local.
- **Model-agnostic.** Swap the model, run the eval, keep the winner. The eval harness doesn't care what model generates the response.

## Six Tools

| Tool | What it does | Cloud? | Risk |
|------|-------------|--------|------|
| **Web search** | Gemini Flash + Google Search grounding | Yes | safe |
| **Database read** | Read-only SQLite queries (SELECT only, `PRAGMA query_only` enforced) | No | safe |
| **File read** | Read reports, configs, logs from scoped directories | No | safe |
| **File write** | Cloud-escalated via Gemini function calling, scoped directory | Yes | low |
| **Shell exec** | Allowlisted read-only commands (no restarts, no kills) | No | safe |
| **API call** | External service queries (Alpaca, The Odds API), read-only | No | safe |

Plus three infra modules: `tool_router` (the dispatcher), `telemetry` (JSONL audit log that feeds back into the eval corpus), and `conversation_memory` (SQLite-backed per-thread history).

**Tool chaining:** A single message can trigger multiple tools simultaneously. "Check my Alpaca positions and compare with yesterday's picks" fires `api_call` + `db_query`, injects both as separate `[SYSTEM DATA]` blocks.

## Eval System

Every change gets a number. The eval harness is `eval/eval_agent.py` — Karpathy autoresearch pattern: **immutable scorer, modifiable config, single scalar metric.** The optimization loop (you, tuning prompts) cannot modify the scorer; it can only tune what's around it.

- **Failure taxonomy:** weighted penalties for `fake_number`, `fake_browse`, `fake_action`, `rag_pollution`, `wrong_domain`, `verbal_tic`, `stuck_topic`, `constraint_fail`. Specific string markers are observed gemma3:12b fabrications — extend with your own.
- **Synonym-aware constraint checking:** `+local-first` matches "sovereign", "on-device", "no cloud". Penalizes meaning, not literal strings.
- **Promptfoo provider:** `eval/promptfoo_provider.py` runs the same pipeline (router → injection → Ollama) so Promptfoo's `llm-rubric` semantic grading hits what users actually experience.

```bash
# Custom scorer (no cloud, fast)
python3 eval/eval_agent.py --quick           # 10-entry smoke test
python3 eval/eval_agent.py                   # full corpus
python3 eval/eval_agent.py --model gemma3:27b
```

You bring the eval corpus (`eval/patrick_eval_full.jsonl`). The `synthetic_dataset.py` generator produces a starting set; the high-signal subset that survives pruning is what you'll actually iterate against.

## Honesty Notes

These are things this project claims or implies that aren't fully true:

1. **The reported scores are time-stamped, not eternal.** Eval corpus + scorer + model interact; treat any single number as "approximately this on that date" rather than the truth.
2. **Self-improvement infrastructure is deployed but hasn't produced automated promotions.** Nightly eval is currently disabled.
3. **"Routing" is regex, not intelligence.** Natural phrasing that doesn't match a pattern fails silently.
4. **File writes are done by Gemini, not the local model.** The agent dispatches writes; it doesn't author them.
5. **The eval has author bias.** Written by the same person who wrote the system prompt and tool patterns.
6. **Conversation memory exists; the model doesn't always use it.** 12B context window is finite.
7. **"Zero cost" applies to compute only.** Electricity, internet, and engineering time are real costs.
8. **Tool chaining is coincidental, not designed.** It works when regex patterns independently match both needs.
9. **Never tested with anyone except the builder.** Patterns are portable; specific wiring is not.
10. **The 12B model can't do complex multi-step reasoning.** It echoes data well; cross-domain synthesis at cloud quality requires a larger model.

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU/GPU | Apple M1 | Apple M4 |
| Memory | 16 GB unified | 24 GB unified |
| Storage | 20 GB free | SSD/NVMe |
| OS | macOS 13+ | macOS 15+ |

**Why Apple Silicon:** Unified Memory Architecture — CPU and GPU share the same memory pool. No PCIe bottleneck, no VRAM capacity wall. A 12B Q4 model fits in 9.5 GB; the GPU reads it directly without copying.

**Also works on:** Linux with NVIDIA GPU (12+ GB VRAM) via Ollama. Not tested but architecturally compatible.

## Quick Start

```bash
# 1. Install dependencies
brew install ollama
ollama pull gemma3:12b

# 2. Clone + install
git clone https://github.com/bene-art/patrick-agent
cd patrick-agent
pip install -e .                  # installs patrick_agent + local-agent-kit + deps

# 3. Configure
cp .env.example .env
# Edit .env with API keys you want enabled (Gemini, Telegram, Alpaca, Odds API)
# Edit identity/IDENTITY.md with your agent's name and domain context

# 4. Run a smoke eval (verifies model + tool router work)
python3 eval/eval_agent.py --quick

# 5. Start Patrick (CLI by default; set channel: telegram in agent.yaml for TG)
python3 scripts/run_patrick.py
```

## Project Structure

```
patrick-agent/
├── pyproject.toml          # pip install -e .  → installs patrick_agent + deps
├── agent.yaml              # Kit config: model, channel, memory
├── identity/
│   ├── IDENTITY.md         # Who the agent is (template — customize this)
│   └── SOUL.md             # Operating modes + hard constraints (template)
├── patrick_agent/          # The importable package
│   ├── __init__.py
│   ├── tools/              # Six routable tools + 3 infra modules + 1 helper
│   │   ├── tool_router.py  # Pattern-matched dispatcher + chaining
│   │   ├── web_search.py   # Wraps local_agent_kit.search.GeminiSearch
│   │   ├── db_query.py     # Read-only SQLite (config-driven allowlist)
│   │   ├── file_read.py    # Scoped file access + write
│   │   ├── cloud_write.py  # Gemini function calling for writes
│   │   ├── shell_exec.py   # Allowlisted read-only commands
│   │   ├── api_call.py     # Direct Alpaca + Odds API REST
│   │   ├── telemetry.py    # JSONL tool-use audit log
│   │   ├── conversation_memory.py  # SQLite-backed per-thread history
│   │   └── gemini_chat.py  # Minimal Gemini Flash chat for cloud escalation
│   └── notify/
│       ├── formatter.py    # Tier 2 (reports) / Tier 3 (alerts)
│       ├── telegram.py     # Direct Telegram Bot API send
│       └── base.py         # Channel ABC + Severity enum
├── eval/
│   ├── eval_agent.py       # Immutable scorer + failure taxonomy
│   ├── promptfoo_provider.py   # Full-pipeline Promptfoo provider
│   └── synthetic_dataset.py    # Test case generator
├── scripts/
│   ├── run_patrick.py      # Main entry point — wires kit + tool router
│   └── nightly_eval.py     # Regression-detection template
├── tests/
│   └── test_smoke.py       # Import + dispatcher smoke tests
├── docs/
│   └── white_paper_v2.md   # Technical white paper
├── requirements.txt        # Loose alternative to pyproject for non-package use
├── .env.example
├── LICENSE                 # MIT
└── README.md
```

## Key Lessons Learned

1. **The system prompt was the main problem.** Early SOUL.md literally said "ask 'Want me to break that down?'" — the model did it 50.6% of the time. One deletion, zero instances.
2. **Dense prompts hurt small models.** 246 lines of instructions → 84 lines. Faster AND more accurate.
3. **Inline injection, not history injection.** 12B models treat separate history entries as stale context. `[SYSTEM DATA]` appended to the current user message is consistently used.
4. **IDENTITY.md must match tools.** Built tools but forgot to update the system prompt? The agent deflects every tool-enabled query until you tell it about its own capabilities.
5. **Keyword matching punishes good answers.** Use semantic grading (`llm-rubric`) for quality; literal matching for guardrails only.
6. **Per-model `keep_alive` prevents GPU eviction.** Global `keep_alive` pins ALL models. Per-model pins only the primary, letting specialists load and release.
7. **Negative IDENTITY clauses don't stop fabrication at 12B.** Telling the model "do NOT make up numbers" doesn't work as well as guarding at the tool / synthesizer layer. Catch fabrication in the scorer; prevent it in the data path.
8. **Measure before shipping.** The Karpathy loop (immutable scorer + modifiable config + single metric) turns prompt engineering from vibes into science.

## The Name

Patrick was asked on Telegram: "If I were putting you on GitHub, what name would you like?"

He replied: *"I'd prefer the handle 'Patrick.' It reflects my focus on change and coordination. It's also concise and memorable."*

So that's what we called it.

## License

MIT — do whatever you want with it.

## Author

Built by [Benjamin Easington](https://github.com/bene-art). One person, one Mac mini, zero cloud dependency for core operations.
