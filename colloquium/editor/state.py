"""Editor state: one shared :class:`EditorState` per deck, one :class:`Session` per browser tab."""

from __future__ import annotations

import re
from pathlib import Path

from colloquium.editor.document import DeckDocument

_SECTION_RE_TEMPLATE = r'<section class="slide [^"]*" data-index="{n}".*?</section>'


class EditorState:
    """Per-deck state shared by every client: document, undo history, last build."""

    def __init__(self, path: Path):
        self.path = path
        self.doc = DeckDocument.load(path)
        if not self.doc.slides:
            self.doc.insert_slide(0)
        self.undo: list[str] = []
        self.redo: list[str] = []
        self.version = 0
        self.html = ""
        self._master_text = None
        self.last_written_mtime = 0.0
        self.last_known_mtime = path.stat().st_mtime
        self.rebuild()

    # ----- build -----------------------------------------------------------
    def _deck(self):
        from colloquium.parse import parse_markdown

        deck = parse_markdown(self.doc.to_text())
        if deck.bibliography and not Path(deck.bibliography).is_absolute():
            deck.bibliography = str(self.path.parent / deck.bibliography)
        return deck

    def rebuild(self, changed: int | None = None) -> None:
        """Rebuild the preview HTML; a single changed slide is re-rendered alone when safe."""
        from colloquium.build import build_deck

        deck = self._deck()
        master_text = "\n".join(self.doc.slides[i].text for i in self.doc.master_indices())
        try:
            if changed is None or master_text != self._master_text or not self._rebuild_one(deck, changed):
                self.html = build_deck(deck, include_master=True)
        except Exception as exc:  # keep the editor alive on a bad build
            self.html = f"<html><body><pre>Build failed:\n{exc}</pre></body></html>"
        self._master_text = master_text
        self.version += 1

    def _rebuild_one(self, deck, src_index: int) -> bool:
        """Re-render only slide *src_index* into the cached HTML. False when a full build is needed."""
        from colloquium.build import build_slide_section

        if not self.html or deck.bibliography or src_index >= len(self.doc.slides):
            return False
        chunk = self.doc.slides[src_index]
        if chunk.is_master or not chunk.text.strip() or "```outline" in chunk.text:
            return False
        rendered = self.rendered_index(src_index)
        pattern = re.compile(_SECTION_RE_TEMPLATE.format(n=rendered), re.DOTALL)
        if len(pattern.findall(self.html)) != 1:
            return False
        section = build_slide_section(deck, rendered)
        if section is None:
            return False
        self.html = pattern.sub(lambda _: section, self.html, count=1)
        return True

    def rendered_index(self, src_index: int) -> int:
        """Map a source slide index to its position in the built deck."""
        after = [(s.get_directive("after") or "") == "references" for s in self.doc.slides]
        blank = [not s.text.strip() for s in self.doc.slides]
        main = [i for i, a in enumerate(after) if not a and not blank[i]]
        post = [i for i, a in enumerate(after) if a and not blank[i]]
        if blank[src_index]:
            # an empty chunk renders nothing; show the slide that follows it
            return min(sum(1 for j in main if j < src_index), max(len(main) - 1, 0))
        n_refs = len(re.findall(r'<section class="[^"]*\bslide--references\b', self.html))
        if src_index in main:
            return main.index(src_index)
        return len(main) + n_refs + post.index(src_index)

    def source_index(self, rendered: int) -> int | None:
        """Inverse of rendered_index; None for the auto-generated references slides."""
        for i in range(len(self.doc.slides)):
            if self.doc.slides[i].text.strip() and self.rendered_index(i) == rendered:
                return i
        return None

    # ----- mutations ---------------------------------------------------------
    def snapshot(self) -> None:
        self.undo.append(self.doc.to_text())
        if len(self.undo) > 200:
            self.undo.pop(0)
        self.redo.clear()

    def commit(self, changed: int | None = None) -> None:
        self.doc.save()
        self.last_written_mtime = self.path.stat().st_mtime
        self.last_known_mtime = self.last_written_mtime
        self.rebuild(changed)

    def restore(self, text: str) -> None:
        self.doc = DeckDocument.from_text(text, self.path)
        if not self.doc.slides:
            self.doc.insert_slide(0)
        self.commit()

    def do_undo(self) -> bool:
        if not self.undo:
            return False
        self.redo.append(self.doc.to_text())
        self.restore(self.undo.pop())
        return True

    def do_redo(self) -> bool:
        if not self.redo:
            return False
        self.undo.append(self.doc.to_text())
        self.restore(self.redo.pop())
        return True

    def reload_from_disk(self) -> bool:
        """Pick up external edits (user's text editor). Returns True if reloaded."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime <= self.last_known_mtime:
            return False
        self.last_known_mtime = mtime
        text = self.path.read_text(encoding="utf-8")
        if text == self.doc.to_text():
            return False
        self.undo.append(self.doc.to_text())
        self.redo.clear()
        self.doc = DeckDocument.from_text(text, self.path)
        if not self.doc.slides:
            self.doc.insert_slide(0)
        self.rebuild()
        return True


class Session:
    """Per-client UI state: which slide is open, what is selected."""

    def __init__(self):
        self.index = 0
        self.selection: dict | None = None
        self.extra: list[dict] = []
        self.clipboard: list[str] = []
        self.cropping = False

    def clamp(self, n_slides: int) -> None:
        self.index = max(0, min(self.index, n_slides - 1))
