"""App icons without an image library: a solid tile with a block letter, as PNG or SVG."""

from __future__ import annotations

import struct
import zlib

# 5x7 bitmap font for the icon letter (A-Z, 0-9). Each row is 5 bits, most significant bit on the left.
FONT = {
    "A": [14, 17, 17, 31, 17, 17, 17], "B": [30, 17, 17, 30, 17, 17, 30], "C": [14, 17, 16, 16, 16, 17, 14],
    "D": [30, 17, 17, 17, 17, 17, 30], "E": [31, 16, 16, 30, 16, 16, 31], "F": [31, 16, 16, 30, 16, 16, 16],
    "G": [14, 17, 16, 23, 17, 17, 15], "H": [17, 17, 17, 31, 17, 17, 17], "I": [14, 4, 4, 4, 4, 4, 14],
    "J": [7, 2, 2, 2, 2, 18, 12], "K": [17, 18, 20, 24, 20, 18, 17], "L": [16, 16, 16, 16, 16, 16, 31],
    "M": [17, 27, 21, 21, 17, 17, 17], "N": [17, 17, 25, 21, 19, 17, 17], "O": [14, 17, 17, 17, 17, 17, 14],
    "P": [30, 17, 17, 30, 16, 16, 16], "Q": [14, 17, 17, 17, 21, 18, 13], "R": [30, 17, 17, 30, 20, 18, 17],
    "S": [15, 16, 16, 14, 1, 1, 30], "T": [31, 4, 4, 4, 4, 4, 4], "U": [17, 17, 17, 17, 17, 17, 14],
    "V": [17, 17, 17, 17, 17, 10, 4], "W": [17, 17, 17, 21, 21, 21, 10], "X": [17, 17, 10, 4, 10, 17, 17],
    "Y": [17, 17, 10, 4, 4, 4, 4], "Z": [31, 1, 2, 4, 8, 16, 31],
    "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14], "2": [14, 17, 1, 2, 4, 8, 31],
    "3": [30, 1, 1, 14, 1, 1, 30], "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14],
    "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8], "8": [14, 17, 17, 14, 17, 17, 14],
    "9": [14, 17, 17, 15, 1, 2, 12],
}


def hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def text_color(bg: str) -> tuple[int, int, int]:
    r, g, b = hex_rgb(bg)
    return (20, 24, 30) if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else (255, 255, 255)


def icon_png(size: int, color: str, letter: str, letter_scale: float = 0.5) -> bytes:
    """A square PNG: `color` background with `letter` centred, about half the icon tall."""
    bg = hex_rgb(color)
    fg = text_color(color)
    glyph = FONT.get((letter or "?")[0].upper(), FONT["O"])
    cell = max(1, int(size * letter_scale / 7))
    gw, gh = 5 * cell, 7 * cell
    x0, y0 = (size - gw) // 2, (size - gh) // 2
    rows = []
    for y in range(size):
        gy = (y - y0) // cell if y0 <= y < y0 + gh else -1
        bits = glyph[gy] if gy >= 0 else 0
        row = bytearray(b"\x00")  # filter type 0
        for x in range(size):
            gx = (x - x0) // cell if x0 <= x < x0 + gw else -1
            on = gx >= 0 and bits >> (4 - gx) & 1
            row += bytes(fg if on else bg)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def icon_svg(color: str, letter: str) -> str:
    r, g, b = text_color(color)
    ch = (letter or "?")[0].upper()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="{color}"/>'
            f'<text x="256" y="256" dy=".35em" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" '
            f'font-weight="700" font-size="300" fill="rgb({r},{g},{b})">{ch}</text></svg>')
