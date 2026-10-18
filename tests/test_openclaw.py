import httpx
import pytest

from salesbot.config import Settings
from salesbot.tools import CATALOG, ToolContext, ToolError

TOOL = CATALOG["openclaw_browse"]


def ctx(**kw):
    return ToolContext(settings=Settings(**kw), store=None, agent_name="researcher")


async def test_sends_task_to_gateway_and_returns_answer(monkeypatch):
    seen = {}

    async def fake_post(self, url, json=None, headers=None):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Acme opened a NJ warehouse (https://acme.example/news)"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = await TOOL.handler({"task": "What is new at Acme?"}, ctx(openclaw_url="http://127.0.0.1:18789/", openclaw_token="tok", openclaw_agent="scout"))
    assert out.startswith("Acme opened")
    assert seen["url"] == "http://127.0.0.1:18789/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["json"]["model"] == "openclaw:scout"
    assert seen["json"]["user"] == "myops:researcher"
    assert seen["json"]["messages"][0]["role"] == "system" and "Research only" in seen["json"]["messages"][0]["content"]
    assert seen["json"]["messages"][1] == {"role": "user", "content": "What is new at Acme?"}


@pytest.mark.parametrize(("status", "message"), [(401, "rejected the token"), (404, "endpoint is off"), (500, "error 500")])
async def test_gateway_errors_are_explained(monkeypatch, status, message):
    async def fake_post(self, url, json=None, headers=None):
        return httpx.Response(status, text="nope")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(ToolError, match=message):
        await TOOL.handler({"task": "x"}, ctx(openclaw_url="http://gw", openclaw_token="t"))


async def test_not_connected():
    with pytest.raises(ToolError, match="not connected"):
        await TOOL.handler({"task": "x"}, ctx())


async def test_manager_gets_openclaw_only_when_connected(team):
    assert "openclaw_browse" not in team.manager().tools
    team.settings.openclaw_url, team.settings.openclaw_token = "http://gw", "t"
    assert "openclaw_browse" in team.manager().tools
