"""Web front-end: chat with the Manager and manage the team from a browser."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import html
import re
import secrets
import time
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from .agents import Team
from .apps import AppSpec
from .apps.icons import icon_png
from .apps.native import project_zip
from .apps.pwa import SERVICE_WORKER, head_tags, manifest
from .commands import run_command
from .connections import PROVIDER_LABELS
from .llm import Message
from .llm.hunter import hunt, load_hunt
from .media.video import from_dict as video_from_dict
from .media.video import render_mp4

log = logging.getLogger(__name__)
COOKIE = "salesbot_token"
PKCE_COOKIE = "salesbot_or_verifier"
OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"
CHAT_ID = "web"

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MyOps</title>
<style>body{font:15px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f6f7f9;color:#1b1f24}form{background:#fff;padding:28px;border-radius:12px;
box-shadow:0 1px 3px #0002;display:grid;gap:12px;width:min(320px,90vw)}input,button{font:inherit;
padding:10px;border-radius:8px;border:1px solid #ccd}button{background:#2457d6;color:#fff;border:0}
p{color:#b42318;margin:0}</style></head><body><form method="post" action="/login">
<h2 style="margin:0">MyOps</h2>{error}<input type="hidden" name="next" value="{next}"><input type="password" name="token" placeholder="Access token"
autofocus required><button>Sign in</button></form></body></html>"""


class ChatIn(BaseModel):
    text: str


class HireIn(BaseModel):
    job_description: str


class TestIn(BaseModel):
    provider: str


