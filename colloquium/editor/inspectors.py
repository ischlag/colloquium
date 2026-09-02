"""Right-hand inspector: slide directives, cells, blocks, placed elements, theme."""

from __future__ import annotations

from nicegui import ui

from colloquium.editor import theme as theme_mod
from colloquium.editor.util import ALIGNS, LAYOUTS, PADDINGS, SHAPES, SIZES, VALIGNS, hex_color, js, px_or_none


class InspectorsMixin:
    @ui.refreshable
    def inspector(self):
        st, ses = self.st, self.ses
        chunk = self.slide
        self.pos_label.text = f"{'theme' if chunk.is_master else ses.index + 1} / {len(st.doc.slides)}"
        sel = ses.selection
        kind = sel.get("kind") if sel else None
        if kind == "master":
            self._master_ref_inspector(int(sel["index"]))
        elif chunk.is_master and kind in {None, "title", "cell", "content", "block"}:
            self._theme_inspector()
        elif kind == "place":
            self._place_inspector(int(sel["index"]))
        elif kind == "block":
            self._block_inspector(sel)
        elif kind in {"cell", "content"}:
            self._cell_inspector(int(sel.get("index", 0)))
        elif kind == "title":
            self._title_inspector()
            self._slide_inspector()
        else:
            self._slide_inspector()

    # ------------------------------------------------------------- slide
    def _title_inspector(self):
        ui.label("Title").classes("ce-section")
        ui.input(value=self.slide.get_title()).props("dense outlined").classes("w-full").on(
            "blur", lambda e: self.set_title(e.sender.value)
        ).on("keydown.enter", lambda e: self.set_title(e.sender.value))

    def _slide_inspector(self):
        chunk = self.slide
        ui.label("Slide").classes("ce-section")
        if not self.ses.selection or self.ses.selection.get("kind") != "title":
            ui.input(label="Title", value=chunk.get_title()).props("dense outlined").classes("w-full").on(
                "blur", lambda e: self.set_title(e.sender.value)
            ).on("keydown.enter", lambda e: self.set_title(e.sender.value))

        def dsel(key, options, label):
            cur = chunk.get_directive(key) or ""
            opts = {"": "(default)"}
            opts.update({o: o for o in options if o})
            if cur and cur not in opts:
                opts[cur] = cur
            ui.select(opts, value=cur, label=label, on_change=lambda e, k=key: self.set_directive(k, e.value)).props(
                "dense outlined options-dense"
            ).classes("w-full")

        def dtext(key, label, placeholder=""):
            cur = chunk.get_directive(key) or ""
            ui.input(label=label, value=cur, placeholder=placeholder).props("dense outlined").classes("w-full").on(
                "blur", lambda e, k=key: self.set_directive(k, e.sender.value)
            ).on("keydown.enter", lambda e, k=key: self.set_directive(k, e.sender.value))

        def pair(a, b):
            with ui.row().classes("w-full gap-2 no-wrap"):
                with ui.column().classes("flex-1 gap-0"):
                    a()
                with ui.column().classes("flex-1 gap-0"):
                    b()

        pair(lambda: dsel("layout", LAYOUTS, "Layout"), lambda: dtext("columns", "Columns", "e.g. 60/40 or 3"))
        pair(lambda: dtext("rows", "Rows", "e.g. 35/65"), lambda: dsel("size", SIZES, "Text size"))
        pair(lambda: dsel("align", ALIGNS, "Align"), lambda: dsel("valign", VALIGNS, "V-align"))
        pair(lambda: dsel("padding", PADDINGS, "Padding"), lambda: dtext("class", "Classes"))
        dtext("style", "Inline style", "background: #1a1a2e")
        ui.textarea(label="Speaker notes", value=chunk.get_directive("notes") or "").props("dense outlined autogrow").classes("w-full").on(
            "blur", lambda e: self.set_directive("notes", e.sender.value)
        )

        ui.label("Content (markdown)").classes("ce-section")
        spans = chunk.cell_spans()
        for i in range(len(spans)):
            label = f"Cell {i + 1}" if len(spans) > 1 else "Body"
            ui.textarea(label=label, value=chunk.get_cell(i)).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
                "blur", lambda e, i=i: self.set_cell(i, e.sender.value)
            ).on("keydown.ctrl.enter", lambda e, i=i: self.set_cell(i, e.sender.value))

        self._place_list(chunk, "Placed elements")
        self._raw_section(chunk)

    def _place_list(self, chunk, title: str):
        refs = chunk.place_refs()
        if not refs:
            return
        ui.label(title).classes("ce-section")
        for r in refs:
            s = r.spec
            name = s.src if s.kind == "image" else (s.text.strip().splitlines() or ["text"])[0][:40]
            ui.item(f"{r.index + 1}. {s.kind}: {name}", on_click=lambda r=r: self.select_place(r.index)).props("clickable dense")

    def _raw_section(self, chunk):
        ui.label("Raw slide markdown").classes("ce-section")
        ui.textarea(value=chunk.text).props("dense outlined autogrow input-class=font-mono input-style=font-size:11px").classes("w-full").on(
            "blur", lambda e: self.set_raw(e.sender.value)
        ).on("keydown.ctrl.enter", lambda e: self.set_raw(e.sender.value))

    # ------------------------------------------------------------- cells / blocks
    def _cell_inspector(self, i: int):
        chunk = self.slide
        spans = chunk.cell_spans()
        if i >= len(spans):
            i = 0
        ui.label(f"Cell {i + 1} of {len(spans)}" if len(spans) > 1 else "Body").classes("ce-section")
        ui.textarea(value=chunk.get_cell(i)).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
            "blur", lambda e, i=i: self.set_cell(i, e.sender.value)
        ).on("keydown.ctrl.enter", lambda e, i=i: self.set_cell(i, e.sender.value))
        ui.label("blur or Ctrl+Enter applies").classes("text-xs text-gray-400")
        ui.input(label="Cell style (CSS)", value=chunk.get_cell_style(i)).props("dense outlined").classes("w-full").on(
            "blur", lambda e, i=i: self.set_cell_style_raw(i, e.sender.value)
        )
        if len(spans) > 1:
            ui.label("Drag the blue divider between cells on the canvas to resize columns/rows; the toolbar sets alignment, colour and size for this cell.").classes("text-xs text-gray-400")
        ui.button("Back to slide", icon="arrow_back", on_click=lambda: self.select_none()).props("flat dense")

    def _block_inspector(self, sel: dict):
        chunk = self.slide
        c, b = divmod(int(sel.get("index", 0)), 100)
        blocks = chunk.cell_blocks(c) if c < len(chunk.cell_spans()) else []
        ui.label("Inline block").classes("ce-section")
        if b >= len(blocks) or (sel.get("count") is not None and int(sel["count"]) != len(blocks)):
            ui.label("Cannot map this block to the markdown source; edit the cell instead.").classes("text-xs text-gray-400")
            ui.button("Back to slide", icon="arrow_back", on_click=lambda: self.select_none()).props("flat dense")
            return
        count = sel.get("count")
        ui.textarea(label="Markdown", value=chunk.get_cell_block(c, b)).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
            "blur", lambda e: self.set_block(c, b, e.sender.value, count)
        ).on("keydown.ctrl.enter", lambda e: self.set_block(c, b, e.sender.value, count))
        ui.label("Flows with the layout. Drag it on the canvas to turn it into a free object; the toolbar has the shortcut.").classes("text-xs text-gray-400")
        with ui.row().classes("gap-1 mt-2"):
            ui.button("Delete", icon="delete", on_click=lambda: self.delete_block(c, b, count)).props("flat dense color=negative")
            ui.button("Back to slide", icon="arrow_back", on_click=lambda: self.select_none()).props("flat dense")

    # ------------------------------------------------------------- placed elements
    def _place_inspector(self, i: int):
        chunk = self.slide
        refs = chunk.place_refs()
        if i >= len(refs):
            self.select_none()
            return
        spec = refs[i].spec
        ui.label(f"Placed {spec.kind} {i + 1}").classes("ce-section")
        self._arrange_section()
        ui.label("Geometry").classes("ce-section")

        def num(label, attr, step=0.5, digits=1, allow_none=False):
            val = getattr(spec, attr)

            def commit(e, attr=attr):
                v = e.sender.value
                if v is None or v == "":
                    if not allow_none:
                        return
                    v = None
                else:
                    v = float(v)
                self.set_place_attr(i, attr, v)

            ui.number(label=label, value=val, step=step, format=f"%.{digits}f").props("dense outlined").classes("w-full").on(
                "blur", commit
            ).on("keydown.enter", commit)

        def pair(a, b):
            with ui.row().classes("w-full gap-2 no-wrap"):
                with ui.column().classes("flex-1 gap-0"):
                    a()
                with ui.column().classes("flex-1 gap-0"):
                    b()

        pair(lambda: num("x %", "x"), lambda: num("y %", "y"))
        pair(lambda: num("w %", "w", allow_none=True), lambda: num("h % (blank = auto)", "h", allow_none=True))

        if spec.kind == "image":
            ui.label("Image").classes("ce-section")
            ui.label(spec.src).classes("text-xs font-mono break-all")
            ui.label("Crop, size and replace are in the toolbar above the canvas.").classes("text-xs text-gray-400")
            if spec.crop:
                ui.label("crop: " + ", ".join(f"{c:.3f}" for c in spec.crop)).classes("text-xs text-gray-500 font-mono")
        else:
            if spec.kind == "shape":
                ui.label("Shape").classes("ce-section")
                pair(
                    lambda: ui.select({k: k for k in SHAPES}, value=spec.shape, label="Shape", on_change=lambda e: self.set_place_attr(i, "shape", e.value)).props("dense outlined options-dense").classes("w-full"),
                    lambda: num("stroke px", "stroke_width", step=0.5, digits=1, allow_none=True),
                )
                pair(
                    lambda: ui.color_input(label="Fill", value=spec.fill or "").props("dense outlined").classes("w-full").on("blur", lambda e: self.set_place_attr(i, "fill", e.sender.value or "")),
                    lambda: ui.color_input(label="Stroke", value=spec.stroke or "").props("dense outlined").classes("w-full").on("blur", lambda e: self.set_place_attr(i, "stroke", e.sender.value or "")),
                )
                if spec.shape in {"line", "arrow"}:
                    ui.switch("Flip (bottom-left to top-right)", value=spec.flip, on_change=lambda e: self.set_place_attr(i, "flip", bool(e.value))).props("dense")
            ui.label("Text (markdown)" if spec.kind == "text" else "Label (markdown, centred)").classes("ce-section")
            ui.textarea(value=spec.text).props("dense outlined autogrow input-class=font-mono input-style=font-size:12px").classes("w-full").on(
                "blur", lambda e: self.set_place_text(i, e.sender.value)
            ).on("keydown.ctrl.enter", lambda e: self.set_place_text(i, e.sender.value))
            ui.label("Size, colour, alignment: toolbar above the canvas.").classes("text-xs text-gray-400")

        ui.label("Advanced").classes("ce-section")
        pair(
            lambda: ui.number(label="z-index", value=spec.z, step=1).props("dense outlined").classes("w-full").on(
                "blur", lambda e: self.set_place_attr(i, "z", None if e.sender.value in (None, "") else int(e.sender.value))
            ),
            lambda: num("rotate °", "rotate", step=1, digits=0, allow_none=True),
        )
        ui.input(label="Extra CSS style", value=spec.style).props("dense outlined").classes("w-full").on(
            "blur", lambda e: self.set_place_attr(i, "style", e.sender.value.strip())
        )
        if spec.group:
            with ui.row().classes("items-center gap-2"):
                ui.label(f"Group: {spec.group} (click selects the group, Alt+click one member)").classes("text-xs text-gray-500")
                ui.button("Ungroup", on_click=lambda: self.ungroup_items([{"kind": "place", "index": i}] + self.ses.extra)).props("flat dense size=sm")
        with ui.row().classes("gap-1 mt-2"):
            ui.button("Delete", icon="delete", on_click=lambda: self.delete_place(i)).props("flat dense color=negative")
            ui.button("Back to slide", icon="arrow_back", on_click=lambda: self.select_none()).props("flat dense")

    def _arrange_section(self):
        ses = self.ses
        n_sel = 1 + len(ses.extra)
        ui.label(f"Arrange ({n_sel} selected)" if n_sel > 1 else "Arrange").classes("ce-section")
        with ui.row().classes("gap-0 no-wrap"):
            for icon, mode, tip in [
                ("flip_to_front", "front", "Bring to front (Ctrl+Shift+Up)"),
                ("arrow_upward", "forward", "Bring forward (Ctrl+Up)"),
                ("arrow_downward", "backward", "Send backward (Ctrl+Down)"),
                ("flip_to_back", "back", "Send to back (Ctrl+Shift+Down)"),
            ]:
                ui.button(icon=icon, on_click=lambda e, m=mode: self.arrange(ses.selection, m)).props("flat dense").tooltip(tip)
            ui.separator().props("vertical")
            ui.button(icon="content_copy", on_click=lambda: self.duplicate_items([ses.selection] + ses.extra)).props("flat dense").tooltip("Duplicate (Ctrl+D)")
            ui.button(icon="copy_all", on_click=lambda: self.copy_to_clipboard([ses.selection] + ses.extra)).props("flat dense").tooltip("Copy (Ctrl+C)")
            ui.button(icon="content_paste", on_click=lambda: self.paste_clipboard()).props("flat dense").tooltip("Paste (Ctrl+V)")
            ui.separator().props("vertical")
            ui.button("Group", on_click=lambda: self.group_items([ses.selection] + ses.extra)).props("flat dense").tooltip("Group the selection (Ctrl+G): moves, aligns and resizes as one")
            ui.button("Ungroup", on_click=lambda: self.ungroup_items([ses.selection] + ses.extra)).props("flat dense").tooltip("Ctrl+Shift+G")
        with ui.row().classes("gap-0 no-wrap"):
            for icon, mode, tip in [
                ("align_horizontal_left", "left", "Align left"),
                ("align_horizontal_center", "center", "Align centre"),
                ("align_horizontal_right", "right", "Align right"),
                ("align_vertical_top", "top", "Align top"),
                ("align_vertical_center", "middle", "Align middle"),
                ("align_vertical_bottom", "bottom", "Align bottom"),
            ]:
                ui.button(icon=icon, on_click=lambda e, m=mode: ui.run_javascript(f"window.colloquiumEditor.align({js(m)})")).props("flat dense").tooltip(tip)
            ui.separator().props("vertical")
            for icon, axis, tip in [("horizontal_distribute", "x", "Distribute horizontally (3+ selected)"), ("vertical_distribute", "y", "Distribute vertically (3+ selected)")]:
                ui.button(icon=icon, on_click=lambda e, a=axis: ui.run_javascript(f"window.colloquiumEditor.distribute({js(a)})")).props("flat dense").tooltip(tip)
        ui.label("one element aligns to the slide; several align to their common box · shift-click adds to the selection").classes("text-xs text-gray-400")

    # ------------------------------------------------------------- theme slide
    def _master_ref_inspector(self, i: int):
        ui.label("Theme element").classes("ce-section")
        ui.label("This element comes from the theme slide and repeats on every slide. Edit or move it there.").classes("text-xs text-gray-400")
        ui.button("Edit on theme slide", icon="palette", on_click=lambda: self.goto_master(i)).props("flat dense")
        ui.label("This slide can opt out of theme elements with <!-- master: off -->.").classes("text-xs text-gray-400")
        ui.button("Opt this slide out", on_click=lambda: self.set_directive("master", "off")).props("flat dense size=sm")

    def _theme_inspector(self):
        chunk = self.slide
        ui.label("Theme slide").classes("ce-section")
        ui.label(
            "Not part of the presentation. Anything placed here (Add image / text / shape) repeats on every slide "
            "behind its content; set a z-index on an element to put it in front. A slide opts out with <!-- master: off -->."
        ).classes("text-xs text-gray-400")
        css = self.st.doc.get_custom_css()
        defaults = theme_mod.theme_defaults()

        ui.label("Colours").classes("ce-section")
        for name, label in theme_mod.COLOR_VARS:
            cur = theme_mod.get_root_var(css, name)
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.input(value=hex_color(cur) or hex_color(defaults.get(name)) or "#000000").props("type=color dense borderless").style("width: 44px").on(
                    "change", lambda e, n=name: self.set_theme_var(n, e.sender.value)
                )
                ui.label(label).classes("text-sm flex-1")
                if cur:
                    ui.label(cur).classes("text-xs font-mono text-gray-500")
                    ui.button(icon="format_color_reset", on_click=lambda e, n=name: self.set_theme_var(n, None)).props("flat dense size=sm").tooltip("Back to the theme default")
                else:
                    ui.label("default").classes("text-xs text-gray-400")

        ui.label("Fonts").classes("ce-section")
        for name, label in theme_mod.FONT_VARS:
            cur = theme_mod.get_root_var(css, name) or ""
            ui.input(label=label, value=cur, placeholder=defaults.get(name, "")).props("dense outlined").classes("w-full").on(
                "blur", lambda e, n=name: self.set_theme_var(n, e.sender.value.strip() or None)
            ).on("keydown.enter", lambda e, n=name: self.set_theme_var(n, e.sender.value.strip() or None))
        ui.label("CSS font stacks; a @font-face in the custom CSS below makes local fonts available.").classes("text-xs text-gray-400")

        ui.label("Slide background").classes("ce-section")
        bg = theme_mod.get_background_image(css)
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            ui.label(bg or "none").classes("text-xs font-mono flex-1 break-all")
            ui.button("Choose image", icon="image", on_click=lambda: self.background_dialog()).props("flat dense size=sm")
            if bg:
                ui.button(icon="delete", on_click=lambda: self.set_background(None)).props("flat dense size=sm").tooltip("Remove background image")
        pad = px_or_none(theme_mod.get_root_var(css, "--colloquium-slide-padding")) or px_or_none(defaults.get("--colloquium-slide-padding"))
        ui.number(label="Slide padding px", value=pad, step=4, format="%.0f").props("dense outlined").classes("w-full").on(
            "blur", lambda e: self.set_theme_var("--colloquium-slide-padding", None if e.sender.value in (None, "") else f"{int(e.sender.value)}px")
        )

        ui.label("Custom CSS (frontmatter custom_css)").classes("ce-section")
        ui.textarea(value=css).props("dense outlined autogrow input-class=font-mono input-style=font-size:11px").classes("w-full").on(
            "blur", lambda e: self.set_custom_css_raw(e.sender.value)
        ).on("keydown.ctrl.enter", lambda e: self.set_custom_css_raw(e.sender.value))
        ui.label("blur or Ctrl+Enter applies").classes("text-xs text-gray-400")

        self._place_list(chunk, "Theme elements")
        self._raw_section(chunk)
        ui.button("Remove theme slide", icon="delete", on_click=lambda: self.del_slide()).props("flat dense color=negative").classes("mt-2")
