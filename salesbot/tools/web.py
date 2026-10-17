"""Web search (Brave Search API) and page fetch tools."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import Tool, ToolContext, ToolError, schema, string

MAX_PAGE_CHARS = 8000


async def _web_search(args: dict[str, Any], ctx: ToolContext) -> str:
    if not ctx.settings.brave_api_key:
        raise ToolError("Web search is not configured (set BRAVE_API_KEY).")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": args["query"], "count": 5},
            headers={"X-Subscription-Token": ctx.settings.brave_api_key, "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise ToolError(f"Search error {resp.status_code}: {resp.text[:200]}")
    results = resp.json().get("web", {}).get("results", [])
    if not results:
        return "No results."
    return "\n\n".join(
        f"{r.get('title', '')}\n{r.get('url', '')}\n{_strip_html(r.get('description', ''))}" for r in results
    )


async def _check_public_url(url: str) -> None:
    """Refuse URLs that point at private, loopback or link-local addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolError("Only http(s) URLs can be fetched.")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, None)
    except socket.gaierror as exc:
        raise ToolError(f"Could not resolve {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ToolError("Refusing to fetch a private or internal address.")


async def _web_fetch(args: dict[str, Any], ctx: ToolContext) -> str:
    url = args["url"]
    await _check_public_url(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        resp = await client.get(url, headers={"User-Agent": "salesbot/0.1"})
    if resp.is_redirect:
        return f"Redirected to {resp.headers.get('location', '')} - fetch that URL to follow it."
    if resp.status_code >= 400:
        raise ToolError(f"HTTP {resp.status_code} fetching {url}")
    text = _strip_html(resp.text) if "html" in resp.headers.get("content-type", "") else resp.text
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n[truncated]"
    return text


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


WEB_SEARCH = Tool(
    "web_search",
    "Search the web. Returns the top results with title, URL and snippet.",
    schema({"query": string("Search query")}, ["query"]),
    _web_search,
)

WEB_FETCH = Tool(
    "web_fetch",
    "Fetch a public web page and return its text content.",
    schema({"url": string("Full http(s) URL")}, ["url"]),
    _web_fetch,
)