def create_app(team: Team) -> FastAPI:
    token = team.settings.web_token

    async def hunt_daily() -> None:
        """Refresh the free API hunter's picks once a day while the router is in use."""
        while True:
            await asyncio.sleep(60)
            last = load_hunt(team.settings).get("hunted_at")
            if "router" in team.settings.default_model or not last:
                try:
                    stamp = time.mktime(time.strptime(last, "%Y-%m-%d %H:%M UTC")) if last else 0
                    if time.time() - stamp > 86400:
                        await hunt(team.settings, team.gateway)
                except Exception:  # never let the background job take the app down
                    logging.getLogger(__name__).exception("free API hunt failed")
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await team.store.open()
        await team.load_settings()
        task = asyncio.create_task(hunt_daily())
        yield
        task.cancel()
        await team.store.close()

    app = FastAPI(title="MyOps", lifespan=lifespan, docs_url=None, redoc_url=None)

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
            return HTMLResponse(login_page())
        return HTMLResponse(resources.files("salesbot").joinpath("web/index.html").read_text())

    def login_page(error: str = "", next_path: str = "/") -> str:
        return LOGIN_PAGE.replace("{error}", error).replace("{next}", next_path)

    @app.post("/login")
    async def login(token_in: str = Form(alias="token"), next_path: str = Form("/", alias="next")) -> Any:
        # Only redirect within this site.
        next_path = next_path if re.fullmatch(r"/[A-Za-z0-9/_-]*", next_path or "") else "/"
        if not token or not hmac.compare_digest(token_in.encode(), token.encode()):
            return HTMLResponse(login_page("<p>Wrong token.</p>", next_path), status_code=401)
        resp = RedirectResponse(next_path, status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp

    # --- mobile apps: instant install (web app) and native projects ------------

    async def app_spec(slug: str) -> AppSpec:
        data = await team.store.get_app(slug)
        if data is None:
            raise HTTPException(status_code=404, detail="No such app")
        return AppSpec.from_dict(data)

    @app.get("/sw.js")
    async def service_worker() -> Response:
        return Response(SERVICE_WORKER, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})

    @app.get("/app/{slug}/manifest.webmanifest")
    async def app_manifest(slug: str) -> JSONResponse:
        return JSONResponse(manifest(await app_spec(slug)), media_type="application/manifest+json")

    @app.get("/app/{slug}/icon-{size}.png")
    async def app_icon(slug: str, size: int) -> Response:
        if size not in (180, 192, 512):
            raise HTTPException(status_code=404)
        spec = await app_spec(slug)
        return Response(icon_png(size, spec.color, spec.letter), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/app/{slug}", response_class=HTMLResponse)
    async def app_page(slug: str, request: Request) -> Any:
        """The team's web app, branded and installable as this business's app."""
        spec = await app_spec(slug)
        tags = head_tags(spec)
        if not authorized(request):
            return HTMLResponse(login_page(next_path=f"/app/{slug}").replace("<title>MyOps</title>", tags))
        page = resources.files("salesbot").joinpath("web/index.html").read_text()
        page = re.sub(r"<title>.*?</title>", "", page, count=1).replace("</head>", tags + "</head>", 1)
        return HTMLResponse(page.replace("<h1>MyOps</h1>", f"<h1>{html.escape(spec.name)}</h1>", 1))

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

    # --- the Scribe's notes and the Video Producer's videos ----------------------

    @app.get("/api/notes", dependencies=api)
    async def list_notes() -> list[dict[str, Any]]:
        return [await team.store.get_note(n["id"]) for n in await team.store.list_notes()]

    @app.delete("/api/notes/{note_id}", dependencies=api)
    async def delete_note(note_id: int) -> dict[str, bool]:
        if not await team.store.delete_note(note_id):
            raise HTTPException(status_code=404, detail="No such note")
        return {"ok": True}

    @app.get("/api/videos", dependencies=api)
    async def list_videos() -> list[dict[str, Any]]:
        return await team.store.list_videos()

    @app.get("/api/videos/{video_id}.mp4", dependencies=api)
    async def video_file(video_id: int) -> FileResponse:
        video = await team.store.get_video(video_id)
        path = team.video_path(video_id)
        if video is None or not video["file"] or not os.path.exists(path):
            raise HTTPException(status_code=404, detail="No rendered video")
        return FileResponse(path, media_type="video/mp4")

    @app.post("/api/videos/{video_id}/render", dependencies=api)
    async def render_video(video_id: int) -> dict[str, Any]:
        video = await team.store.get_video(video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="No such video")
        try:
            await render_mp4(video_from_dict(video), team.video_path(video_id), video.get("brand", ""))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        await team.store.set_video_file(video_id, f"{video_id}.mp4")
        return await team.store.get_video(video_id)

    @app.delete("/api/videos/{video_id}", dependencies=api)
    async def delete_video(video_id: int) -> dict[str, bool]:
        if not await team.store.delete_video(video_id):
            raise HTTPException(status_code=404, detail="No such video")
        try:
            os.remove(team.video_path(video_id))
        except FileNotFoundError:
            pass
        return {"ok": True}

    # --- API router and free API hunter ---------------------------------------

    @app.get("/api/apps", dependencies=api)
    async def list_apps(request: Request) -> list[dict[str, Any]]:
        return [team.app_links(AppSpec.from_dict(a), base_url(request)) for a in await team.store.list_apps()]

    @app.get("/api/apps/{slug}/native.zip", dependencies=api)
    async def app_native(slug: str, request: Request) -> Response:
        spec = await app_spec(slug)
        try:
            data = project_zip(spec, spec.server_url or base_url(request))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{slug}-native.zip"'})

    def base_url(request: Request) -> str:
        return team.settings.public_url or str(request.base_url).rstrip("/")

    @app.get("/api/router", dependencies=api)
    async def router_status() -> dict[str, Any]:
        hunted = load_hunt(team.settings)
        return {**team.gateway.provider("router").status(), "hunt": hunted,
                "explicit": bool(team.settings.router_models.strip()), "prefer": team.settings.router_prefer}

    @app.post("/api/router/hunt", dependencies=api)
    async def router_hunt() -> dict[str, Any]:
        await hunt(team.settings, team.gateway)
        return await router_status()

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
