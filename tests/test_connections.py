import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from salesbot import connections
from salesbot.config import Settings

from .test_webapp import make_client


def test_apply_layers_saved_values_and_picks_model():
    base = Settings(default_model_auto=True, default_model="anthropic:claude-opus-5-5")
    s = connections.apply(base, {"openrouter_api_key": "sk-or-abc", "smtp_port": "465", "require_approval": "false"})
    assert s.openrouter_api_key == "sk-or-abc" and s.smtp_port == 465 and s.require_approval is False
    assert s.default_model == "openrouter:openrouter/auto"  # no Claude key or CLI in tests
    assert connections.apply(base, {"anthropic_api_key": "sk-ant-x"}).default_model == "anthropic:claude-opus-5-5"
    pinned = connections.apply(base, {"openrouter_api_key": "k", "default_model": "xai:grok-4"})
    assert pinned.default_model == "xai:grok-4"
    assert base.openrouter_api_key == ""  # base settings untouched


def test_validate_and_describe_never_leak_secrets():
    assert connections.validate({"smtp_port": "587", "openai_api_key": "  ", "require_approval": "on"}) == {
        "smtp_port": "587", "openai_api_key": None, "require_approval": "true"}
    with pytest.raises(ValueError, match="Unknown setting"):
        connections.validate({"web_token": "x"})
    with pytest.raises(ValueError, match="SMTP port"):
        connections.validate({"smtp_port": "abc"})
    fields = {f["key"]: f for f in connections.describe(Settings(openai_api_key="sk-1234567890abcdef"), {"openai_api_key": "x"})}
    assert fields["openai_api_key"] == {**fields["openai_api_key"], "set": True, "hint": "sk-12…cdef", "source": "saved"}
    assert "value" not in fields["openai_api_key"]
    assert fields["smtp_port"]["value"] == 587


def test_save_test_and_clear_connection(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        data = client.put("/api/connections", json={"openai_api_key": "sk-1234567890abcdef", "smtp_host": "smtp.example.com"}).json()
        fields = {f["key"]: f for f in data["fields"]}
        assert fields["openai_api_key"]["hint"] == "sk-12…cdef" and "sk-1234567890abcdef" not in str(data)
        assert fields["smtp_host"]["value"] == "smtp.example.com"
        assert {p["name"]: p["connected"] for p in data["providers"]}["openai"] is True
        assert client.get("/api/status").json()["email"] is True
        assert client.put("/api/connections", json={"bogus": 1}).status_code == 400

        assert client.post("/api/connections/test", json={"provider": "fake"}).status_code == 400
        res = client.post("/api/connections/test", json={"provider": "xai"}).json()
        assert res["ok"] is False and "XAI_API_KEY" in res["error"]

        data = client.put("/api/connections", json={"openai_api_key": None}).json()
        assert {p["name"]: p["connected"] for p in data["providers"]}["openai"] is False


def test_openrouter_sign_in(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    exchanged = {}

    async def fake_post(self, url, json=None, **kwargs):
        exchanged.update(url=url, body=json)
        return httpx.Response(200, json={"key": "sk-or-v1-from-oauth-0000"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with client:
        start = client.get("/connect/openrouter", follow_redirects=False)
        assert start.status_code == 303
        target = urlparse(start.headers["location"])
        q = parse_qs(target.query)
        assert target.netloc == "openrouter.ai" and q["code_challenge_method"] == ["S256"]
        assert q["callback_url"] == ["http://testserver/connect/openrouter/callback"]
        verifier = client.cookies.get("salesbot_or_verifier")
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert q["code_challenge"] == [expected]

        done = client.get("/connect/openrouter/callback?code=abc", follow_redirects=False)
        assert done.headers["location"] == "/?connect=openrouter-ok"
        assert exchanged["body"] == {"code": "abc", "code_verifier": verifier, "code_challenge_method": "S256"}
        providers = {p["name"]: p["connected"] for p in client.get("/api/connections").json()["providers"]}
        assert providers["openrouter"] is True

        client.cookies.clear()
        assert client.get("/connect/openrouter/callback?code=abc", follow_redirects=False).headers["location"] == "/?connect=openrouter-failed"
