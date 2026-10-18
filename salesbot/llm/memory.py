"""Buffer memory: keep a conversation inside whichever model is answering.

When the API router moves a conversation to a model with a smaller context window,
`fit` keeps the opening request and the newest messages word for word and folds the
middle into a compact summary, never splitting a tool call from its result.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import Message, ToolSpec

if TYPE_CHECKING:
    from ..config import Settings

CHARS_PER_TOKEN = 4
OUTPUT_RESERVE = 4096
# Context windows by provider when the hunter has not measured the model.
DEFAULT_CONTEXT = {
    "anthropic": 200_000, "claude_code": 200_000, "openai": 128_000, "xai": 128_000,
    "gemini": 1_000_000, "openrouter": 128_000, "groq": 128_000, "ollama": 8_192,
}


def tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def message_tokens(m: Message) -> int:
    n = tokens(m.text)
    for c in m.tool_calls:
        n += tokens(c.name + json.dumps(c.arguments))
    for r in m.tool_results:
        n += tokens(r.content)
    return n + 4


def context_window(model_ref: str, settings: Settings) -> int:
    from .hunter import load_hunt

    for c in load_hunt(settings).get("chain", []) + load_hunt(settings).get("rejected", []):
        if c.get("model") == model_ref and c.get("context"):
            return int(c["context"])
    return DEFAULT_CONTEXT.get(model_ref.partition(":")[0].lower(), 32_000)


def _line(m: Message, limit: int = 300) -> str:
    if m.role == "tool":
        return "\n".join(f"  -> {r.name}{' (error)' if r.is_error else ''}: {r.content[:limit]}" for r in m.tool_results)
    who = "Request" if m.role == "user" else "Assistant"
    parts = [f"{who}: {m.text[:limit]}"] if m.text else []
    parts += [f"Assistant called {c.name}({json.dumps(c.arguments)[:120]})" for c in m.tool_calls]
    return "\n".join(parts)


def summarize_messages(messages: list[Message], max_chars: int) -> str:
    """Extractive summary: what was asked, which tools ran and what they returned."""
    lines = [_line(m) for m in messages]
    text = "\n".join(x for x in lines if x)
    if len(text) <= max_chars:
        return text
    # Keep the start (context) and the end (latest state) of the folded part.
    half = max_chars // 2
    return text[:half] + "\n[...]\n" + text[-half:]


def fit(messages: list[Message], budget: int, system: str = "", tools: list[ToolSpec] | None = None) -> list[Message]:
    """Return messages that fit in `budget` tokens (system prompt and tool specs included)."""
    fixed = tokens(system) + sum(tokens(t.name + t.description + json.dumps(t.parameters)) for t in tools or [])
    room = budget - fixed
    if sum(message_tokens(m) for m in messages) <= room or len(messages) < 4:
        return messages
    # The opening request stays verbatim; if the history opens with the assistant, it is folded too.
    head = messages[0] if messages[0].role == "user" else Message(role="user", text="(continuing an earlier conversation)")
    if messages[0].role != "user":
        messages = [head, *messages]
    # Fill from the newest message backwards, leaving a quarter of the room for the summary.
    tail: list[Message] = []
    used = message_tokens(head)
    for m in reversed(messages[1:]):
        cost = message_tokens(m)
        if used + cost > room * 0.75:
            break
        tail.insert(0, m)
        used += cost
    # A tool result needs the assistant turn that called it: start the tail after any orphans.
    while tail and tail[0].role == "tool":
        tail.pop(0)
    folded = messages[1 : len(messages) - len(tail)]
    if not folded:
        return messages
    summary = summarize_messages(folded, max(400, int(room * 0.2) * CHARS_PER_TOKEN))
    note = (f"{head.text}\n\n[Buffer memory: {len(folded)} earlier messages were condensed to fit this model's "
            f"context window. Summary of what happened so far:]\n{summary}\n[End of summary; the latest messages follow.]")
    out = [Message(role="user", text=note), *tail]
    # Keep strict user/assistant alternation for providers that require it.
    if len(out) > 1 and out[1].role == "user":
        out[0] = Message(role="user", text=note + "\n\n" + out[1].text)
        out.pop(1)
    return out
