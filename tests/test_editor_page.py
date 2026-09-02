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
