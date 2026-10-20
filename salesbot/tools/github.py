"""GitHub repository search and repo inspection (public GitHub REST API; a token only raises the rate limit)."""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from .base import Tool, ToolContext, ToolError, schema, string

API = "https://api.github.com"
MAX_README_CHARS = 4000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _headers(ctx: ToolContext) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "myops-git-hunter", "X-GitHub-Api-Version": "2022-11-28"}
    if ctx.settings.github_token:
        h["Authorization"] = f"Bearer {ctx.settings.github_token}"
    return h


async def _get(ctx: ToolContext, path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{API}{path}", params=params, headers=_headers(ctx))
    if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
        raise ToolError("GitHub's rate limit is used up for now; wait a minute (a GitHub token in Settings raises it).")
    if resp.status_code == 404:
        raise ToolError(f"Not found on GitHub: {path}")
    if resp.status_code >= 400:
        raise ToolError(f"GitHub error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _summary(r: dict[str, Any]) -> str:
    lic = (r.get("license") or {}).get("spdx_id") or "no license"
    topics = ", ".join((r.get("topics") or [])[:6])
    return (f"{r['full_name']} - {r.get('stargazers_count', 0)} stars, {r.get('language') or 'n/a'}, {lic}, "
            f"last push {str(r.get('pushed_at', ''))[:10]}{', archived' if r.get('archived') else ''}\n"
            f"{r.get('html_url', '')}\n{(r.get('description') or '').strip()}"
            + (f"\nTopics: {topics}" if topics else ""))


async def _search(args: dict[str, Any], ctx: ToolContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("Give a search query.")
    sort = args.get("sort") or "best"
    params: dict[str, Any] = {"q": query, "per_page": max(1, min(15, int(args.get("limit") or 8)))}
    if sort != "best":
        params.update(sort=sort, order="desc")
    data = await _get(ctx, "/search/repositories", params)
    items = data.get("items") or []
    if not items:
        return f"No repositories match {query!r}. Try broader words or fewer qualifiers."
    return f"{data.get('total_count', len(items))} matches for {query!r}; top {len(items)}:\n\n" + "\n\n".join(map(_summary, items))


async def _inspect(args: dict[str, Any], ctx: ToolContext) -> str:
    repo = str(args.get("repo") or "").strip().removeprefix("https://github.com/").strip("/")
    if not REPO_RE.match(repo):
        raise ToolError("Give the repository as owner/name.")
    r = await _get(ctx, f"/repos/{repo}")
    out = [_summary(r), f"Open issues: {r.get('open_issues_count', 0)}. Forks: {r.get('forks_count', 0)}. "
           f"Created {str(r.get('created_at', ''))[:10]}."]
    try:
        rel = await _get(ctx, f"/repos/{repo}/releases/latest")
        out.append(f"Latest release: {rel.get('tag_name')} ({str(rel.get('published_at', ''))[:10]}).")
    except ToolError:
        out.append("No published releases.")
    try:
        readme = await _get(ctx, f"/repos/{repo}/readme")
        text = base64.b64decode(readme.get("content", "")).decode("utf-8", "replace")
        out.append("README (start):\n" + text[:MAX_README_CHARS] + ("\n[truncated]" if len(text) > MAX_README_CHARS else ""))
    except ToolError:
        out.append("No README.")
    return "\n\n".join(out)


GITHUB_SEARCH = Tool(
    "github_search",
    "Search public GitHub repositories. Use GitHub search syntax: keywords plus qualifiers such as language:python, "
    "stars:>500, pushed:>2026-01-01, topic:llm, license:mit, archived:false.",
    schema({
        "query": string("GitHub search query with qualifiers"),
        "sort": {"type": "string", "enum": ["best", "stars", "updated"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 15},
    }, ["query"]),
    _search,
)

GITHUB_REPO = Tool(
    "github_repo",
    "Inspect one GitHub repository: stars, license, activity, latest release and the start of its README.",
    schema({"repo": string("owner/name")}, ["repo"]),
    _inspect,
)
