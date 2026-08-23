"""NiceGUI slide editor: ``colloquium edit [deck.md]``.

Three panes: slide list | live preview (the real build in an iframe, with a
drag/resize overlay) | inspector. Every edit is written straight back to the
markdown file via :mod:`colloquium.editor.document`, so the file stays the
single source of truth and ``colloquium serve`` / git keep working alongside.
"""

from __future__ import annotations

import re
from pathlib import Path

from colloquium.editor import images
from colloquium.editor.document import DeckDocument
from colloquium.elements import place

LAYOUTS = [
    "content", "title", "title-left", "title-banner", "title-sidebar",
    "section-break", "two-column", "image-left", "image-right", "code",
]
ALIGNS = ["", "left", "center", "right"]
VALIGNS = ["", "top", "center", "bottom"]
SIZES = ["", "small", "large", "xl"]
PADDINGS = ["", "none", "small", "large"]
SHAPES = ["rect", "rounded", "ellipse", "line", "arrow"]

_OVERLAY_JS = (Path(__file__).parent / "overlay.js").read_text(encoding="utf-8")

_PAGE_CSS = """
html, body { height: 100%; margin: 0; }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.ce-root { height: 100vh; width: 100vw; display: flex; flex-direction: column; }
.ce-main { flex: 1; min-height: 0; width: 100%; display: flex; }
.ce-thumbs { width: 230px; display: flex; flex-direction: column; border-right: 1px solid #e2e5ea; background: #f7f8fa; }
.ce-thumbs-frame { flex: 1; width: 100%; border: 0; background: #f7f8fa; }
.ce-thumb { padding: 8px 10px; border-bottom: 1px solid #eceef2; cursor: pointer; font-size: 13px; }
.ce-thumb:hover { background: #edf1f7; }
.ce-thumb.active { background: #dbe7ff; }
.ce-thumb .n { color: #7b8496; margin-right: 6px; font-variant-numeric: tabular-nums; }
.ce-thumb .t { color: #1b1f27; }
.ce-thumb .meta { color: #9aa3b2; font-size: 11px; margin-top: 2px; }
.ce-center { flex: 1; min-width: 0; display: flex; flex-direction: column; background: #2b2f36; }
.ce-frame-wrap { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 12px; }
.ce-frame { width: min(100%, calc((100vh - 110px) * 16 / 9)); aspect-ratio: 16 / 9; border: 0; background: #000; box-shadow: 0 6px 30px rgba(0,0,0,0.4); }
.ce-inspector { width: 360px; overflow-y: auto; border-left: 1px solid #e2e5ea; background: #fff; }
.ce-inspector .q-field { margin-bottom: 2px; }
.ce-section { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #7b8496; margin: 14px 0 4px; }
"""


_THUMBS_CSS = """
html, body { background: #f7f8fa !important; margin: 0; padding: 8px 10px; overflow-y: auto !important; overflow-x: hidden; }
.colloquium-deck { position: static !important; transform: none !important; width: auto !important; height: auto !important; background: none !important; overflow: visible !important; padding: 6px 4px; counter-reset: ce-slide; }
.slide { display: flex !important; position: relative !important; zoom: 0.1555; margin: 0 0 70px 0; cursor: pointer; box-shadow: 0 0 0 8px #d7dbe2; counter-increment: ce-slide; overflow: visible !important; }
.slide.ce-current { box-shadow: 0 0 0 28px #1e78ff; }
.slide.ce-drop-before { box-shadow: 0 -60px 0 -20px #1e78ff, 0 0 0 8px #d7dbe2; }
.slide.ce-drop-after { box-shadow: 0 60px 0 -20px #1e78ff, 0 0 0 8px #d7dbe2; }
.slide::before { content: counter(ce-slide); position: absolute; right: 0; bottom: -64px; font: 700 52px/1 system-ui, sans-serif; color: #7b8496; z-index: 5; }
.slide--references::before { content: "refs"; }
.colloquium-present, .colloquium-progress, .colloquium-picker-trigger, .colloquium-toast, .colloquium-overflow-warn, .colloquium-picker-overlay { display: none !important; }
.slide * { pointer-events: none; }
.slide.ce-dragging { opacity: 0.4; }
"""

_THUMBS_JS = """
(function () {
  function slides() { return Array.from(document.querySelectorAll('.colloquium-deck > .slide')); }
  function send(data) { parent.postMessage(Object.assign({ source: 'ce-thumbs' }, data), '*'); }
  let dragIndex = -1;
  window.ceHighlight = function (index) {
    slides().forEach((s, i) => s.classList.toggle('ce-current', i === index));
    const cur = slides()[index];
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  };
  document.addEventListener('DOMContentLoaded', () => {
    slides().forEach((s, i) => {
      s.setAttribute('draggable', 'true');
      s.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); send({ type: 'click', index: i }); }, true);
      s.addEventListener('dragstart', (e) => { dragIndex = i; s.classList.add('ce-dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); });
      s.addEventListener('dragend', () => { dragIndex = -1; slides().forEach((x) => x.classList.remove('ce-dragging', 'ce-drop-before', 'ce-drop-after')); });
      s.addEventListener('dragover', (e) => {
        if (dragIndex < 0) return;
        e.preventDefault();
        const r = s.getBoundingClientRect();
        const after = e.clientY > r.top + r.height / 2;
        slides().forEach((x) => x.classList.remove('ce-drop-before', 'ce-drop-after'));
        s.classList.add(after ? 'ce-drop-after' : 'ce-drop-before');
      });
      s.addEventListener('drop', (e) => {
        e.preventDefault();
        if (dragIndex < 0) return;
        const r = s.getBoundingClientRect();
        const after = e.clientY > r.top + r.height / 2;
        let dst = i + (after ? 1 : 0);
        if (dragIndex < dst) dst -= 1;
        if (dst !== dragIndex) send({ type: 'move', src: dragIndex, dst: dst });
      });
    });
    send({ type: 'ready' });
  });
})();
"""


def thumbs_html(deck_html: str) -> str:
    """Turn the built deck into a scrollable contact sheet for the slide list."""
    inject = f"<style>{_THUMBS_CSS}</style><script>{_THUMBS_JS}</script></head>"
    return deck_html.replace("</head>", inject, 1)


