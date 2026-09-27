"""The editor's view of a slide must match what the browser renders.

`cell_spans` and `cell_blocks` decide which part of the markdown an on-canvas
click maps to. The overlay finds the same things by walking the DOM, so any
disagreement means the editor rewrites the wrong element. These tests build
the real HTML, walk it the way overlay.js does, and compare.
"""

from html.parser import HTMLParser

import pytest

from colloquium.build import build_deck
from colloquium.editor.document import SlideChunk
from colloquium.parse import parse_markdown

ROOT = __import__('pathlib').Path(__file__).resolve().parent.parent

VOID = {"img", "br", "hr", "input", "source", "meta", "link", "area", "base", "col", "embed", "track", "wbr"}
BLOCK = {
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hgroup", "hr", "main", "menu", "nav", "ol", "p", "pre", "section", "table", "ul",
}
SKIP = {"colloquium-place-layer", "colloquium-citations", "slide-footnotes", "colloquium-slide-meta", "colloquium-footer"}


class _Node:
    def __init__(self, tag="", cls=""):
        self.tag = tag
        self.cls = cls.split()
        self.children: list["_Node"] = []


class _Tree(HTMLParser):
    """Minimal element tree of the first slide of a built deck."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = _Node("root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if self._stack[-1].tag == "p" and tag in BLOCK:   # HTML5 closes an open <p>
            self._stack.pop()
        node = _Node(tag, dict(attrs).get("class") or "")
        self._stack[-1].children.append(node)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Node(tag, dict(attrs).get("class") or ""))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return


def _find(node: _Node, cls: str) -> _Node | None:
    if cls in node.cls:
        return node
    for child in node.children:
        hit = _find(child, cls)
        if hit is not None:
            return hit
    return None


def dom_cells(src: str) -> list[_Node]:
    """The cell containers of the first slide, in the order overlay.js finds them."""
    html = build_deck(parse_markdown(src))
    tree = _Tree()
    tree.feed(html.split("</head>", 1)[-1])
    content = _find(tree.root, "slide-content")
    assert content is not None, "no .slide-content in the built slide"
    rows = [c for c in content.children if "colloquium-row" in c.cls]
    if rows:
        out = []
        for row in rows:
            cols = [c for c in row.children if "col" in c.cls]
            out.extend(cols or [row])
        return out
    cols = [c for c in content.children if "col" in c.cls]
    return cols or [content]


def dom_blocks(cell: _Node) -> list[str]:
    """Tag names of a cell's element children, as overlay.js `blocksIn` sees them."""
    return [c.tag for c in cell.children if not (set(c.cls) & SKIP)]


def source_blocks(chunk: SlideChunk, i: int) -> list[str]:
    """Tag names the document layer believes the cell's blocks render as."""
    out = []
    for b in chunk.cell_blocks(i):
        if b.kind == "html":
            out.append(b.tag)
        else:
            text = chunk.text[b.start:b.end].lstrip()
            if text.startswith("#"):
                out.append(f"h{min(len(text) - len(text.lstrip('#')), 6)}")
            elif text.startswith(("- ", "* ", "+ ")):
                out.append("ul")
            elif text.startswith("```") or text.startswith("~~~"):
                out.append("pre")
            elif text.startswith(">"):
                out.append("blockquote")
            elif text.startswith("|"):
                out.append("table")
            else:
                out.append("p")
    return out


