"""Provider-neutral message types shared by every LLM adapter.

Agents only ever see these types, so the same agent loop can run on Claude,
GPT, Grok or Gemini. Each adapter translates them to its own wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    # The provider's own representation of an assistant turn. Replayed verbatim
    # to the same provider so provider-specific state (e.g. Claude thinking
    # blocks, Gemini thought signatures) survives the round trip.
    raw: Any = None
    raw_provider: str | None = None


@dataclass
class LLMResponse:
    message: Message
    stop_reason: str = "end_turn"

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls


class LLMError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    async def complete(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> LLMResponse: ...
