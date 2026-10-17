"""Email (SMTP) and SMS (Twilio) tools, gated by the human approval queue."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from ..config import Settings
from .base import Tool, ToolContext, ToolError, schema, string


def _send_email_sync(settings: Settings, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)


async def deliver_email(settings: Settings, payload: dict[str, Any]) -> str:
    if not settings.smtp_host:
        raise ToolError("Email is not configured (set SMTP_HOST and related settings).")
    await asyncio.to_thread(_send_email_sync, settings, payload["to"], payload["subject"], payload["body"])
    return f"Email sent to {payload['to']}."


async def deliver_sms(settings: Settings, payload: dict[str, Any]) -> str:
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        raise ToolError("SMS is not configured (set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER).")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            data={"To": payload["to"], "From": settings.twilio_from_number, "Body": payload["body"]},
        )
    if resp.status_code >= 400:
        raise ToolError(f"Twilio error {resp.status_code}: {resp.text[:300]}")
    return f"SMS sent to {payload['to']}."


DELIVERERS = {"email": deliver_email, "sms": deliver_sms}


async def _queue_or_send(kind: str, payload: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.settings.require_approval:
        action_id = await ctx.store.add_pending(kind, payload, ctx.agent_name)
        return (
            f"Queued {kind} to {payload['to']} for human approval as action #{action_id}. "
            "It will be sent once the owner approves it."
        )
    return await DELIVERERS[kind](ctx.settings, payload)


async def execute_action(settings: Settings, kind: str, payload: dict[str, Any]) -> str:
    """Run an approved action from the queue."""
    return await DELIVERERS[kind](settings, payload)


async def _send_email(args: dict[str, Any], ctx: ToolContext) -> str:
    payload = {"to": args["to"], "subject": args["subject"], "body": args["body"]}
    return await _queue_or_send("email", payload, ctx)


async def _send_sms(args: dict[str, Any], ctx: ToolContext) -> str:
    return await _queue_or_send("sms", {"to": args["to"], "body": args["body"]}, ctx)


SEND_EMAIL = Tool(
    "send_email",
    "Send an email. May be queued for the owner's approval before it goes out.",
    schema(
        {"to": string("Recipient email address"), "subject": string("Subject line"), "body": string("Plain-text body")},
        ["to", "subject", "body"],
    ),
    _send_email,
)

SEND_SMS = Tool(
    "send_sms",
    "Send a text message (SMS). May be queued for the owner's approval before it goes out.",
    schema(
        {"to": string("Recipient phone number in E.164 format, e.g. +15551234567"), "body": string("Message text")},
        ["to", "body"],
    ),
    _send_sms,
)
