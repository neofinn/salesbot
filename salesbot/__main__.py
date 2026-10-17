"""Entry point: `python -m salesbot telegram` or `python -m salesbot chat`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .agents import Team
from .commands import run_command
from .config import Settings
from .llm import LLMGateway
from .store import Store


def _make_team(settings: Settings) -> Team:
    store = Store(os.path.join(settings.data_dir, "salesbot.db"))
    return Team(settings, store, LLMGateway(settings))


async def _chat(settings: Settings) -> None:
    team = _make_team(settings)
    await team.store.open()
    print("salesbot chat - talk to the Manager. /help for commands, Ctrl-D to quit.")
    try:
        while True:
            try:
                text = (await asyncio.to_thread(input, "you> ")).strip()
            except EOFError:
                break
            if not text:
                continue
            reply = await run_command(team, "cli", text)
            if reply is None:
                reply = await team.handle("cli", text)
            print(f"manager> {reply}\n")
    finally:
        await team.store.close()


def _telegram(settings: Settings) -> None:
    from .telegram_bot import build_application

    app = build_application(_make_team(settings))
    app.run_polling()


def main() -> None:
    parser = argparse.ArgumentParser(prog="salesbot")
    parser.add_argument("mode", nargs="?", default="telegram", choices=["telegram", "chat"])
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    settings = Settings.from_env()
    if args.mode == "chat":
        asyncio.run(_chat(settings))
    else:
        _telegram(settings)


if __name__ == "__main__":
    main()
