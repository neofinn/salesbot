"""Lets a bot look up the code book: rules, templates and pitfalls for a language."""

from __future__ import annotations

from typing import Any

from .. import codebook
from .base import Tool, ToolContext, ToolError, schema


async def _lookup(args: dict[str, Any], ctx: ToolContext) -> str:
    name = str(args.get("language") or "").strip().lower()
    aliases = {"js": "javascript", "node": "javascript", "ts": "typescript", "html": "html-css", "css": "html-css",
               "shell": "bash", "sh": "bash", "postgres": "sql", "sqlite": "sql", "mysql": "sql", "py": "python"}
    name = aliases.get(name, name)
    text = codebook.chapter(name)
    if not text:
        raise ToolError(f"No chapter for {name!r}. Chapters: {', '.join(codebook.chapters())}.")
    return text


CODE_REFERENCE = Tool(
    "code_reference",
    "Read the code book: rules, ready-to-use templates and common pitfalls for a language, or the 'method' "
    "chapter (step-by-step routine and self-check for writing code that works first time).",
    schema({"language": {"type": "string", "enum": codebook.chapters()}}, ["language"]),
    _lookup,
)
