"""Editor page tests with NiceGUI's simulated user: event handlers wired to the document layer."""

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")
pytest.importorskip("pytest_asyncio")
from nicegui.testing import User  # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]

DECK = """---
title: Test
---

## First

<!-- columns: 60/40 -->

Left para.

- a
- b

|||

Right ![fig](images/fig.png) side

---

## Second

```place
x: 10
y: 10
w: 20
text: |
  hello
```

```place
x: 40
y: 10
w: 20
text: |
  world
```
"""


def ev(**args):
    return SimpleNamespace(args=args)


@pytest.fixture
def deck(tmp_path):
    p = tmp_path / "deck.md"
    p.write_text(DECK, encoding="utf-8")
    return p


def make_app(deck):
    """Register the editor page from this module so NiceGUI's test reset never purges colloquium modules."""
    from nicegui import ui

    from colloquium.editor.app import EditorApp

    editor_app = EditorApp(deck, register_page=False)

    @ui.page("/")
    def index():   # lives in this module: NiceGUI purges the route owner's module after each test
        editor_app.index_page()

    return editor_app


@pytest.fixture
async def page(user: User, deck):
    editor_app = make_app(deck)
    await user.open("/")
    await user.should_see("colloquium edit")
    return editor_app.pages[-1]


async def test_page_opens_and_selects_block(page, deck):
    with page.client:
        assert page.slide.get_title() == "First"
        page.on_select(ev(kind="block", index=0, cell=0, block=0, count=2, box={"x": 5, "y": 20, "w": 50, "h": 5}))
        assert page.ses.selection["kind"] == "block"
        assert page.edit_value(page.ses.selection) == "Left para."


async def test_block_drag_converts_to_place_and_undo_restores(page, deck):
    with page.client:
        page.on_block_convert(ev(cell=0, block=1, count=2, x=12.5, y=40, w=30))
        text = deck.read_text()
        assert "```place\nx: 12.5\ny: 40\nw: 30\ntext: |\n  - a\n  - b\n```" in text
        assert page.ses.selection == {"kind": "place", "index": 0}
        page.on_command(ev(name="undo"))
        assert deck.read_text() == DECK


async def test_block_count_mismatch_is_refused(page, deck):
    with page.client:
        page.on_block_convert(ev(cell=0, block=1, count=5, x=1, y=1, w=1))
        assert deck.read_text() == DECK


async def test_inline_image_resize_and_lift(page, deck):
    with page.client:
        page.on_block_image_size(ev(cell=1, block=0, count=1, img=0, width=300))
        assert '<img src="images/fig.png" alt="fig" style="width: 300px">' in deck.read_text()
        page.on_block_convert(ev(cell=1, block=0, count=1, img=0, x=50, y=50, w=25))
        text = deck.read_text()
        assert "src: images/fig.png" in text and "Right  side" in text


async def test_geometry_group_and_cell_resize(page, deck):
    with page.client:
        page.goto(1)
        assert page.slide.get_title() == "Second"
        page.on_geometry(ev(items=[{"kind": "place", "index": 0, "x": 15, "y": 12, "w": 20}]))
        assert "x: 15\ny: 12\nw: 20" in deck.read_text()
        page.on_command(ev(name="group", selection=[{"kind": "place", "index": 0}, {"kind": "place", "index": 1}]))
        assert deck.read_text().count("group: g1") == 2
        assert page.ses.selection == {"kind": "place", "index": 0} and page.ses.extra == [{"kind": "place", "index": 1}]
        page.on_command(ev(name="ungroup", selection=[{"kind": "place", "index": 0}, {"kind": "place", "index": 1}]))
        assert "group:" not in deck.read_text()
        page.goto(0)
        page.on_cell_resize(ev(axis="cols", row=None, fractions=[70.0, 30.0]))
        assert "<!-- columns: 70/30 -->" in deck.read_text()


async def test_theme_slide_and_theme_var(page, deck):
    with page.client:
        page.theme_slide()
        assert page.slide.is_master and page.ses.index == 0
        page.set_theme_var("--colloquium-accent", "#1188ff")
        text = deck.read_text()
        assert "custom_css: |" in text and "--colloquium-accent: #1188ff;" in text
        assert 'slide--master' in page.st.html.split('</style>')[-1]
        page.add_text()
        page.goto(1)
        assert 'data-master-index="0"' in page.st.html


async def test_two_sessions_share_document_but_not_selection(user: User, deck):
    from colloquium.editor.state import Session
    from colloquium.editor.page import EditorPage

    editor_app = make_app(deck)
    await user.open("/")
    await user.should_see("colloquium edit")
    a = editor_app.pages[-1]
    with a.client:
        b = EditorPage(editor_app.state(), Session())
        b.goto(1)
        a.on_select(ev(kind="title", index=0))
        assert a.ses.index == 0 and b.ses.index == 1 and b.ses.selection is None
        a.set_title("Renamed")
        assert b.st.doc.slides[0].get_title() == "Renamed"
        b.poll()
        assert b.seen_version == a.st.version


