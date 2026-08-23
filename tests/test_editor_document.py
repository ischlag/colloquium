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


ANNO_DECK = """## Landscape

<!-- class: landscape -->

<div class="anno" style="top: 368px; left: 40px; max-width: 300px"><span class="anno-mark">*</span> Promised, never delivered.</div>
<div class="anno" style="top: 615px; left: 396px; max-width: 330px">Restrictive licence.</div>

<!-- columns: 2 -->

### Closed

OpenAI<br>
xAI

|||

### Open

DeepSeek
"""


def test_html_abs_refs_and_style_update():
    doc = DeckDocument.from_text(ANNO_DECK)
    chunk = doc.slides[0]
    refs = chunk.html_abs_refs()
    assert [(r.left_px, r.top_px, r.width_px) for r in refs] == [(40, 368, 300), (396, 615, 330)]
    assert refs[0].classes == ["anno"]
    chunk.set_html_abs_style(1, left="525px", top="472px", width="250px", **{"max-width": None})
    assert 'style="top: 472px; left: 525px; width: 250px"' in chunk.text
    chunk.set_html_abs_inner(0, "Edited <b>inner</b>")
    assert chunk.html_abs_refs()[0].inner == "Edited <b>inner</b>"
    # untouched parts are byte-identical
    assert chunk.text.count("Restrictive licence.") == 1
    assert "### Closed\n\nOpenAI<br>\nxAI" in chunk.text


def test_cell_edit_hides_and_preserves_positioned_html():
    doc = DeckDocument.from_text(ANNO_DECK)
    chunk = doc.slides[0]
    cell = chunk.get_cell(0)
    assert "anno" not in cell
    assert cell.startswith("<!-- class: landscape -->")
    chunk.set_cell(0, cell.replace("xAI", "xAI (Grok)"))
    expected = ANNO_DECK.replace("xAI\n", "xAI (Grok)\n").strip("\n")
    assert chunk.text == expected
    chunk.set_cell(0, chunk.get_cell(0))
    assert chunk.text == expected


def test_convert_html_abs_to_place():
    doc = DeckDocument.from_text(ANNO_DECK)
    chunk = doc.slides[0]
    idx = chunk.convert_html_abs_to_place(1)
    assert idx == 0
    spec = chunk.get_place(0)
    assert spec.classes == ["anno"]
    assert spec.x == round(396 / 12.8, 1) and spec.y == round(615 / 7.2, 1)
    assert spec.w == round(330 / 12.8, 1)
    assert spec.text.strip() == "Restrictive licence."
    assert len(chunk.html_abs_refs()) == 1
    assert len(parse_markdown(doc.to_text()).slides) == 1


def test_reorder_place_and_html():
    text = "## T\n\n```place\nx: 1\ny: 1\ntext: |\n  A\n```\n\nmiddle\n\n```place\nx: 2\ny: 2\ntext: |\n  B\n```\n\n```place\nx: 3\ny: 3\ntext: |\n  C\n```"
    chunk = SlideChunk(text)
    assert chunk.reorder_place(0, 2) == 2
    assert [r.spec.text.strip() for r in chunk.place_refs()] == ["B", "C", "A"]
    assert "\n\nmiddle\n\n" in chunk.text
    assert chunk.reorder_place(2, 0) == 0
    assert chunk.text == text
    doc = DeckDocument.from_text(ANNO_DECK)
    c = doc.slides[0]
    c.reorder_html_abs(0, 1)
    refs = c.html_abs_refs()
    assert refs[0].inner == "Restrictive licence." and refs[1].inner.endswith("never delivered.")
    c.reorder_html_abs(1, 0)
    assert c.text == ANNO_DECK.strip("\n")


def test_duplicate_and_paste():
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    j = chunk.duplicate_place(0)
    assert j == 1
    refs = chunk.place_refs()
    assert len(refs) == 2 and refs[1].spec.x == 7 and refs[1].spec.y == 82
    assert chunk.get_cell(0) == "Left text." and chunk.get_cell(1).startswith("Right text.")
    c = DeckDocument.from_text(ANNO_DECK).slides[0]
    j = c.duplicate_html_abs(0)
    refs = c.html_abs_refs()
    assert j == 1 and len(refs) == 3 and (refs[1].left_px, refs[1].top_px) == (60, 388)
    c.append_raw(refs[0].inner and '<div class="anno" style="top: 1px; left: 2px">pasted</div>')
    assert c.html_abs_refs()[-1].inner == "pasted"


def test_convert_flow_image_to_place():
    chunk = SlideChunk("## T\n\nIntro.\n\n![A figure](images/fig.png)\n\nAfter.")
    assert [r[2] for r in chunk.flow_image_refs()] == ["images/fig.png"]
    idx = chunk.convert_flow_image_to_place(0, 10, 20, 40)
    assert idx == 0
    assert "![A figure]" not in chunk.text
    assert chunk.get_cell(0) == "Intro.\n\nAfter."
    spec = chunk.get_place(0)
    assert (spec.src, spec.x, spec.y, spec.w) == ("images/fig.png", 10, 20, 40)
