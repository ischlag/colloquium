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


def test_update_style_and_place_style_props():
    from colloquium.editor.document import update_style

    assert update_style("top: 1px; left: 2px", left="5px", color="red") == "top: 1px; left: 5px; color: red"
    assert update_style("top: 1px; left: 2px", top=None) == "left: 2px"
    assert update_style("", background_color="#fff") == "background-color: #fff"
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    chunk.set_place_style_props(0, color="#e4002b", border="1px solid #000")
    assert chunk.get_place(0).style == "color: #e4002b; border: 1px solid #000"
    chunk.set_place_style_props(0, color=None)
    assert chunk.get_place(0).style == "border: 1px solid #000"


def test_set_flow_image_size():
    chunk = SlideChunk("## T\n\n![A figure](images/fig.png)\n\n|||\n\n<img src=\"b.png\" alt=\"B\" style=\"height: 380px; width: auto; border-radius: 8px;\">")
    chunk.set_flow_image_size(0, width_px=512.4)
    assert '<img src="images/fig.png" alt="A figure" style="width: 512px">' in chunk.text
    chunk.set_flow_image_size(1, width_px=300)
    assert 'style="width: 300px; border-radius: 8px"' in chunk.text
    chunk.set_flow_image_size(1, height_px=200)
    assert 'style="border-radius: 8px; height: 200px"' in chunk.text
    assert [r[2] for r in chunk.flow_image_refs()] == ["images/fig.png", "b.png"]


def test_cell_style_get_set():
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    assert chunk.get_cell_style(0) == ""
    chunk.set_cell_style_props(0, **{"text-align": "center"})
    assert chunk.get_cell_style(0) == "text-align: center"
    assert "<!-- cell-style: text-align: center -->" in chunk.text
    chunk.set_cell_style_props(1, color="red")
    assert chunk.get_cell_style(1) == "color: red"
    assert chunk.get_cell_style(0) == "text-align: center"
    chunk.set_cell_style_props(0, **{"text-align": None})
    assert chunk.get_cell_style(0) == ""
    chunk.set_cell_style(1, "")
    assert doc.to_text().count("cell-style") == 0
    # surrounding content untouched
    assert chunk.get_cell(0) == "Left text."
    assert len(chunk.place_refs()) == 1


def test_cell_flow_blocks_and_convert():
    doc = DeckDocument.from_text(DECK)
    chunk = doc.slides[1]
    blocks0 = [chunk.text[a:b] for a, b in chunk.cell_flow_blocks(0)]
    assert blocks0 == ["Left text."]
    # notes directive is not a visible block
    blocks1 = [chunk.text[a:b] for a, b in chunk.cell_flow_blocks(1)]
    assert blocks1 == ["Right text."]
    chunk.set_cell_block(1, 0, "Right text edited.")
    assert chunk.get_cell_block(1, 0) == "Right text edited."
    assert "<!-- notes: speaker notes -->" in chunk.text
    idx = chunk.convert_cell_block_to_place(0, 0, 12, 34, 25)
    spec = chunk.get_place(idx)
    assert spec.text.strip() == "Left text." and spec.x == 12 and spec.w == 25
    assert chunk.get_cell(0) == ""


def test_convert_image_block_to_place():
    chunk = SlideChunk("## T\n\nIntro.\n\n![Fig](images/f.png)\n\nAfter.")
    blocks = chunk.cell_flow_blocks(0)
    assert len(blocks) == 3
    idx = chunk.convert_cell_block_to_place(0, 1, 5, 6, 40)
    spec = chunk.get_place(idx)
    assert spec.src == "images/f.png" and spec.kind == "image"
    assert chunk.get_cell(0) == "Intro.\n\nAfter."


def test_flow_blocks_skip_fences_and_kept_html():
    text = "## T\n\npara one\n\n```python\ncode\n\nstill code\n```\n\n<div class=\"anno\" style=\"top: 1px; left: 2px\">pinned</div>\n\nlast"
    chunk = SlideChunk(text)
    blocks = [chunk.text[a:b] for a, b in chunk.cell_flow_blocks(0)]
    assert blocks == ["para one", "```python\ncode\n\nstill code\n```", "last"]