class EditorState:
    """Mutable editor state shared by all UI callbacks of one session."""

    def __init__(self, path: Path):
        self.path = path
        self.doc = DeckDocument.load(path)
        self.index = 0
        self.selection: dict | None = None
        self.extra: list[dict] = []
        self.clipboard: list[str] = []
        self.undo: list[str] = []
        self.redo: list[str] = []
        self.version = 0
        self.html = ""
        self.last_written_mtime = 0.0
        self.last_known_mtime = path.stat().st_mtime
        self.rebuild()

    # ----- build -----------------------------------------------------------
    def rebuild(self) -> None:
        from colloquium.build import build_deck
        from colloquium.parse import parse_markdown

        deck = parse_markdown(self.doc.to_text())
        if deck.bibliography and not Path(deck.bibliography).is_absolute():
            deck.bibliography = str(self.path.parent / deck.bibliography)
        try:
            self.html = build_deck(deck)
        except Exception as exc:  # keep the editor alive on a bad build
            self.html = f"<html><body><pre>Build failed:\n{exc}</pre></body></html>"
        self.version += 1

    def rendered_index(self, src_index: int) -> int:
        """Map a source slide index to its position in the built deck."""
        after = [
            (s.get_directive("after") or "") == "references" for s in self.doc.slides
        ]
        main = [i for i, a in enumerate(after) if not a]
        post = [i for i, a in enumerate(after) if a]
        has_refs = "slide--references" in self.html
        if src_index in main:
            return main.index(src_index)
        return len(main) + (1 if has_refs else 0) + post.index(src_index)

    def source_index(self, rendered: int) -> int | None:
        """Inverse of rendered_index; None for the auto-generated references slide."""
        for i in range(len(self.doc.slides)):
            if self.rendered_index(i) == rendered:
                return i
        return None

    # ----- mutations ---------------------------------------------------------
    def snapshot(self) -> None:
        self.undo.append(self.doc.to_text())
        if len(self.undo) > 200:
            self.undo.pop(0)
        self.redo.clear()

    def commit(self) -> None:
        self.doc.save()
        self.last_written_mtime = self.path.stat().st_mtime
        self.last_known_mtime = self.last_written_mtime
        self.rebuild()

    def restore(self, text: str) -> None:
        self.doc = DeckDocument.from_text(text, self.path)
        self.index = min(self.index, max(len(self.doc.slides) - 1, 0))
        self.selection = None
        self.commit()

    def do_undo(self) -> bool:
        if not self.undo:
            return False
        self.redo.append(self.doc.to_text())
        self.restore(self.undo.pop())
        return True

    def do_redo(self) -> bool:
        if not self.redo:
            return False
        self.undo.append(self.doc.to_text())
        self.restore(self.redo.pop())
        return True

    def reload_from_disk(self) -> bool:
        """Pick up external edits (user's text editor). Returns True if reloaded."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime <= self.last_known_mtime:
            return False
        self.last_known_mtime = mtime
        text = self.path.read_text(encoding="utf-8")
        if text == self.doc.to_text():
            return False
        self.undo.append(self.doc.to_text())
        self.doc = DeckDocument.from_text(text, self.path)
        self.index = min(self.index, max(len(self.doc.slides) - 1, 0))
        self.selection = None
        self.rebuild()
        return True

    @property
    def slide(self):
        return self.doc.slides[self.index]


def run_editor(path: str | None, port: int = 8765, open_browser: bool = True) -> None:
    from fastapi.responses import HTMLResponse
    from nicegui import app, ui

    deck_path = Path(path).resolve() if path else None
    states: dict[str, EditorState] = {}

    def get_state() -> EditorState | None:
        if deck_path is None:
            return None
        key = str(deck_path)
        if key not in states:
            states[key] = EditorState(deck_path)
        return states[key]

    @app.get("/deck/__preview__.html")
    def _preview():
        st = get_state()
        return HTMLResponse(st.html if st else "<p>No deck loaded</p>")

    @app.get("/deck/__thumbs__.html")
    def _thumbs():
        st = get_state()
        return HTMLResponse(thumbs_html(st.html) if st else "<p>No deck loaded</p>")

    if deck_path is not None:
        app.add_static_files("/deck", str(deck_path.parent))

    # ------------------------------------------------------------------
    @ui.page("/")
    def index_page():
        nonlocal deck_path
        ui.add_css(_PAGE_CSS)
        ui.add_body_html(f"<script>{_OVERLAY_JS}</script>")
        if deck_path is None:
            _file_picker_page(ui, lambda p: _set_deck(p))
            return
        _editor_page(ui, app, get_state())

    def _set_deck(p: Path):
        nonlocal deck_path
        deck_path = p.resolve()
        app.add_static_files("/deck", str(deck_path.parent))
        ui.navigate.reload()

    ui.run(
        port=port,
        title="colloquium edit",
        reload=False,
        show=open_browser,
        favicon="🖼️",
    )


# ----------------------------------------------------------------------------
def _file_picker_page(ui, on_pick):
    """Minimal local file-system picker for choosing a deck .md."""
    with ui.column().classes("items-center w-full p-8"):
        ui.label("Open a colloquium deck").classes("text-xl")
        _fs_browser(ui, Path.cwd(), {".md"}, on_pick, height="70vh")


def _fs_browser(ui, start: Path, suffixes: set[str], on_pick, height="50vh"):
    """Directory browser as a list; calls on_pick(Path) for a chosen file."""
    current = {"dir": start.resolve()}

    with ui.column().classes("w-full max-w-3xl gap-1"):
        path_label = ui.label().classes("font-mono text-sm text-gray-600")
        listing = ui.column().classes("w-full gap-0 overflow-y-auto border rounded").style(f"height: {height}")

    def render():
        path_label.text = str(current["dir"])
        listing.clear()
        d = current["dir"]
        try:
            entries = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            entries = []
        with listing:
            if d.parent != d:
                ui.item("..", on_click=lambda: go(d.parent)).props("clickable").classes("text-gray-500")
            for p in entries:
                if p.name.startswith(".") and p.name not in {".."}:
                    continue
                if p.is_dir():
                    ui.item(f"📁 {p.name}", on_click=lambda p=p: go(p)).props("clickable")
                elif p.suffix.lower() in suffixes:
                    ui.item(f"📄 {p.name}", on_click=lambda p=p: on_pick(p)).props("clickable").classes("text-blue-700")

    def go(p: Path):
        current["dir"] = p
        render()

    render()


# ----------------------------------------------------------------------------
def _editor_page(ui, app, st: EditorState):
    deck_dir = st.path.parent

    # --------------------------------------------------------- helpers
    def preview_src() -> str:
        return f"/deck/__preview__.html?capture&edit&v={st.version}#{st.rendered_index(st.index) + 1}"

    def thumbs_src() -> str:
        return f"/deck/__thumbs__.html?capture&edit&v={st.version}"

    def highlight_thumb():
        ui.run_javascript(
            "(function(){var f=document.getElementById('ce-thumbs');"
            f"if(f&&f.contentWindow&&f.contentWindow.ceHighlight)f.contentWindow.ceHighlight({st.rendered_index(st.index)});"
            "})()"
        )

    class _Thumbs:
        """Small shim so call sites can keep saying thumbs.refresh()."""

        @staticmethod
        def refresh():
            thumbs_frame.props(f'src="{thumbs_src()}"')
            thumbs_frame.update()

    thumbs = _Thumbs()

    def js_select():
        sel = st.selection or {"kind": "slide", "index": 0}
        sel = {"kind": sel["kind"], "index": sel["index"]}
        ui.run_javascript(f"window.colloquiumEditor && window.colloquiumEditor.select({_json(sel)}, {_json(st.extra)})")

    def refresh_all(reload_frame: bool = True, reload_thumbs: bool = True):
        if reload_thumbs:
            thumbs.refresh()
        else:
            highlight_thumb()
        inspector.refresh()
        if reload_frame:
            frame.props(f'src="{preview_src()}"')
            frame.update()

    def mutate(fn, reload_frame: bool = True):
        """Snapshot, apply fn() to the document, save, rebuild, refresh."""
        st.snapshot()
        fn()
        st.commit()
        refresh_all(reload_frame)

    def goto(i: int):
        if i == st.index:
            return
        st.index = max(0, min(i, len(st.doc.slides) - 1))
        st.selection = None
        st.extra = []
        refresh_all(reload_thumbs=False)

    def notify(msg: str, color: str = "primary"):
        ui.notify(msg, color=color, position="bottom-right", timeout=1500)

    # --------------------------------------------------------- layout
    with ui.element("div").classes("ce-root"):
        with ui.row().classes("items-center w-full px-3 py-1 gap-2 bg-white border-b"):
            ui.label("colloquium edit").classes("font-bold")
            ui.label(str(st.path)).classes("text-xs text-gray-500 font-mono")
            ui.space()
            ui.button("Add image", icon="image", on_click=lambda: add_image_dialog()).props("flat dense")
            ui.button("Add text", icon="text_fields", on_click=lambda: add_text()).props("flat dense")
            with ui.button("Add shape", icon="category").props("flat dense"):
                with ui.menu():
                    for shp, icon in [("rect", "crop_square"), ("rounded", "rounded_corner"), ("ellipse", "circle"), ("line", "horizontal_rule"), ("arrow", "arrow_forward")]:
                        ui.menu_item(shp, on_click=lambda e, shp=shp: add_shape(shp))
            ui.button("New slide", icon="add", on_click=lambda: new_slide()).props("flat dense")
            ui.button("Duplicate", icon="content_copy", on_click=lambda: dup_slide()).props("flat dense")
            ui.button("Delete slide", icon="delete", on_click=lambda: del_slide()).props("flat dense color=negative")
            ui.separator().props("vertical")
            ui.button(icon="undo", on_click=lambda: undo()).props("flat dense").tooltip("Undo (Ctrl+Z)")
            ui.button(icon="redo", on_click=lambda: redo()).props("flat dense").tooltip("Redo (Ctrl+Y)")
            ui.button("Build HTML", icon="build", on_click=lambda: build_html()).props("flat dense")
            ui.button(icon="open_in_new", on_click=lambda: ui.navigate.to(f"/deck/__preview__.html#{st.rendered_index(st.index)+1}", new_tab=True)).props("flat dense").tooltip("Open preview in new tab")

        with ui.element("div").classes("ce-main"):
            with ui.element("div").classes("ce-thumbs"):
                thumbs_frame = ui.element("iframe").classes("ce-thumbs-frame").props(f'id="ce-thumbs" src="{thumbs_src()}"')

            with ui.element("div").classes("ce-center"):
                with ui.element("div").classes("ce-frame-wrap"):
                    frame = ui.element("iframe").classes("ce-frame").props(f'id="ce-preview" src="{preview_src()}"')
                with ui.row().classes("items-center px-3 py-1 gap-2 text-white text-xs"):
                    ui.button(icon="chevron_left", on_click=lambda: goto(st.index - 1)).props("flat dense color=white")
                    pos_label = ui.label()
                    ui.button(icon="chevron_right", on_click=lambda: goto(st.index + 1)).props("flat dense color=white")
                    ui.space()
                    ui.label("click selects · shift-click multi-select · double-click edits · drag moves · handles resize · Ctrl+D duplicate · Ctrl+C/V copy/paste · Ctrl+↑/↓ order · arrows nudge · Del removes").classes("text-gray-400")

            with ui.element("div").classes("ce-inspector p-3") as inspector_pane:
                @ui.refreshable
                def inspector():
                    pos_label.text = f"{st.index + 1} / {len(st.doc.slides)}"
                    sel = st.selection
                    if sel and sel.get("kind") == "place":
                        _place_inspector(sel["index"])
                    elif sel and sel.get("kind") == "html":
                        _html_inspector(sel["index"])
                    elif sel and sel.get("kind") == "img":
                        _img_inspector(sel["index"], sel.get("box"))
                    elif sel and sel.get("kind") in {"cell", "content"}:
                        _cell_inspector(sel.get("index", 0))
                    elif sel and sel.get("kind") == "title":
                        _title_inspector()
                        _slide_inspector()
                    else:
                        _slide_inspector()

    # --------------------------------------------------------- inspectors
    def _title_inspector():
        ui.label("Title").classes("ce-section")
        chunk = st.slide
        ui.input(value=chunk.get_title()).props("dense outlined").classes("w-full").on(
            "blur", lambda e: set_title(e.sender.value)
        ).on("keydown.enter", lambda e: set_title(e.sender.value))

    def set_title(value):
        if value.strip() == st.slide.get_title():
            return
        mutate(lambda: st.slide.set_title(value))

    def _slide_inspector():
        chunk = st.slide
        ui.label("Slide").classes("ce-section")
        if not st.selection or st.selection.get("kind") != "title":
            ui.input(label="Title", value=chunk.get_title()).props("dense outlined").classes("w-full").on(
                "blur", lambda e: set_title(e.sender.value)
            ).on("keydown.enter", lambda e: set_title(e.sender.value))

        def dsel(key, options, label):
            cur = chunk.get_directive(key) or ""
            opts = {"": "(default)"}
            opts.update({o: o for o in options if o})
            if cur and cur not in opts:
                opts[cur] = cur
            ui.select(opts, value=cur, label=label, on_change=lambda e, k=key: set_directive(k, e.value)).props(
                "dense outlined options-dense"
            ).classes("w-full")

        def dtext(key, label, placeholder=""):
            cur = chunk.get_directive(key) or ""
            ui.input(label=label, value=cur, placeholder=placeholder).props("dense outlined").classes("w-full").on(
                "blur", lambda e, k=key: set_directive(k, e.sender.value)
            ).on("keydown.enter", lambda e, k=key: set_directive(k, e.sender.value))

        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                dsel("layout", LAYOUTS, "Layout")
            with ui.column().classes("flex-1 gap-0"):
                dtext("columns", "Columns", "e.g. 60/40 or 3")
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                dtext("rows", "Rows", "e.g. 35/65")
            with ui.column().classes("flex-1 gap-0"):
                dsel("size", SIZES, "Text size")
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                dsel("align", ALIGNS, "Align")
            with ui.column().classes("flex-1 gap-0"):
                dsel("valign", VALIGNS, "V-align")
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                dsel("padding", PADDINGS, "Padding")
            with ui.column().classes("flex-1 gap-0"):
                dtext("class", "Classes")
        dtext("style", "Inline style", "background: #1a1a2e")
        ui.textarea(label="Speaker notes", value=chunk.get_directive("notes") or "").props("dense outlined autogrow").classes("w-full").on(
            "blur", lambda e: set_directive("notes", e.sender.value)
        )

        ui.label("Content (markdown)").classes("ce-section")
        spans = chunk.cell_spans()
        for i in range(len(spans)):
            label = f"Cell {i + 1}" if len(spans) > 1 else "Body"
            ui.textarea(label=label, value=chunk.get_cell(i)).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
                "blur", lambda e, i=i: set_cell(i, e.sender.value)
            ).on("keydown.ctrl.enter", lambda e, i=i: set_cell(i, e.sender.value))

        hrefs = chunk.html_abs_refs()
        if hrefs:
            ui.label("Positioned HTML elements").classes("ce-section")
            for r in hrefs:
                preview = re.sub(r"<[^>]+>", "", r.inner).strip()[:40]
                ui.item(f"{r.index + 1}. <{r.tag}> {preview}", on_click=lambda r=r: select_html(r.index)).props("clickable dense")
        refs = chunk.place_refs()
        if refs:
            ui.label("Placed elements").classes("ce-section")
            for r in refs:
                s = r.spec
                name = s.src if s.kind == "image" else (s.text.strip().splitlines() or ["text"])[0][:40]
                ui.item(f"{r.index + 1}. {s.kind}: {name}", on_click=lambda r=r: select_place(r.index)).props("clickable dense")

        ui.label("Raw slide markdown").classes("ce-section")
        ui.textarea(value=chunk.text).props("dense outlined autogrow input-class=font-mono input-style=font-size:11px").classes("w-full").on(
            "blur", lambda e: set_raw(e.sender.value)
        ).on("keydown.ctrl.enter", lambda e: set_raw(e.sender.value))

    def _cell_inspector(i: int):
        chunk = st.slide
        spans = chunk.cell_spans()
        if i >= len(spans):
            i = 0
        ui.label(f"Cell {i + 1} of {len(spans)}" if len(spans) > 1 else "Body").classes("ce-section")
        ui.textarea(value=chunk.get_cell(i)).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
            "blur", lambda e, i=i: set_cell(i, e.sender.value)
        ).on("keydown.ctrl.enter", lambda e, i=i: set_cell(i, e.sender.value))
        ui.label("blur or Ctrl+Enter applies").classes("text-xs text-gray-400")
        ui.button("Back to slide", icon="arrow_back", on_click=lambda: select_none()).props("flat dense")

    def _place_inspector(i: int):
        chunk = st.slide
        refs = chunk.place_refs()
        if i >= len(refs):
            select_none()
            return
        spec = refs[i].spec
        ui.label(f"Placed {spec.kind} {i + 1}").classes("ce-section")
        _arrange_section({"kind": "place", "index": i})
        ui.label("Geometry").classes("ce-section")

        def num(label, attr, step=0.5, digits=1, allow_none=False):
            val = getattr(spec, attr)

            def on_change(e, attr=attr):
                v = e.value
                if v is None or v == "":
                    if not allow_none:
                        return
                    v = None
                else:
                    v = float(v)
                if getattr(spec, attr) == v:
                    return
                setattr(spec, attr, v)
                mutate(lambda: chunk.set_place(i, spec))

            ui.number(label=label, value=val, step=step, format=f"%.{digits}f", on_change=on_change).props(
                "dense outlined"
            ).classes("w-full")

        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                num("x %", "x")
            with ui.column().classes("flex-1 gap-0"):
                num("y %", "y")
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                num("w %", "w", allow_none=True)
            with ui.column().classes("flex-1 gap-0"):
                num("h % (blank = auto)", "h", allow_none=True)

        if spec.kind == "image":
            ui.label("Image").classes("ce-section")
            ui.label(spec.src).classes("text-xs font-mono break-all")
            with ui.row().classes("gap-1"):
                ui.button("Replace", icon="folder", on_click=lambda: add_image_dialog(replace_index=i)).props("flat dense")
                ui.button("Crop", icon="crop", on_click=lambda: crop_dialog(i)).props("flat dense")
                if spec.crop:
                    ui.button("Clear crop", icon="crop_free", on_click=lambda: clear_crop(i)).props("flat dense")
            if spec.crop:
                ui.label("crop: " + ", ".join(f"{c:.3f}" for c in spec.crop)).classes("text-xs text-gray-500 font-mono")
        else:
            if spec.kind == "shape":
                ui.label("Shape").classes("ce-section")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    with ui.column().classes("flex-1 gap-0"):
                        ui.select({k: k for k in SHAPES}, value=spec.shape, label="Shape", on_change=lambda e: set_place_attr(i, "shape", e.value)).props("dense outlined options-dense").classes("w-full")
                    with ui.column().classes("flex-1 gap-0"):
                        num("stroke px", "stroke_width", step=0.5, digits=1, allow_none=True)
                with ui.row().classes("w-full gap-2 no-wrap"):
                    with ui.column().classes("flex-1 gap-0"):
                        ui.color_input(label="Fill", value=spec.fill or "", on_change=lambda e: set_place_attr(i, "fill", e.value or "")).props("dense outlined").classes("w-full")
                    with ui.column().classes("flex-1 gap-0"):
                        ui.color_input(label="Stroke", value=spec.stroke or "", on_change=lambda e: set_place_attr(i, "stroke", e.value or "")).props("dense outlined").classes("w-full")
                if spec.shape in {"line", "arrow"}:
                    ui.switch("Flip (bottom-left to top-right)", value=spec.flip, on_change=lambda e: set_place_attr(i, "flip", bool(e.value))).props("dense")
                ui.label("Colours accept any CSS value (e.g. rgba(...)); clear a field for the default.").classes("text-xs text-gray-400")
            ui.label("Text (markdown)" if spec.kind == "text" else "Label (markdown, centred)").classes("ce-section")
            ui.textarea(value=spec.text).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
                "blur", lambda e: set_place_text(i, e.sender.value)
            ).on("keydown.ctrl.enter", lambda e: set_place_text(i, e.sender.value))
            with ui.row().classes("w-full gap-2 no-wrap"):
                with ui.column().classes("flex-1 gap-0"):
                    num("font scale", "size", step=0.05, digits=2, allow_none=True)
                with ui.column().classes("flex-1 gap-0"):
                    ui.select({"": "(default)", "left": "left", "center": "center", "right": "right"}, value=spec.align, label="Align", on_change=lambda e: set_place_attr(i, "align", e.value)).props("dense outlined options-dense").classes("w-full")

        ui.label("Advanced").classes("ce-section")
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                ui.number(label="z-index", value=spec.z, step=1, on_change=lambda e: set_place_attr(i, "z", None if e.value in (None, "") else int(e.value))).props("dense outlined").classes("w-full")
            with ui.column().classes("flex-1 gap-0"):
                num("rotate °", "rotate", step=1, digits=0, allow_none=True)
        ui.input(label="Extra CSS style", value=spec.style).props("dense outlined").classes("w-full").on(
            "blur", lambda e: set_place_attr(i, "style", e.sender.value.strip())
        )
        with ui.row().classes("gap-1 mt-2"):
            ui.button("Delete", icon="delete", on_click=lambda: delete_place(i)).props("flat dense color=negative")
            ui.button("Back to slide", icon="arrow_back", on_click=lambda: select_none()).props("flat dense")

    def _arrange_section(sel: dict):
        n_sel = 1 + len(st.extra)
        ui.label(f"Arrange ({n_sel} selected)" if n_sel > 1 else "Arrange").classes("ce-section")
        with ui.row().classes("gap-0 no-wrap"):
            for icon, mode, tip in [
                ("flip_to_front", "front", "Bring to front (Ctrl+Shift+Up)"),
                ("arrow_upward", "forward", "Bring forward (Ctrl+Up)"),
                ("arrow_downward", "backward", "Send backward (Ctrl+Down)"),
                ("flip_to_back", "back", "Send to back (Ctrl+Shift+Down)"),
            ]:
                ui.button(icon=icon, on_click=lambda e, m=mode: arrange(st.selection, m)).props("flat dense").tooltip(tip)
            ui.separator().props("vertical")
            ui.button(icon="content_copy", on_click=lambda: duplicate_items([st.selection] + st.extra)).props("flat dense").tooltip("Duplicate (Ctrl+D)")
            ui.button(icon="copy_all", on_click=lambda: copy_to_clipboard([st.selection] + st.extra)).props("flat dense").tooltip("Copy (Ctrl+C)")
            ui.button(icon="content_paste", on_click=lambda: paste_clipboard()).props("flat dense").tooltip("Paste (Ctrl+V)")
        with ui.row().classes("gap-0 no-wrap"):
            for icon, mode, tip in [
                ("align_horizontal_left", "left", "Align left"),
                ("align_horizontal_center", "center", "Align centre"),
                ("align_horizontal_right", "right", "Align right"),
                ("align_vertical_top", "top", "Align top"),
                ("align_vertical_center", "middle", "Align middle"),
                ("align_vertical_bottom", "bottom", "Align bottom"),
            ]:
                ui.button(icon=icon, on_click=lambda e, m=mode: ui.run_javascript(f"window.colloquiumEditor.align({_json(m)})")).props("flat dense").tooltip(tip)
            ui.separator().props("vertical")
            for icon, axis, tip in [("horizontal_distribute", "x", "Distribute horizontally (3+ selected)"), ("vertical_distribute", "y", "Distribute vertically (3+ selected)")]:
                ui.button(icon=icon, on_click=lambda e, a=axis: ui.run_javascript(f"window.colloquiumEditor.distribute({_json(a)})")).props("flat dense").tooltip(tip)
        ui.label("one element aligns to the slide; several align to their common box · shift-click adds to the selection").classes("text-xs text-gray-400")

    def _img_inspector(i: int, box: dict | None):
        chunk = st.slide
        refs = chunk.flow_image_refs()
        if i >= len(refs):
            ui.label("Inline image").classes("ce-section")
            ui.label("Cannot map this image to the markdown source.").classes("text-xs text-gray-400")
            return
        src = refs[i][2]
        ui.label("Inline image").classes("ce-section")
        ui.label(src).classes("text-xs font-mono break-all")
        ui.label("This image flows with the text. Convert it to a placed element to move, resize and crop it freely.").classes("text-xs text-gray-400")

        def convert():
            b = box or {"x": 30, "y": 20, "w": 40}

            def apply():
                idx = chunk.convert_flow_image_to_place(i, float(b["x"]), float(b["y"]), float(b["w"]))
                st.selection = {"kind": "place", "index": idx}
                st.extra = []

            mutate(apply)

        ui.button("Convert to placed image", icon="swap_horiz", on_click=convert).props("flat dense")
        ui.button("Back to slide", icon="arrow_back", on_click=lambda: select_none()).props("flat dense")

    def _html_inspector(i: int):
        chunk = st.slide
        refs = chunk.html_abs_refs()
        if i >= len(refs):
            select_none()
            return
        ref = refs[i]
        ui.label(f"HTML element {i + 1} (<{ref.tag}{(' .' + ' .'.join(ref.classes)) if ref.classes else ''}>)").classes("ce-section")
        ui.label("Positioned with inline px styles (1280x720 slide space).").classes("text-xs text-gray-400")
        _arrange_section({"kind": "html", "index": i})
        ui.label("Geometry").classes("ce-section")

        def pxnum(label, key, value):
            def on_change(e, key=key):
                v = e.value
                cur = ref.get(key)
                new = None if v in (None, "") else f"{int(float(v))}px"
                if new == cur:
                    return
                props = {key: new}
                if key == "width" and new:
                    props["max-width"] = None
                mutate(lambda: chunk.set_html_abs_style(i, **props), reload_frame=False)

            ui.number(label=label, value=value, step=1, format="%.0f", on_change=on_change).props("dense outlined").classes("w-full")

        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                pxnum("left px", "left", ref.left_px)
            with ui.column().classes("flex-1 gap-0"):
                pxnum("top px", "top", ref.top_px)
        with ui.row().classes("w-full gap-2 no-wrap"):
            with ui.column().classes("flex-1 gap-0"):
                pxnum("width px", "width", ref.width_px)
            with ui.column().classes("flex-1 gap-0"):
                pxnum("height px", "height", _px_or_none(ref.get("height")))
        ui.label("Inner HTML").classes("ce-section")
        ui.textarea(value=ref.inner).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
            "blur", lambda e: set_html_inner(i, e.sender.value)
        ).on("keydown.ctrl.enter", lambda e: set_html_inner(i, e.sender.value))
        ui.label("blur or Ctrl+Enter applies; double-click the element to edit on the canvas").classes("text-xs text-gray-400")
        ui.input(label="Full inline style", value=ref.style).props("dense outlined").classes("w-full").on(
            "blur", lambda e: set_html_style_raw(i, e.sender.value)
        )
        with ui.row().classes("gap-1 mt-2"):
            ui.button("Convert to place block", icon="swap_horiz", on_click=lambda: convert_html(i)).props("flat dense").tooltip(
                "Rewrites this element as a ```place block (percent coordinates, editable like any placed text)"
            )
            ui.button("Back to slide", icon="arrow_back", on_click=lambda: select_none()).props("flat dense")

    # --------------------------------------------------------- actions
    def set_html_inner(i, value):
        if value == st.slide.html_abs_refs()[i].inner:
            return
        mutate(lambda: st.slide.set_html_abs_inner(i, value))

    def set_html_style_raw(i, value):
        ref = st.slide.html_abs_refs()[i]
        if value.strip() == ref.style:
            return

        def apply():
            chunk = st.slide
            r = chunk.html_abs_refs()[i]
            tag_text = chunk.text[r.start : r.end].replace(f'style="{r.style}"', f'style="{value.strip()}"', 1)
            chunk.text = chunk.text[: r.start] + tag_text + chunk.text[r.end :]

        mutate(apply)

    def convert_html(i):
        def apply():
            idx = st.slide.convert_html_abs_to_place(i)
            st.selection = {"kind": "place", "index": idx}

        mutate(apply)

    def set_directive(key, value):
        cur = st.slide.get_directive(key) or ""
        if (value or "").strip() == cur:
            return
        mutate(lambda: st.slide.set_directive(key, value))

    def set_cell(i, value):
        if value.strip("\n") == st.slide.get_cell(i):
            return
        mutate(lambda: st.slide.set_cell(i, value))

    def set_raw(value):
        if value.strip("\n") == st.slide.text:
            return

        def apply():
            st.slide.text = value.strip("\n")

        mutate(apply)

    def select_none():
        st.selection = None
        st.extra = []
        inspector.refresh()
        js_select()

    def select_html(i):
        st.selection = {"kind": "html", "index": i}
        inspector.refresh()
        js_select()

    def select_place(i):
        st.selection = {"kind": "place", "index": i}
        inspector.refresh()
        js_select()

    def set_place_text(i, value):
        spec = st.slide.get_place(i)
        if value.rstrip("\n") == spec.text.rstrip("\n"):
            return
        spec.text = (value.rstrip("\n") + "\n") if value.strip() else ""
        mutate(lambda: st.slide.set_place(i, spec))

    def set_place_attr(i, attr, value):
        spec = st.slide.get_place(i)
        if getattr(spec, attr) == value:
            return
        setattr(spec, attr, value)
        mutate(lambda: st.slide.set_place(i, spec))

    def delete_place(i):
        st.selection = None
        mutate(lambda: st.slide.remove_place(i))

    def clear_crop(i):
        spec = st.slide.get_place(i)
        spec.crop = None
        mutate(lambda: st.slide.set_place(i, spec))

    def add_shape(shape: str):
        if shape in {"line", "arrow"}:
            spec = place.PlaceSpec(x=20, y=50, w=30, h=0.5, shape=shape)
        else:
            spec = place.PlaceSpec(x=30, y=30, w=25, h=20, shape=shape)

        def apply():
            idx = st.slide.add_place(spec)
            st.selection = {"kind": "place", "index": idx}
            st.extra = []

        mutate(apply)

    def add_text():
        spec = place.PlaceSpec(x=10, y=40, w=30, text="New text\n")

        def apply():
            idx = st.slide.add_place(spec)
            st.selection = {"kind": "place", "index": idx}

        mutate(apply)

    def add_image_from(p: Path, replace_index: int | None = None):
        rel = images.import_image(p, deck_dir)
        size = images.image_size(deck_dir / rel)

        def apply():
            if replace_index is None:
                spec = place.PlaceSpec(x=30, y=20, w=images.default_place_width(size), src=rel)
                idx = st.slide.add_place(spec)
                st.selection = {"kind": "place", "index": idx}
            else:
                spec = st.slide.get_place(replace_index)
                spec.src = rel
                spec.crop = None
                st.slide.set_place(replace_index, spec)

        mutate(apply)
        notify(f"Image: {rel}")

    def add_image_dialog(replace_index: int | None = None):
        with ui.dialog() as dlg, ui.card().classes("w-[760px] max-w-full"):
            ui.label("Pick an image (copied into the deck folder if outside it)").classes("text-sm")

            def pick(p: Path):
                dlg.close()
                add_image_from(p, replace_index)

            _fs_browser(ui, deck_dir, images.IMAGE_SUFFIXES, pick, height="55vh")
            ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def crop_dialog(i: int):
        spec = st.slide.get_place(i)
        src_path = deck_dir / spec.src
        size = images.image_size(src_path)
        if not size:
            notify("Cannot read image size (SVG?)", "warning")
            return
        W, H = size
        crop = list(spec.crop) if spec.crop else [0.0, 0.0, 1.0, 1.0]
        drag = {"start": None}

        with ui.dialog() as dlg, ui.card().classes("w-[900px] max-w-full"):
            ui.label("Drag a rectangle over the original; the source file is never modified.").classes("text-sm")
            img = ui.interactive_image(
                f"/deck/{spec.src}",
                events=["mousedown", "mousemove", "mouseup"],
                cross=True,
            ).classes("w-full").style("max-height: 60vh")

            def svg():
                x, y, w, h = crop
                return (
                    f'<rect x="0" y="0" width="{W}" height="{H}" fill="rgba(0,0,0,0.45)" mask="url(#ce-m)"/>'
                    f'<mask id="ce-m"><rect x="0" y="0" width="{W}" height="{H}" fill="white"/>'
                    f'<rect x="{x*W:.1f}" y="{y*H:.1f}" width="{w*W:.1f}" height="{h*H:.1f}" fill="black"/></mask>'
                    f'<rect x="{x*W:.1f}" y="{y*H:.1f}" width="{w*W:.1f}" height="{h*H:.1f}" '
                    f'fill="none" stroke="#1e78ff" stroke-width="{max(2, W/400):.1f}"/>'
                )

            img.content = svg()
            nums = {}

            def set_from_nums():
                try:
                    vals = [float(nums[k].value) for k in ("x", "y", "w", "h")]
                except (TypeError, ValueError):
                    return
                if vals[2] > 0 and vals[3] > 0:
                    crop[:] = vals
                    img.content = svg()

            def sync_nums():
                for k, v in zip(("x", "y", "w", "h"), crop):
                    nums[k].value = round(v, 3)

            def on_mouse(e):
                if e.type == "mousedown":
                    drag["start"] = (e.image_x, e.image_y)
                elif e.type in {"mousemove", "mouseup"} and drag["start"]:
                    x0, y0 = drag["start"]
                    x1, y1 = e.image_x, e.image_y
                    x, y = max(0, min(x0, x1)), max(0, min(y0, y1))
                    w, h = min(W, max(x0, x1)) - x, min(H, max(y0, y1)) - y
                    if w > 2 and h > 2:
                        crop[:] = [x / W, y / H, w / W, h / H]
                        img.content = svg()
                    if e.type == "mouseup":
                        drag["start"] = None
                        sync_nums()

            img.on_mouse(on_mouse)
            with ui.row().classes("gap-2 no-wrap w-full"):
                for k in ("x", "y", "w", "h"):
                    nums[k] = ui.number(label=k, step=0.01, format="%.3f", on_change=lambda e: set_from_nums()).props("dense outlined").classes("flex-1")
            sync_nums()

            def apply():
                spec.crop = None if crop == [0.0, 0.0, 1.0, 1.0] else [round(c, 4) for c in crop]
                dlg.close()
                mutate(lambda: st.slide.set_place(i, spec))

            with ui.row().classes("gap-2"):
                ui.button("Apply crop", icon="check", on_click=apply).props("dense")
                ui.button("Reset", icon="crop_free", on_click=lambda: (crop.__setitem__(slice(None), [0.0, 0.0, 1.0, 1.0]), img.__setattr__("content", svg()), sync_nums())).props("flat dense")
                ui.button("Cancel", on_click=dlg.close).props("flat dense")
        dlg.open()

    def new_slide():
        def apply():
            st.doc.insert_slide(st.index + 1)
            st.index += 1
            st.selection = None

        mutate(apply)

    def dup_slide():
        def apply():
            st.doc.duplicate_slide(st.index)
            st.index += 1
            st.selection = None

        mutate(apply)

    def del_slide():
        if len(st.doc.slides) <= 1:
            notify("Cannot delete the only slide", "warning")
            return

        def apply():
            st.doc.delete_slide(st.index)
            st.index = min(st.index, len(st.doc.slides) - 1)
            st.selection = None

        mutate(apply)

    def move_slide(delta: int):
        dst = st.index + delta
        if dst < 0 or dst >= len(st.doc.slides):
            return

        def apply():
            st.doc.move_slide(st.index, dst)
            st.index = dst

        mutate(apply)

    def undo():
        if st.do_undo():
            refresh_all()
        else:
            notify("Nothing to undo", "warning")

    def redo():
        if st.do_redo():
            refresh_all()
        else:
            notify("Nothing to redo", "warning")

    def build_html():
        from colloquium.build import build_file

        out = build_file(str(st.path))
        notify(f"Built {Path(out).name}")

    # --------------------------------------------------------- iframe events
    def on_select(e):
        sel = e.args or {}
        if sel.get("kind") == "slide":
            st.selection = None
        else:
            st.selection = {"kind": sel.get("kind"), "index": int(sel.get("index", 0))}
            if sel.get("box"):
                st.selection["box"] = sel["box"]
        st.extra = [
            {"kind": x.get("kind"), "index": int(x.get("index", 0))}
            for x in (sel.get("extra") or [])
        ]
        inspector.refresh()
        if sel.get("kind") == "html" and int(sel.get("index", 0)) >= len(st.slide.html_abs_refs()):
            notify("This element has no matching source; edit the raw markdown instead", "warning")

    def apply_geometry_item(a: dict) -> bool:
        kind, i = a.get("kind"), int(a["index"])
        chunk = st.slide
        if kind == "place":
            refs = chunk.place_refs()
            if i >= len(refs):
                return False
            spec = refs[i].spec
            spec.x = float(a["x"])
            spec.y = float(a["y"])
            if a.get("w") is not None:
                spec.w = float(a["w"])
            spec.h = float(a["h"]) if a.get("h") is not None else None
            chunk.set_place(i, spec)
            return True
        if kind == "html":
            if i >= len(chunk.html_abs_refs()):
                return False
            props = {"left": f"{int(a['left'])}px", "top": f"{int(a['top'])}px"}
            if a.get("width") is not None:
                props["width"] = f"{int(a['width'])}px"
                props["max-width"] = None
            if a.get("height") is not None:
                props["height"] = f"{int(a['height'])}px"
            chunk.set_html_abs_style(i, **props)
            return True
        return False

    def on_geometry(e):
        items = (e.args or {}).get("items") or []
        if not items:
            return
        # The iframe already shows the new geometry; rebuild without reloading
        # it so dragging feels instant. The next navigation picks up the build.
        st.snapshot()
        ok = all(apply_geometry_item(a) for a in items)
        st.commit()
        thumbs.refresh()
        inspector.refresh()
        if not ok:
            notify("Some elements could not be mapped to the source", "warning")

    def selected_items(args) -> list[dict]:
        sels = args.get("selection") or ([st.selection] if st.selection else [])
        return [x for x in sels if x and x.get("kind") in {"place", "html"}]

    def on_command(e):
        a = e.args or {}
        name = a.get("name")
        if name == "undo":
            undo()
        elif name == "redo":
            redo()
        elif name == "paste":
            paste_clipboard()
        elif name == "copy":
            copy_to_clipboard(selected_items(a))
        elif name == "duplicate":
            duplicate_items(selected_items(a))
        elif name == "delete":
            delete_items(selected_items(a))
        elif name in {"front", "back", "forward", "backward"}:
            items = selected_items(a)
            if items:
                arrange(items[0], name)

    def copy_to_clipboard(items):
        chunk = st.slide
        blocks = []
        for it in items:
            i = int(it["index"])
            if it["kind"] == "place" and i < len(chunk.place_refs()):
                blocks.append(chunk.place_refs()[i].spec.to_markdown())
            elif it["kind"] == "html" and i < len(chunk.html_abs_refs()):
                r = chunk.html_abs_refs()[i]
                blocks.append(chunk.text[r.start : r.end].strip("\n"))
        st.clipboard = blocks
        if blocks:
            notify(f"Copied {len(blocks)} element(s)")

    def paste_clipboard():
        if not st.clipboard:
            notify("Clipboard is empty", "warning")
            return

        def apply():
            chunk = st.slide
            first = None
            for block in st.clipboard:
                chunk.append_raw(block)
                if block.startswith("```place"):
                    idx = len(chunk.place_refs()) - 1
                    spec = chunk.get_place(idx)
                    spec.x += 2
                    spec.y += 2
                    chunk.set_place(idx, spec)
                    first = first or {"kind": "place", "index": idx}
                else:
                    idx = len(chunk.html_abs_refs()) - 1
                    if idx >= 0:
                        r = chunk.html_abs_refs()[idx]
                        chunk.set_html_abs_style(idx, left=f"{int((r.left_px or 0) + 20)}px", top=f"{int((r.top_px or 0) + 20)}px")
                        first = first or {"kind": "html", "index": idx}
            st.selection = first
            st.extra = []

        mutate(apply)

    def duplicate_items(items):
        if not items:
            return

        def apply():
            chunk = st.slide
            sels = []
            for kind, dup in (("place", chunk.duplicate_place), ("html", chunk.duplicate_html_abs)):
                idxs = sorted({int(x["index"]) for x in items if x["kind"] == kind})
                # duplicate from the highest index down so earlier indices stay
                # valid; each duplicate lands right after its original, which
                # shifts every later original by one per earlier duplicate.
                for i in reversed(idxs):
                    dup(i)
                sels += [{"kind": kind, "index": i + 1 + k} for k, i in enumerate(idxs)]
            st.selection = sels[0] if sels else None
            st.extra = sels[1:]

        mutate(apply)

    def delete_items(items):
        if not items:
            return

        def apply():
            chunk = st.slide
            for it in sorted(items, key=lambda x: -int(x["index"])):
                i = int(it["index"])
                if it["kind"] == "place" and i < len(chunk.place_refs()):
                    chunk.remove_place(i)
                elif it["kind"] == "html" and i < len(chunk.html_abs_refs()):
                    r = chunk.html_abs_refs()[i]
                    chunk.text = re.sub(r"\n{3,}", "\n\n", chunk.text[: r.start] + chunk.text[r.end :]).strip("\n")
            st.selection = None
            st.extra = []

        mutate(apply)

    def arrange(item, mode):
        kind, i = item["kind"], int(item["index"])
        chunk = st.slide
        n = len(chunk.place_refs()) if kind == "place" else len(chunk.html_abs_refs())
        if i >= n:
            return
        target = {"front": n - 1, "back": 0, "forward": min(i + 1, n - 1), "backward": max(i - 1, 0)}[mode]
        if target == i:
            return

        def apply():
            j = chunk.reorder_place(i, target) if kind == "place" else chunk.reorder_html_abs(i, target)
            st.selection = {"kind": kind, "index": j}
            st.extra = []

        mutate(apply)

    def edit_value(sel) -> str | None:
        kind, i = sel.get("kind"), int(sel.get("index", 0))
        chunk = st.slide
        if kind == "title":
            return chunk.get_title()
        if kind in {"cell", "content"}:
            spans = chunk.cell_spans()
            return chunk.get_cell(i if i < len(spans) else 0)
        if kind == "place":
            refs = chunk.place_refs()
            if i < len(refs) and refs[i].spec.kind == "text":
                return refs[i].spec.text.rstrip("\n")
            return None
        if kind == "html":
            refs = chunk.html_abs_refs()
            return refs[i].inner if i < len(refs) else None
        return None

    def on_edit_request(e):
        sel = e.args or {}
        value = edit_value(sel)
        if value is None:
            notify("Nothing editable here", "warning")
            return
        ui.run_javascript(f"window.colloquiumEditor.openEditor({_json(sel)}, {_json(value)})")

    def on_edit_commit(e):
        a = e.args or {}
        kind, i, value = a.get("kind"), int(a.get("index", 0)), a.get("value", "")
        if kind == "title":
            set_title(value)
        elif kind in {"cell", "content"}:
            spans = st.slide.cell_spans()
            set_cell(i if i < len(spans) else 0, value)
        elif kind == "place":
            set_place_text(i, value)
        elif kind == "html":
            set_html_inner(i, value)

    def on_ready(e):
        js_select()

    def on_thumb(e):
        a = e.args or {}
        t = a.get("type")
        if t == "ready":
            highlight_thumb()
        elif t == "click":
            src = st.source_index(int(a.get("index", 0)))
            if src is not None:
                goto(src)
        elif t == "move":
            src = st.source_index(int(a.get("src", 0)))
            dst = st.source_index(int(a.get("dst", 0)))
            if src is None:
                return
            if dst is None:
                dst = len(st.doc.slides) - 1

            def apply():
                st.doc.move_slide(src, dst)
                st.index = dst

            mutate(apply)

    ui.on("ce-thumb", on_thumb)
    ui.add_body_html(
        "<script>window.addEventListener('message', function(ev){"
        "if(ev.data && ev.data.source === 'ce-thumbs') emitEvent('ce-thumb', ev.data);});</script>"
    )
    ui.on("ce-select", on_select)
    ui.on("ce-geometry", on_geometry)
    ui.on("ce-command", on_command)
    ui.on("ce-ready", on_ready)
    ui.on("ce-edit-request", on_edit_request)
    ui.on("ce-edit-commit", on_edit_commit)

    def on_key(e):
        if not e.action.keydown:
            return
        if e.modifiers.ctrl and e.key == "z":
            undo()
        elif e.modifiers.ctrl and (e.key == "y" or (e.key == "Z")):
            redo()
        elif e.key == "PageDown":
            goto(st.index + 1)
        elif e.key == "PageUp":
            goto(st.index - 1)

    ui.keyboard(on_key=on_key, ignore=["input", "textarea", "select"])

    # Pick up external edits of the .md (user's text editor) once a second.
    def poll_disk():
        if st.reload_from_disk():
            refresh_all()
            notify("Reloaded from disk")

    ui.timer(1.0, poll_disk)

    # Render the dynamic panes now that every callback above is defined.
    with inspector_pane:
        inspector()
    ui.run_javascript("window.colloquiumEditor.attach('ce-preview')")


def _px_or_none(value: str | None) -> float | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*px\s*", value or "")
    return float(m.group(1)) if m else None


def _json(obj) -> str:
    import json

    return json.dumps(obj)


def _esc(text: str) -> str:
    import html

    return html.escape(text)
