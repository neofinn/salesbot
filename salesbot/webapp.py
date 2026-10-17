"""Web front-end: chat with the Manager and manage the team from a browser."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .agents import Team
from .commands import run_command

log = logging.getLogger(__name__)
COOKIE = "salesbot_token"
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


def create_app(team: Team) -> FastAPI:
    token = team.settings.web_token

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await team.store.open()
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
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
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
        }

    return app


def serve(team: Team) -> None:
    import uvicorn

    s = team.settings
    if s.web_host not in ("127.0.0.1", "localhost", "::1") and not s.web_token:
        raise SystemExit("Set SALESBOT_WEB_TOKEN before exposing the web app beyond localhost.")
    uvicorn.run(create_app(team), host=s.web_host, port=s.web_port)