def test_row_spans_and_row_columns():
    text = "## T\n\n<!-- rows: 30/70 -->\n\nTop.\n\n===\n\n<!-- row-columns: 40/60 -->\n\nA\n\n|||\n\nB"
    doc = DeckDocument.from_text(text)
    chunk = doc.slides[0]
    assert len(chunk.row_spans()) == 2
    chunk.set_row_columns(1, "55/45")
    assert "<!-- row-columns: 55/45 -->" in chunk.text
    assert chunk.text.count("row-columns") == 1
    chunk.set_row_columns(0, "20/80")
    rows = chunk.row_spans()
    assert "<!-- row-columns: 20/80 -->" in chunk.text[rows[0][0]:rows[0][1]]


def test_format_grid_fractions():
    from colloquium.editor.document import format_grid_fractions

    assert format_grid_fractions([60, 40]) == "60/40"
    assert format_grid_fractions([615.2, 380.1]) == "62/38"
    assert format_grid_fractions([1, 1, 1]) == "34/33/33"
    total = sum(int(x) for x in format_grid_fractions([3.3, 96.7]).split("/"))
    assert total == 100


def test_place_group_round_trip():
    from colloquium.elements.place import PlaceSpec, parse_spec

    spec = PlaceSpec(x=1, y=2, w=3, text="hi\n", group="g1")
    again = parse_spec(spec.to_yaml())
    assert again.group == "g1"
    assert 'group: g1' in spec.to_yaml()


MASTER_DECK = """---
title: T
custom_css: |
  :root {
    --colloquium-accent: #e4002b;
  }
---

<!-- master: true -->

```place
src: logo.png
x: 90
y: 3
w: 8
```

```place
x: 2
y: 95
w: 30
z: 1
text: |
  footer note
```

---

## First

Body.

---

<!-- master: off -->

## Bare

No logo here.
"""


def test_master_slide_excluded_and_layer_stamped():
    from colloquium.build import build_deck

    deck = parse_markdown(MASTER_DECK)
    assert deck.slides[0].metadata["master"] == "on"
    assert deck.slides[2].metadata["master"] == "off"
    html = build_deck(deck)
    assert html.count('<section class="slide') == 2
    assert "<section class=\"slide slide--master" not in html and " slide--master" not in html.split("</style>")[-1]
    first = html.split("<section")[1]
    assert 'data-master-index="0"' in first and 'data-master-index="1"' in first
    assert 'colloquium-master-layer--front' in first  # z: 1 goes in front
    assert first.count('class="colloquium-place-layer colloquium-master-layer') == 2
    assert "data-place-index" not in first
    bare = html.split("<section")[2]
    assert "colloquium-master-layer" not in bare


def test_master_slide_included_in_editor_build():
    from colloquium.build import build_deck

    html = build_deck(parse_markdown(MASTER_DECK), include_master=True)
    assert html.count('<section class="slide') == 3
    master = html.split("<section")[1]
    assert "slide--master" in master
    assert 'data-place-index="0"' in master and "colloquium-master-layer" not in master


def test_document_master_helpers_and_custom_css():
    from colloquium.editor import theme

    doc = DeckDocument.from_text(MASTER_DECK)
    assert doc.master_indices() == [0]
    assert doc.slides[0].is_master and not doc.slides[2].is_master
    assert doc.to_text() == MASTER_DECK
    css = doc.get_custom_css()
    assert theme.get_root_var(css, "--colloquium-accent") == "#e4002b"
    css = theme.set_root_var(css, "--colloquium-accent", "#00aa00")
    css = theme.set_root_var(css, "--colloquium-bg", "#fafafa")
    css = theme.set_background_image(css, "assets/bg.png")
    doc.set_custom_css(css)
    again = DeckDocument.from_text(doc.to_text())
    c2 = again.get_custom_css()
    assert theme.get_root_var(c2, "--colloquium-accent") == "#00aa00"
    assert theme.get_root_var(c2, "--colloquium-bg") == "#fafafa"
    assert theme.get_background_image(c2) == "assets/bg.png"
    assert "title: T" in again.frontmatter
    c3 = theme.set_background_image(theme.set_root_var(c2, "--colloquium-bg", None), None)
    assert theme.get_root_var(c3, "--colloquium-bg") is None and theme.get_background_image(c3) is None
    # body untouched
    assert again.slides[1].text == "## First\n\nBody."
    plain = DeckDocument.from_text("## S\n\nbody\n")
    assert plain.master_indices() == []
    assert plain.add_master_slide() == 0
    assert plain.slides[0].is_master and len(plain.slides) == 2
    plain.set_custom_css(":root {\n  --colloquium-bg: #000;\n}")
    assert plain.to_text().startswith("---\ncustom_css: |\n  :root {\n")
    assert len(parse_markdown(plain.to_text()).slides) == 2


