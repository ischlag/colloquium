"""Events from the preview overlay (overlay.js) and the thumbs pane, plus keyboard and polling."""

from __future__ import annotations

from nicegui import ui

from colloquium.editor.document import format_grid_fractions
from colloquium.editor.util import js


class EventsMixin:
    def _register_events(self):
        ui.on("ce-thumb", self.on_thumb)
        ui.add_body_html(
            "<script>window.addEventListener('message', function(ev){"
            "if(ev.data && ev.data.source === 'ce-thumbs') emitEvent('ce-thumb', ev.data);});</script>"
        )
        ui.on("ce-select", self.on_select)
        ui.on("ce-geometry", self.on_geometry)
        ui.on("ce-crop", self.on_crop)
        ui.on("ce-crop-state", self.on_crop_state)
        ui.on("ce-block-move", self.on_block_convert)
        ui.on("ce-block-resize", self.on_block_convert)
        ui.on("ce-block-image-size", self.on_block_image_size)
        ui.on("ce-cell-resize", self.on_cell_resize)
        ui.on("ce-goto-master", self.on_goto_master)
        ui.on("ce-command", self.on_command)
        ui.on("ce-ready", self.on_ready)
        ui.on("ce-edit-request", self.on_edit_request)
        ui.on("ce-edit-commit", self.on_edit_commit)
        ui.keyboard(on_key=self.on_key, ignore=["input", "textarea", "select"])
        ui.timer(1.0, self.poll)

    # ------------------------------------------------------------- selection
    def on_select(self, e):
        sel = e.args or {}
        ses = self.ses
        if sel.get("kind") == "slide":
            ses.selection = None
        else:
            ses.selection = {"kind": sel.get("kind"), "index": int(sel.get("index", 0))}
            for k in ("box", "font", "cell", "block", "count", "img"):
                if sel.get(k) is not None:
                    ses.selection[k] = sel[k]
        ses.extra = [{"kind": x.get("kind"), "index": int(x.get("index", 0))} for x in (sel.get("extra") or []) if x.get("kind") == "place"]
        self.inspector.refresh()
        self.toolbar.refresh()

    def on_ready(self, e):
        self.js_select()

    # ------------------------------------------------------------- geometry
    def apply_geometry_item(self, a: dict) -> bool:
        if a.get("kind") != "place":
            return False
        i = int(a["index"])
        chunk = self.slide
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

    def on_geometry(self, e):
        items = (e.args or {}).get("items") or []
        if not items:
            return
        # The iframe already shows the new geometry; rebuild without reloading
        # it so dragging feels instant. The next navigation picks up the build.
        st = self.st
        st.snapshot()
        try:
            ok = all(self.apply_geometry_item(a) for a in items)
        except (ValueError, IndexError) as exc:
            st.undo.pop()
            self.notify(f"Edit refused: {exc}", "warning")
            self.refresh_all()
            return
        st.commit(self.ses.index)
        self.refresh_all(reload_frame=False)
        if not ok:
            self.notify("Some elements could not be mapped to the source", "warning")

    def on_block_convert(self, e):
        a = e.args or {}
        self.convert_block(int(a.get("cell", 0)), int(a.get("block", 0)), a.get("count"), float(a["x"]), float(a["y"]), float(a["w"]), a.get("img"))

    def on_block_image_size(self, e):
        a = e.args or {}
        c, b, k = int(a.get("cell", 0)), int(a.get("block", 0)), int(a.get("img", 0))
        if not self.block_ok(c, b, a.get("count")):
            self.refresh_all()
            return
        if k >= len(self.slide.block_images(c, b)):
            self.notify("Cannot map this image to the markdown source", "warning")
            self.refresh_all()
            return
        self.mutate(lambda: self.slide.set_block_image_size(c, b, k, width_px=a.get("width"), height_px=a.get("height")))

    def on_cell_resize(self, e):
        a = e.args or {}
        try:
            fr = [float(x) for x in (a.get("fractions") or [])]
        except (TypeError, ValueError):
            return
        if len(fr) < 2 or any(f <= 0 for f in fr):
            return
        value = format_grid_fractions(fr)
        chunk = self.slide
        axis = a.get("axis")
        row = a.get("row")

        def apply():
            if axis == "rows":
                chunk.set_directive("rows", value)
            elif row is None:
                chunk.set_directive("columns", value)
            else:
                chunk.set_row_columns(int(row), value)

        self.mutate(apply)

    # ------------------------------------------------------------- commands
    def selected_items(self, args) -> list[dict]:
        sels = args.get("selection") or ([self.ses.selection] if self.ses.selection else [])
        return [x for x in sels if x and x.get("kind") == "place"]

    def on_command(self, e):
        a = e.args or {}
        name = a.get("name")
        if name == "undo":
            self.undo()
        elif name == "redo":
            self.redo()
        elif name == "paste":
            self.paste_clipboard()
        elif name == "paste_inplace":
            self.paste_clipboard(offset=False)
        elif name == "refresh":
            self.refresh_all()
        elif name == "format":
            items = self.selected_items(a)
            if items:
                self.apply_format(a.get("fmt", "bold"), int(items[0]["index"]))
        elif name == "copy":
            self.copy_to_clipboard(self.selected_items(a))
        elif name == "duplicate":
            self.duplicate_items(self.selected_items(a))
        elif name == "delete":
            self.delete_items(self.selected_items(a))
        elif name == "group":
            self.group_items(self.selected_items(a))
        elif name == "ungroup":
            self.ungroup_items(self.selected_items(a))
        elif name == "delete_selection":
            self.delete_selection()
        elif name in {"front", "back", "forward", "backward"}:
            items = self.selected_items(a)
            if items:
                self.arrange(items[0], name)

    # ------------------------------------------------------------- in-place editing
    def edit_value(self, sel) -> str | None:
        kind, i = sel.get("kind"), int(sel.get("index", 0))
        chunk = self.slide
        if kind == "title":
            return chunk.get_title()
        if kind == "block":
            c, b = divmod(i, 100)
            return chunk.get_cell_block(c, b) if self.block_ok(c, b, sel.get("count")) else None
        if kind in {"cell", "content"}:
            spans = chunk.cell_spans()
            return chunk.get_cell(i if i < len(spans) else 0)
        if kind == "place":
            refs = chunk.place_refs()
            if i < len(refs) and refs[i].spec.kind == "text":
                return refs[i].spec.text.rstrip("\n")
        return None

    def on_edit_request(self, e):
        sel = e.args or {}
        value = self.edit_value(sel)
        if value is None:
            self.notify("Nothing editable here", "warning")
            return
        ui.run_javascript(f"window.colloquiumEditor.openEditor({js(sel)}, {js(value)})")

    def on_edit_commit(self, e):
        a = e.args or {}
        kind, i, value = a.get("kind"), int(a.get("index", 0)), a.get("value", "")
        if kind == "title":
            self.set_title(value)
        elif kind == "block":
            c, b = divmod(i, 100)
            self.set_block(c, b, value, a.get("count"))
        elif kind in {"cell", "content"}:
            spans = self.slide.cell_spans()
            self.set_cell(i if i < len(spans) else 0, value)
        elif kind == "place":
            self.set_place_text(i, value)

    # ------------------------------------------------------------- crop / master / thumbs
    def on_crop_state(self, e):
        self.ses.cropping = bool((e.args or {}).get("active"))
        self.toolbar.refresh()

    def on_crop(self, e):
        self.ses.cropping = False
        a = e.args or {}
        i = int(a["index"])
        refs = self.slide.place_refs()
        if i >= len(refs):
            return
        spec = refs[i].spec
        spec.x, spec.y, spec.w = float(a["x"]), float(a["y"]), float(a["w"])
        spec.h = float(a["h"]) if a.get("h") is not None else None
        spec.crop = [float(c) for c in a["crop"]] if a.get("crop") else None
        self.ses.selection = {"kind": "place", "index": i}
        self.mutate(lambda: self.slide.set_place(i, spec))

    def on_goto_master(self, e):
        self.goto_master(int((e.args or {}).get("index", 0)))

    def on_thumb(self, e):
        a = e.args or {}
        t = a.get("type")
        st = self.st
        if t == "ready":
            self.highlight_thumb()
        elif t == "click":
            src = st.source_index(int(a.get("index", 0)))
            if src is not None:
                self.goto(src)
        elif t == "move":
            src = st.source_index(int(a.get("src", 0)))
            dst = st.source_index(int(a.get("dst", 0)))
            if src is None:
                return
            if dst is None:
                dst = len(st.doc.slides) - 1
            self.move_slide_to(src, dst)

    # ------------------------------------------------------------- keyboard / polling
    def on_key(self, e):
        if not e.action.keydown:
            return
        if self.ses.cropping and e.key == "Enter":
            ui.run_javascript("window.colloquiumEditor.cropCommit()")
            return
        if self.ses.cropping and e.key == "Escape":
            ui.run_javascript("window.colloquiumEditor.cropCancel()")
            return
        sel = self.ses.selection
        items = [sel] + self.ses.extra if sel else []
        if e.modifiers.ctrl and e.key == "z":
            self.undo()
        elif e.modifiers.ctrl and (e.key == "y" or e.key == "Z"):
            self.redo()
        elif e.key in {"Delete", "Backspace"}:
            self.delete_selection()
        elif e.modifiers.ctrl and e.key == "d" and sel:
            self.duplicate_items(items)
        elif e.modifiers.ctrl and e.key == "c" and sel:
            self.copy_to_clipboard(items)
        elif e.modifiers.ctrl and e.key == "v":
            self.paste_clipboard(offset=not e.modifiers.shift)
        elif e.modifiers.ctrl and e.key in {"g", "G"} and sel:
            (self.ungroup_items if e.modifiers.shift else self.group_items)(items)
        elif e.key == "PageDown":
            self.goto(self.ses.index + 1)
        elif e.key == "PageUp":
            self.goto(self.ses.index - 1)

    def poll(self):
        """Pick up external edits of the .md and edits made from other tabs."""
        st = self.st
        if st.reload_from_disk():
            self.ses.selection = None
            self.refresh_all()
            self.notify("Reloaded from disk")
        elif st.version != self.seen_version:
            self.ses.clamp(len(st.doc.slides))
            self.refresh_all()
