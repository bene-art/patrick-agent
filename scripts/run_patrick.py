#!/usr/bin/env python3
"""Run Patrick — the reference agent built on local-agent-kit.

Wires Patrick's tool router into local_agent_kit.Agent so the kit's
channel + Ollama plumbing is reused, but every message also flows through
Patrick's pattern-matched tool router for [SYSTEM DATA] injection.

Usage:
    python3 scripts/run_patrick.py
    python3 scripts/run_patrick.py --channel cli       # override channel
    python3 scripts/run_patrick.py --channel telegram

The script expects an `agent.yaml` and `identity/IDENTITY.md` at the
patrick-agent repo root. Edit those to customize the agent.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)


def _build_patrick_agent_cls():
    """Lazy-build the PatrickAgent class.

    Importing `local_agent_kit` happens here so `--help` works on a
    fresh clone before `pip install -e .` has been run.
    """
    from local_agent_kit.agent import Agent

    class PatrickAgent(Agent):
        """Agent subclass that runs Patrick's full tool router before each LLM call."""

        async def handle(self, text: str) -> str:
            # 1. Route through Patrick's tool detector.
            try:
                from patrick_agent.tools.tool_router import route_tools
                tool_blocks = await route_tools(text)
            except Exception as exc:
                logger.warning("tool router failed: %s", exc)
                tool_blocks = []

            # 2. Inject [SYSTEM DATA] inline into the user message.
            full_msg = text
            if tool_blocks:
                full_msg = text + "\n\n" + "\n\n".join(tool_blocks)

            # 3. Call Ollama via the parent's implementation.
            response = await self._ollama_chat(full_msg)

            # 4. Update conversation history (mirror Agent.handle).
            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": response})
            if len(self._history) > self.config.memory_max_history:
                self._history = self._history[-self.config.memory_max_history:]

            return response

    return PatrickAgent


def main():
    parser = argparse.ArgumentParser(description="Run Patrick — the reference agent.")
    parser.add_argument("--channel", choices=["cli", "telegram"],
                        help="Override channel from agent.yaml")
    parser.add_argument("--dir", default=str(REPO_ROOT),
                        help="Patrick repo / agent directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    agent_dir = Path(args.dir)

    # Imports below depend on local-agent-kit being installed (pip install -e .).
    PatrickAgent = _build_patrick_agent_cls()
    from local_agent_kit.agent import load_config

    config = load_config(agent_dir)
    if args.channel:
        config.channel = args.channel

    # Pick channel from (possibly overridden) config.
    if config.channel == "telegram":
        from local_agent_kit.channels.telegram_channel import TelegramChannel
        channel = TelegramChannel()
    else:
        from local_agent_kit.channels.cli_channel import CLIChannel
        channel = CLIChannel(agent_name=config.name)

    # Patrick's tool router covers web_search separately, so we leave the
    # kit's built-in search off to avoid double-calling.
    agent = PatrickAgent(config=config, channel=channel, search=None)

    print(f"Starting {config.name} ({config.model}) on {config.channel}...")
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
