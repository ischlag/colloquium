"""The browser half and the Python half of the editor have to agree.

overlay.js runs in the page and talks to the editor through named events and
a small API object. Nothing in Python type-checks that, so these tests read
both sides and compare the names, the shared constants and the payload fields.
"""

import inspect
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parent.parent / "colloquium" / "editor"
OVERLAY = (EDITOR / "overlay.js").read_text(encoding="utf-8")
EVENTS = (EDITOR / "events.py").read_text(encoding="utf-8")
PY_SOURCES = {p.name: p.read_text(encoding="utf-8") for p in EDITOR.glob("*.py")}

# Sent by the thumbnail pane (thumbs.py) through postMessage, not by overlay.js.
NOT_FROM_OVERLAY = {"ce-thumb"}


def test_every_event_the_canvas_sends_is_handled():
    emitted = set(re.findall(r'emit\("(ce-[a-z-]+)"', OVERLAY))
    handled = set(re.findall(r'ui\.on\("(ce-[a-z-]+)"', EVENTS))
    assert emitted - handled == set(), "the canvas emits events nobody handles"
    assert handled - emitted - NOT_FROM_OVERLAY == set(), "handlers wait for events nobody sends"


def test_every_api_call_from_python_exists_in_the_overlay():
    api = set(re.findall(r"^    ([A-Za-z]\w*)\(", OVERLAY, re.MULTILINE))
    api |= set(re.findall(r"^    ([A-Za-z]\w*)\(\w*\)\s*\{", OVERLAY, re.MULTILINE))
    called = set()
    for src in PY_SOURCES.values():
        called |= set(re.findall(r"window\.colloquiumEditor\.(\w+)\(", src))
    assert called, "no API calls found; the regex needs updating"
    assert called <= api, f"Python calls missing overlay functions: {sorted(called - api)}"


def test_block_index_stride_matches():
    from colloquium.editor.util import BLOCK_STRIDE

    m = re.search(r"const BLOCK_STRIDE = (\d+);", OVERLAY)
    assert m, "overlay.js no longer declares BLOCK_STRIDE"
    assert int(m.group(1)) == BLOCK_STRIDE


def test_block_payload_fields_line_up():
    """A block event carries cell/block/count so Python can refuse a stale index."""
    payload = re.search(r"function blockPayload\(sel\) \{(.*?)\n  \}", OVERLAY, re.DOTALL)
    assert payload, "blockPayload disappeared"
    for field in ("cell", "block", "count"):
        assert f"{field}:" in payload.group(1)
    for field in ("cell", "block", "count"):
        assert f'a.get("{field}"' in EVENTS or f'.get("{field}"' in EVENTS


def test_the_removed_selection_kinds_are_really_gone():
    for dead in ('kind === "html"', 'kind === "img"'):
        assert dead not in OVERLAY
    for name, src in PY_SOURCES.items():
        assert 'kind") == "html"' not in src, name
        assert '"kind": "img"' not in src, name


def test_geometry_only_ever_describes_place_elements():
    item = re.search(r"function geometryItem\(sel, el, box, opts\) \{(.*?)\n  \}", OVERLAY, re.DOTALL)
    assert item and 'kind: "place"' in item.group(1)
    assert 'a.get("kind") != "place"' in EVENTS


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_overlay_parses():
    subprocess.run(["node", "--check", str(EDITOR / "overlay.js")], check=True, capture_output=True)


def test_the_build_helpers_the_editor_leans_on_still_exist():
    """The editor mirrors these build-side rules; a rename must fail loudly here."""
    from colloquium import build, parse

    assert callable(parse._normalize_grid_spec)
    assert parse._normalize_grid_spec("60/40") == "60-40" and parse._normalize_grid_spec("junk") is None
    assert build._ROW_SPLIT_RE.pattern == r"^\s*===+\s*$", "row splitting changed in build.py"
    assert r"<p>\|\|\|</p>" in inspect.getsource(build._build_columns_html), "column splitting changed in build.py"
