"""Slash commands shared by the Telegram bot and the local CLI chat."""

from __future__ import annotations

from .agents import Team

HELP = """Talk to the Manager in plain language, e.g.
  "Hire a bot that finds SaaS companies in Berlin and adds them as leads"
  "Ask the lead researcher to find 10 dentists in Austin and draft intro emails"

Commands:
  /team              list bots on the team
  /hire <job>        hire a new bot for a job description
  /fire <name>       retire a bot
  /pending           emails/texts waiting for your approval
  /approve <id>      send a queued email/text
  /reject <id>       discard a queued email/text
  /reset             clear the Manager's memory of this chat
  /help              this message"""


async def run_command(team: Team, chat_id: str, text: str) -> str | None:
    """Return a reply for a slash command, or None if `text` isn't one."""
    if not text.startswith("/"):
        return None
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@", 1)[0].lower()  # Telegram may append @BotName
    arg = arg.strip()

    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/team":
        bots = await team.roster()
        if not bots:
            return "Staff: manager, hr, recruiter. No worker bots yet - try /hire <job>."
        lines = [f"- {b.name}: {b.role} ({b.model}; tools: {', '.join(b.tools) or 'none'})" for b in bots]
        return "Staff: manager, hr, recruiter.\nBots:\n" + "\n".join(lines)
    if cmd == "/hire":
        return await team.hire(arg) if arg else "Usage: /hire <job description>"
    if cmd == "/fire":
        return await team.fire(arg) if arg else "Usage: /fire <bot name>"
    if cmd == "/pending":
        return await team.pending_summary()
    if cmd in ("/approve", "/reject"):
        if not arg.lstrip("#").isdigit():
            return f"Usage: {cmd} <action id>"
        action_id = int(arg.lstrip("#"))
        return await (team.approve(action_id) if cmd == "/approve" else team.reject(action_id))
    if cmd == "/reset":
        await team.store.clear_chat(chat_id)
        return "Manager memory for this chat cleared."
    return f"Unknown command {cmd}. Try /help."
