from __future__ import annotations

from collections import defaultdict, deque

import pytest

from salesbot.agents import Team
from salesbot.config import Settings
from salesbot.llm import LLMGateway, LLMResponse, Message, ToolCall
from salesbot.store import Store


class FakeProvider:
    """Scripted LLM: replies are queued per agent, keyed by a system-prompt marker."""

    name = "fake"

    def __init__(self) -> None:
        self.scripts: dict[str, deque] = defaultdict(deque)
        self.calls: list[tuple[str, list[Message], list[str]]] = []

    def script(self, marker: str, *replies: tuple[str, list[tuple[str, dict]]]) -> None:
        for text, calls in replies:
            self.scripts[marker].append((text, calls))

    async def complete(self, model, system, messages, tools):
        self.calls.append((system, list(messages), [t.name for t in tools]))
        for marker, queue in self.scripts.items():
            if marker in system and queue:
                text, calls = queue.popleft()
                tool_calls = [ToolCall(id=f"c{len(self.calls)}_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)]
                return LLMResponse(Message(role="assistant", text=text, tool_calls=tool_calls))
        raise AssertionError(f"No scripted reply for system prompt: {system[:60]!r}")


@pytest.fixture(autouse=True)
def no_claude_cli(monkeypatch):
    """Keep tests independent of whether the Claude Code CLI is installed."""
    monkeypatch.setenv("CLAUDE_CLI", "salesbot-test-missing-claude")


@pytest.fixture
def settings(tmp_path):
    return Settings(default_model="fake:test", data_dir=str(tmp_path), require_approval=True)


@pytest.fixture
async def team(settings):
    store = await Store(":memory:").open()
    gateway = LLMGateway(settings)
    gateway.register(FakeProvider())
    yield Team(settings, store, gateway)
    await store.close()


@pytest.fixture
def fake(team) -> FakeProvider:
    return team.gateway.provider("fake")
