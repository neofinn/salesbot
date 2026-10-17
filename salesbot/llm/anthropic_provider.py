"""Claude adapter (Anthropic Python SDK)."""

from __future__ import annotations

from typing import Any

import anthropic

from .base import LLMResponse, Message, ToolCall, ToolSpec

# Models that accept server-side refusal fallbacks (`fallbacks="default"`).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str = "", effort: str = "medium") -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()
        self.effort = effort

    def _to_wire(self, messages: list[Message]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                wire.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                if m.raw_provider == self.name and m.raw is not None:
                    # Replay unchanged so thinking blocks stay valid.
                    wire.append({"role": "assistant", "content": m.raw})
                    continue
                blocks: list[dict[str, Any]] = []
                if m.text:
                    blocks.append({"type": "text", "text": m.text})
                for c in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
                wire.append({"role": "assistant", "content": blocks or m.text})
            else:
                wire.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": r.call_id,
                                "content": r.content,
                                "is_error": r.is_error,
                            }
                            for r in m.tool_results
                        ],
                    }
                )
        return wire

    async def complete(
        self, model: str, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 16000,
            "system": system,
            "messages": self._to_wire(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        if model in _FALLBACK_MODELS:
            # On a safety-classifier decline, the API retries on Anthropic's
            # recommended fallback model inside the same call.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        response = await self.client.beta.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            return LLMResponse(
                message=Message(role="assistant", text="I can't help with that request."),
                stop_reason="refusal",
            )

        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMResponse(
            message=Message(
                role="assistant", text=text, tool_calls=calls, raw=response.content, raw_provider=self.name
            ),
            stop_reason=response.stop_reason or "end_turn",
        )
