"""Mobile apps for the team: one app per business, each with its own name, icon, color and server.

Every app is instantly installable as a web app (Add to Home Screen on Android and iPhone) at
/app/<slug>, and can be exported as a native Android/iOS project (Capacitor) that a CI workflow
builds. Both load the team from the server, so updates reach phones without reinstalling.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "app-" + s
    return s[:32].rstrip("-")


@dataclass
class AppSpec:
    slug: str
    name: str
    short_name: str = ""
    color: str = "#233a57"  # icon background and theme color
    background: str = "#ffffff"  # splash background
    letter: str = ""
    description: str = ""
    # The MyOps server this app opens. Empty = this server. A separate business can run its own
    # MyOps server (its own team and data) and get its own app pointing there.
    server_url: str = ""
    platforms: list[str] = field(default_factory=lambda: ["android", "ios"])
    version: int = 1
    notes: str = ""

    def __post_init__(self) -> None:
        self.short_name = (self.short_name or self.name)[:12]
        self.letter = (self.letter or self.name[:1] or "M")[:1].upper()

    @property
    def bundle_id(self) -> str:
        return "com.myops." + self.slug.replace("-", "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppSpec:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def validate(spec: AppSpec) -> list[str]:
    problems = []
    if not SLUG_RE.match(spec.slug):
        problems.append("slug must be 2-32 characters: lowercase letters, digits or -, starting with a letter")
    if not spec.name.strip():
        problems.append("name is empty")
    for label, c in (("color", spec.color), ("background", spec.background)):
        if not HEX_RE.match(c):
            problems.append(f"{label} must be a hex color like #233a57")
    if spec.server_url and not re.match(r"^https?://[^\s/]+", spec.server_url):
        problems.append("server_url must start with http:// or https://")
    bad = [p for p in spec.platforms if p not in ("android", "ios")]
    if bad:
        problems.append(f"unknown platforms: {', '.join(bad)}")
    return problems
