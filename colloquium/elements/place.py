"""Place element — free positioning of images and text on a slide.

A ```place fenced block pins an image or a markdown text block at an absolute
position on the slide, expressed in percent of slide width/height so the
result is resolution independent:

    ```place
    x: 55
    y: 20
    w: 40
    h: 30          # optional for images (natural aspect) and text (auto)
    src: images/fig.png
    crop: [0.1, 0.05, 0.8, 0.9]   # x, y, w, h as fractions of the original
    ```

    ```place
    x: 5
    y: 70
    w: 45
    size: 0.8      # font scale
    align: center  # left | center | right
    text: |
      Some **markdown**
    ```

Unlike the other elements, place blocks are extracted from the slide source
*before* markdown rendering and rendered into a dedicated layer that is a
direct child of the slide, so they never interfere with column/row layout
and their coordinates are always slide-relative.

Cropping is non-destructive: the original file is referenced unchanged and the
crop rectangle only offsets/scales the image inside an overflow-hidden box.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field

import yaml

from colloquium.md import create_base_md

# Matches a ```place fenced block in raw markdown (not rendered HTML).
PLACE_FENCE_RE = re.compile(
    r"^```place[ \t]*\n(.*?)^```[ \t]*$\n?",
    re.DOTALL | re.MULTILINE,
)

_block_md = create_base_md()

_ALIGNS = {"left", "center", "right"}


@dataclass
class PlaceSpec:
    """A parsed place block."""

    x: float = 0.0
    y: float = 0.0
    w: float | None = None
    h: float | None = None
    src: str = ""
    text: str = ""
    crop: list[float] | None = None
    size: float | None = None
    align: str = ""
    z: int | None = None
    rotate: float | None = None
    classes: list[str] = field(default_factory=list)
    style: str = ""
    raw: str = ""
    error: str = ""

    @property
    def kind(self) -> str:
        return "image" if self.src else "text"

    def to_yaml(self) -> str:
        """Serialize back to the YAML body of a ```place block."""
        lines = [f"x: {_fmt(self.x)}", f"y: {_fmt(self.y)}"]
        if self.w is not None:
            lines.append(f"w: {_fmt(self.w)}")
        if self.h is not None:
            lines.append(f"h: {_fmt(self.h)}")
        if self.src:
            lines.append(f"src: {self.src}")
        if self.crop:
            lines.append("crop: [" + ", ".join(_fmt(c, 3) for c in self.crop) + "]")
        if self.size is not None:
            lines.append(f"size: {_fmt(self.size, 2)}")
        if self.align:
            lines.append(f"align: {self.align}")
        if self.z is not None:
            lines.append(f"z: {self.z}")
        if self.rotate is not None:
            lines.append(f"rotate: {_fmt(self.rotate)}")
        if self.classes:
            lines.append(f"class: {' '.join(self.classes)}")
        if self.style:
            lines.append(f"style: {self.style}")
        if self.text:
            lines.append("text: |")
            lines.extend(f"  {line}" if line else "" for line in self.text.rstrip("\n").splitlines())
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        return "```place\n" + self.to_yaml() + "```"


def _fmt(value: float, digits: int = 1) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _num(value, default=None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def reset() -> None:
    """Reset element-local state between builds."""
    return None


def parse_spec(yaml_str: str) -> PlaceSpec:
    """Parse the YAML body of a place block into a PlaceSpec."""
    raw = yaml_str
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return PlaceSpec(raw=raw, error=f"Invalid place YAML: {exc}")
    if not isinstance(data, dict):
        return PlaceSpec(raw=raw, error="Place spec must be a YAML mapping")

    spec = PlaceSpec(raw=raw)
    spec.x = _num(data.get("x"), 0.0)
    spec.y = _num(data.get("y"), 0.0)
    spec.w = _num(data.get("w"))
    spec.h = _num(data.get("h"))
    spec.src = str(data.get("src", "") or "").strip()
    text = data.get("text", "")
    spec.text = text if isinstance(text, str) else str(text)
    spec.size = _num(data.get("size"))
    align = str(data.get("align", "") or "").strip().lower()
    spec.align = align if align in _ALIGNS else ""
    z = data.get("z")
    spec.z = int(z) if isinstance(z, (int, float)) else None
    spec.rotate = _num(data.get("rotate"))
    classes = data.get("class", "")
    spec.classes = str(classes).split() if classes else []
    spec.style = str(data.get("style", "") or "").strip()

    crop = data.get("crop")
    if isinstance(crop, (list, tuple)) and len(crop) == 4:
        try:
            vals = [float(c) for c in crop]
        except (TypeError, ValueError):
            vals = []
        if vals and vals[2] > 0 and vals[3] > 0:
            spec.crop = vals
    elif isinstance(crop, str):
        parts = [p for p in re.split(r"[,\s]+", crop.strip()) if p]
        if len(parts) == 4:
            try:
                vals = [float(p) for p in parts]
                if vals[2] > 0 and vals[3] > 0:
                    spec.crop = vals
            except ValueError:
                pass

    if not spec.src and not spec.text.strip():
        spec.error = "Place block needs src or text"
    return spec


def extract(content: str) -> tuple[str, list[PlaceSpec]]:
    """Remove all ```place blocks from slide markdown and return their specs."""
    specs: list[PlaceSpec] = []

    def _take(match: re.Match) -> str:
        specs.append(parse_spec(match.group(1)))
        return ""

    remaining = PLACE_FENCE_RE.sub(_take, content)
    remaining = re.sub(r"\n{3,}", "\n\n", remaining)
    return remaining.strip(), specs


def _box_style(spec: PlaceSpec) -> str:
    parts = [f"left: {_fmt(spec.x, 2)}%", f"top: {_fmt(spec.y, 2)}%"]
    if spec.w is not None:
        parts.append(f"width: {_fmt(spec.w, 2)}%")
    if spec.h is not None:
        parts.append(f"height: {_fmt(spec.h, 2)}%")
    if spec.z is not None:
        parts.append(f"z-index: {spec.z}")
    if spec.rotate:
        parts.append(f"transform: rotate({_fmt(spec.rotate, 2)}deg)")
    if spec.size is not None and spec.size > 0:
        parts.append(f"font-size: {_fmt(spec.size, 3)}em")
    if spec.style:
        parts.append(spec.style.rstrip(";"))
    return "; ".join(parts)


def _crop_style(crop: list[float]) -> str:
    cx, cy, cw, ch = crop
    return (
        f"width: {_fmt(100.0 / cw, 3)}%; height: {_fmt(100.0 / ch, 3)}%; "
        f"left: {_fmt(-cx / cw * 100.0, 3)}%; top: {_fmt(-cy / ch * 100.0, 3)}%"
    )


def render_spec(spec: PlaceSpec, index: int, md=None) -> str:
    """Render one place spec as an absolutely positioned element."""
    if spec.error:
        return (
            f'<div class="colloquium-place colloquium-place--error" data-place-index="{index}" '
            f'style="left: 2%; top: 2%">{html_module.escape(spec.error)}</div>'
        )

    classes = ["colloquium-place", f"colloquium-place--{spec.kind}"]
    if spec.align:
        classes.append(f"colloquium-place--align-{spec.align}")
    classes.extend(html_module.escape(c) for c in spec.classes)
    attrs = (
        f'class="{" ".join(classes)}" data-place-index="{index}" '
        f'style="{html_module.escape(_box_style(spec), quote=True)}"'
    )

    if spec.kind == "image":
        src = html_module.escape(spec.src, quote=True)
        crop = spec.crop
        crop_attr = ""
        img_style = ""
        if crop:
            crop_attr = f' data-crop="{" ".join(_fmt(c, 4) for c in crop)}"'
            img_style = f' style="{_crop_style(crop)}"'
        return (
            f"<div {attrs}{crop_attr}>"
            f'<img src="{src}" alt=""{img_style}>'
            f"</div>"
        )

    renderer = md or _block_md
    body = renderer.render(spec.text).strip()
    return f"<div {attrs}>{body}</div>"


def render_layer(specs: list[PlaceSpec], md=None) -> str:
    """Render all place specs of a slide into the place layer."""
    if not specs:
        return ""
    items = "\n".join(render_spec(spec, i, md) for i, spec in enumerate(specs))
    return f'<div class="colloquium-place-layer">\n{items}\n</div>'
