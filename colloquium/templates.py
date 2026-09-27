"""Deck templates shipped with the package (``colloquium new``, the editor's file picker)."""

from __future__ import annotations

import shutil
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


def template_names() -> list[str]:
    return sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir() and any(p.glob("*.md")))


def create_deck(target: Path, template: str = "starter") -> Path:
    """Copy *template* into directory *target* and return the new deck's .md path.

    The deck file is named after the target directory (``talk/talk.md``) and
    its title is set to that name. Refuses to overwrite an existing deck.
    """
    src = TEMPLATES_DIR / template
    if not src.is_dir():
        raise ValueError(f"Unknown template {template!r}; available: {', '.join(template_names())}")
    target = Path(target).expanduser().resolve()
    name = target.name or "deck"
    deck = target / f"{name}.md"
    if deck.exists():
        raise FileExistsError(f"{deck} already exists")
    target.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.suffix == ".md":
            text = item.read_text(encoding="utf-8")
            text = text.replace(f'title: "{template.capitalize()} deck"', f'title: "{name}"', 1)
            deck.write_text(text, encoding="utf-8")
        elif item.is_dir():
            shutil.copytree(item, target / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target / item.name)
    return deck
