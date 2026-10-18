"""Connections: settings the owner can change from the web app.

Values saved in the web app are stored in the database and take precedence over
environment variables; clearing a value falls back to the environment again.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

from .config import Settings, pick_default_model

Kind = Literal["secret", "text", "int", "bool"]


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    kind: Kind = "text"
    placeholder: str = ""


FIELDS: tuple[Field, ...] = (
    Field("anthropic_api_key", "Anthropic (Claude) API key", "ai", "secret", "sk-ant-..."),
    Field("openai_api_key", "OpenAI API key", "ai", "secret", "sk-..."),
    Field("xai_api_key", "xAI (Grok) API key", "ai", "secret", "xai-..."),
    Field("gemini_api_key", "Google Gemini API key", "ai", "secret", "AIza..."),
    Field("openrouter_api_key", "OpenRouter API key", "ai", "secret", "sk-or-..."),
    Field("groq_api_key", "Groq API key (free tier)", "ai", "secret", "gsk_..."),
    Field("ollama_url", "Ollama server URL (local models, e.g. Qwen)", "ai", "text", "http://127.0.0.1:11434"),
    Field("default_model", "Model for Manager, HR and Recruiter", "ai", "text", "auto, or router"),
    Field("router_models", "API router chain (comma-separated; empty = free API hunter's pick)", "router", "text", "gemini:gemini-2.5-flash, claude_code"),
    Field("router_prefer", "API router order: free first, or quality first", "router", "text", "free"),
    Field("smtp_host", "SMTP host", "email", "text", "smtp.gmail.com"),
    Field("smtp_port", "SMTP port", "email", "int", "587"),
    Field("smtp_user", "SMTP username", "email", "text"),
    Field("smtp_password", "SMTP password", "email", "secret"),
    Field("smtp_from", "From address", "email", "text", "you@company.com"),
    Field("twilio_account_sid", "Twilio account SID", "sms", "text", "AC..."),
    Field("twilio_auth_token", "Twilio auth token", "sms", "secret"),
    Field("twilio_from_number", "Twilio phone number", "sms", "text", "+15551234567"),
    Field("brave_api_key", "Brave Search API key", "search", "secret"),
    Field("openclaw_url", "OpenClaw Gateway URL", "openclaw", "text", "http://127.0.0.1:18789"),
    Field("openclaw_token", "OpenClaw Gateway token", "openclaw", "secret"),
    Field("openclaw_agent", "OpenClaw agent id", "openclaw", "text", "main"),
    Field("public_url", "Public address of this server (for phone apps)", "behaviour", "text", "https://ops.example.com"),
    Field("require_approval", "Require my approval before emails/texts are sent", "behaviour", "bool"),
)
FIELDS_BY_KEY = {f.key: f for f in FIELDS}

PROVIDER_LABELS = {
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
    "xai": "xAI Grok",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter (Claude, GPT, Grok, Gemini & more with one sign-in)",
    "groq": "Groq (fast, free tier)",
    "ollama": "Ollama on this server (local models such as Qwen)",
    "claude_code": "Claude Code CLI on this server (signed-in account, no key)",
    "router": "API router (tries free models first, falls back automatically)",
}


def parse(field: Field, raw: Any) -> Any:
    if field.kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if field.kind == "int":
        return int(raw)
    return str(raw).strip()


def apply(base: Settings, saved: dict[str, str]) -> Settings:
    """Environment settings with saved values layered on top."""
    settings = dataclasses.replace(base)
    for key, raw in saved.items():
        field = FIELDS_BY_KEY.get(key)
        if field is not None:
            setattr(settings, key, parse(field, raw))
    if base.default_model_auto and not saved.get("default_model"):
        settings.default_model = pick_default_model(settings)
    return settings


def mask(value: str) -> str:
    return "saved" if len(value) < 12 else f"{value[:5]}…{value[-4:]}"


def describe(settings: Settings, saved: dict[str, str]) -> list[dict[str, Any]]:
    """Field list for the UI. Secret values are never sent back, only a masked hint."""
    out = []
    for f in FIELDS:
        value = getattr(settings, f.key)
        entry: dict[str, Any] = {
            "key": f.key,
            "label": f.label,
            "group": f.group,
            "kind": f.kind,
            "placeholder": f.placeholder,
            "source": "saved" if f.key in saved else ("env" if value not in ("", None) else ""),
        }
        if f.kind == "secret":
            entry["set"] = bool(value)
            entry["hint"] = mask(value) if value else ""
        else:
            entry["value"] = value
        out.append(entry)
    return out


def validate(values: dict[str, Any]) -> dict[str, str | None]:
    """Check keys and types; returns values ready to store (None = clear)."""
    clean: dict[str, str | None] = {}
    for key, raw in values.items():
        field = FIELDS_BY_KEY.get(key)
        if field is None:
            raise ValueError(f"Unknown setting {key!r}")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            clean[key] = None
            continue
        try:
            parsed = parse(field, raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.label}: invalid value") from exc
        if key == "router_prefer" and str(parsed).lower() not in ("free", "quality"):
            raise ValueError("API router order must be free or quality")
        clean[key] = str(parsed).lower() if field.kind == "bool" else str(parsed)
    return clean
