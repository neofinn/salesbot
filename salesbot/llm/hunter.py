"""Free API hunter: finds models this server can use for free, checks they really work
(including tool calling, which the agents need) and builds the API router's chain.

Sources: OpenRouter's free models (needs a free OpenRouter key), Google Gemini's free tier,
Groq's free tier, a local Ollama server, and the signed-in Claude Code CLI. API keys you
pay for are added after the free models as a last resort.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import TYPE_CHECKING, Any

import httpx

from .base import Message, ToolSpec

if TYPE_CHECKING:
    from ..config import Settings
    from . import LLMGateway

# Model families that handle agent tool calling well, best first.
STRONG = ["qwen3", "deepseek", "gpt-oss", "kimi", "glm", "llama-3.3-70b", "llama-4", "gemini", "mistral", "qwen"]
PROBE_TOOL = ToolSpec("record_answer", "Record the answer.", {
    "type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]})
MAX_PROBES = 10


def hunt_path(settings: Settings) -> str:
    return os.path.join(settings.data_dir, "router.json")


def load_hunt(settings: Settings) -> dict[str, Any]:
    try:
        with open(hunt_path(settings)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _family_rank(model_id: str) -> int:
    m = model_id.lower()
    return next((i for i, f in enumerate(STRONG) if f in m), len(STRONG))


async def _openrouter_free(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get("https://openrouter.ai/api/v1/models")
    resp.raise_for_status()
    out = []
    for m in resp.json().get("data", []):
        price = m.get("pricing", {})
        if str(price.get("prompt")) not in ("0", "0.0") or str(price.get("completion")) not in ("0", "0.0"):
            continue
        if "tools" not in (m.get("supported_parameters") or []) or (m.get("context_length") or 0) < 32000:
            continue
        out.append({"model": f"openrouter:{m['id']}", "source": "OpenRouter free", "free": True,
                    "context": m.get("context_length"), "rank": (_family_rank(m["id"]), -(m.get("context_length") or 0))})
    return sorted(out, key=lambda c: c["rank"])[:4]


async def _gemini_free(client: httpx.AsyncClient, key: str) -> list[dict[str, Any]]:
    resp = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key, "pageSize": 200})
    resp.raise_for_status()
    names = []
    for m in resp.json().get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if ("flash" in name and "generateContent" in m.get("supportedGenerationMethods", [])
                and not re.search(r"image|tts|audio|live|exp|preview|thinking|embedding", name)):
            names.append(name)

    def version(n: str) -> tuple:
        v = re.search(r"(\d+(?:\.\d+)?)", n)
        return (float(v.group(1)) if v else 0, "lite" not in n)

    names.sort(key=version, reverse=True)
    return [{"model": f"gemini:{n}", "source": "Gemini free tier", "free": True, "rank": (i,)} for i, n in enumerate(names[:2])]


async def _groq_free(client: httpx.AsyncClient, key: str) -> list[dict[str, Any]]:
    resp = await client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
    resp.raise_for_status()
    ids = [m["id"] for m in resp.json().get("data", []) if not re.search(r"whisper|guard|tts|playai|prompt|distil|compound", m["id"])]
    ids.sort(key=_family_rank)
    return [{"model": f"groq:{i}", "source": "Groq free tier", "free": True, "rank": (n,)} for n, i in enumerate(ids[:3])]


async def _ollama_local(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    resp = await client.get(url.rstrip("/") + "/api/tags")
    resp.raise_for_status()
    names = sorted((m["name"] for m in resp.json().get("models", [])), key=_family_rank)
    return [{"model": f"ollama:{n}", "source": "Ollama (this server)", "free": True, "rank": (i,)} for i, n in enumerate(names[:2])]


async def probe(gateway: LLMGateway, ref: str, timeout: float = 60) -> dict[str, Any]:
    """One tiny request that must come back as a tool call: proves the key, quota and tool support."""
    started = time.time()
    try:
        r = await asyncio.wait_for(gateway.complete(
            ref, "You are a test. Always answer by calling the record_answer tool.",
            [Message(role="user", text="What is 2 + 3? Call record_answer with the result.")], [PROBE_TOOL]), timeout)
    except Exception as exc:  # report every failure as data, never stop the hunt
        from .router import classify

        return {"ok": False, "tools": False, "error": f"{classify(exc)[0]}: {str(exc)[:160]}"}
    called = any(c.name == "record_answer" for c in r.tool_calls)
    return {"ok": True, "tools": called, "latency_s": round(time.time() - started, 2),
            "answer_ok": called and "5" in json.dumps([c.arguments for c in r.tool_calls])}


async def hunt(settings: Settings, gateway: LLMGateway) -> dict[str, Any]:
    """Discover, probe and rank. Saves the result where the router reads it."""
    from .claude_code_provider import cli_available

    found: list[dict[str, Any]] = []
    notes: list[str] = []
    async with httpx.AsyncClient(timeout=20) as client:
        jobs = {"OpenRouter": _openrouter_free(client)}
        if settings.gemini_api_key:
            jobs["Gemini"] = _gemini_free(client, settings.gemini_api_key)
        else:
            notes.append("Gemini: add a free key from aistudio.google.com to include its free tier.")
        if settings.groq_api_key:
            jobs["Groq"] = _groq_free(client, settings.groq_api_key)
        else:
            notes.append("Groq: add a free key from console.groq.com to include its free tier.")
        if settings.ollama_url:
            jobs["Ollama"] = _ollama_local(client, settings.ollama_url)
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, results):
        if isinstance(res, Exception):
            notes.append(f"{name}: could not list models ({str(res)[:120]}).")
        else:
            found.extend(res)
    if any(c["model"].startswith("openrouter:") for c in found) and not settings.openrouter_api_key:
        notes.append("OpenRouter has free models, but using them needs a free OpenRouter key (or Sign in with OpenRouter).")
        found = [c for c in found if not c["model"].startswith("openrouter:")]

    own: list[dict[str, Any]] = []
    if cli_available():
        own.append({"model": "claude_code", "source": "your Claude account (Claude Code)", "free": False})
    for p in ("anthropic", "openai", "xai"):
        if getattr(settings, f"{p}_api_key", ""):
            own.append({"model": p, "source": f"your {p} API key (paid)", "free": False})

    to_probe = (found + own)[:MAX_PROBES]
    probes = await asyncio.gather(*(probe(gateway, c["model"]) for c in to_probe))
    for c, p in zip(to_probe, probes):
        c.update(p)
        c.pop("rank", None)
    working = [c for c in to_probe if c.get("ok") and c.get("tools")]
    free = sorted((c for c in working if c["free"]), key=lambda c: c.get("latency_s") or 99)
    paid = [c for c in working if not c["free"]]
    chain = paid + free if settings.router_prefer == "quality" else free + paid
    result = {"hunted_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "prefer": settings.router_prefer,
              "chain": chain, "rejected": [c for c in to_probe if c not in working], "notes": notes}
    os.makedirs(settings.data_dir, exist_ok=True)
    with open(hunt_path(settings), "w") as fh:
        json.dump(result, fh, indent=2)
    return result
