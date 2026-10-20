"""The code book: compact coding knowledge per language, so small, fast models (Haiku class and below)
write working code. Each chapter has rules, templates and pitfalls; `method` is the step-by-step routine
every coding task follows. Chapters load into a bot's prompt by the languages its task mentions, or on
demand through the `code_reference` tool."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources

# chapter -> words in a task that mean it applies
TRIGGERS: dict[str, tuple[str, ...]] = {
    "python": ("python", ".py", "django", "flask", "fastapi", "pandas", "pytest", "pip "),
    "javascript": ("javascript", " js", ".js", "node", "react", "vue", "express", "npm", "web app", "website", "frontend", "browser"),
    "typescript": ("typescript", ".ts", "tsx", "angular", "next.js", "nextjs"),
    "html-css": ("html", "css", "web page", "webpage", "landing page", "website", "web app", "ui ", "layout", "pwa"),
    "sql": ("sql", "database", "postgres", "mysql", "sqlite", "supabase", "query", "table"),
    "bash": ("bash", "shell", "script", "linux", "cron", "terminal", "command line", "deploy"),
}
CODING = re.compile(r"\b(code|coding|program|script|app|function|bug|debug|api|website|web page|html|css|sql|"
                    r"python|javascript|typescript|bash|developer|build)\b", re.I)


@lru_cache(maxsize=None)
def chapter(name: str) -> str:
    try:
        return resources.files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def chapters() -> list[str]:
    return sorted(p.name[:-3] for p in resources.files(__package__).iterdir() if p.name.endswith(".md"))


def detect(text: str) -> list[str]:
    t = f" {text.lower()} "
    return [name for name, words in TRIGGERS.items() if any(w in t for w in words)]


def is_coding(text: str) -> bool:
    return bool(CODING.search(text or ""))


def for_task(text: str, max_chars: int = 9000) -> str:
    """The method plus the chapters the task needs, within a character budget (small models have small contexts)."""
    names = detect(text) or ["python", "javascript"]
    parts, used = [chapter("method")], len(chapter("method"))
    for name in names:
        body = chapter(name)
        if body and used + len(body) <= max_chars:
            parts.append(body)
            used += len(body)
    return "Code book (follow it exactly):\n\n" + "\n\n".join(p for p in parts if p)
