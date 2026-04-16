"""Tool router — detects what tools a message needs and executes them.


Runs BEFORE the LLM call. Fetches external data and injects it as
[SYSTEM DATA] context so Patrick can answer with real information
instead of saying "I don't have that data."

This is intent-based routing, not model-driven tool calling.
gemma3:12b doesn't support Ollama native tool calling, so we
detect tool needs via keyword patterns and execute deterministically.

Usage:
    from delta_infra.tools.tool_router import route_tools
    context_blocks = await route_tools("What's the NBA injury report?")
    # Returns: [("[SYSTEM DATA — web search]\n...injury data...")]
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Intent patterns ───────────────────────────────────────────────────
# Each pattern maps to a tool + query extraction logic.
# Order matters — first match wins.

_WEB_SEARCH_PATTERNS = [
    # Explicit search requests
    r"(?i)(?:search|look up|google|find out|check online)\s+(.+)",
    # "What's X at/doing" — stock/crypto prices
    r"(?i)what(?:'s| is)\s+(.+?)\s+(?:trading at|at right now|at now|at today|price|doing)",
    # Stock tickers / market indices
    r"(?i)(?:s&p|nasdaq|dow|spy|qqq|btc|eth)\s*\d*\s+(.+)",
    # News/current events/sports
    r"(?i)(?:any |latest |today'?s? )?(?:news|injury|injuries|report|update|headline|lineup|schedule|scores?|standings?|results?)s?\s*(?:on|about|for|of)?\s*(.+)",
    r"(?i)(?:what|who)\s+(?:won|happened|scored|played)\s+(.+)",
    # Today/tonight/tomorrow + sports/events
    r"(?i)(?:today|tonight|tomorrow|this week)(?:'?s)?\s+(.+?(?:game|match|lineup|schedule|fight|race|event)s?)",
    r"(?i)(?:nba|nhl|mlb|nfl|ufc|premier league|champions league)\s+(.+)",
    # Weather
    r"(?i)(?:what'?s? the |)weather\s+(.+)",
    # "Tell me about X" when X is clearly external
    r"(?i)(?:tell me about|what do you know about|who is|who are)\s+((?!delta|patrick|scout|pulse|mkt|autoresearch|commander).+)",
    # Questions about external people, companies, concepts
    r"(?i)(?:how (?:is|are|did|has)|what (?:is|are|did|has)|when (?:is|does|did))\s+((?!delta|patrick|scout|pulse|mkt|autoresearch|commander|the system|the architecture|you ).{10,})",
]

_DB_QUERY_PATTERNS = [
    # Record / stats queries about betting
    r"(?i)(?:scout'?s?|betting|picks?)\s+(?:record|stats|win rate|accuracy|results?)(?:\s+(.+))?",
    r"(?i)how many (?:picks?|bets?|trades?)",
    r"(?i)(?:what'?s?|show me|how'?s?)\s+(?:the |our |my |scout'?s? )?(?:record|win rate|P&?L|pnl|results?|picks?)",
    r"(?i)(?:what was|show me|how did)\s+(?:yesterday'?s?|last week'?s?|this month'?s?|this week'?s?|today'?s?)\s+(?:picks?|record|results?|P&?L|pnl|betting)",
    # Calibration
    r"(?i)(?:calibration|brier|accuracy)\s+(?:score|data|stats?|look)",
    r"(?i)how (?:is|are) (?:the )?(?:calibration|brier|accuracy)",
    # Broad picks/betting mention (for chaining with other tools)
    r"(?i)(?:yesterday'?s?|today'?s?|recent|last|latest)\s+(?:picks?|bets?|results?)",
    r"(?i)compare.*(?:picks?|bets?|record|results?)",
]

_FILE_READ_PATTERNS = [
    # Morning report / picks report
    r"(?i)(?:show|read|open|what did|what does|what's in)\s+(?:me )?(?:the |today'?s? |yesterday'?s? |this morning'?s? )?(?:morning |picks? |evening )?(?:report|brief|briefing)",
    # Config files
    r"(?i)(?:show|read|what's in)\s+(?:me )?(?:the )?(?:config|configuration|settings?)\s*(?:for |of )?\s*(.+)?",
    # Logs
    r"(?i)(?:show|read|check|what's in)\s+(?:me )?(?:the )?(?:log|logs)\s*(?:for |of )?\s*(.+)?",
    # Weekly intel
    r"(?i)(?:show|read|what's in)\s+(?:me )?(?:the )?(?:weekly|intel|bridge)\s+(?:report|intel|briefing)",
    # IDENTITY / SOUL
    r"(?i)(?:show|read|what's in)\s+(?:me )?(?:your |patrick'?s? )?(?:identity|soul|IDENTITY\.md|SOUL\.md)",
    # Eval results
    r"(?i)(?:show|read|what's in|what were)\s+(?:me )?(?:the )?(?:eval|evaluation)\s+(?:result|score|report)s?",
    # Master Plan docs
    r"(?i)(?:show|read|what's in)\s+(?:me )?(?:the |patrick'?s? )?(?:master plan|project summar|agent status|patrick status)",
    r"(?i)(?:master plan|agent status|project summar)",
]

_API_CALL_PATTERNS = [
    # Alpaca / portfolio
    r"(?i)(?:what's|show me|check)\s+(?:my |the |our )?(?:alpaca|portfolio|positions?|holdings?|stock)\s*(?:value|account|balance|status)?",
    r"(?i)(?:alpaca|paper trading)\s+(?:account|status|positions?|balance|portfolio)",
    r"(?i)(?:how (?:is|are) )?(?:my |the |our )?(?:stocks?|positions?|portfolio)\s+(?:doing|looking|today)?",
    # Odds
    r"(?i)(?:what are |show me |get )?(?:the |tonight'?s? |today'?s? )?(?:odds|lines|spreads?)\s+(?:for |on )?(.+)?",
    r"(?i)(?:nba|mlb|nhl)\s+(?:odds|lines|spreads?)",
]

_SHELL_EXEC_PATTERNS = [
    # System status checks
    r"(?i)(?:is |are )?(?:ollama|the server|betting server|api|services?)\s+(?:running|up|down|alive|status)",
    r"(?i)(?:check |show me |what's )?(?:the )?(?:disk|storage|memory|ram|cpu)\s*(?:space|usage|pressure|left)?",
    r"(?i)(?:what's|show me|check)\s+(?:the )?(?:uptime|system load|system status)",
    r"(?i)(?:what|which)\s+(?:processes?|services?)\s+(?:are |is )?(?:running|using|eating|hogging)",
    r"(?i)(?:how much |)(?:disk|storage|memory|ram)\s+(?:is |do we have |)(?:left|free|available|used)",
    r"(?i)(?:list |show )?(?:running |active )?(?:launchd |delta )?(?:jobs|services|daemons)",
    r"(?i)ollama (?:ps|status|list|models)",
]

_FILE_WRITE_PATTERNS = [
    # Update master plan docs
    r"(?i)(?:update|write|edit|change|fix|rewrite)\s+(?:the |your |my |patrick'?s? )?(?:master plan|project summar|agent status|patrick status|STATUS\.md)",
    # Log / note taking
    r"(?i)(?:log|note|record|write down|save)\s+(?:that |this |today'?s? )?(.+)",
]


async def route_tools(message: str) -> list[str]:
    """Detect tool needs and execute them.

    Args:
        message: The user's raw message.

    Returns:
        List of [SYSTEM DATA] blocks to inject into LLM context.
        Empty list if no tools needed.

    Side effect: logs telemetry for every invocation.
    """
    blocks: list[str] = []
    _tools_fired: list[str] = []  # track for telemetry

    # ── Tool chaining: check ALL tool groups, collect all matches ──
    # Each group fires at most once (break within group).
    # Multiple groups can fire for the same message.
    # Example: "Check Alpaca positions and compare with yesterday's picks"
    #   → API (alpaca_positions) + DB (recent picks) → both injected

    # 0. File WRITE (cloud-escalated) — exclusive, no chaining
    write_matched = False
    for pattern in _FILE_WRITE_PATTERNS:
        m = re.search(pattern, message)
        if m:
            logger.info("tool_router: file_write triggered for: %r", message[:60])
            result = await _route_file_write(message)
            if result:
                blocks.append(f"[SYSTEM DATA — file operation]\n{result}")
                _tools_fired.append("file_write")
            write_matched = True
            break

    # Write is exclusive — if writing, don't chain other tools
    if not write_matched:
        # 1. File read
        for pattern in _FILE_READ_PATTERNS:
            m = re.search(pattern, message)
            if m:
                logger.info("tool_router: file_read triggered for: %r", message[:60])
                result = await _route_file_read(message)
                if result:
                    blocks.append(f"[SYSTEM DATA — file contents]\n{result}")
                    _tools_fired.append("file_read")
                break

        # 2. DB query
        for pattern in _DB_QUERY_PATTERNS:
            m = re.search(pattern, message)
            if m:
                logger.info("tool_router: db_query triggered for: %r", message[:60])
                result = await _route_db_query(message)
                if result:
                    blocks.append(f"[SYSTEM DATA — database query]\n{result}")
                    _tools_fired.append("db_query")
                break

        # 3. API call
        for pattern in _API_CALL_PATTERNS:
            m = re.search(pattern, message)
            if m:
                logger.info("tool_router: api_call triggered for: %r", message[:60])
                result = await _route_api_call(message)
                if result:
                    blocks.append(f"[SYSTEM DATA — API response]\n{result}")
                    _tools_fired.append("api_call")
                break

        # 4. Shell exec
        for pattern in _SHELL_EXEC_PATTERNS:
            m = re.search(pattern, message)
            if m:
                logger.info("tool_router: shell_exec triggered for: %r", message[:60])
                result = await _route_shell_exec(message)
                if result:
                    blocks.append(f"[SYSTEM DATA — system command]\n{result}")
                    _tools_fired.append("shell_exec")
                break

        # 5. Web search (explicit patterns)
        if not any(t in _tools_fired for t in ["file_read", "db_query", "api_call", "shell_exec"]):
            for pattern in _WEB_SEARCH_PATTERNS:
                m = re.search(pattern, message)
                if m:
                    query = message
                    logger.info("tool_router: web_search triggered, query=%r", query[:80])
                    from delta_infra.tools.web_search import web_search
                    result = await web_search(query)
                    if result and "[" not in result[:5]:
                        blocks.append(
                            f"[SYSTEM DATA — web search results]\n{result}"
                        )
                        _tools_fired.append("web_search")
                    break

    # 5. Web search FALLBACK — if nothing matched and the question
    #    looks external (not about BenAi internals), search the web.
    #    This catches natural phrasing that regex patterns miss.
    if not blocks:
        ml = message.lower()
        _INTERNAL_KEYWORDS = {
            "delta", "patrick", "scout", "pulse", "mkt", "autoresearch",
            "commander", "architecture", "identity", "soul", "system",
            "config", "launchd", "daemon", "briefing", "dispatch",
        }
        is_internal = any(kw in ml for kw in _INTERNAL_KEYWORDS)
        is_question = any(ml.startswith(q) for q in [
            "what", "who", "where", "when", "how", "why", "is ", "are ",
            "did ", "does ", "can ", "tell", "show", "any ", "which",
        ])
        # Only search if it looks like an external question
        if is_question and not is_internal and len(message) > 10:
            logger.info("tool_router: web_search FALLBACK for: %r", message[:80])
            from delta_infra.tools.web_search import web_search
            result = await web_search(message)
            if result and "[" not in result[:5]:
                blocks.append(
                    f"[SYSTEM DATA — web search results]\n{result}"
                )

    # ── Telemetry: log what happened ──
    try:
        from delta_infra.tools.telemetry import log_tool_use, log_tool_skip
        if _tools_fired:
            tool_name = "+".join(_tools_fired) if len(_tools_fired) > 1 else _tools_fired[0]
            log_tool_use(tool_name, message, "\n".join(blocks))
        elif blocks:
            log_tool_use("web_search_fallback", message, blocks[0])
        else:
            log_tool_skip(message)
    except Exception:
        pass  # telemetry must never break the pipeline

    if _tools_fired and len(_tools_fired) > 1:
        logger.info("tool_router: CHAINED %d tools: %s", len(_tools_fired), _tools_fired)

    return blocks


async def _route_db_query(message: str) -> str:
    """Map natural language to a database query."""
    from delta_infra.tools.db_query import db_query
    ml = message.lower()

    if any(w in ml for w in ["pick", "bet", "record", "win rate"]):
        return await db_query(
            "picks",
            "SELECT ts, sport, market, label, result, pnl "
            "FROM picks WHERE picked = 1 ORDER BY ts DESC LIMIT 15",
        )

    if any(w in ml for w in ["calibration", "brier", "accuracy"]):
        return await db_query(
            "picks",
            "SELECT sport, COUNT(*) as total, "
            "SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins, "
            "ROUND(SUM(pnl), 2) as net_pnl "
            "FROM picks WHERE picked = 1 AND result IS NOT NULL "
            "GROUP BY sport",
        )

    if any(w in ml for w in ["trade", "p&l", "pnl", "portfolio"]):
        return await db_query(
            "picks",
            "SELECT substr(ts, 1, 10) as day, COUNT(*) as picks, "
            "SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, "
            "ROUND(SUM(pnl), 2) as net "
            "FROM picks WHERE picked = 1 AND result IS NOT NULL "
            "GROUP BY day ORDER BY day DESC LIMIT 10",
        )

    return ""


async def _route_api_call(message: str) -> str:
    """Map natural language to an API call."""
    from delta_infra.tools.api_call import api_call
    ml = message.lower()

    if any(w in ml for w in ["alpaca", "portfolio", "positions", "holdings", "stock account"]):
        if any(w in ml for w in ["position", "holding", "stock"]):
            return await api_call("alpaca_positions")
        return await api_call("alpaca_account")

    if any(w in ml for w in ["odds", "lines", "spread"]):
        if "mlb" in ml or "baseball" in ml:
            return await api_call("odds_mlb")
        if "nhl" in ml or "hockey" in ml:
            return await api_call("odds_nhl")
        # Default to NBA
        return await api_call("odds_nba")

    return ""


async def _route_shell_exec(message: str) -> str:
    """Map natural language to an allowlisted shell command."""
    from delta_infra.tools.shell_exec import shell_exec
    ml = message.lower()

    if "ollama" in ml and any(w in ml for w in ["ps", "status", "running", "loaded", "models"]):
        if "list" in ml or "available" in ml or "models" in ml:
            return await shell_exec("ollama_list")
        return await shell_exec("ollama_ps")

    if any(w in ml for w in ["disk", "storage", "space"]):
        return await shell_exec("disk_space")

    if any(w in ml for w in ["memory", "ram"]):
        if "process" in ml or "using" in ml or "eating" in ml or "hogging" in ml:
            return await shell_exec("top_mem")
        return await shell_exec("memory")

    if any(w in ml for w in ["uptime", "system load", "load average"]):
        return await shell_exec("uptime")

    if any(w in ml for w in ["process", "service"]) and any(w in ml for w in ["running", "active"]):
        if "python" in ml:
            return await shell_exec("python_procs")
        return await shell_exec("launchd_delta")

    if any(w in ml for w in ["launchd", "jobs", "daemons"]):
        return await shell_exec("launchd_delta")

    if any(w in ml for w in ["port", "listening"]):
        return await shell_exec("ports")

    if "cpu" in ml:
        return await shell_exec("top_cpu")

    if any(w in ml for w in ["git status", "git log", "commit"]):
        if "log" in ml or "commit" in ml:
            return await shell_exec("git_log")
        return await shell_exec("git_status")

    return ""


async def _route_file_write(message: str) -> str:
    """Route write operations to Gemini cloud escalation."""
    from delta_infra.tools.cloud_write import cloud_write_file
    from delta_infra.tools.file_read import file_read
    ml = message.lower()

    # Load Patrick's current identity as context for accurate writes
    identity_ctx = ""
    try:
        identity_ctx = await file_read(
            str(Path.home() / "patrick-agent" / "identity" / "IDENTITY.md")
        )
    except Exception:
        pass

    if any(w in ml for w in ["agent status", "patrick status", "patrick's status"]):
        return await cloud_write_file(
            path="07_Agents/Patrick/STATUS.md",
            instruction=message,
            context=identity_ctx,
        )

    if "project summar" in ml:
        return await cloud_write_file(
            path="06_Project_Summaries/patrick-agent.md",
            instruction=message,
            context=identity_ctx,
        )

    if "master plan" in ml:
        return await cloud_write_file(
            path="project-docs.md",
            instruction=message,
            context=identity_ctx,
        )

    if any(w in ml for w in ["log", "note", "record"]):
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        return await cloud_write_file(
            path=f"05_Logs_and_Notes/Session_Notes/{date_str}_patrick_log.md",
            instruction=message,
            context=identity_ctx,
        )

    return ""


async def _route_file_read(message: str) -> str:
    """Map natural language to a file read."""
    from delta_infra.tools.file_read import file_read, list_files
    ml = message.lower()

    if any(w in ml for w in ["morning report", "picks report", "today's report"]):
        # Find the most recent report
        listing = await list_files("reports")
        if listing and "[" not in listing[:5]:
            # Read the first (most recent) file
            first_file = listing.split("\n")[0].strip()
            if first_file:
                return await file_read(f"reports/{first_file}")
        return "[no reports found]"

    if any(w in ml for w in ["weekly intel", "bridge report", "weekly report"]):
        listing = await list_files("identity/outbox")
        if listing and "[" not in listing[:5]:
            first_file = listing.split("\n")[0].strip()
            if first_file:
                return await file_read(f"identity/outbox/{first_file}")
        return "[no weekly intel found]"

    if any(w in ml for w in ["identity", "identity.md"]):
        return await file_read("identity/IDENTITY.md")

    if any(w in ml for w in ["soul", "soul.md"]):
        return await file_read("identity/SOUL.md")

    if any(w in ml for w in ["eval result", "evaluation result", "eval score"]):
        listing = await list_files("data/eval/results")
        if listing and "[" not in listing[:5]:
            first_file = listing.split("\n")[0].strip()
            if first_file:
                return await file_read(f"data/eval/results/{first_file}")
        return "[no eval results found]"

    if any(w in ml for w in ["master plan"]):
        return await file_read(str(Path.home() / "Desktop/project-docs/project-docs.md"))

    if any(w in ml for w in ["agent status", "patrick status", "patrick's status"]):
        return await file_read(str(Path.home() / "Desktop/project-docs/07_Agents/Patrick/STATUS.md"))

    if any(w in ml for w in ["project summar"]):
        listing = await list_files(str(Path.home() / "Desktop/project-docs/06_Project_Summaries"))
        return listing if listing else "[no project summaries found]"

    if "config" in ml:
        # Try to find the specific config mentioned
        for cfg in ["betting_profit", "alerting", "routing", "cluster", "features"]:
            if cfg in ml:
                return await file_read(f"config/{cfg}.yaml")
        # Default: list available configs
        return await list_files("config")

    if "log" in ml:
        listing = await list_files("logs")
        return listing if listing else "[no logs found]"

    return ""
