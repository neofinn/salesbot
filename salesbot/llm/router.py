"""API router: one model reference ("router") that tries a chain of models in order.

A model that is rate-limited, out of quota or failing is put on cooldown and the
request moves to the next one, so free tiers can be stacked and paid accounts kept
as the last resort. The chain comes from settings (router_models) or, when that is
empty, from the free API hunter's last run.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import LLMError, LLMResponse, Message, ToolSpec

if TYPE_CHECKING:
    from . import LLMGateway

log = logging.getLogger(__name__)

RATE_LIMIT_COOLDOWN = 90.0
AUTH_COOLDOWN = 3600.0
ERROR_COOLDOWN = 30.0


@dataclass
class RouteStats:
    ok: int = 0
    failed: int = 0
    last_error: str = ""
    last_used: float = 0.0
    cooldown_until: float = 0.0
    latencies: list[float] = field(default_factory=list)

    def as_dict(self, now: float) -> dict:
        return {
            "ok": self.ok,
            "failed": self.failed,
            "last_error": self.last_error,
            "last_used": self.last_used,
            "cooldown_seconds": max(0, round(self.cooldown_until - now)),
            "avg_latency_s": round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else None,
        }


def classify(exc: Exception) -> tuple[str, float]:
    """Return (kind, cooldown seconds) for a provider error."""
    text = f"{type(exc).__name__} {exc}".lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or re.search(r"rate.?limit|quota|resource.?exhausted|too many requests|429", text):
        retry = re.search(r"retry.{0,20}?(\d+(?:\.\d+)?)\s*s", text)
        return "rate_limited", min(max(float(retry.group(1)), 10.0), 3600.0) if retry else RATE_LIMIT_COOLDOWN
    if status in (401, 403) or re.search(r"unauthori[sz]ed|invalid api key|permission|forbidden|no api key|401|403", text):
        return "auth", AUTH_COOLDOWN
    return "error", ERROR_COOLDOWN


class RouterProvider:
    name = "router"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway
        self.stats: dict[str, RouteStats] = {}

    def chain(self) -> list[str]:
        from .hunter import load_hunt

        explicit = [m.strip() for m in self.gateway.settings.router_models.split(",") if m.strip()]
        if explicit:
            return [m for m in explicit if not m.startswith("router")]
        hunted = load_hunt(self.gateway.settings)
        return [c["model"] for c in hunted.get("chain", [])]

    def status(self) -> dict:
        now = time.time()
        return {"chain": [{"model": m, **self.stats.get(m, RouteStats()).as_dict(now)} for m in self.chain()]}

    async def complete(self, model: str, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        chain = [model] if model else self.chain()
        if not chain:
            raise LLMError("The API router has no models. Run the free API hunter or set ROUTER_MODELS.")
        now = time.time()
        ready = [m for m in chain if self.stats.get(m, RouteStats()).cooldown_until <= now]
        # Everything cooling down: try the one that frees up first rather than failing outright.
        order = ready or sorted(chain, key=lambda m: self.stats[m].cooldown_until)[:1]
        errors = []
        for ref in order:
            st = self.stats.setdefault(ref, RouteStats())
            started = time.time()
            try:
                response = await self.gateway.complete(ref, system, messages, tools)
            except Exception as exc:  # any provider failure moves on to the next model
                kind, cooldown = classify(exc)
                st.failed += 1
                st.last_error = f"{kind}: {str(exc)[:200]}"
                st.cooldown_until = time.time() + cooldown
                errors.append(f"{ref} ({kind})")
                log.warning("router: %s failed (%s), trying the next model", ref, kind)
                continue
            st.ok += 1
            st.last_used = time.time()
            st.latencies = (st.latencies + [st.last_used - started])[-20:]
            return response
        raise LLMError("Every model in the API router failed: " + ", ".join(errors))
