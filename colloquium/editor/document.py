"""Lossless, string-level editing of a colloquium markdown deck.

The editor never round-trips through ``Slide``/``Deck`` objects (that path is
lossy: columns, rows and most directives become CSS classes). Instead the file
is split into frontmatter, raw slide chunks and the separators between them,
and every edit is a targeted rewrite inside one chunk. Untouched slides are
emitted byte for byte, so git diffs only show what actually changed.
"""

from __future__ import annotations

import re

import yaml
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
_CUSTOM_CSS_BLOCK_RE = re.compile(r"^custom_css:[ \t]*\|[-+]?[ \t]*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)", re.MULTILINE)
_CELL_STYLE_RE = re.compile(r"<!--\s*cell-style\s*:\s*(.*?)\s*-->[ \t]*\n?", re.DOTALL)
_ROW_COLUMNS_RE = re.compile(r"<!--\s*row-columns\s*:\s*(.*?)\s*-->", re.DOTALL)

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

    @property
    def is_master(self) -> bool:
        """True for a theme slide (``<!-- master: true -->``)."""
        v = (self.get_directive("master") or "").strip().lower()
        return bool(v) and v not in {"off", "false", "no", "0", "none"}

    def _delete_span(self, a: int, b: int) -> None:
        """Remove text[a:b] and collapse the blank lines it leaves behind."""
        head, tail = self.text[:a], self.text[b:]
        if head.endswith("\n\n") and tail.startswith("\n"):
            tail = tail.lstrip("\n")
        elif head.endswith("\n") and tail.startswith("\n\n"):
            head = head.rstrip("\n") + "\n"
        self.text = head + tail

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
            # Drop duplicates first, from the back, while their offsets are valid.
            for extra in reversed(matches[1:]):
                self._delete_span(extra.start(), extra.end())
            m = matches[0]
            if value:
                replacement = f"<!-- {key}: {value} -->"
                # keep whatever followed the directive (newline) intact
                tail = m.group(0)[len(m.group(0).rstrip("\n \t")):]
                self.text = self.text[: m.start()] + replacement + tail + self.text[m.end():]
            else:
                self._delete_span(m.start(), m.end())
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
        masked = _mask_fences(body)
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
        """Spans the cell editor hides but must preserve: the place blocks."""
        return [(r.start, r.end) for r in self._place_refs_in(text)]

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
        # keep the place blocks that live in this cell
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


    # ----- per-cell style -----------------------------------------------------
    def get_cell_style(self, i: int) -> str:
        """Inline CSS applied to cell *i* via a ``<!-- cell-style: ... -->`` comment."""
        s, e = self.cell_spans()[i]
        m = _CELL_STYLE_RE.search(self.text[s:e])
        return m.group(1).strip() if m else ""

    def set_cell_style(self, i: int, value: str) -> None:
        """Set the full ``<!-- cell-style: ... -->`` of cell *i* (empty removes it)."""
        s, e = self.cell_spans()[i]
        seg = self.text[s:e]
        m = _CELL_STYLE_RE.search(seg)
        new = value.strip().rstrip(";")
        if m:
            if new:
                trail = "\n" if m.group(0).endswith("\n") else ""
                seg = seg[: m.start()] + f"<!-- cell-style: {new} -->{trail}" + seg[m.end():]
            else:
                seg = re.sub(r"\n{3,}", "\n\n", seg[: m.start()] + seg[m.end():])
        elif new:
            k = 0
            while k < len(seg) and seg[k] == "\n":
                k += 1
            seg = seg[:k] + f"<!-- cell-style: {new} -->\n\n" + seg[k:]
        else:
            return
        self.text = (self.text[:s] + seg + self.text[e:]).strip("\n")

    def set_cell_style_props(self, i: int, **props: str | None) -> None:
        self.set_cell_style(i, update_style(self.get_cell_style(i), **props))

    # ----- flow blocks (markdown blocks as objects) ---------------------------
    # ----- flow blocks (what the browser renders as top-level elements) ------
    def cell_blocks(self, i: int) -> list["Block"]:
        """The blocks of cell *i*, in the order the browser renders them.

        Uses markdown-it's own block tokenizer so the list matches the
        rendered top-level elements one to one; raw HTML blocks are split
        into their top-level elements. Place blocks are masked out (they
        render into their own layer) and comments render nothing.
        """
        s, e = self.cell_spans()[i]
        seg = self.text[s:e]
        masked = seg
        for a, b in self._kept_spans(seg):
            masked = masked[:a] + re.sub(r"[^\n]", " ", masked[a:b]) + masked[b:]
        line_starts = [0] + [m.end() for m in re.finditer(r"\n", masked)]

        def span(a: int, b: int) -> tuple[int, int]:
            start = line_starts[a] if a < len(line_starts) else len(masked)
            end = line_starts[b] if b < len(line_starts) else len(masked)
            while end > start and masked[end - 1] in " \t\n":
                end -= 1
            while start < end and masked[start] in " \t":
                start += 1
            return start, end

        out: list[Block] = []
        for t in _md().parse(masked):
            if t.level != 0 or t.nesting == -1 or t.map is None:
                continue
            a, b = span(t.map[0], t.map[1])
            if b <= a:
                continue
            if t.type == "html_block":
                out.extend(_html_elements(masked, a, b))
            else:
                out.append(Block(a, b, "md"))
        for blk in out:
            blk.start += s
            blk.end += s
            blk.inner_start += s
            blk.inner_end += s
        return out

    def cell_flow_blocks(self, i: int) -> list[tuple[int, int]]:
        return [(b.start, b.end) for b in self.cell_blocks(i)]

    def get_cell_block(self, i: int, j: int) -> str:
        blk = self.cell_blocks(i)[j]
        return self.text[blk.start:blk.end]

    def set_cell_block(self, i: int, j: int, value: str) -> None:
        blk = self.cell_blocks(i)[j]
        value = value.strip("\n")
        if value:
            self.text = self.text[: blk.start] + value + self.text[blk.end :]
        else:
            self._delete_span(blk.start, blk.end)
        self.text = self.text.strip("\n")

    def remove_cell_block(self, i: int, j: int) -> None:
        blk = self.cell_blocks(i)[j]
        self._delete_span(blk.start, blk.end)
        self.text = self.text.strip("\n")

    def convert_cell_block_to_place(self, i: int, j: int, x: float, y: float, w: float) -> int:
        """Lift a flow block out of the cell into a ```place block.

        A px-positioned HTML element keeps its own position, classes and
        remaining style; an image-only block becomes a placed image; anything
        else becomes placed text at the given box.
        """
        blk = self.cell_blocks(i)[j]
        text = self.text[blk.start:blk.end].strip("\n")
        spec = place.PlaceSpec(x=round(x, 1), y=round(y, 1), w=round(w, 1))
        if blk.kind == "html" and blk.positioned:
            spec.x = round((blk.px("left") or 0) / 12.8, 1)
            spec.y = round((blk.px("top") or 0) / 7.2, 1)
            width = blk.px("width") or blk.px("max-width")
            spec.w = round(width / 12.8, 1) if width else None
            spec.text = self.text[blk.inner_start:blk.inner_end].strip() + "\n"
            spec.classes = blk.classes
            keep = [(k, v) for k, v in parse_inline_style(blk.style) if k not in {"position", "top", "left", "width", "max-width"}]
            if keep:
                spec.style = format_inline_style(keep)
        else:
            m = _MD_IMAGE_RE.fullmatch(text) or _HTML_IMG_RE.fullmatch(text)
            if m:
                spec.src = m.group("src")
            else:
                spec.text = text + "\n"
        self._delete_span(blk.start, blk.end)
        self.text = self.text.strip("\n")
        return self.add_place(spec)

    # ----- images inside a block ----------------------------------------------
    def block_images(self, i: int, j: int) -> list[tuple[int, int, str]]:
        """(start, end, src) of the images inside block *j*, in DOM order."""
        blk = self.cell_blocks(i)[j]
        seg = self.text[blk.start:blk.end]
        found = [(m.start(), m.end(), m.group("src")) for m in _MD_IMAGE_RE.finditer(seg)]
        found += [(m.start(), m.end(), m.group("src")) for m in _HTML_IMG_RE.finditer(seg)]
        return [(blk.start + a, blk.start + b, src) for a, b, src in sorted(found)]

    def set_block_image_size(self, i: int, j: int, k: int, width_px: float | None = None, height_px: float | None = None) -> None:
        """Resize an inline image by writing an explicit width or height.

        Markdown images become ``<img>`` tags (markdown has no size syntax);
        the other dimension is cleared so the aspect ratio is preserved.
        """
        start, end, src = self.block_images(i, j)[k]
        raw = self.text[start:end]
        props: dict[str, str | None] = {}
        if width_px is not None:
            props.update(width=f"{int(round(width_px))}px", height=None)
        if height_px is not None:
            props.update(height=f"{int(round(height_px))}px", width=None)
        m = _HTML_IMG_RE.fullmatch(raw)
        if m:
            sm = re.search(r'\sstyle="([^"]*)"', raw)
            if sm:
                new_style = update_style(sm.group(1), **props)
                tag = raw[: sm.start()] + f' style="{new_style}"' + raw[sm.end():]
            else:
                new_style = update_style("", **props)
                tag = raw[:-1].rstrip("/").rstrip() + f' style="{new_style}">'
        else:
            mm = _MD_IMAGE_RE.fullmatch(raw)
            alt = re.match(r"!\[([^\]]*)\]", raw).group(1) if mm else ""
            alt_attr = f' alt="{alt}"' if alt else ""
            tag = f'<img src="{src}"{alt_attr} style="{update_style("", **props)}">'
        self.text = self.text[:start] + tag + self.text[end:]

    def convert_block_image_to_place(self, i: int, j: int, k: int, x: float, y: float, w: float) -> int:
        """Lift one image out of a block into a placed image at the given box."""
        blk = self.cell_blocks(i)[j]
        start, end, src = self.block_images(i, j)[k]
        rest = (self.text[blk.start:start] + self.text[end:blk.end]).strip()
        spec = place.PlaceSpec(x=round(x, 1), y=round(y, 1), w=round(w, 1), src=src)
        if rest:
            self.text = self.text[:start] + self.text[end:]
        else:
            self._delete_span(blk.start, blk.end)
        self.text = self.text.strip("\n")
        return self.add_place(spec)

    # ----- rows and grid fractions --------------------------------------------
    def row_spans(self) -> list[tuple[int, int]]:
        """Spans of ``===``-separated rows in the body (place blocks masked)."""
        start, end = self._body_span()
        body = self.text[start:end]
        masked = body
        for ref in self._place_refs_in(body):
            masked = masked[: ref.start] + " " * (ref.end - ref.start) + masked[ref.end :]
        spans = []
        pos = 0
        for m in _ROW_SPLIT_RE.finditer(masked):
            spans.append((start + pos, start + m.start()))
            pos = m.end()
        spans.append((start + pos, end))
        return spans

    def set_row_columns(self, row: int, value: str) -> None:
        """Set the ``<!-- row-columns: ... -->`` spec inside row *row*."""
        a, b = self.row_spans()[row]
        seg = self.text[a:b]
        m = _ROW_COLUMNS_RE.search(seg)
        if m:
            seg = seg[: m.start()] + f"<!-- row-columns: {value} -->" + seg[m.end() :]
        else:
            k = 0
            while k < len(seg) and seg[k] == "\n":
                k += 1
            seg = seg[:k] + f"<!-- row-columns: {value} -->\n\n" + seg[k:]
        self.text = (self.text[:a] + seg + self.text[b:]).strip("\n")

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
        if spec.error:
            raise ValueError("This place block has invalid YAML; fix it in the raw markdown first")
        ref = self.place_refs()[i]
        block = spec.to_markdown()
        raw = self.text[ref.start : ref.end]
        trail = "\n" if raw.endswith("\n") else ""
        self.text = self.text[: ref.start] + block + trail + self.text[ref.end :]

    # ----- raw absolutely positioned HTML ---------------------------------------
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

    def append_raw(self, block: str) -> None:
        """Append a raw block (place block or HTML) to the end of the slide."""
        self.text = self.text.rstrip("\n") + "\n\n" + block.strip("\n")

    # ----- inline markdown / html images in the flow ---------------------------
    def set_place_style_props(self, i: int, **props: str | None) -> None:
        """Update CSS declarations in a place block's ``style:`` (None removes)."""
        spec = self.get_place(i)
        spec.style = update_style(spec.style, **props)
        self.set_place(i, spec)

    def add_place(self, spec: place.PlaceSpec) -> int:
        refs = self.place_refs()
        self.text = self.text.rstrip("\n") + "\n\n" + spec.to_markdown()
        return len(refs)

    def remove_place(self, i: int) -> None:
        ref = self.place_refs()[i]
        self.text = re.sub(r"\n{3,}", "\n\n", self.text[: ref.start] + self.text[ref.end :]).strip("\n")


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=\"(?P<src>[^\"]+)\"[^>]*>", re.IGNORECASE)
_CSS_DECL_RE = re.compile(r"\s*([a-zA-Z-]+)\s*:\s*([^;]*?)\s*(?:;|$)")


