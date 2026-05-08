"""Minimal ANSI SGR → HTML span converter (foreground color only).

Handles the subset of ANSI codes that plotext emits:
  - \x1b[0m         → reset (closes open span)
  - \x1b[38;5;Nm    → 8-bit (256-color) foreground
  - \x1b[38;2;R;G;Bm → 24-bit (truecolor) foreground
Any other SGR code is stripped (no styling applied, but text preserved).
HTML special characters (<, >, &) are escaped before insertion.
"""
from __future__ import annotations

import html
import re

_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _build_8bit_palette() -> list[str]:
    palette: list[str] = [
        "#000000", "#800000", "#008000", "#808000", "#000080", "#800080", "#008080", "#c0c0c0",
        "#808080", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "#00ffff", "#ffffff",
    ]
    levels = (0, 95, 135, 175, 215, 255)
    for r in levels:
        for g in levels:
            for b in levels:
                palette.append(f"#{r:02x}{g:02x}{b:02x}")
    for v in range(24):
        c = 8 + v * 10
        palette.append(f"#{c:02x}{c:02x}{c:02x}")
    return palette


_PALETTE = _build_8bit_palette()


def ansi_to_html(text: str) -> str:
    parts: list[str] = []
    open_span = False
    pos = 0
    for m in _ANSI_RE.finditer(text):
        before = text[pos:m.start()]
        if before:
            parts.append(html.escape(before))
        codes_str = m.group(1) or "0"
        codes = [int(c) for c in codes_str.split(";") if c != ""]
        if not codes:
            codes = [0]
        i = 0
        new_style: str | None = None
        reset = False
        while i < len(codes):
            c = codes[i]
            if c == 0:
                reset = True
                i += 1
            elif c == 38 and i + 2 < len(codes) and codes[i + 1] == 5:
                idx = codes[i + 2]
                if 0 <= idx < len(_PALETTE):
                    new_style = f"color:{_PALETTE[idx]}"
                i += 3
            elif c == 38 and i + 4 < len(codes) and codes[i + 1] == 2:
                r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                new_style = f"color:#{r:02x}{g:02x}{b:02x}"
                i += 5
            else:
                i += 1
        if open_span and (reset or new_style is not None):
            parts.append("</span>")
            open_span = False
        if new_style is not None:
            parts.append(f'<span style="{new_style}">')
            open_span = True
        pos = m.end()
    tail = text[pos:]
    if tail:
        parts.append(html.escape(tail))
    if open_span:
        parts.append("</span>")
    return "".join(parts)