SPLIT_CASES = [
    ("plain body", "## T\n\nOne.\n\nTwo."),
    ("columns", "## T\n\n<!-- columns: 2 -->\n\nA\n\n|||\n\nB"),
    ("three columns", "## T\n\n<!-- columns: 3 -->\n\nA\n\n|||\n\nB\n\n|||\n\nC"),
    ("uneven columns", "## T\n\n<!-- columns: 60/40 -->\n\nA\n\n|||\n\nB"),
    ("separator without a directive", "## T\n\nA\n\n|||\n\nB"),
    ("invalid columns value", "## T\n\n<!-- columns: nonsense -->\n\nA\n\n|||\n\nB"),
    ("cols- class instead of directive", "## T\n\n<!-- class: cols-2 colloquium-grid -->\n\nA\n\n|||\n\nB"),
    ("lazy continuation", "## T\n\n<!-- columns: 2 -->\n\nA\n|||\nB"),
    ("separator inside a fence", "## T\n\n<!-- columns: 2 -->\n\n```text\n|||\n```\n\n|||\n\nB"),
    ("mismatched fence markers", "## T\n\n<!-- columns: 2 -->\n\n```text\ncode\n~~~\nmore\n```\n\n|||\n\nRight."),
    ("separator inside a list", "## T\n\n<!-- columns: 2 -->\n\n- a\n- |||\n\n|||\n\nB"),
    ("rows", "## T\n\n<!-- rows: 2 -->\n\nA\n\n===\n\nB"),
    ("rows with four equals", "## T\n\n<!-- rows: 2 -->\n\nA\n\n====\n\nB"),
    ("rows with an indented marker", "## T\n\n<!-- rows: 2 -->\n\nA\n\n  ===\n\nB"),
    ("empty row", "## T\n\n<!-- rows: 2 -->\n\nA\n\n===\n\n===\n\nB"),
    ("rows with row-columns", "## T\n\n<!-- rows: 2 -->\n\nA\n\n===\n\n<!-- row-columns: 2 -->\n\nB\n\n|||\n\nC"),
    ("place block between cells", "## T\n\n<!-- columns: 2 -->\n\nA\n\n```place\nx: 1\ny: 1\ntext: |\n  p\n```\n\n|||\n\nB"),
]


@pytest.mark.parametrize("name,src", SPLIT_CASES, ids=[c[0] for c in SPLIT_CASES])
def test_cell_spans_match_the_rendered_cells(name, src):
    assert len(SlideChunk(src).cell_spans()) == len(dom_cells(src))


BLOCK_CASES = [
    ("paragraphs and lists", "## T\n\nIntro.\n\n- a\n- b\n\nAfter."),
    ("loose list", "## T\n\n- a\n\n- b\n\nAfter."),
    ("heading then text", "## T\n\n### Sub\nText under\n\nMore."),
    ("fence with blank lines", "## T\n\n```python\nx = 1\n\n\ny = 2\n```\n\nAfter."),
    ("table", "## T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nAfter."),
    ("blockquote", "## T\n\n> quoted\n\nAfter."),
    ("positioned divs", '## T\n\n<div class="anno" style="top: 1px; left: 2px">one</div>\n<div class="anno" style="top: 3px; left: 4px">two</div>\n\nAfter.'),
    ("attribute containing a greater-than", '## T\n\n<div data-note="score > 90" style="top: 40px; left: 50px">Anno</div>\n\nAfter.'),
    ("attribute containing an element", '## T\n\n<div data-html="<span>x</span>" style="top: 1px; left: 2px">Real</div>\n<div style="top: 3px; left: 4px">Second</div>\n\nAfter.'),
    ("unclosed paragraph tag", "## T\n\n<div>Before</div>\n<p>orphan\n<div>After</div>\n\nTail."),
    ("unclosed div swallows the rest", "## T\n\n<div>A\n<div>B</div>\n\nTail."),
    ("void and self-closing tags", '## T\n\n<img src="a.png" style="top: 1px; left: 2px">\n<br/>\n<hr>\n\nTail.'),
    ("uppercase tags and single quotes", "## T\n\n<DIV CLASS='anno' STYLE='top: 5px; left: 6px'>X</DIV>\n\nTail."),
    ("comment between elements", '## T\n\n<div style="top: 1px; left: 2px">one</div>\n\n<!-- a note -->\n\nAfter.'),
    ("place block among blocks", "## T\n\nIntro.\n\n```place\nx: 1\ny: 1\ntext: |\n  p\n```\n\nAfter."),
    ("image paragraph", "## T\n\n![fig](a.png)\n\nAfter."),
]


@pytest.mark.parametrize("name,src", BLOCK_CASES, ids=[c[0] for c in BLOCK_CASES])
def test_cell_blocks_match_the_rendered_children(name, src):
    chunk = SlideChunk(src)
    cells = dom_cells(src)
    assert len(chunk.cell_spans()) == len(cells)
    for i, cell in enumerate(cells):
        assert source_blocks(chunk, i) == dom_blocks(cell), f"{name}: cell {i}"


