"""Image helpers for the editor: import into the deck folder, dimensions."""

from __future__ import annotations

import shutil
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def image_size(path: Path) -> tuple[int, int] | None:
    """Return (width, height) in pixels, or None when unknown (e.g. SVG)."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - pillow is an editor extra
        return None
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def import_image(src: Path, deck_dir: Path, subdir: str = "images") -> str:
    """Copy *src* into ``deck_dir/subdir`` unless it already lives under deck_dir.

    Returns the path to use in markdown, relative to the deck file, with
    forward slashes. Name collisions get a numeric suffix unless the existing
    file is byte-identical.
    """
    src = Path(src).resolve()
    deck_dir = Path(deck_dir).resolve()
    try:
        return src.relative_to(deck_dir).as_posix()
    except ValueError:
        pass

    target_dir = deck_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src.name
    n = 1
    while target.exists():
        if target.read_bytes() == src.read_bytes():
            return target.relative_to(deck_dir).as_posix()
        target = target_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1
    shutil.copy2(src, target)
    return target.relative_to(deck_dir).as_posix()


def default_place_width(size: tuple[int, int] | None, max_w: float = 40.0) -> float:
    """Pick an initial width percent for a newly placed image."""
    if not size:
        return max_w
    w, h = size
    # Never taller than ~60% of the slide: w% * (16/9) / aspect = h%
    aspect = w / h if h else 1.0
    width = max_w
    height = width * (16 / 9) / aspect
    if height > 60:
        width = 60 * aspect / (16 / 9)
    return round(width, 1)