_POS_DECL_RE = re.compile(r"(?<![\w-])(?:top|left)\s*:")
_TAG_RE = re.compile(r"<!--.*?-->|<(/?)([a-zA-Z][\w-]*)([^<>]*?)(/?)>", re.DOTALL)
_VOID_TAGS = {"img", "br", "hr", "input", "source", "meta", "link", "area", "base", "col", "embed", "track", "wbr"}
_md_instance = None


def _md():
    global _md_instance
    if _md_instance is None:
        from colloquium.md import create_base_md

        _md_instance = create_base_md()
    return _md_instance


@dataclass
class Block:
    """One rendered top-level element of a cell and where it lives in the source."""

    start: int
    end: int
    kind: str                 # "md" (markdown block) or "html" (raw element)
    tag: str = ""
    attrs: str = ""
    style: str = ""
    inner_start: int = 0
    inner_end: int = 0

    @property
    def positioned(self) -> bool:
        return self.kind == "html" and _POS_DECL_RE.search(self.style) is not None

    @property
    def classes(self) -> list[str]:
        m = re.search(r"""\bclass\s*=\s*("([^"]*)"|'([^']*)')""", self.attrs)
        return (m.group(2) or m.group(3) or "").split() if m else []

    def px(self, key: str) -> float | None:
        return _px(dict(parse_inline_style(self.style)).get(key, ""))


