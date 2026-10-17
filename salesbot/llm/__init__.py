"""LLM gateway: resolve "<provider>:<model>" strings to a provider + model."""

from __future__ import annotations

from ..config import Settings
from .base import LLMError, LLMResponse, Message, Provider, ToolCall, ToolResult, ToolSpec

PROVIDERS = ("anthropic", "openai", "xai", "gemini", "claude_code")

__all__ = [
    "PROVIDERS",
    "LLMError",
    "LLMGateway",
    "LLMResponse",
    "Message",
    "Provider",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
]


class LLMGateway:
    """Creates provider clients lazily and routes requests by model string."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        """Install a provider instance (used by tests and custom backends)."""
        self._providers[provider.name] = provider

    def resolve(self, model_ref: str) -> tuple[str, str]:
        """Split "provider:model"; a bare provider name uses its default model."""
        provider, _, model = model_ref.partition(":")
        provider = provider.strip().lower()
        if provider not in PROVIDERS and provider not in self._providers:
            raise LLMError(f"Unknown LLM provider {provider!r}. Use one of: {', '.join(PROVIDERS)}")
        if not model:
            model = getattr(self.settings, f"{provider}_model", "")
        return provider, model.strip()

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            self._providers[name] = self._build(name)
        return self._providers[name]

    def available(self) -> list[str]:
        """Providers that have credentials configured (or were registered)."""
        found = set(self._providers)
        # The staff already run on the default model, so its provider works
        # even when credentials come from elsewhere (e.g. an `ant auth` profile).
        found.add(self.settings.default_model.partition(":")[0].strip().lower())
        for name in PROVIDERS:
            if self._has_credentials(name):
                found.add(name)
        return sorted(found)

    def configured(self) -> list[str]:
        """Providers with an API key in the settings, plus custom registered ones."""
        found = {name for name in self._providers if name not in PROVIDERS}
        found.update(name for name in PROVIDERS if self._has_credentials(name))
        return sorted(found)

    def _has_credentials(self, name: str) -> bool:
        if name == "claude_code":
            from .claude_code_provider import cli_available

            return cli_available()
        return bool(getattr(self.settings, f"{name}_api_key", ""))

    def _build(self, name: str) -> Provider:
        s = self.settings
        if name == "anthropic":
            from .anthropic_provider import AnthropicProvider

            return AnthropicProvider(api_key=s.anthropic_api_key)
        if name == "claude_code":
            from .claude_code_provider import ClaudeCodeProvider, cli_available

            if not cli_available():
                raise LLMError("The claude CLI is not installed (needed for the claude_code provider).")
            return ClaudeCodeProvider()
        key = getattr(s, f"{name}_api_key", "")
        if not key:
            raise LLMError(f"No API key configured for {name}. Set {name.upper()}_API_KEY.")
        if name == "openai":
            from .openai_provider import OpenAICompatibleProvider

            return OpenAICompatibleProvider("openai", key)
        if name == "xai":
            from .openai_provider import OpenAICompatibleProvider

            return OpenAICompatibleProvider("xai", key, base_url="https://api.x.ai/v1")
        if name == "gemini":
            from .gemini_provider import GeminiProvider

            return GeminiProvider(key)
        raise LLMError(f"Unknown LLM provider {name!r}")

    async def complete(
        self, model_ref: str, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        provider_name, model = self.resolve(model_ref)
        return await self.provider(provider_name).complete(model, system, messages, tools)
