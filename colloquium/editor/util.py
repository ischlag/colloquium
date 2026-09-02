"""Small helpers shared by the editor UI modules."""

from __future__ import annotations

import json
import re

LAYOUTS = [
    "content", "title", "title-left", "title-banner", "title-sidebar",
    "section-break", "two-column", "image-left", "image-right", "code",
]
ALIGNS = ["", "left", "center", "right"]
VALIGNS = ["", "top", "center", "bottom"]
SIZES = ["", "small", "large", "xl"]
PADDINGS = ["", "none", "small", "large"]
SHAPES = ["rect", "rounded", "ellipse", "line", "arrow"]


def hex_color(value: str | None) -> str | None:
    """Return a #rrggbb colour for <input type=color>, or None if not representable."""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    return None


def px_or_none(value: str | None) -> float | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*px\s*", value or "")
    return float(m.group(1)) if m else None


def js(obj) -> str:
    return json.dumps(obj)


class CellStyleTarget:
    """Adapter so a cell's cell-style comment can act as a toolbar text target."""

    def __init__(self, style: str):
        self.style = style
        self.align = ""