def _style_of(attrs: str) -> str:
    m = re.search(r"""\bstyle\s*=\s*("([^"]*)"|'([^']*)')""", attrs)
    return (m.group(2) or m.group(3) or "").strip() if m else ""


def _html_elements(text: str, a: int, b: int) -> list[Block]:
    """Top-level elements of the raw HTML in text[a:b] (comments and bare text render no element)."""
    out: list[Block] = []
    stack: list[str] = []
    cur: tuple[int, str, str, int] | None = None
    for m in _TAG_RE.finditer(text, a, b):
        if m.group(0).startswith("<!--"):
            continue
        closing, tag, attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if not closing:
            if tag in _VOID_TAGS or selfclose:
                if not stack:
                    out.append(Block(m.start(), m.end(), "html", tag, attrs, _style_of(attrs), m.end(), m.end()))
                continue
            if not stack:
                cur = (m.start(), tag, attrs, m.end())
            stack.append(tag)
        elif tag in stack:
            while stack and stack.pop() != tag:
                pass
            if not stack and cur:
                out.append(Block(cur[0], m.end(), "html", cur[1], cur[2], _style_of(cur[2]), cur[3], m.start()))
                cur = None
    return out


def _mask_fences(text: str) -> str:
    """Blank out the lines inside fenced code so separators there are ignored."""
    out = []
    fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            fence = not fence
            out.append(re.sub(r"[^\n]", " ", line))
        elif fence:
            out.append(re.sub(r"[^\n]", " ", line))
        else:
            out.append(line)
    return "".join(out)