def test_positioned_metadata_survives_awkward_attributes():
    chunk = SlideChunk('## T\n\n<div data-note="score > 90" class="anno" style="top: 40px; left: 50px; color: red">Anno</div>\n\nAfter.')
    block = chunk.cell_blocks(0)[0]
    assert block.positioned and block.classes == ["anno"]
    assert block.px("top") == 40 and block.px("left") == 50
    idx = chunk.convert_cell_block_to_place(0, 0, 99, 99, 99)
    spec = chunk.get_place(idx)
    assert (spec.x, spec.y) == (round(50 / 12.8, 1), round(40 / 7.2, 1))
    assert spec.classes == ["anno"] and spec.style == "color: red"
    assert spec.text.strip() == "Anno"


def test_starter_template_matches_its_render():
    from colloquium.templates import TEMPLATES_DIR

    text = (TEMPLATES_DIR / "starter" / "starter.md").read_text(encoding="utf-8")
    from colloquium.editor.document import DeckDocument

    doc = DeckDocument.from_text(text)
    for chunk in doc.slides:
        if chunk.is_master:
            continue
        src = chunk.text
        cells = dom_cells(src)
        assert len(chunk.cell_spans()) == len(cells)
        for i, cell in enumerate(cells):
            assert source_blocks(chunk, i) == dom_blocks(cell)


def _sections(html: str) -> list[_Node]:
    tree = _Tree()
    tree.feed(html.split("</head>", 1)[-1])
    out: list[_Node] = []

    def walk(node: _Node) -> None:
        if node.tag == "section" and "slide" in node.cls:
            out.append(node)
            return
        for child in node.children:
            walk(child)

    walk(tree.root)
    return out


def _cells_of(section: _Node) -> list[_Node] | None:
    content = _find(section, "slide-content")
    if content is None:
        return None
    rows = [c for c in content.children if "colloquium-row" in c.cls]
    if rows:
        out = []
        for row in rows:
            cols = [c for c in row.children if "col" in c.cls]
            out.extend(cols or [row])
        return out
    cols = [c for c in content.children if "col" in c.cls]
    return cols or [content]


DECKS = ["demo.md", "colloquium/templates/starter/starter.md"] + [
    str(p) for p in sorted(ROOT.glob("examples/*/*.md")) if p.name != "README.md"
]


@pytest.mark.parametrize("rel", DECKS, ids=lambda r: r.split("/")[-1])
def test_whole_deck_cells_and_blocks_match_the_build(rel):
    """Every slide of every shipped deck: the editor sees what the browser renders."""
    from colloquium.editor.state import EditorState

    st = EditorState((ROOT / rel).resolve())
    sections = _sections(st.html)
    for i, chunk in enumerate(st.doc.slides):
        if not chunk.text.strip():
            continue
        rendered = st.rendered_index(i)
        if rendered >= len(sections):
            continue
        cells = _cells_of(sections[rendered])
        if cells is None:          # layouts that render no .slide-content
            continue
        assert len(chunk.cell_spans()) == len(cells), f"{rel} slide {i + 1}: cell count"
        for c, cell in enumerate(cells):
            assert len(chunk.cell_blocks(c)) == len(dom_blocks(cell)), f"{rel} slide {i + 1} cell {c}: block count"


def test_a_title_after_a_comment_is_still_the_title():
    chunk = SlideChunk('<!--\nA note about this slide.\n-->\n\n<!-- valign: center -->\n# Centered Hero\n\n<div class="x">y</div>')
    assert chunk.get_title() == "Centered Hero"
    assert [b.tag for b in chunk.cell_blocks(0)] == ["div"], "the title is rendered outside the cell"
    chunk.set_title("Renamed")
    assert "# Renamed" in chunk.text and "A note about this slide." in chunk.text


def test_a_title_right_after_a_directive_is_found():
    chunk = SlideChunk("<!-- rows: 35/65 -->\n## Rows demo\n\nBody text.")
    assert chunk.get_title() == "Rows demo"
    assert chunk.get_cell(0).strip() == "Body text."
