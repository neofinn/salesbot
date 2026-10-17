"""Google Gemini adapter (google-genai SDK)."""

from __future__ import annotations

import uuid

from google import genai
from google.genai import types

from .base import LLMResponse, Message, ToolCall, ToolSpec


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def _to_wire(self, messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m.text)]))
            elif m.role == "assistant":
                if m.raw_provider == self.name and m.raw is not None:
                    contents.append(m.raw)  # keeps thought signatures intact
                    continue
                parts: list[types.Part] = []
                if m.text:
                    parts.append(types.Part.from_text(text=m.text))
                for c in m.tool_calls:
                    parts.append(types.Part.from_function_call(name=c.name, args=c.arguments))
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=r.name,
                                response={"error": r.content} if r.is_error else {"result": r.content},
                            )
                            for r in m.tool_results
                        ],
                    )
                )
        return contents

    async def complete(
        self, model: str, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name, description=t.description, parameters_json_schema=t.parameters
                        )
                        for t in tools
                    ]
                )
            ]
        response = await self.client.aio.models.generate_content(
            model=model, contents=self._to_wire(messages), config=config
        )
        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts if content else None) or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = [
            ToolCall(
                id=p.function_call.id or f"call_{uuid.uuid4().hex[:12]}",
                name=p.function_call.name,
                arguments=dict(p.function_call.args or {}),
            )
            for p in parts
            if p.function_call
        ]
        return LLMResponse(
            message=Message(role="assistant", text=text, tool_calls=calls, raw=content, raw_provider=self.name),
            stop_reason="tool_use" if calls else "end_turn",
        )
