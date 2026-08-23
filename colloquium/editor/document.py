"""Lossless, string-level editing of a colloquium markdown deck.

The editor never round-trips through ``Slide``/``Deck`` objects (that path is
lossy: columns, rows and most directives become CSS classes). Instead the file
is split into frontmatter, raw slide chunks and the separators between them,
and every edit is a targeted rewrite inside one chunk. Untouched slides are
emitted byte for byte, so git diffs only show what actually changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from colloquium.elements import place

# Same slide separator the parser uses.
_SEPARATOR_RE = re.compile(r"(\n---[ \t]*\n)")
_FRONTMATTER_RE = re.compile(r"\A(\s*---[ \t]*\n.*?\n---[ \t]*\n)", re.DOTALL)
_DIRECTIVE_RE = re.compile(r"<!--\s*([a-z][a-z-]*)\s*:\s*(.*?)\s*-->[ \t]*\n?", re.DOTALL)
_TITLE_RE = re.compile(r"^(#{1,2}) (.*)$", re.MULTILINE)
_COLUMN_SPLIT_RE = re.compile(r"^\|\|\|[ \t]*$", re.MULTILINE)
_ROW_SPLIT_RE = re.compile(r"^===[ \t]*$", re.MULTILINE)

DEFAULT_SEPARATOR = "\n\n---\n\n"


@dataclass
class PlaceRef:
    """A place block inside a slide chunk, with its source span."""

    index: int
    start: int
    end: int
    spec: place.PlaceSpec


@dataclass
class SlideChunk:
    """One slide's raw markdown text."""

    text: str

    # ----- directives -------------------------------------------------
    def directives(self) -> list[tuple[str, str]]:
        return [(m.group(1), m.group(2).strip()) for m in _DIRECTIVE_RE.finditer(self.text)]

    def get_directive(self, key: str) -> str | None:
        for k, v in self.directives():
            if k == key:
                return v
        return None

    def set_directive(self, key: str, value: str | None) -> None:
        """Set, replace or (value None/empty) remove a ``<!-- key: value -->``."""
        value = (value or "").strip()
        matches = [m for m in _DIRECTIVE_RE.finditer(self.text) if m.group(1) == key]
        if matches:
            m = matches[0]
            if value:
                replacement = f"<!-- {key}: {value} -->"
                # keep whatever followed the directive (newline) intact
                tail = m.group(0)[len(m.group(0).rstrip("\n \t")):]
                self.text = self.text[: m.start()] + replacement + tail + self.text[m.end():]
            else:
                self.text = self.text[: m.start()] + self.text[m.end():]
            # drop any duplicates of the same key
            for extra in reversed(matches[1:]):
                self.text = self.text[: extra.start()] + self.text[extra.end():]
            self.text = self.text.strip("\n")
            return
        if not value:
            return
        line = f"<!-- {key}: {value} -->"
        # Insert after existing leading directives, before the title/content.
        pos = 0
        for m in _DIRECTIVE_RE.finditer(self.text):
            if self.text[:m.start()].strip():
                break
            pos = m.end()
        head = self.text[:pos]
        rest = self.text[pos:]
        if head and not head.endswith("\n"):
            head += "\n"
        self.text = f"{head}{line}\n{rest}".strip("\n")

    # ----- title --------------------------------------------------------
    def _title_match(self) -> re.Match | None:
        stripped = _DIRECTIVE_RE.sub(lambda m: " " * len(m.group(0)), self.text)
        m = _TITLE_RE.search(stripped)
        if not m:
            return None
        # Ensure it is the first non-directive, non-blank line.
        before = stripped[: m.start()]
        if before.strip():
            return None
        return m

    def get_title(self) -> str:
        m = self._title_match()
        return m.group(2).strip() if m else ""

    def title_level(self) -> int:
        m = self._title_match()
        return len(m.group(1)) if m else 2

    def set_title(self, title: str, level: int | None = None) -> None:
        title = title.strip()
        m = self._title_match()
        if m:
            hashes = "#" * (level or len(m.group(1)))
            if title:
                self.text = self.text[: m.start()] + f"{hashes} {title}" + self.text[m.end():]
            else:
                self.text = (self.text[: m.start()] + self.text[m.end():]).replace("\n\n\n", "\n\n")
            return
        if not title:
            return
        hashes = "#" * (level or 2)
        # After leading directives.
        pos = 0
        for dm in _DIRECTIVE_RE.finditer(self.text):
            if self.text[:dm.start()].strip():
                break
            pos = dm.end()
        head, rest = self.text[:pos], self.text[pos:]
        if head and not head.endswith("\n"):
            head += "\n"
        self.text = f"{head}{hashes} {title}\n\n{rest.lstrip(chr(10))}".strip("\n")

    # ----- body (everything but leading directives, title, notes) -------
    def _body_span(self) -> tuple[int, int]:
        """Span of the content body: after title (or leading directives), whole rest."""
        m = self._title_match()
        if m:
            start = m.end()
        else:
            start = 0
            for dm in _DIRECTIVE_RE.finditer(self.text):
                if self.text[:dm.start()].strip():
                    break
                start = dm.end()
        return start, len(self.text)

    def get_body(self) -> str:
        start, end = self._body_span()
        return self.text[start:end].strip("\n")

    def set_body(self, body: str) -> None:
        start, end = self._body_span()
        head = self.text[:start].rstrip("\n")
        body = body.strip("\n")
        self.text = (f"{head}\n\n{body}" if head and body else head or body).strip("\n")

    # ----- cells (columns / rows) ----------------------------------------
    def cell_spans(self) -> list[tuple[int, int]]:
        """Spans of column/row cells in the body, split on ``|||`` and ``===``.

        Place blocks are masked first so separators inside them are ignored.
        """
        start, end = self._body_span()
        body = self.text[start:end]
        masked = body
        for ref in self._place_refs_in(body):
            masked = masked[: ref.start] + " " * (ref.end - ref.start) + masked[ref.end:]
        cuts = sorted(
            [m for m in _COLUMN_SPLIT_RE.finditer(masked)] + [m for m in _ROW_SPLIT_RE.finditer(masked)],
            key=lambda m: m.start(),
        )
        spans = []
        pos = 0
        for m in cuts:
            spans.append((start + pos, start + m.start()))
            pos = m.end()
        spans.append((start + pos, end))
        return spans

    def get_cell(self, i: int) -> str:
        s, e = self.cell_spans()[i]
        return _strip_place_blocks(self.text[s:e]).strip("\n")

    def set_cell(self, i: int, value: str) -> None:
        spans = self.cell_spans()
        s, e = spans[i]
        old = self.text[s:e]
        # keep the place blocks that live in this cell
        kept = "\n\n".join(self.text[s + r.start : s + r.end].strip("\n") for r in self._place_refs_in(old))
        value = value.strip("\n")
        if kept:
            value = f"{value}\n\n{kept}" if value else kept
        lead = "\n" if s > 0 and not old.startswith("\n") else ("\n\n" if s > 0 else "")
        trail = "\n\n" if e < len(self.text) else ""
        if s == 0:
            lead = ""
        self.text = (self.text[:s] + lead + value + trail + self.text[e:]).strip("\n")

    # ----- place blocks -----------------------------------------------------
    @staticmethod
    def _place_refs_in(text: str) -> list[PlaceRef]:
        refs = []
        for i, m in enumerate(place.PLACE_FENCE_RE.finditer(text)):
            refs.append(PlaceRef(i, m.start(), m.end(), place.parse_spec(m.group(1))))
        return refs

    def place_refs(self) -> list[PlaceRef]:
        return self._place_refs_in(self.text)

    def get_place(self, i: int) -> place.PlaceSpec:
        return self.place_refs()[i].spec

    def set_place(self, i: int, spec: place.PlaceSpec) -> None:
        ref = self.place_refs()[i]
        block = spec.to_markdown()
        raw = self.text[ref.start : ref.end]
        trail = "\n" if raw.endswith("\n") else ""
        self.text = self.text[: ref.start] + block + trail + self.text[ref.end :]

    def add_place(self, spec: place.PlaceSpec) -> int:
        refs = self.place_refs()
        self.text = self.text.rstrip("\n") + "\n\n" + spec.to_markdown()
        return len(refs)

    def remove_place(self, i: int) -> None:
        ref = self.place_refs()[i]
        self.text = re.sub(r"\n{3,}", "\n\n", self.text[: ref.start] + self.text[ref.end :]).strip("\n")