def parse_inline_style(style: str) -> list[tuple[str, str]]:
    return [(k.lower(), v) for k, v in _CSS_DECL_RE.findall(style) if k]


def format_inline_style(decls: list[tuple[str, str]]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in decls)


def update_style(style: str, **props: str | None) -> str:
    """Return *style* with declarations set/removed; untouched keys keep their order."""
    props = {k.replace("_", "-"): v for k, v in props.items()}
    out: list[tuple[str, str]] = []
    seen = set()
    for k, v in parse_inline_style(style):
        if k in props:
            seen.add(k)
            if props[k] is not None:
                out.append((k, props[k]))
        else:
            out.append((k, v))
    for k, v in props.items():
        if k not in seen and v is not None:
            out.append((k, v))
    return format_inline_style(out)


def format_grid_fractions(fractions: list[float]) -> str:
    """Format measured track sizes as an integer percent spec like ``62/38``."""
    vals = [max(1.0, float(f)) for f in fractions]
    total = sum(vals)
    ints = [max(2, int(round(v * 100.0 / total))) for v in vals]
    ints[ints.index(max(ints))] += 100 - sum(ints)
    return "/".join(str(v) for v in ints)


def _px(value: str) -> float | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*px\s*", value or "")
    return float(m.group(1)) if m else None


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

    def master_indices(self) -> list[int]:
        return [i for i, c in enumerate(self.slides) if c.is_master]

    def add_master_slide(self) -> int:
        """Insert a theme slide at the top and return its index."""
        self.insert_slide(0, "<!-- master: true -->")
        return 0

    # ----- frontmatter ----------------------------------------------------------
    def frontmatter_data(self) -> dict:
        m = re.search(r"\A\s*---[ \t]*\n(.*?)\n---[ \t]*\n", self.frontmatter, re.DOTALL)
        if not m:
            return {}
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}

    def get_custom_css(self) -> str:
        v = self.frontmatter_data().get("custom_css")
        return v if isinstance(v, str) else ""

    def set_custom_css(self, css: str) -> None:
        """Rewrite the ``custom_css: |`` block string-level; other keys untouched."""
        css = css.rstrip("\n")
        block = ""
        if css:
            block = "custom_css: |\n" + "".join(("  " + line if line.strip() else "") + "\n" for line in css.split("\n"))
        m = _CUSTOM_CSS_BLOCK_RE.search(self.frontmatter)
        if m:
            self.frontmatter = self.frontmatter[: m.start()] + block + self.frontmatter[m.end():]
            return
        if "custom_css" in self.frontmatter_data():
            raise ValueError("custom_css is not written as a `custom_css: |` block; edit the frontmatter by hand")
        if not block:
            return
        fm = re.match(r"\A(\s*---[ \t]*\n.*?\n)(---[ \t]*\n)", self.frontmatter, re.DOTALL)
        if fm:
            self.frontmatter = self.frontmatter[: fm.end(1)] + block + self.frontmatter[fm.end(1):]
        else:
            self.frontmatter = "---\n" + block + "---\n\n" + self.frontmatter

    def move_slide(self, src: int, dst: int) -> None:
        chunk = self.slides.pop(src)
        self.slides.insert(dst, chunk)
        self._normalize_separators()
