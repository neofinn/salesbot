from fastapi.testclient import TestClient

from salesbot.agents import Team
from salesbot.config import Settings
from salesbot.llm import LLMGateway
from salesbot.store import Store
from salesbot.webapp import create_app

from .conftest import FakeProvider


def make_client(tmp_path, token=""):
    settings = Settings(default_model="fake:test", data_dir=str(tmp_path), web_token=token)
    gateway = LLMGateway(settings)
    fake = FakeProvider()
    gateway.register(fake)
    team = Team(settings, Store(":memory:"), gateway)
    return TestClient(create_app(team)), fake


def test_requires_token_when_configured(tmp_path):
    client, _ = make_client(tmp_path, token="s3cret")
    with client:
        assert "Access token" in client.get("/").text
        assert client.get("/api/team").status_code == 401
        assert client.post("/login", data={"token": "wrong"}).status_code == 401
        resp = client.post("/login", data={"token": "s3cret"}, follow_redirects=False)
        assert resp.status_code == 303
        assert client.get("/api/team").json() == []
        assert "Tell the Manager" in client.get("/").text
        client.cookies.clear()
        assert client.get("/api/team").status_code == 401
        assert client.get("/api/team", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_chat_commands_and_approvals(tmp_path):
    client, fake = make_client(tmp_path)
    fake.script("the Manager", ("Hello! The team is empty.", []))
    with client:
        assert client.post("/api/chat", json={"text": "hi"}).json() == {"reply": "Hello! The team is empty."}
        assert "No worker bots" in client.post("/api/chat", json={"text": "/team"}).json()["reply"]
        assert client.get("/api/history").json()[:2] == [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "Hello! The team is empty."},
        ]
        assert client.get("/api/status").json()["providers"] == ["fake"]  # registered provider counts as configured
        assert client.get("/api/pending").json() == []
        assert client.post("/api/pending/1/reject").json() == {"result": "No pending action #1."}
        assert client.post("/api/team/manager/fire").json() == {"result": "manager is core staff and can't be fired."}
        assert client.post("/api/chat", json={"text": "  "}).status_code == 400
