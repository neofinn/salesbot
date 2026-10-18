"""Storyboards of animated text scenes, rendered to MP4 with ffmpeg in a single pass.

A storyboard is a list of scenes (headline, optional sub line, seconds) with an aspect and a palette.
Each scene's text fades in and out over a solid background with an accent bar, the business name in
a corner and a progress bar along the bottom. No footage or audio: the narration is a script the
owner can record over it.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import textwrap
from dataclasses import asdict, dataclass, field
from typing import Any

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")
FPS = 30


@dataclass
class Scene:
    headline: str
    sub: str = ""
    seconds: float = 4


@dataclass
class VideoSpec:
    title: str
    aspect: str = "16:9"
    bg: str = "#18212b"
    fg: str = "#ffffff"
    accent: str = "#d2551f"
    scenes: list[Scene] = field(default_factory=list)
    narration: str = ""
    caption: str = ""

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS[self.aspect]

    @property
    def duration(self) -> float:
        return sum(s.seconds for s in self.scenes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def from_dict(data: dict[str, Any]) -> VideoSpec:
    """Build a spec from model output or storage, clamping everything to safe values."""
    palette = data.get("palette") if isinstance(data.get("palette"), dict) else {}

    def color(key: str, default: str) -> str:
        value = str(data.get(key) or palette.get(key) or "")
        return value if HEX.match(value) else default

    scenes = []
    for raw in (data.get("scenes") or [])[:12]:
        if not isinstance(raw, dict) or not str(raw.get("headline", "")).strip():
            continue
        try:
            secs = float(raw.get("seconds") or 4)
        except (TypeError, ValueError):
            secs = 4
        scenes.append(Scene(str(raw["headline"]).strip()[:90], str(raw.get("sub") or "").strip()[:160],
                            min(8.0, max(2.0, secs))))
    aspect = str(data.get("aspect") or "16:9")
    return VideoSpec(
        title=str(data.get("title") or "Untitled video").strip()[:120],
        aspect=aspect if aspect in ASPECTS else "16:9",
        bg=color("bg", "#18212b"), fg=color("fg", "#ffffff"), accent=color("accent", "#d2551f"),
        scenes=scenes, narration=str(data.get("narration") or "")[:6000], caption=str(data.get("caption") or "")[:2200],
    )


def problems(spec: VideoSpec) -> list[str]:
    out = []
    if not spec.scenes:
        out.append("a video needs at least one scene with a headline")
    if spec.duration > 90:
        out.append("keep videos to 90 seconds or less")
    return out


def find_font(bold: bool = False) -> str:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return ""


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _wrap(text: str, size: int, width: int) -> list[str]:
    # DejaVu Sans Bold averages about 0.6 em per character.
    return textwrap.wrap(text, max(8, int(width / (size * 0.6)))) or [""]


def _esc(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def filtergraph(spec: VideoSpec, workdir: str, company: str = "") -> str:
    """The ffmpeg filter graph; scene text goes in files under workdir so nothing needs escaping."""
    w, h = spec.size
    big = round(min(w, h) * 0.085)
    small = round(big * 0.45)
    pad = round(w * 0.08)
    bold, regular = _esc(find_font(True)), _esc(find_font(False))
    fg, accent = spec.fg.replace("#", "0x"), spec.accent.replace("#", "0x")
    parts = []
    start = 0.0
    for i, sc in enumerate(spec.scenes):
        end = start + sc.seconds
        head = _wrap(sc.headline, big, w - 2 * pad)
        sub = _wrap(sc.sub, small, w - 2 * pad) if sc.sub else []
        block = len(head) * big * 1.15 + (big * 0.5 + len(sub) * small * 1.3 if sub else 0)
        y = round((h - block) / 2)
        alpha = f"max(0\\,min(1\\,min((t-{start:.2f})/0.5\\,({end:.2f}-t)/0.4)))"
        enable = f"between(t\\,{start:.2f}\\,{end:.2f})"
        head_file = os.path.join(workdir, f"h{i}.txt")
        with open(head_file, "w") as fh:
            fh.write("\n".join(head))
        parts.append(f"drawbox=x={pad}:y={round(y - big * 0.45)}:w={round(big * 1.2)}:h={max(4, round(big * 0.08))}"
                     f":color={accent}:t=fill:enable='{enable}'")
        parts.append(f"drawtext=fontfile='{bold}':textfile='{_esc(head_file)}':expansion=none:fontsize={big}:fontcolor={fg}"
                     f":line_spacing={round(big * 0.15)}:x={pad}:y={y}:alpha='{alpha}':enable='{enable}'")
        if sub:
            sub_file = os.path.join(workdir, f"s{i}.txt")
            with open(sub_file, "w") as fh:
                fh.write("\n".join(sub))
            parts.append(f"drawtext=fontfile='{regular}':textfile='{_esc(sub_file)}':expansion=none:fontsize={small}"
                         f":fontcolor={fg}@0.85:line_spacing={round(small * 0.3)}:x={pad}"
                         f":y={round(y + len(head) * big * 1.15 + big * 0.5)}:alpha='{alpha}':enable='{enable}'")
        start = end
    if company:
        name_file = os.path.join(workdir, "company.txt")
        with open(name_file, "w") as fh:
            fh.write(company[:60])
        parts.append(f"drawtext=fontfile='{bold}':textfile='{_esc(name_file)}':expansion=none:fontsize={round(big * 0.3)}"
                     f":fontcolor={fg}@0.7:x={pad}:y=h-{round(pad * 0.9)}")
    parts.append(f"drawbox=x=0:y=ih-6:w=iw:h=6:color={fg}@0.2:t=fill")
    return f"[0:v]{','.join(parts)}[base];[base][1:v]overlay=x='-w+w*t/{spec.duration:.2f}':y=H-6:shortest=1,format=yuv420p[out]"


async def render_mp4(spec: VideoSpec, out_path: str, company: str = "") -> str:
    """Render the storyboard to an H.264 MP4 at out_path. Raises RuntimeError with a readable reason."""
    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError("ffmpeg is not installed on the server (sudo apt install ffmpeg)")
    if not find_font():
        raise RuntimeError("no DejaVu font found (sudo apt install fonts-dejavu-core)")
    bad = problems(spec)
    if bad:
        raise RuntimeError("; ".join(bad))
    w, h = spec.size
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        graph = filtergraph(spec, tmp, company)
        args = [
            exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={spec.bg.replace('#', '0x')}:s={w}x{h}:r={FPS}:d={spec.duration:.2f}",
            "-f", "lavfi", "-i", f"color=c={spec.accent.replace('#', '0x')}:s={w}x6:r={FPS}:d={spec.duration:.2f}",
            "-filter_complex", graph, "-map", "[out]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", out_path,
        ]
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace').strip()[-500:]}")
    return out_path
