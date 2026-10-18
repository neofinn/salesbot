import json

import httpx
import pytest

from salesbot.config import Settings
from salesbot.llm import LLMError, LLMGateway, LLMResponse, Message
from salesbot.llm import hunter as hunter_mod
from salesbot.llm.router import classify


class RateLimited(Exception):
    status_code = 429


class Scripted:
    """A provider whose models succeed, rate-limit or fail on demand, and call the probe tool."""

    def __init__(self, name, behaviour):
        self.name, self.behaviour, self.calls = name, behaviour, []

    async def complete(self, model, system, messages, tools):
        self.calls.append(model)
        b = self.behaviour.get(model, "ok")
        if b == "429":
            raise RateLimited("Rate limit reached, retry in 20s")
        if b == "auth":
            raise RuntimeError("401 invalid api key")
        if b == "boom":
            raise RuntimeError("server exploded")
        from salesbot.llm import ToolCall

        calls = [ToolCall(id="1", name=t.name, arguments={"answer": "5"}) for t in tools][:1]
        return LLMResponse(Message(role="assistant", text=f"hi from {model}", tool_calls=calls))


def gateway(tmp_path, chain, behaviour):
    gw = LLMGateway(Settings(data_dir=str(tmp_path), router_models=chain))
    gw.register(Scripted("fake", behaviour))
    return gw


def test_classify():
    assert classify(RateLimited("Rate limit reached, retry in 20s")) == ("rate_limited", 20.0)
    assert classify(RuntimeError("RESOURCE_EXHAUSTED quota"))[0] == "rate_limited"
    assert classify(RuntimeError("401 Unauthorized"))[0] == "auth"
    assert classify(RuntimeError("boom"))[0] == "error"


async def test_router_falls_back_and_cools_down(tmp_path):
    gw = gateway(tmp_path, "fake:a, fake:b, fake:c", {"a": "429", "b": "boom"})
    r = await gw.complete("router", "sys", [Message(role="user", text="x")], [])
    assert r.text == "hi from c"
    fake = gw.provider("fake")
    assert fake.calls == ["a", "b", "c"]
    # a and b are cooling down: the next request goes straight to c.
    await gw.complete("router", "sys", [Message(role="user", text="x")], [])
    assert fake.calls[-1] == "c" and fake.calls.count("a") == 1
    status = {c["model"]: c for c in gw.provider("router").status()["chain"]}
    assert status["fake:a"]["cooldown_seconds"] > 0 and "rate_limited" in status["fake:a"]["last_error"]
    assert status["fake:c"]["ok"] == 2


async def test_router_all_failing_and_empty(tmp_path):
    gw = gateway(tmp_path, "fake:a, fake:b", {"a": "auth", "b": "429"})
    with pytest.raises(LLMError, match="Every model"):
        await gw.complete("router", "sys", [Message(role="user", text="x")], [])
    empty = gateway(tmp_path, "", {})
    with pytest.raises(LLMError, match="no models"):
        await empty.complete("router", "sys", [Message(role="user", text="x")], [])
    assert "router" not in empty.available()


async def test_hunter_finds_probes_and_saves_chain(tmp_path, monkeypatch):
    models = {"data": [
        {"id": "qwen/qwen3-coder:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"], "context_length": 262144},
        {"id": "some/notools:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": [], "context_length": 131072},
        {"id": "paid/model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "supported_parameters": ["tools"], "context_length": 131072},
    ]}
    gem = {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
    ]}

    async def fake_get(self, url, params=None, headers=None):
        req = httpx.Request("GET", url)
        if "openrouter" in url:
            return httpx.Response(200, json=models, request=req)
        if "generativelanguage" in url:
            return httpx.Response(200, json=gem, request=req)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("salesbot.llm.claude_code_provider.cli_available", lambda: False)
    settings = Settings(data_dir=str(tmp_path), openrouter_api_key="k", gemini_api_key="g", anthropic_api_key="a")
    gw = LLMGateway(settings)
    beh = {"qwen/qwen3-coder:free": "ok", "gemini-2.5-flash": "429", "claude-opus-5-5": "ok"}
    for name in ("openrouter", "gemini", "anthropic"):
        gw.register(Scripted(name, beh))
    result = await hunter_mod.hunt(settings, gw)
    models_in_chain = [c["model"] for c in result["chain"]]
    assert models_in_chain == ["openrouter:qwen/qwen3-coder:free", "anthropic"]  # free first, paid last
    assert result["rejected"][0]["model"] == "gemini:gemini-2.5-flash" and "rate_limited" in result["rejected"][0]["error"]
    assert any("Groq" in n for n in result["notes"])
    assert json.load(open(tmp_path / "router.json"))["chain"][0]["model"] == models_in_chain[0]
    # The router now uses the hunted chain.
    r = await gw.complete("router", "sys", [Message(role="user", text="x")], [])
    assert r.text == "hi from qwen/qwen3-coder:free"
    # Quality-first puts your own accounts ahead of the free models.
    settings.router_prefer = "quality"
    again = await hunter_mod.hunt(settings, gw)
    assert [c["model"] for c in again["chain"]][0] == "anthropic"


def test_router_endpoints_and_settings(tmp_path, monkeypatch):
    from .test_webapp import make_client

    async def fake_hunt(settings, gw):
        result = {"hunted_at": "2026-10-18 10:00 UTC", "prefer": "free", "chain": [{"model": "fake:free1", "source": "test", "free": True}], "rejected": [], "notes": []}
        (tmp_path / "router.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr("salesbot.webapp.hunt", fake_hunt)
    client, _ = make_client(tmp_path)
    with client:
        assert client.get("/api/router").json()["chain"] == []
        body = client.post("/api/router/hunt").json()
        assert [c["model"] for c in body["chain"]] == ["fake:free1"] and body["hunt"]["hunted_at"]
        assert client.put("/api/connections", json={"router_prefer": "sideways"}).status_code == 400
        assert client.put("/api/connections", json={"router_models": "fake:a, fake:b", "groq_api_key": "gsk_123"}).status_code == 200
        r = client.get("/api/router").json()
        assert r["explicit"] and [c["model"] for c in r["chain"]] == ["fake:a", "fake:b"]
        names = {p["name"]: p["connected"] for p in client.get("/api/connections").json()["providers"]}
        assert names["groq"] and names["router"]
