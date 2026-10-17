"""Telegram front-end: the owner chats with the Manager from their phone."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from .agents import Team
from .commands import run_command

log = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4000


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks


def build_application(team: Team) -> Application:
    """Build the bot. The team's store is opened on the bot's own event loop."""
    settings = team.settings
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")
    allowed = set(settings.telegram_allowed_user_ids)
    if not allowed:
        log.warning("TELEGRAM_ALLOWED_USER_IDS is empty: the bot will refuse every user.")

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        user = update.effective_user
        if msg is None or not msg.text or user is None:
            return
        if str(user.id) not in allowed:
            await msg.reply_text(f"Sorry, you're not authorized. Your Telegram user ID is {user.id}.")
            return
        chat_id = str(msg.chat_id)
        await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)
        try:
            reply = await run_command(team, chat_id, msg.text)
            if reply is None:
                reply = await team.handle(chat_id, msg.text)
        except Exception as exc:
            log.exception("failed to handle message")
            reply = f"Something went wrong: {type(exc).__name__}: {exc}"
        for chunk in split_message(reply):
            await msg.reply_text(chunk)

    async def post_init(app: Application) -> None:
        await team.store.open()

    async def post_shutdown(app: Application) -> None:
        await team.store.close()

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT, on_message))
    return app
