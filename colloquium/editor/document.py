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

    def _kept_spans(self, text: str) -> list[tuple[int, int]]:
        """Spans of blocks the cell editor hides but must preserve.

        Place blocks and px-positioned HTML elements have their own editing
        paths; cell text editing works on everything else.
        """
        spans = [(r.start, r.end) for r in self._place_refs_in(text)]
        masked = text
        for a, b in spans:
            masked = masked[:a] + " " * (b - a) + masked[b:]
        spans += [(m.start(), m.end()) for m in _HTML_ABS_RE.finditer(masked)]
        return sorted(spans)

    def get_cell(self, i: int) -> str:
        s, e = self.cell_spans()[i]
        text = self.text[s:e]
        for a, b in reversed(self._kept_spans(text)):
            text = text[:a] + text[b:]
        return re.sub(r"\n{3,}", "\n\n", text).strip("\n")

    def set_cell(self, i: int, value: str) -> None:
        spans = self.cell_spans()
        s, e = spans[i]
        old = self.text[s:e]
        # keep the place blocks / positioned HTML that live in this cell
        kept_spans = self._kept_spans(old)
        kept = "\n".join(old[a:b].strip("\n") for a, b in kept_spans)
        value = value.strip("\n")
        if kept:
            # Kept blocks stay at the top when they were only preceded by
            # directives/blank lines (the common "annotations first" layout),
            # otherwise they go to the end of the cell.
            prefix = old[: kept_spans[0][0]]
            prefix_is_head = not _DIRECTIVE_RE.sub("", prefix).strip()
            if prefix_is_head and value:
                # Re-emit as many leading directives as originally preceded
                # the kept blocks, then the kept blocks, then the rest.
                n_head = len(_DIRECTIVE_RE.findall(prefix))
                cut = 0
                for k, m in enumerate(_DIRECTIVE_RE.finditer(value)):
                    if k >= n_head or value[cut:m.start()].strip():
                        break
                    cut = m.end()
                head = value[:cut].strip("\n")
                rest = value[cut:].strip("\n")
                value = "\n\n".join(x for x in [head, kept, rest] if x)
            else:
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

    # ----- raw absolutely positioned HTML ---------------------------------------
    def html_abs_refs(self) -> list[HtmlAbsRef]:
        refs = []
        masked = self.text
        for r in self._place_refs_in(self.text):
            masked = masked[: r.start] + " " * (r.end - r.start) + masked[r.end :]
        for i, m in enumerate(_HTML_ABS_RE.finditer(masked)):
            refs.append(
                HtmlAbsRef(
                    i, m.start(), m.end(), m.group("tag"), m.group("attrs"), m.group("style"),
                    m.group("inner"), m.start("inner"), m.end("inner"),
                )
            )
        return refs

    def set_html_abs_style(self, i: int, **props: str | None) -> None:
        """Update inline style declarations (value None removes the key)."""
        ref = self.html_abs_refs()[i]
        # keep original order for untouched keys, append new keys at the end
        order = [k for k, _ in ref.decls]
        out: list[tuple[str, str]] = []
        for k, v in ref.decls:
            if k in props:
                if props[k] is not None:
                    out.append((k, props[k]))
            else:
                out.append((k, v))
        for k, v in props.items():
            if k not in order and v is not None:
                out.append((k, v))
        new_style = format_inline_style(out)
        # replace only the style attribute value inside the opening tag
        tag_text = self.text[ref.start : ref.end]
        tag_text = tag_text.replace(f'style="{ref.style}"', f'style="{new_style}"', 1)
        self.text = self.text[: ref.start] + tag_text + self.text[ref.end :]

    def set_html_abs_inner(self, i: int, inner: str) -> None:
        ref = self.html_abs_refs()[i]
        self.text = self.text[: ref.inner_start] + inner + self.text[ref.inner_end :]

    def convert_html_abs_to_place(self, i: int) -> int:
        """Replace a px-positioned HTML element with an equivalent place block."""
        ref = self.html_abs_refs()[i]
        spec = place.PlaceSpec(
            x=round((ref.left_px or 0) / 12.8, 1),
            y=round((ref.top_px or 0) / 7.2, 1),
            w=round(ref.width_px / 12.8, 1) if ref.width_px else None,
            text=ref.inner.strip() + "\n",
            classes=ref.classes,
        )
        keep = [
            (k, v) for k, v in ref.decls
            if k not in {"position", "top", "left", "width", "max-width"}
        ]
        if keep:
            spec.style = format_inline_style(keep)
        before = self.text[: ref.start].rstrip(" \t")
        after = self.text[ref.end :]
        self.text = re.sub(r"\n{3,}", "\n\n", before.rstrip("\n") + "\n\n" + spec.to_markdown() + "\n" + after.lstrip(" \t")).strip("\n")
        return len(self.place_refs()) - 1

    # ----- stacking order (later in source = drawn on top) ----------------------
    def _swap_spans(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        """Swap two non-overlapping source spans, keeping everything between."""
        (a0, a1), (b0, b1) = sorted([a, b])
        t = self.text
        # spans may include a trailing newline; never move those
        while a1 > a0 and t[a1 - 1] == "\n":
            a1 -= 1
        while b1 > b0 and t[b1 - 1] == "\n":
            b1 -= 1
        self.text = t[:a0] + t[b0:b1] + t[a1:b0] + t[a0:a1] + t[b1:]

    def reorder_place(self, i: int, new_index: int) -> int:
        """Move place block *i* to position *new_index* among place blocks."""
        refs = self.place_refs()
        new_index = max(0, min(new_index, len(refs) - 1))
        step = 1 if new_index > i else -1
        while i != new_index:
            refs = self.place_refs()
            self._swap_spans((refs[i].start, refs[i].end), (refs[i + step].start, refs[i + step].end))
            i += step
        return i

    def reorder_html_abs(self, i: int, new_index: int) -> int:
        refs = self.html_abs_refs()
        new_index = max(0, min(new_index, len(refs) - 1))
        step = 1 if new_index > i else -1
        while i != new_index:
            refs = self.html_abs_refs()
            self._swap_spans((refs[i].start, refs[i].end), (refs[i + step].start, refs[i + step].end))
            i += step
        return i

    def duplicate_place(self, i: int, dx: float = 2.0, dy: float = 2.0) -> int:
        ref = self.place_refs()[i]
        spec = place.parse_spec(ref.spec.to_yaml())
        spec.x += dx
        spec.y += dy
        block = spec.to_markdown()
        end = ref.end
        while end > ref.start and self.text[end - 1] == "\n":
            end -= 1
        self.text = self.text[:end] + "\n\n" + block + self.text[end:]
        return i + 1

    def duplicate_html_abs(self, i: int, dx: float = 20, dy: float = 20) -> int:
        ref = self.html_abs_refs()[i]
        raw = self.text[ref.start : ref.end]
        self.text = self.text[: ref.end] + "\n" + raw + self.text[ref.end :]
        j = i + 1
        self.set_html_abs_style(
            j,
            left=f"{int((ref.left_px or 0) + dx)}px",
            top=f"{int((ref.top_px or 0) + dy)}px",
        )
        return j

    def append_raw(self, block: str) -> None:
        """Append a raw block (place block or HTML) to the end of the slide."""
        self.text = self.text.rstrip("\n") + "\n\n" + block.strip("\n")

    # ----- inline markdown / html images in the flow ---------------------------
    def flow_image_refs(self) -> list[tuple[int, int, str]]:
        """(start, end, src) of ``![alt](src)`` and ``<img src>`` outside place blocks."""
        masked = self.text
        for r in self._place_refs_in(self.text):
            masked = masked[: r.start] + " " * (r.end - r.start) + masked[r.end :]
        found = []
        for m in _MD_IMAGE_RE.finditer(masked):
            found.append((m.start(), m.end(), m.group("src")))
        for m in _HTML_IMG_RE.finditer(masked):
            found.append((m.start(), m.end(), m.group("src")))
        return sorted(found)

    def convert_flow_image_to_place(self, k: int, x: float, y: float, w: float) -> int:
        start, end, src = self.flow_image_refs()[k]
        # drop a figure/paragraph wrapper line if the image was alone on it
        line_start = self.text.rfind("\n", 0, start) + 1
        line_end = self.text.find("\n", end)
        line_end = len(self.text) if line_end == -1 else line_end
        line = self.text[line_start:line_end]
        if line.strip() == self.text[start:end].strip():
            start, end = line_start, line_end
        spec = place.PlaceSpec(x=round(x, 1), y=round(y, 1), w=round(w, 1), src=src)
        before = self.text[:start].rstrip(" \t")
        after = self.text[end:]
        self.text = re.sub(r"\n{3,}", "\n\n", before.rstrip("\n") + "\n\n" + after.lstrip("\n")).strip("\n")
        return self.add_place(spec)

    def add_place(self, spec: place.PlaceSpec) -> int:
        refs = self.place_refs()
        self.text = self.text.rstrip("\n") + "\n\n" + spec.to_markdown()
        return len(refs)

    def remove_place(self, i: int) -> None:
        ref = self.place_refs()[i]
        self.text = re.sub(r"\n{3,}", "\n\n", self.text[: ref.start] + self.text[ref.end :]).strip("\n")


# Raw HTML elements positioned with inline top/left (e.g. hand-written
# annotation callouts). Non-nested only: the inner content must not contain
# another tag of the same name.
_HTML_ABS_RE = re.compile(
    r"<(?P<tag>div|span|p)\b(?P<attrs>[^>]*\bstyle=\"(?P<style>[^\"]*\b(?:top|left)\s*:[^\"]*)\"[^>]*)>"
    r"(?P<inner>(?:(?!<(?P=tag)\b).)*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=\"(?P<src>[^\"]+)\"[^>]*>", re.IGNORECASE)
_CSS_DECL_RE = re.compile(r"\s*([a-zA-Z-]+)\s*:\s*([^;]*?)\s*(?:;|$)")


def parse_inline_style(style: str) -> list[tuple[str, str]]:
    return [(k.lower(), v) for k, v in _CSS_DECL_RE.findall(style) if k]


def format_inline_style(decls: list[tuple[str, str]]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in decls)


def _px(value: str) -> float | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*px\s*", value or "")
    return float(m.group(1)) if m else None


@dataclass
class HtmlAbsRef:
    """A raw HTML element with inline top/left, and its source span."""

    index: int
    start: int
    end: int
    tag: str
    attrs: str
    style: str
    inner: str
    inner_start: int
    inner_end: int

    @property
    def classes(self) -> list[str]:
        m = re.search(r'\bclass="([^"]*)"', self.attrs)
        return m.group(1).split() if m else []

    @property
    def decls(self) -> list[tuple[str, str]]:
        return parse_inline_style(self.style)

    def get(self, key: str) -> str | None:
        for k, v in self.decls:
            if k == key:
                return v
        return None

    @property
    def left_px(self) -> float | None:
        return _px(self.get("left") or "")

    @property
    def top_px(self) -> float | None:
        return _px(self.get("top") or "")

    @property
    def width_px(self) -> float | None:
        return _px(self.get("width") or "") or _px(self.get("max-width") or "")


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
