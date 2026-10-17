"""Settings loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in _env(name).split(",") if item.strip()]


@dataclass
class Settings:
    # Model used by the built-in staff (manager, HR, recruiter) and as the
    # default for newly hired bots. Format: "<provider>:<model>".
    default_model: str = "anthropic:claude-opus-5-5"
    # Per-provider default models, used when a spec names only the provider.
    anthropic_model: str = "claude-opus-5-5"
    openai_model: str = "gpt-5"
    xai_model: str = "grok-4"
    gemini_model: str = "gemini-2.5-pro"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    gemini_api_key: str = ""

    telegram_bot_token: str = ""
    # Only these Telegram user IDs may command the team. Empty = nobody.
    telegram_allowed_user_ids: list[str] = field(default_factory=list)

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    brave_api_key: str = ""

    # Web app: a shared access token is required unless bound to localhost.
    web_token: str = ""
    web_host: str = "127.0.0.1"
    web_port: int = 8000

    data_dir: str = "data"
    # When true, emails and SMS are queued for human approval instead of sent.
    require_approval: bool = True
    max_agent_steps: int = 12

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            default_model=_env("SALESBOT_DEFAULT_MODEL", cls.default_model),
            anthropic_model=_env("ANTHROPIC_MODEL", cls.anthropic_model),
            openai_model=_env("OPENAI_MODEL", cls.openai_model),
            xai_model=_env("XAI_MODEL", cls.xai_model),
            gemini_model=_env("GEMINI_MODEL", cls.gemini_model),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            openai_api_key=_env("OPENAI_API_KEY"),
            xai_api_key=_env("XAI_API_KEY"),
            gemini_api_key=_env("GEMINI_API_KEY"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_ids=_env_list("TELEGRAM_ALLOWED_USER_IDS"),
            smtp_host=_env("SMTP_HOST"),
            smtp_port=int(_env("SMTP_PORT", "587")),
            smtp_user=_env("SMTP_USER"),
            smtp_password=_env("SMTP_PASSWORD"),
            smtp_from=_env("SMTP_FROM"),
            twilio_account_sid=_env("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=_env("TWILIO_AUTH_TOKEN"),
            twilio_from_number=_env("TWILIO_FROM_NUMBER"),
            brave_api_key=_env("BRAVE_API_KEY"),
            web_token=_env("SALESBOT_WEB_TOKEN"),
            web_host=_env("SALESBOT_WEB_HOST", cls.web_host),
            web_port=int(_env("PORT", _env("SALESBOT_WEB_PORT", "8000"))),
            data_dir=_env("SALESBOT_DATA_DIR", cls.data_dir),
            require_approval=_env_bool("SALESBOT_REQUIRE_APPROVAL", True),
            max_agent_steps=int(_env("SALESBOT_MAX_AGENT_STEPS", "12")),
        )