# ----- hardening pass -------------------------------------------------------

def test_set_directive_with_duplicate_keys_keeps_content():
    chunk = SlideChunk("<!-- class: a -->\n\n## T\n\nBody text here.\n\n<!-- class: b -->\n\nMore.")
    chunk.set_directive("class", "abc")
    assert chunk.text == "<!-- class: abc -->\n\n## T\n\nBody text here.\n\nMore."
    chunk = SlideChunk("<!-- class: a -->\n\n## T\n\nBody.\n\n<!-- class: b -->\n\nMore.")
    chunk.set_directive("class", None)
    assert chunk.text == "## T\n\nBody.\n\nMore."


def test_html_abs_ignores_margin_top_and_border_left():
    chunk = SlideChunk('## T\n\n<p style="margin-top: 24px">intro</p>\n\n<div style="border-left: 4px solid red">note</div>\n\n<div style="top: 50px; left: 100px">callout</div>')
    refs = chunk.html_abs_refs()
    assert [r.inner for r in refs] == ["callout"]
    assert [chunk.text[a:b] for a, b in chunk.cell_flow_blocks(0)] == [
        '<p style="margin-top: 24px">intro</p>', '<div style="border-left: 4px solid red">note</div>']


def test_multiline_notes_comment_is_not_a_block():
    chunk = SlideChunk("## T\n\nPara.\n\n<!-- notes: first\n\nsecond paragraph -->\n\nLast.")
    assert [chunk.text[a:b] for a, b in chunk.cell_flow_blocks(0)] == ["Para.", "Last."]


def test_set_place_refuses_invalid_yaml():
    chunk = SlideChunk("## T\n\n```place\nx: 1\ntext: it's: bad: yaml\n```")
    spec = chunk.get_place(0)
    assert spec.error
    with pytest.raises(ValueError):
        chunk.set_place(0, spec)
    assert "it's: bad: yaml" in chunk.text


def test_place_unknown_keys_survive_round_trip():
    chunk = SlideChunk("## T\n\n```place\nx: 1\ny: 2\nw: 10\nnote: keep me\nopacity: 0.5\ntext: |\n  hi\n```")
    spec = chunk.get_place(0)
    assert spec.extra == {"note": "keep me", "opacity": 0.5}
    spec.x = 5
    chunk.set_place(0, spec)
    again = chunk.get_place(0)
    assert again.x == 5 and again.extra == {"note": "keep me", "opacity": 0.5}
    assert "note: keep me" in chunk.text and "opacity: 0.5" in chunk.text


def test_convert_html_abs_returns_inserted_index():
    text = '## T\n\n<div style="top: 10px; left: 20px">early</div>\n\n```place\nx: 1\ny: 1\ntext: |\n  P0\n```\n\n```place\nx: 2\ny: 2\ntext: |\n  P1\n```'
    chunk = SlideChunk(text)
    idx = chunk.convert_html_abs_to_place(0)
    assert idx == 0
    assert chunk.get_place(idx).text.strip() == "early"
    assert [r.spec.text.strip() for r in chunk.place_refs()] == ["early", "P0", "P1"]


def test_place_extract_leaves_code_blocks_and_separators_alone():
    from colloquium.elements.place import extract

    src = "Left\n```place\nx: 1\ny: 1\n```\n|||\n\nRight\n\n```python\ndef a():\n    pass\n\n\ndef b():\n    pass\n```"
    remaining, specs = extract(src)
    assert len(specs) == 1
    assert remaining.startswith("Left\n\n|||")
    assert "    pass\n\n\ndef b()" in remaining
    untouched = "a\n\n\n\nb"
    assert extract(untouched)[0] == untouched


def test_place_block_comment_does_not_become_title():
    deck = parse_markdown("```place\nx: 5\n# main figure\nsrc: fig.png\n```\n\nBody\n\n## Real title")
    slide = deck.slides[0]
    assert slide.title == "Real title"
    assert "# main figure" in slide.content
    assert slide.layout == "content"


def test_place_numbers_reject_non_finite_and_accept_percent():
    from colloquium.elements.place import parse_spec

    spec = parse_spec("x: 55%\ny: .nan\nz: .inf\nw: 40%")
    assert spec.x == 55 and spec.y == 0 and spec.z is None and spec.w == 40
