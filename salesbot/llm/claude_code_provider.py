"""Claude via the Claude Code CLI (`claude -p`), using whatever login the CLI has.

Useful when there is no API key but Claude Code is installed and signed in. Each
turn is one non-interactive `claude -p` call with Claude Code's own tools turned
off; salesbot's tools are described in the system prompt and the model answers
through a JSON schema (`--json-schema`), which we map back to tool calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from typing import Any

from .base import LLMError, LLMResponse, Message, ToolCall, ToolSpec

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Message to the user; empty while you are calling tools"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["text", "tool_calls"],
}

TOOL_PROTOCOL = """

## Your tools
This application runs the tools below for you. You have no other tools, and these ARE available:
you call them by listing them in the "tool_calls" field of your JSON response. The application runs
every call and sends you the results as <tool_result> blocks in the next turn.
- To act, return "tool_calls" (several at once is fine) and leave "text" empty.
- When the work is finished, return your final message in "text" with an empty "tool_calls".
- Only use these tool names, with arguments matching each JSON schema.

{tools}"""


def response_schema(tools: list[ToolSpec]) -> dict[str, Any]:
    schema = json.loads(json.dumps(RESPONSE_SCHEMA))
    call = schema["properties"]["tool_calls"]["items"]["properties"]["name"]
    if tools:
        call["enum"] = [t.name for t in tools]
    else:
        schema["properties"]["tool_calls"]["maxItems"] = 0
    return schema


def cli_available() -> bool:
    return shutil.which(os.environ.get("CLAUDE_CLI", "claude")) is not None


class ClaudeCodeProvider:
    name = "claude_code"

    def __init__(self, cli: str | None = None, timeout: float = 600) -> None:
        self.cli = cli or os.environ.get("CLAUDE_CLI", "claude")
        self.timeout = timeout
        # Run outside any project so no CLAUDE.md, settings or MCP servers leak in.
        self.workdir = tempfile.mkdtemp(prefix="salesbot-claude-")

    @staticmethod
    def render_transcript(messages: list[Message]) -> str:
        parts = []
        for m in messages:
            if m.role == "user":
                parts.append(f"<user>\n{m.text}\n</user>")
            elif m.role == "assistant":
                body = m.text
                if m.tool_calls:
                    calls = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls]
                    body += f"\n<tool_calls>{json.dumps(calls)}</tool_calls>"
                parts.append(f"<assistant>\n{body.strip()}\n</assistant>")
            else:
                for r in m.tool_results:
                    status = "error" if r.is_error else "ok"
                    parts.append(f'<tool_result id="{r.call_id}" name="{r.name}" status="{status}">\n{r.content}\n</tool_result>')
        parts.append("Continue as the assistant: answer the latest user message or act on the tool results.")
        return "\n\n".join(parts)

    @staticmethod
    def render_system(system: str, tools: list[ToolSpec]) -> str:
        if not tools:
            return system
        listing = "\n".join(
            f"- {t.name}: {t.description}\n  arguments schema: {json.dumps(t.parameters)}" for t in tools
        )
        return system + TOOL_PROTOCOL.format(tools=listing)

    async def complete(
        self, model: str, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        args = [
            self.cli,
            "-p",
            "--output-format", "json",
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--system-prompt", self.render_system(system, tools),
            "--json-schema", json.dumps(response_schema(tools)),
        ]
        if model and model != "default":
            args += ["--model", model]
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(self.render_transcript(messages).encode()), timeout=self.timeout
            )
        except TimeoutError as exc:
            proc.kill()
            raise LLMError(f"claude CLI timed out after {self.timeout:.0f}s") from exc
        try:
            result: dict[str, Any] = json.loads(out.decode() or "{}")
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude CLI returned non-JSON output: {(out or err).decode()[:300]}") from exc
        if proc.returncode != 0 or result.get("is_error"):
            detail = result.get("result") or err.decode()[:300] or f"exit code {proc.returncode}"
            raise LLMError(f"claude CLI failed: {detail}")

        data = result.get("structured_output")
        if not isinstance(data, dict):
            # No structured output (e.g. a refusal): treat the plain result as the reply.
            return LLMResponse(Message(role="assistant", text=str(result.get("result", ""))))
        calls = [
            ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=str(c.get("name", "")), arguments=dict(c.get("arguments") or {}))
            for c in data.get("tool_calls") or []
            if isinstance(c, dict)
        ]
        return LLMResponse(
            Message(role="assistant", text=str(data.get("text", "")), tool_calls=calls),
            stop_reason="tool_use" if calls else "end_turn",
        )
