"""The editor page: layout, refresh plumbing and the mutate/goto core.

Behaviour is split into mixins by concern (actions, inspectors, toolbar,
events); they all operate on ``self.st`` (deck state shared by every tab) and
``self.ses`` (this tab's slide index and selection).
"""

from __future__ import annotations

from nicegui import context, ui

from colloquium.editor.actions import ActionsMixin
from colloquium.editor.events import EventsMixin
from colloquium.editor.inspectors import InspectorsMixin
from colloquium.editor.state import EditorState, Session
from colloquium.editor.toolbar import ToolbarMixin
from colloquium.editor.util import js

HINT = (
    "click selects · shift-click multi-select · double-click edits · drag moves · handles resize · "
    "Ctrl+G group · Ctrl+D duplicate · Ctrl+C/V copy/paste · Ctrl+↑/↓ order · arrows nudge · Del removes"
)


class EditorPage(ActionsMixin, InspectorsMixin, ToolbarMixin, EventsMixin):
    def __init__(self, st: EditorState, ses: Session):
        self.st = st
        self.ses = ses
        self.deck_dir = st.path.parent
        self.seen_version = st.version
        self.client = context.client   # handlers run inside this client's UI context
        self._layout()
        self._register_events()
        with self.inspector_pane:
            self.inspector()
        with self.toolbar_pane:
            self.toolbar()
        ui.run_javascript("window.colloquiumEditor.attach('ce-preview')")

    # --------------------------------------------------------- state helpers
    @property
    def slide(self):
        self.ses.clamp(len(self.st.doc.slides))
        return self.st.doc.slides[self.ses.index]

    def preview_src(self) -> str:
        return f"/deck/__preview__.html?capture&edit&v={self.st.version}#{self.st.rendered_index(self.ses.index) + 1}"

    def thumbs_src(self) -> str:
        return f"/deck/__thumbs__.html?capture&edit&v={self.st.version}"

    def highlight_thumb(self) -> None:
        ui.run_javascript(
            "(function(){var f=document.getElementById('ce-thumbs');"
            f"if(f&&f.contentWindow&&f.contentWindow.ceHighlight)f.contentWindow.ceHighlight({self.st.rendered_index(self.ses.index)});"
            "})()"
        )

    def js_select(self) -> None:
        sel = self.ses.selection or {"kind": "slide", "index": 0}
        sel = {k: v for k, v in sel.items() if k in {"kind", "index", "img"}}
        ui.run_javascript(f"window.colloquiumEditor && window.colloquiumEditor.select({js(sel)}, {js(self.ses.extra)})")

    def notify(self, msg: str, color: str = "primary") -> None:
        ui.notify(msg, color=color, position="bottom-right", timeout=1500)

    # --------------------------------------------------------- refresh / mutate
    def refresh_all(self, reload_frame: bool = True, reload_thumbs: bool = True) -> None:
        self.seen_version = self.st.version
        if reload_thumbs:
            self.thumbs_frame.props(f'src="{self.thumbs_src()}"')
            self.thumbs_frame.update()
        else:
            self.highlight_thumb()
        self.inspector.refresh()
        self.toolbar.refresh()
        if reload_frame:
            self.frame.props(f'src="{self.preview_src()}"')
            self.frame.update()

    def mutate(self, fn, reload_frame: bool = True, whole_deck: bool = False) -> bool:
        """Snapshot, apply fn() to the document, save, rebuild, refresh.

        Returns False (and reports) when the document layer refused the edit.
        """
        st = self.st
        st.snapshot()
        try:
            fn()
        except (ValueError, IndexError) as exc:
            st.undo.pop()
            self.notify(f"Edit refused: {exc}", "warning")
            self.refresh_all(reload_frame)
            return False
        st.commit(None if whole_deck else self.ses.index)
        self.ses.clamp(len(st.doc.slides))
        self.refresh_all(reload_frame)
        return True

    def goto(self, i: int) -> None:
        if i == self.ses.index:
            return
        self.ses.index = max(0, min(i, len(self.st.doc.slides) - 1))
        self.ses.selection = None
        self.ses.extra = []
        self.refresh_all(reload_thumbs=False)

    def select(self, sel: dict | None, extra: list[dict] | None = None) -> None:
        self.ses.selection = sel
        self.ses.extra = extra or []
        self.inspector.refresh()
        self.toolbar.refresh()
        self.js_select()

    # --------------------------------------------------------- layout
    def _layout(self) -> None:
        st = self.st
        with ui.element("div").classes("ce-root"):
            with ui.row().classes("items-center w-full px-3 py-1 gap-2 bg-white border-b"):
                ui.label("colloquium edit").classes("font-bold")
                ui.label(str(st.path)).classes("text-xs text-gray-500 font-mono")
                ui.space()
                ui.button("Add image", icon="image", on_click=lambda: self.add_image_dialog()).props("flat dense")
                ui.button("Add text", icon="text_fields", on_click=lambda: self.add_text()).props("flat dense")
                with ui.button("Add shape", icon="category").props("flat dense"):
                    with ui.menu():
                        for shp in ["rect", "rounded", "ellipse", "line", "arrow"]:
                            ui.menu_item(shp, on_click=lambda e, shp=shp: self.add_shape(shp))
                ui.button("Theme slide", icon="palette", on_click=lambda: self.theme_slide()).props("flat dense").tooltip(
                    "Elements placed on the theme slide repeat on every slide; also colours, fonts and background"
                )
                ui.button("New slide", icon="add", on_click=lambda: self.new_slide()).props("flat dense")
                ui.button("Duplicate", icon="content_copy", on_click=lambda: self.dup_slide()).props("flat dense")
                ui.button("Delete slide", icon="delete", on_click=lambda: self.del_slide()).props("flat dense color=negative")
                ui.separator().props("vertical")
                ui.button(icon="undo", on_click=lambda: self.undo()).props("flat dense").tooltip("Undo (Ctrl+Z)")
                ui.button(icon="redo", on_click=lambda: self.redo()).props("flat dense").tooltip("Redo (Ctrl+Y)")
                ui.button("Build HTML", icon="build", on_click=lambda: self.build_html()).props("flat dense")
                ui.button(icon="open_in_new", on_click=lambda: ui.navigate.to(f"/deck/__preview__.html#{st.rendered_index(self.ses.index) + 1}", new_tab=True)).props("flat dense").tooltip("Open preview in new tab")

            with ui.element("div").classes("ce-main"):
                with ui.element("div").classes("ce-thumbs"):
                    self.thumbs_frame = ui.element("iframe").classes("ce-thumbs-frame").props(f'id="ce-thumbs" src="{self.thumbs_src()}"')

                with ui.element("div").classes("ce-center"):
                    with ui.element("div").classes("ce-toolbar") as toolbar_pane:
                        pass
                    self.toolbar_pane = toolbar_pane
                    with ui.element("div").classes("ce-frame-wrap"):
                        self.frame = ui.element("iframe").classes("ce-frame").props(f'id="ce-preview" src="{self.preview_src()}"')
                    with ui.row().classes("items-center px-3 py-1 gap-2 text-white text-xs"):
                        ui.button(icon="chevron_left", on_click=lambda: self.goto(self.ses.index - 1)).props("flat dense color=white")
                        self.pos_label = ui.label()
                        ui.button(icon="chevron_right", on_click=lambda: self.goto(self.ses.index + 1)).props("flat dense color=white")
                        ui.space()
                        ui.label(HINT).classes("text-gray-400")

                with ui.element("div").classes("ce-inspector p-3") as inspector_pane:
                    pass
                self.inspector_pane = inspector_pane
