"""Tool definitions: a JSON-schema spec plus an async handler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..llm import ToolSpec
from ..store import Store


@dataclass
class ToolContext:
    settings: Settings
    store: Store
    agent_name: str


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[str]]


class ToolError(Exception):
    """Raised by a handler to report a failure back to the model."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters)


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}
