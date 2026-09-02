"""NiceGUI slide editor: ``colloquium edit [deck.md]``.

Three panes: slide list | live preview (the real build in an iframe, with a
drag/resize overlay) | inspector. Every edit is written straight back to the
markdown file via :mod:`colloquium.editor.document`, so the file stays the
single source of truth and ``colloquium serve`` / git keep working alongside.

Module map: ``state`` (shared deck state + per-tab session), ``page`` (layout
and the mutate/refresh core), ``actions`` / ``inspectors`` / ``toolbar`` /
``events`` (mixins by concern), ``document`` (string-level markdown edits),
``theme`` / ``images`` / ``picker`` / ``thumbs`` (helpers).
"""

from __future__ import annotations

from pathlib import Path

from colloquium.editor.state import EditorState, Session
from colloquium.editor.thumbs import thumbs_html

_OVERLAY_JS = (Path(__file__).parent / "overlay.js").read_text(encoding="utf-8")

_PAGE_CSS = """
html, body { height: 100%; margin: 0; }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.ce-root { height: 100vh; width: 100vw; display: flex; flex-direction: column; }
.ce-main { flex: 1; min-height: 0; width: 100%; display: flex; }
.ce-thumbs { width: 230px; display: flex; flex-direction: column; border-right: 1px solid #e2e5ea; background: #f7f8fa; }
.ce-thumbs-frame { flex: 1; width: 100%; border: 0; background: #f7f8fa; }
.ce-center { flex: 1; min-width: 0; display: flex; flex-direction: column; background: #2b2f36; }
.ce-toolbar { min-height: 38px; display: flex; align-items: center; gap: 2px; padding: 2px 10px; background: #1f2329; color: #e6e8ec; border-bottom: 1px solid #3a3f47; }
.ce-toolbar .q-btn { color: #e6e8ec; }
.ce-toolbar .ce-tb-label { font-size: 12px; color: #9aa3b2; margin: 0 6px 0 10px; }
.ce-toolbar .q-field { width: 44px; } .ce-toolbar .q-field__control { height: 28px; min-height: 28px; } .ce-toolbar input[type=color] { padding: 0; height: 26px; cursor: pointer; }
.ce-frame-wrap { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 12px; }
.ce-frame { width: min(100%, calc((100vh - 110px) * 16 / 9)); aspect-ratio: 16 / 9; border: 0; background: #000; box-shadow: 0 6px 30px rgba(0,0,0,0.4); }
.ce-inspector { width: 360px; overflow-y: auto; border-left: 1px solid #e2e5ea; background: #fff; }
.ce-inspector .q-field { margin-bottom: 2px; }
.ce-section { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #7b8496; margin: 14px 0 4px; }
"""


class EditorApp:
    """Registers the editor's routes and page on the NiceGUI app; ``run_editor`` starts it."""

    def __init__(self, path: Path | None, root: Path | None = None, register_page: bool = True):
        from fastapi.responses import HTMLResponse
        from nicegui import app, ui

        self.deck_path = Path(path).resolve() if path else None
        self.root = (root or Path.cwd()).resolve()
        self.states: dict[str, EditorState] = {}
        self.pages: list = []   # live EditorPage instances, mainly for tests
        editor_app = self

        @app.get("/deck/__preview__.html")
        def _preview():
            st = editor_app.state()
            return HTMLResponse(st.html if st else "<p>No deck loaded</p>")

        @app.get("/deck/__thumbs__.html")
        def _thumbs():
            st = editor_app.state()
            return HTMLResponse(thumbs_html(st.html) if st else "<p>No deck loaded</p>")

        if self.deck_path is not None:
            app.add_static_files("/deck", str(self.deck_path.parent))

        if register_page:
            ui.page("/")(self.index_page)

    def index_page(self) -> None:
        """Body of the editor page (registered at ``/``; tests register it themselves)."""
        from nicegui import ui

        from colloquium.editor.page import EditorPage
        from colloquium.editor.picker import file_picker_page

        ui.add_css(_PAGE_CSS)
        ui.add_body_html(f"<script>{_OVERLAY_JS}</script>")
        if self.deck_path is None:
            file_picker_page(ui, self.set_deck, self.root)
            return
        self.pages.append(EditorPage(self.state(), Session()))

    def state(self) -> EditorState | None:
        if self.deck_path is None:
            return None
        key = str(self.deck_path)
        if key not in self.states:
            self.states[key] = EditorState(self.deck_path)
        return self.states[key]

    def set_deck(self, p: Path) -> None:
        from nicegui import app, ui

        self.deck_path = p.resolve()
        app.add_static_files("/deck", str(self.deck_path.parent))
        ui.navigate.reload()


def run_editor(path: str | None, port: int = 8791, open_browser: bool = True, host: str = "127.0.0.1") -> None:
    from nicegui import ui

    EditorApp(path)
    ui.run(
        host=host,
        port=port,
        title="colloquium edit",
        reload=False,
        show=open_browser,
        favicon="🖼️",
    )
