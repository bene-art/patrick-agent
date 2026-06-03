"""Patrick Agent — a local-first AI agent reference implementation.

Built on top of `local-agent-kit`. The package provides:

- `patrick_agent.tools`      — six routable tools + telemetry + conversation memory
- `patrick_agent.notify`     — Telegram channel + tiered message formatter

The eval harness, scripts, and identity templates live at the repo root
(not inside this package) because they're consumed by scripts, not
imported by application code.
"""

__version__ = "0.2.0"
