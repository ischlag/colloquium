"""Tests for the lossless editor document layer."""

from pathlib import Path

import pytest

from colloquium.editor.document import DeckDocument, SlideChunk
from colloquium.elements import place
from colloquium.parse import parse_markdown


ROOT = Path(__file__).resolve().parent.parent

DECK = """---
title: Demo
author: Me
---

<!-- layout: title -->

# Hello

Subtitle

---

<!-- columns: 60/40 -->

## Two columns

Left text.

```place
x: 5
y: 80
w: 30
text: |
  pinned
```

|||

Right text.

<!-- notes: speaker notes -->

---

## Plain

Body only.
"""


@pytest.mark.parametrize(
    "rel",
    [
        "demo.md",
        "examples/hello/hello.md",
        "examples/rows-and-columns/rows-and-columns.md",
        "examples/footnotes/footnotes.md",
        "examples/animations/animations.md",
        "examples/title-slides/title-slides.md",
    ],
)
def test_round_trip_is_byte_exact(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    doc = DeckDocument.from_text(text, rel)
    assert doc.to_text() == text
    assert len(doc.slides) == len(parse_markdown(text).slides)


def test_split_and_edit_only_touches_one_slide():
    doc = DeckDocument.from_text(DECK)
    assert len(doc.slides) == 3
    assert doc.to_text() == DECK
    doc.slides[2].set_title("Renamed")
    out = doc.to_text()
    assert out.count("## Renamed") == 1
    # everything before the last slide is untouched
    assert out.split("## Renamed")[0] == DECK.split("## Plain")[0]


def test_directive_set_replace_remove():
    chunk = SlideChunk("<!-- columns: 60/40 -->\n\n## T\n\nbody")
    assert chunk.get_directive("columns") == "60/40"
    chunk.set_directive("columns", "50/50")
    assert chunk.text == "<!-- columns: 50/50 -->\n\n## T\n\nbody"
    chunk.set_directive("align", "center")
    assert chunk.text.startswith("<!-- columns: 50/50 -->\n<!-- align: center -->\n\n## T")
    chunk.set_directive("columns", None)
    assert chunk.text == "<!-- align: center -->\n\n## T\n\nbody"
    chunk.set_directive("align", "")
    assert chunk.text == "## T\n\nbody"


def test_directive_added_to_slide_without_directives():
    chunk = SlideChunk("## T\n\nbody")
    chunk.set_directive("layout", "section-break")
    assert chunk.text == "<!-- layout: section-break -->\n## T\n\nbody"


def test_title_get_set():
    chunk = SlideChunk("<!-- layout: title -->\n\n# Hello\n\nSub")
    assert chunk.get_title() == "Hello"
    assert chunk.title_level() == 1
    chunk.set_title("Bye")
    assert chunk.text == "<!-- layout: title -->\n\n# Bye\n\nSub"
    chunk = SlideChunk("just body")
    chunk.set_title("New")
    assert chunk.text == "## New\n\njust body"


def test_body_excludes_title_and_leading_directives():
    chunk = SlideChunk("<!-- columns: 2 -->\n\n## T\n\nleft\n\n|||\n\nright\n\n<!-- notes: n -->")
    assert chunk.get_body() == "left\n\n|||\n\nright\n\n<!-- notes: n -->"
    chunk.set_body("only")
    assert chunk.text == "<!-- columns: 2 -->\n\n## T\n\nonly"


def test_cells_split_and_edit_keep_place_blocks():
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    assert len(chunk.cell_spans()) == 2
    assert chunk.get_cell(0) == "Left text."
    assert chunk.get_cell(1) == "Right text.\n\n<!-- notes: speaker notes -->"
    chunk.set_cell(0, "Left edited.")
    assert len(chunk.place_refs()) == 1
    assert chunk.get_cell(0) == "Left edited."
    assert chunk.get_cell(1) == "Right text.\n\n<!-- notes: speaker notes -->"
    deck = parse_markdown(doc.to_text())
    assert "Left edited." in deck.slides[1].content
    chunk.set_cell(1, "Right edited.")
    assert chunk.get_cell(1) == "Right edited."


def test_place_update_add_remove():
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    spec = chunk.get_place(0)
    assert spec.x == 5 and spec.text.strip() == "pinned"
    spec.x = 12.5
    spec.y = 70
    chunk.set_place(0, spec)
    again = chunk.get_place(0)
    assert again.x == 12.5 and again.y == 70 and again.text.strip() == "pinned"
    # surrounding content intact
    assert chunk.get_cell(0) == "Left text."
    assert chunk.get_cell(1).startswith("Right text.")

    i = chunk.add_place(place.PlaceSpec(x=1, y=2, w=3, src="a.png"))
    assert i == 1
    assert chunk.get_place(1).src == "a.png"
    chunk.remove_place(0)
    assert len(chunk.place_refs()) == 1
    assert chunk.get_place(0).src == "a.png"
    assert "pinned" not in chunk.text


def test_slide_operations():
    doc = DeckDocument.from_text(DECK)
    doc.duplicate_slide(2)
    assert len(doc.slides) == 4
    assert doc.slides[3].text == doc.slides[2].text
    doc.move_slide(3, 0)
    assert doc.slides[0].get_title() == "Plain"
    doc.delete_slide(0)
    assert len(doc.slides) == 3
    assert doc.to_text() == DECK
    doc.insert_slide(1)
    assert doc.slides[1].get_title() == "New slide"
    assert len(parse_markdown(doc.to_text()).slides) == 4
