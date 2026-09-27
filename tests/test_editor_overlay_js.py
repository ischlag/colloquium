"""Run overlay.js in node against a stub document to test its geometry maths."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parent.parent / "colloquium" / "editor" / "overlay.js"

HARNESS = r"""
const fs = require("fs");
// --- the smallest DOM the overlay needs to compute a box
const SLIDE_W = 1280, SLIDE_H = 720, SCALE = 0.75;   // the deck is CSS-scaled
const slide = {
  offsetWidth: SLIDE_W,
  offsetHeight: SLIDE_H,
  getBoundingClientRect: () => ({ left: 100, top: 50, width: SLIDE_W * SCALE, height: SLIDE_H * SCALE }),
};
function element(x, y, w, h, transform) {
  // x, y, w, h are layout px inside the slide
  const rot = /rotate\(\s*(-?[\d.]+)deg\s*\)/.exec(transform || "");
  let bw = w, bh = h;
  if (rot) {   // axis-aligned bounding box of the rotated element
    const a = (parseFloat(rot[1]) * Math.PI) / 180;
    bw = Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a));
    bh = Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a));
  }
  const cx = x + w / 2, cy = y + h / 2;
  return {
    style: { transform: transform || "" },
    offsetWidth: w, offsetHeight: h,
    getBoundingClientRect: () => ({
      left: 100 + (cx - bw / 2) * SCALE, top: 50 + (cy - bh / 2) * SCALE,
      width: bw * SCALE, height: bh * SCALE,
    }),
  };
}
global.window = { addEventListener() {} };
global.document = { getElementById: () => null, addEventListener() {} };
global.emitEvent = (name, data) => { (global.__events = global.__events || []).push([name, data]); };
eval(fs.readFileSync(process.argv[2], "utf8"));
const api = global.window.colloquiumEditor;
const int = api._internals;
int.state.slide = slide;
int.state.doc = { querySelectorAll: () => [] };

const out = {};
// an ordinary element: percentages of the slide, unaffected by the CSS scale
out.plain = int.elPercentBox(element(128, 72, 256, 144));
// the same element rotated: the source box must not grow
out.rotated = int.elPercentBox(element(128, 72, 256, 144, "rotate(30deg)"));
out.rotatedRight = int.elPercentBox(element(128, 72, 256, 144, "rotate(90deg)"));
out.angle = int.rotationOf(element(0, 0, 10, 10, "rotate(-12.5deg)"));
out.noAngle = int.rotationOf(element(0, 0, 10, 10, "translate(4px, 5px)"));

// a drag interrupted by a reload must leave nothing behind and report idle
const el = element(0, 0, 10, 10);
el.style.position = "relative"; el.style.zIndex = "50"; el.style.transform = "translate(9px, 9px)";
int.state.drag = { mode: "move-block", el: el, sel: { kind: "block", index: 0 } };
int.setBusy();
int.cancelDrag();
out.afterCancel = { drag: int.state.drag, transform: el.style.transform, position: el.style.position, busy: int.state.busy };
out.events = global.__events;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    harness = tmp_path_factory.mktemp("js") / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run(["node", str(harness), str(OVERLAY)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def close(a, b, tol=0.01):
    return abs(a - b) < tol


def test_plain_geometry_is_percent_of_the_slide(result):
    box = result["plain"]
    assert close(box["x"], 10) and close(box["y"], 10)
    assert close(box["w"], 20) and close(box["h"], 20)


def test_a_rotated_element_keeps_its_unrotated_box(result):
    for key in ("rotated", "rotatedRight"):
        box = result[key]
        assert close(box["x"], 10) and close(box["y"], 10), key
        assert close(box["w"], 20) and close(box["h"], 20), key


def test_rotation_is_read_from_the_inline_transform(result):
    assert close(result["angle"], -12.5)
    assert result["noAngle"] == 0


def test_cancelling_a_drag_clears_the_element_and_reports_idle(result):
    after = result["afterCancel"]
    assert after["drag"] is None
    assert after["transform"] == "" and after["position"] == ""
    assert after["busy"] is False
    assert ["ce-busy", {"busy": True}] in result["events"]
    assert ["ce-busy", {"busy": False}] in result["events"]
