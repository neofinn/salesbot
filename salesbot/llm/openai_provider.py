"""Adapter for OpenAI and any OpenAI-compatible API (used for xAI Grok)."""

from __future__ import annotations

import json
from typing import Any

import openai

from .base import LLMResponse, Message, ToolCall, ToolSpec


class OpenAICompatibleProvider:
    def __init__(self, name: str, api_key: str, base_url: str | None = None) -> None:
        self.name = name
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _to_wire(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                wire.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                wire.append(entry)
            else:
                for r in m.tool_results:
                    content = f"ERROR: {r.content}" if r.is_error else r.content
                    wire.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
        return wire

    async def complete(
        self, model: str, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": model, "messages": self._to_wire(system, messages)}
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        calls: list[ToolCall] = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResponse(
            message=Message(role="assistant", text=choice.message.content or "", tool_calls=calls),
            stop_reason="tool_use" if calls else (choice.finish_reason or "end_turn"),
        )
