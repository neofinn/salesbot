import base64

import httpx
import pytest

from salesbot.config import Settings
from salesbot.tools import CATALOG, ToolContext, ToolError

REPO = {"full_name": "jugaad-py/jugaad-data", "stargazers_count": 583, "language": "Python", "forks_count": 90,
        "license": {"spdx_id": "MIT"}, "pushed_at": "2026-09-30T10:00:00Z", "created_at": "2020-01-01T00:00:00Z",
        "html_url": "https://github.com/jugaad-py/jugaad-data", "description": "NSE data", "topics": ["nse", "india"],
        "open_issues_count": 12}


def ctx(**kw):
    return ToolContext(settings=Settings(**kw), store=None, agent_name="git_hunter")


def fake_github(monkeypatch, routes, seen=None):
    async def fake_get(self, url, params=None, headers=None):
        if seen is not None:
            seen.append((url, params, headers))
        path = url.removeprefix("https://api.github.com")
        status, body = routes.get(path, (404, {"message": "Not Found"}))
        return httpx.Response(status, json=body, headers=body.pop("_headers", {}) if isinstance(body, dict) else {})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


async def test_search_lists_repos_with_license_and_activity(monkeypatch):
    seen = []
    fake_github(monkeypatch, {"/search/repositories": (200, {"total_count": 1, "items": [REPO]})}, seen)
    out = await CATALOG["github_search"].handler({"query": "nse language:python", "sort": "stars", "limit": 5}, ctx(github_token="ghp_x"))
    assert "jugaad-py/jugaad-data - 583 stars, Python, MIT, last push 2026-09-30" in out
    assert "Topics: nse, india" in out
    _, params, headers = seen[0]
    assert params == {"q": "nse language:python", "per_page": 5, "sort": "stars", "order": "desc"}
    assert headers["Authorization"] == "Bearer ghp_x"


async def test_search_without_token_and_no_results(monkeypatch):
    seen = []
    fake_github(monkeypatch, {"/search/repositories": (200, {"total_count": 0, "items": []})}, seen)
    out = await CATALOG["github_search"].handler({"query": "zzz"}, ctx())
    assert out.startswith("No repositories match")
    assert "Authorization" not in seen[0][2] and "sort" not in seen[0][1]


async def test_rate_limit_is_explained(monkeypatch):
    fake_github(monkeypatch, {"/search/repositories": (403, {"message": "limit", "_headers": {"x-ratelimit-remaining": "0"}})})
    with pytest.raises(ToolError, match="rate limit"):
        await CATALOG["github_search"].handler({"query": "x"}, ctx())


async def test_inspect_reads_release_and_readme(monkeypatch):
    readme = base64.b64encode(b"# jugaad-data\nDownload NSE data.").decode()
    fake_github(monkeypatch, {
        "/repos/jugaad-py/jugaad-data": (200, REPO),
        "/repos/jugaad-py/jugaad-data/releases/latest": (200, {"tag_name": "v0.27", "published_at": "2026-08-01T00:00:00Z"}),
        "/repos/jugaad-py/jugaad-data/readme": (200, {"content": readme}),
    })
    out = await CATALOG["github_repo"].handler({"repo": "https://github.com/jugaad-py/jugaad-data"}, ctx())
    assert "Latest release: v0.27 (2026-08-01)" in out and "Download NSE data." in out and "Open issues: 12" in out


async def test_inspect_rejects_bad_names():
    with pytest.raises(ToolError, match="owner/name"):
        await CATALOG["github_repo"].handler({"repo": "../../etc"}, ctx())


def test_manager_can_ask_the_git_hunter(team):
    assert "ask_git_hunter" in team.manager().tools
    assert set(team.git_hunter().tools) == {"github_search", "github_repo"}
