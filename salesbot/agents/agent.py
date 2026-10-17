"""A single bot employee: a role prompt, a model and a set of tools."""

from __future__ import annotations

import asyncio
import json
import logging

from ..config import Settings
from ..llm import LLMGateway, Message, ToolResult
from ..store import AgentSpec, Store
from ..tools import Tool, ToolContext, ToolError

log = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        spec: AgentSpec,
        tools: list[Tool],
        gateway: LLMGateway,
        settings: Settings,
        store: Store,
    ) -> None:
        self.spec = spec
        self.tools = {t.name: t for t in tools}
        self.gateway = gateway
        self.settings = settings
        self.store = store

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, task: str, history: list[Message] | None = None) -> str:
        """Work on a task, calling tools as needed, and return the final answer."""
        messages: list[Message] = [*(history or []), Message(role="user", text=task)]
        specs = [t.spec for t in self.tools.values()]
        ctx = ToolContext(settings=self.settings, store=self.store, agent_name=self.name)

        for step in range(self.settings.max_agent_steps):
            response = await self.gateway.complete(self.spec.model, self.spec.system_prompt, messages, specs)
            messages.append(response.message)
            if not response.tool_calls:
                return response.text.strip() or "(no response)"
            log.info("%s step %d: %s", self.name, step, [c.name for c in response.tool_calls])
            results = await asyncio.gather(*(self._call(c.id, c.name, c.arguments, ctx) for c in response.tool_calls))
            messages.append(Message(role="tool", tool_results=list(results)))

        return f"{self.name} stopped after {self.settings.max_agent_steps} steps without finishing."

    async def _call(self, call_id: str, name: str, arguments: dict, ctx: ToolContext) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(call_id, name, f"Unknown tool {name!r}.", is_error=True)
        try:
            return ToolResult(call_id, name, await tool.handler(dict(arguments), ctx))
        except ToolError as exc:
            return ToolResult(call_id, name, str(exc), is_error=True)
        except (KeyError, TypeError, ValueError) as exc:
            return ToolResult(call_id, name, f"Bad arguments {json.dumps(arguments)}: {exc}", is_error=True)
        except Exception as exc:  # report tool crashes to the model instead of killing the run
            log.exception("tool %s failed", name)
            return ToolResult(call_id, name, f"{type(exc).__name__}: {exc}", is_error=True)