async def test_delete_key_removes_selection(page, deck):
    with page.client:
        page.goto(1)
        page.on_select(ev(kind="place", index=1))
        page.on_key(SimpleNamespace(action=SimpleNamespace(keydown=True), key="Delete", modifiers=SimpleNamespace(ctrl=False, shift=False)))
        assert "world" not in deck.read_text() and "hello" in deck.read_text()
        page.goto(0)
        page.on_select(ev(kind="block", index=1, cell=0, block=1, count=2))
        page.on_command(ev(name="delete_selection"))
        assert "- a\n- b" not in deck.read_text() and "Left para." in deck.read_text()


# ----- the preview must always be what the deck really builds to -------------

def full_build(deck_path):
    from colloquium.build import build_deck
    from colloquium.parse import parse_markdown

    return build_deck(parse_markdown(deck_path.read_text(encoding="utf-8")), include_master=True)


async def test_preview_matches_a_full_build_after_every_kind_of_edit(page, deck):
    with page.client:
        page.goto(0)
        page.set_title("Renamed")
        assert page.st.html == full_build(deck)
        page.goto(1)
        page.on_geometry(ev(items=[{"kind": "place", "index": 0, "x": 11, "y": 12, "w": 20}]))
        assert page.st.html == full_build(deck)
        page.new_slide()
        assert page.st.html == full_build(deck)
        page.del_slide()
        assert page.st.html == full_build(deck)


async def test_blank_slide_that_gains_content_keeps_every_slide(page, deck):
    with page.client:
        page.st.doc.insert_slide(1, "")
        page.st.commit()
        page.goto(1)
        assert page.st.html.count('<section class="slide') == 2
        page.add_text()
        assert page.st.html == full_build(deck)
        assert page.st.html.count('<section class="slide') == 3


async def test_raw_html_with_a_section_tag_does_not_corrupt_the_preview(page, deck):
    with page.client:
        page.goto(0)
        page.set_raw('## First\n\n<div class="x">before</section>after</div>\n\nmore')
        assert page.st.html == full_build(deck)


# ----- one deck, several tabs ------------------------------------------------

def second_tab(page):
    from colloquium.editor.page import EditorPage
    from colloquium.editor.state import Session

    return EditorPage(page.st, Session())


async def test_a_tab_follows_its_slide_when_another_tab_inserts_or_deletes(page, deck):
    with page.client:
        b = second_tab(page)
        b.goto(1)
        assert b.slide.get_title() == "Second"
        page.goto(0)
        page.new_slide()                      # shifts everything after slide 0
        assert b.slide.get_title() == "Second", "tab B must still be on its own slide"
        b.set_title("Renamed by B")
        assert [s.get_title() for s in page.st.doc.slides] == ["First", "New slide", "Renamed by B"]
        b.poll()
        assert b.ses.drifted == ""


async def test_a_tab_whose_slide_disappears_is_told(page, deck):
    with page.client:
        b = second_tab(page)
        b.goto(1)
        page.goto(1)
        page.del_slide()
        assert b.slide.get_title() == "First"
        b.poll()
        assert "gone" in b.ses.drifted or b.ses.drifted == ""


async def test_an_external_edit_keeps_the_tab_on_its_slide(page, deck):
    import os
    import time

    with page.client:
        page.goto(1)
        assert page.slide.get_title() == "Second"
        deck.write_text("## Inserted\n\nnew\n\n---\n\n" + DECK.split("---\n", 1)[1].split("\n---\n\n")[0] + "\n\n---\n\n" + deck.read_text().split("---\n\n")[-1], encoding="utf-8")
        os.utime(deck, (time.time() + 2, time.time() + 2))
        page.poll()
        assert page.slide.get_title() == "Second"


# ----- refusals and guards ---------------------------------------------------

async def test_geometry_batch_is_all_or_nothing(page, deck):
    with page.client:
        page.goto(1)
        before = deck.read_text()
        page.on_geometry(ev(items=[
            {"kind": "place", "index": 0, "x": 33, "y": 33, "w": 20},
            {"kind": "place", "index": 7, "x": 44, "y": 44, "w": 20},
        ]))
        assert deck.read_text() == before, "a batch with an unmappable item must change nothing"
        page.on_geometry(ev(items=[{"kind": "place", "index": 0, "x": 33, "y": 33, "w": 20}]))
        assert "x: 33" in deck.read_text()


async def test_poll_does_not_reload_while_the_canvas_is_busy(page, deck):
    import os
    import time

    with page.client:
        page.on_busy(ev(busy=True))
        deck.write_text(deck.read_text() + "\n\n---\n\n## Added behind the editor\n\nx\n", encoding="utf-8")
        os.utime(deck, (time.time() + 2, time.time() + 2))
        page.poll()
        assert len(page.st.doc.slides) == 2, "a drag or open editor must not be interrupted"
        page.on_busy(ev(busy=False))
        page.poll()
        assert len(page.st.doc.slides) == 3
