"""Tests for the place element (free positioning of images and text)."""

from colloquium.build import build_deck
from colloquium.elements import place
from colloquium.parse import parse_markdown


IMAGE_BLOCK = """```place
x: 52
y: 18
w: 44
src: fig.png
crop: [0.05, 0.1, 0.6, 0.8]
```"""

TEXT_BLOCK = """```place
x: 4
y: 62
w: 40
size: 0.85
align: center
text: |
  **Bold** and a list:
  - one
  - two
```"""


def test_extract_removes_blocks_and_keeps_order():
    content = f"Intro paragraph.\n\n{IMAGE_BLOCK}\n\nMiddle.\n\n{TEXT_BLOCK}\n"
    remaining, specs = place.extract(content)
    assert remaining == "Intro paragraph.\n\nMiddle."
    assert [s.kind for s in specs] == ["image", "text"]
    assert specs[0].src == "fig.png"
    assert specs[0].crop == [0.05, 0.1, 0.6, 0.8]
    assert specs[0].h is None
    assert specs[1].size == 0.85
    assert specs[1].align == "center"
    assert specs[1].text.startswith("**Bold**")


def test_parse_crop_string_form():
    spec = place.parse_spec("x: 1\ny: 2\nw: 3\nsrc: a.png\ncrop: 0.1, 0.2, 0.3, 0.4\n")
    assert spec.crop == [0.1, 0.2, 0.3, 0.4]


def test_invalid_crop_is_ignored():
    spec = place.parse_spec("x: 1\ny: 2\nsrc: a.png\ncrop: [0, 0, 0, 1]\n")
    assert spec.crop is None


def test_missing_src_and_text_is_error():
    spec = place.parse_spec("x: 1\ny: 2\n")
    assert spec.error
    html = place.render_spec(spec, 0)
    assert "colloquium-place--error" in html


def test_render_image_with_crop():
    spec = place.parse_spec("x: 52\ny: 18\nw: 44\nsrc: fig.png\ncrop: [0.05, 0.1, 0.6, 0.8]\n")
    html = place.render_spec(spec, 3)
    assert 'data-place-index="3"' in html
    assert 'data-crop="0.05 0.1 0.6 0.8"' in html
    assert "left: 52%; top: 18%; width: 44%" in html
    # 1/0.6 = 166.667% wide, offset -0.05/0.6 = -8.333%
    assert "width: 166.667%" in html
    assert "left: -8.333%" in html
    assert "height: 125%" in html
    assert "top: -12.5%" in html


def test_render_text_block():
    spec = place.parse_spec("x: 4\ny: 62\nw: 40\nsize: 0.85\nalign: right\ntext: |\n  **Bold**\n")
    html = place.render_spec(spec, 0)
    assert "colloquium-place--text" in html
    assert "colloquium-place--align-right" in html
    assert "font-size: 0.85em" in html
    assert "<strong>Bold</strong>" in html


def test_round_trip_to_markdown():
    spec = place.parse_spec(
        "x: 52\ny: 18\nw: 44\nh: 30\nsrc: fig.png\ncrop: [0.05, 0.1, 0.6, 0.8]\nz: 3\nrotate: -5\n"
    )
    text = spec.to_markdown()
    again = place.parse_spec(text.split("\n", 1)[1].rsplit("```", 1)[0])
    assert again.x == 52 and again.y == 18 and again.w == 44 and again.h == 30
    assert again.src == "fig.png"
    assert again.crop == [0.05, 0.1, 0.6, 0.8]
    assert again.z == 3 and again.rotate == -5


def test_text_round_trip_preserves_multiline():
    spec = place.parse_spec(TEXT_BLOCK.split("\n", 1)[1].rsplit("```", 1)[0])
    again = place.parse_spec(spec.to_yaml())
    assert again.text == spec.text


def test_build_puts_layer_outside_content_and_keeps_columns():
    md = f"""---
title: T
---

<!-- columns: 60/40 -->

## Slide

Left column.

{IMAGE_BLOCK}

|||

Right column.
"""
    deck = parse_markdown(md)
    html = build_deck(deck)
    layer_pos = html.index('<div class="colloquium-place-layer">')
    content_end = html.index("</div>", html.index('class="slide-content'))
    assert layer_pos > content_end
    assert "colloquium-grid" in html
    assert "```place" not in html
    assert "language-place" not in html


def test_shapes_render_and_round_trip():
    spec = place.parse_spec('x: 10\ny: 10\nw: 30\nh: 20\nshape: rounded\nfill: "#ffe"\nstroke: "#e4002b"\nstroke_width: 2\ntext: |\n  **Hi**\n')
    assert spec.kind == "shape"
    html = place.render_spec(spec, 0)
    assert "colloquium-place--shape" in html
    assert "background: #ffe" in html and "border: 2px solid #e4002b" in html and "border-radius: 16px" in html
    assert "<strong>Hi</strong>" in html
    again = place.parse_spec(spec.to_yaml())
    assert (again.shape, again.fill, again.stroke, again.stroke_width) == ("rounded", "#ffe", "#e4002b", 2)

    arrow = place.parse_spec("x: 0\ny: 0\nw: 20\nh: 10\nshape: arrow\nflip: true\n")
    html = place.render_spec(arrow, 1)
    assert "<line" in html and 'y1="100%"' in html and "marker-end" in html
    assert place.render_spec(arrow, 1) == html  # deterministic ids
    assert place.parse_spec(arrow.to_yaml()).flip is True


def test_group_renders_data_attribute():
    from colloquium.elements.place import PlaceSpec, render_spec

    html = render_spec(PlaceSpec(x=1, y=2, w=10, text="hi", group="g2"), 0)
    assert 'data-group="g2"' in html


def test_cell_style_comment_styles_columns():
    from colloquium.build import build_deck
    from colloquium.parse import parse_markdown

    src = "## A\n\n<!-- cell-style: text-align: center -->\n\n<!-- columns: 2 -->\n\nLeft.\n\n|||\n\nRight."
    html = build_deck(parse_markdown(src))
    assert '<div class="col" style="text-align: center">' in html
    assert "cell-style" not in html.split("</style>")[-1]
