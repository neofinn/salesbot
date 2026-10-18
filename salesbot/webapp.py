"""Web front-end: chat with the Manager and manage the team from a browser."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .agents import Team
from .commands import run_command
from .connections import PROVIDER_LABELS
from .llm import Message

log = logging.getLogger(__name__)
COOKIE = "salesbot_token"
PKCE_COOKIE = "salesbot_or_verifier"
OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"
CHAT_ID = "web"

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>salesbot</title>
<style>body{font:15px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f6f7f9;color:#1b1f24}form{background:#fff;padding:28px;border-radius:12px;
box-shadow:0 1px 3px #0002;display:grid;gap:12px;width:min(320px,90vw)}input,button{font:inherit;
padding:10px;border-radius:8px;border:1px solid #ccd}button{background:#2457d6;color:#fff;border:0}
p{color:#b42318;margin:0}</style></head><body><form method="post" action="/login">
<h2 style="margin:0">salesbot</h2>{error}<input type="password" name="token" placeholder="Access token"
autofocus required><button>Sign in</button></form></body></html>"""


class ChatIn(BaseModel):
    text: str


class HireIn(BaseModel):
    job_description: str


class TestIn(BaseModel):
    provider: str


def create_app(team: Team) -> FastAPI:
    token = team.settings.web_token

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await team.store.open()
        await team.load_settings()
        yield
        await team.store.close()

    app = FastAPI(title="salesbot", lifespan=lifespan, docs_url=None, redoc_url=None)

    def authorized(request: Request) -> bool:
        if not token:
            return True
        supplied = request.cookies.get(COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ")
        return hmac.compare_digest(supplied.encode(), token.encode())

    def require_auth(request: Request) -> None:
        if not authorized(request):
            raise HTTPException(status_code=401, detail="Not signed in")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        if not authorized(request):
            return HTMLResponse(LOGIN_PAGE.replace("{error}", ""))
        return HTMLResponse(resources.files("salesbot").joinpath("web/index.html").read_text())

    @app.post("/login")
    async def login(token_in: str = Form(alias="token")) -> Any:
        if not token or not hmac.compare_digest(token_in.encode(), token.encode()):
            return HTMLResponse(LOGIN_PAGE.replace("{error}", "<p>Wrong token.</p>"), status_code=401)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp

    @app.post("/logout")
    async def logout() -> Any:
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    api = [Depends(require_auth)]

    @app.get("/api/history", dependencies=api)
    async def history() -> list[dict[str, str]]:
        return [{"role": r, "text": t} for r, t in await team.store.recent_chat(CHAT_ID, limit=100)]

    @app.post("/api/chat", dependencies=api)
    async def chat(body: ChatIn) -> dict[str, str]:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Empty message")
        try:
            reply = await run_command(team, CHAT_ID, text)
            if reply is None:
                reply = await team.handle(CHAT_ID, text)
        except Exception as exc:
            log.exception("chat failed")
            reply = f"Something went wrong: {type(exc).__name__}: {exc}"
        return {"reply": reply}

    @app.get("/api/team", dependencies=api)
    async def roster() -> list[dict[str, Any]]:
        return [
            {"name": b.name, "role": b.role, "model": b.model, "tools": b.tools} for b in await team.roster()
        ]

    @app.post("/api/team/hire", dependencies=api)
    async def hire(body: HireIn) -> dict[str, str]:
        return {"result": await team.hire(body.job_description)}

    @app.post("/api/team/{name}/fire", dependencies=api)
    async def fire(name: str) -> dict[str, str]:
        return {"result": await team.fire(name)}

    @app.get("/api/pending", dependencies=api)
    async def pending() -> list[dict[str, Any]]:
        return await team.store.list_pending()

    @app.post("/api/pending/{action_id}/approve", dependencies=api)
    async def approve(action_id: int) -> dict[str, str]:
        return {"result": await team.approve(action_id)}

    @app.post("/api/pending/{action_id}/reject", dependencies=api)
    async def reject(action_id: int) -> dict[str, str]:
        return {"result": await team.reject(action_id)}

    @app.get("/api/leads", dependencies=api)
    async def leads(q: str = "", status: str = "") -> list[dict[str, Any]]:
        return await team.store.find_leads(q, status, limit=500)

    @app.get("/api/status", dependencies=api)
    async def status() -> dict[str, Any]:
        s = team.settings
        return {
            "default_model": s.default_model,
            "providers": team.gateway.configured(),
            "require_approval": s.require_approval,
            "email": bool(s.smtp_host),
            "sms": bool(s.twilio_account_sid),
            "web_search": bool(s.brave_api_key),
            "openclaw": bool(s.openclaw_url and s.openclaw_token),
        }

    # --- connections ----------------------------------------------------------

    @app.get("/api/connections", dependencies=api)
    async def get_connections() -> dict[str, Any]:
        configured = set(team.gateway.configured())
        return {
            "fields": await team.describe_settings(),
            "providers": [
                {"name": name, "label": label, "connected": name in configured}
                for name, label in PROVIDER_LABELS.items()
            ],
            "default_model": team.settings.default_model,
            "default_model_auto": team.base_settings.default_model_auto,
        }

    @app.put("/api/connections", dependencies=api)
    async def put_connections(values: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            await team.save_settings(values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await get_connections()

    @app.post("/api/connections/test", dependencies=api)
    async def test_connection(body: TestIn) -> dict[str, Any]:
        if body.provider not in PROVIDER_LABELS:
            raise HTTPException(status_code=400, detail="Unknown provider")
        try:
            resp = await asyncio.wait_for(
                team.gateway.complete(
                    body.provider,
                    "You are a connection test. Reply with exactly: OK",
                    [Message(role="user", text="ping")],
                    [],
                ),
                timeout=120,
            )
        except Exception as exc:  # report any provider failure to the UI
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
        return {"ok": True, "reply": resp.text[:200]}

    @app.get("/connect/openrouter", dependencies=api)
    async def connect_openrouter(request: Request) -> Any:
        """Start OpenRouter's OAuth (PKCE) sign-in; it returns an API key for this app."""
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        callback = str(request.url_for("openrouter_callback"))
        url = httpx.URL(
            OPENROUTER_AUTH,
            params={"callback_url": callback, "code_challenge": challenge, "code_challenge_method": "S256"},
        )
        resp = RedirectResponse(str(url), status_code=303)
        resp.set_cookie(PKCE_COOKIE, verifier, httponly=True, samesite="lax", max_age=600)
        return resp

    @app.get("/connect/openrouter/callback", name="openrouter_callback", dependencies=api)
    async def openrouter_callback(request: Request, code: str = "") -> Any:
        verifier = request.cookies.get(PKCE_COOKIE, "")
        if not code or not verifier:
            return RedirectResponse("/?connect=openrouter-failed", status_code=303)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                OPENROUTER_KEYS,
                json={"code": code, "code_verifier": verifier, "code_challenge_method": "S256"},
            )
        key = r.json().get("key") if r.status_code < 400 else None
        if not key:
            log.warning("OpenRouter key exchange failed: %s %s", r.status_code, r.text[:200])
            return RedirectResponse("/?connect=openrouter-failed", status_code=303)
        await team.save_settings({"openrouter_api_key": key})
        resp = RedirectResponse("/?connect=openrouter-ok", status_code=303)
        resp.delete_cookie(PKCE_COOKIE)
        return resp

    return app


def serve(team: Team) -> None:
    import uvicorn

    s = team.settings
    if s.web_host not in ("127.0.0.1", "localhost", "::1") and not s.web_token:
        raise SystemExit("Set SALESBOT_WEB_TOKEN before exposing the web app beyond localhost.")
    # Trust X-Forwarded-* from the hosting platform's proxy so OAuth callback URLs use https.
    uvicorn.run(create_app(team), host=s.web_host, port=s.web_port, proxy_headers=True, forwarded_allow_ips="*")