def _strip_place_blocks(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", place.PLACE_FENCE_RE.sub("", text))


@dataclass
class DeckDocument:
    """A deck file as frontmatter + slide chunks + separators."""

    path: Path
    frontmatter: str = ""
    slides: list[SlideChunk] = field(default_factory=list)
    separators: list[str] = field(default_factory=list)
    trailing: str = "\n"

    @classmethod
    def load(cls, path: str | Path) -> "DeckDocument":
        path = Path(path)
        return cls.from_text(path.read_text(encoding="utf-8"), path)

    @classmethod
    def from_text(cls, text: str, path: str | Path = "deck.md") -> "DeckDocument":
        doc = cls(path=Path(path))
        fm = _FRONTMATTER_RE.match(text)
        body = text
        if fm:
            doc.frontmatter = fm.group(1)
            body = text[fm.end():]
        # trailing whitespace of the file is restored verbatim on save
        stripped = body.rstrip()
        doc.trailing = body[len(stripped):] or "\n"
        body = stripped
        parts = _SEPARATOR_RE.split(body)
        chunks = parts[0::2]
        seps = parts[1::2]
        # Leading blank lines before the first slide belong to the frontmatter gap.
        if chunks and not chunks[0].strip():
            doc.frontmatter += chunks[0] + (seps[0] if seps else "")
            chunks = chunks[1:]
            seps = seps[1:]
        # Chunks are stored stripped of surrounding blank lines; that whitespace
        # moves into the neighbouring separators so the round trip stays exact
        # while slide operations (duplicate, insert) see normalized text.
        stripped_chunks = []
        full_seps = []
        for i, c in enumerate(chunks):
            core = c.strip("\n")
            lead = c[: len(c) - len(c.lstrip("\n"))]
            trail = c[len(c.rstrip("\n")):]
            if i == 0:
                doc.frontmatter += lead
            else:
                full_seps[-1] += lead
            stripped_chunks.append(core)
            if i < len(seps):
                full_seps.append(trail + seps[i])
            else:
                doc.trailing = trail + doc.trailing
        doc.slides = [SlideChunk(c) for c in stripped_chunks]
        doc.separators = full_seps
        return doc

    def to_text(self) -> str:
        out = [self.frontmatter]
        for i, chunk in enumerate(self.slides):
            out.append(chunk.text)
            if i < len(self.slides) - 1:
                sep = self.separators[i] if i < len(self.separators) else DEFAULT_SEPARATOR
                out.append(sep)
        return "".join(out) + self.trailing

    def save(self) -> None:
        self.path.write_text(self.to_text(), encoding="utf-8")

    @property
    def base_dir(self) -> Path:
        return self.path.parent

    # ----- slide-level operations --------------------------------------------
    def _normalize_separators(self) -> None:
        need = max(len(self.slides) - 1, 0)
        self.separators = (self.separators + [DEFAULT_SEPARATOR] * need)[:need]

    def insert_slide(self, index: int, text: str = "## New slide\n\nContent") -> None:
        self.slides.insert(index, SlideChunk(text.strip("\n")))
        self.separators.insert(min(index, len(self.separators)), DEFAULT_SEPARATOR)
        self._normalize_separators()

    def duplicate_slide(self, index: int) -> None:
        self.insert_slide(index + 1, self.slides[index].text)

    def delete_slide(self, index: int) -> None:
        del self.slides[index]
        if self.separators:
            del self.separators[min(index, len(self.separators) - 1)]
        self._normalize_separators()

    def move_slide(self, src: int, dst: int) -> None:
        chunk = self.slides.pop(src)
        self.slides.insert(dst, chunk)
        self._normalize_separators()
