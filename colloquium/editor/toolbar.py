"""Formatting toolbar above the canvas: text, image, block and cell tools."""

from __future__ import annotations

from nicegui import ui

from colloquium.editor.document import parse_inline_style
from colloquium.editor.util import CellStyleTarget, hex_color, js, px_or_none


class ToolbarMixin:
    def _text_target(self):
        """(kind, index, spec_or_target) for the selected text-bearing element, or None."""
        sel = self.ses.selection
        if not sel:
            return None
        i = int(sel["index"])
        if sel["kind"] == "place":
            refs = self.slide.place_refs()
            if i < len(refs) and refs[i].spec.kind in {"text", "shape"}:
                return ("place", i, refs[i].spec)
        if sel["kind"] in {"cell", "content"}:
            spans = self.slide.cell_spans()
            j = i if i < len(spans) else 0
            return ("cell", j, CellStyleTarget(self.slide.get_cell_style(j)))
        return None

    @staticmethod
    def _style_get(target, key):
        return dict(parse_inline_style(target[2].style)).get(key)

    def set_style(self, key, value):
        t = self._text_target()
        if not t:
            return
        kind, i, _ = t
        if self._style_get(t, key) == value:
            return
        if kind == "place":
            self.mutate(lambda: self.slide.set_place_style_props(i, **{key: value}))
        else:
            self.mutate(lambda: self.slide.set_cell_style_props(i, **{key: value}))

    def font_step(self, delta: int):
        t = self._text_target()
        if not t:
            return
        kind, i, obj = t
        if kind == "place":
            cur = obj.size if obj.size else 1.0
            new = max(0.3, round(cur + 0.1 * delta, 2))
            self.set_place_attr(i, "size", None if abs(new - 1.0) < 1e-6 else new)
        else:
            cur = px_or_none(self._style_get(t, "font-size")) or float((self.ses.selection or {}).get("font") or 16)
            self.set_style("font-size", f"{int(max(6, cur + 2 * delta))}px")

    def set_text_align(self, value):
        t = self._text_target()
        if not t:
            return
        kind, i, _ = t
        if kind == "place":
            self.set_place_attr(i, "align", value)
        else:
            self.set_style("text-align", value or None)

    def toggle_border(self):
        t = self._text_target()
        if t:
            self.set_style("border", None if self._style_get(t, "border") else "2px solid currentColor")

    @ui.refreshable
    def toolbar(self):
        ses = self.ses
        sel = ses.selection
        if ses.cropping:
            ui.label("Cropping").classes("ce-tb-label")
            ui.button("Apply crop", icon="check", on_click=lambda: ui.run_javascript("window.colloquiumEditor.cropCommit()")).props("dense size=sm color=orange")
            ui.button("Cancel", icon="close", on_click=lambda: ui.run_javascript("window.colloquiumEditor.cropCancel()")).props("flat dense size=sm")
            ui.label("drag the orange handles to cut · drag inside to move the image · click outside or Enter applies · Esc cancels").classes("text-xs")
            return
        t = self._text_target()
        if not t:
            kind = sel.get("kind") if sel else None
            if kind == "place":
                refs = self.slide.place_refs()
                i = int(sel["index"])
                if i < len(refs) and refs[i].spec.kind == "image":
                    ui.label("Image").classes("ce-tb-label")
                    ui.button("Crop", icon="crop", on_click=lambda: ui.run_javascript("window.colloquiumEditor.cropEnter()")).props("flat dense size=sm").tooltip("Crop on the canvas (orange handles)")
                    ui.button("Reset size", icon="photo_size_select_actual", on_click=lambda: ui.run_javascript("window.colloquiumEditor.resetSize()")).props("flat dense size=sm").tooltip("Natural pixel size of the (cropped) image")
                    if refs[i].spec.crop:
                        ui.button("Reset crop", icon="crop_free", on_click=lambda: self.clear_crop(i)).props("flat dense size=sm")
                    ui.button("Replace", icon="folder", on_click=lambda: self.add_image_dialog(replace_index=i)).props("flat dense size=sm")
                    return
            if kind == "master":
                ui.label("Theme element").classes("ce-tb-label")
                ui.label("repeats on every slide · double-click to edit it on the theme slide").classes("text-xs")
                ui.button("Edit on theme slide", icon="palette", on_click=lambda: self.goto_master(int(sel["index"]))).props("flat dense size=sm")
                return
            if kind == "block":
                if sel.get("img") is not None:
                    ui.label("Inline image").classes("ce-tb-label")
                    ui.label("drag handles to resize in place · drag the image to place it freely").classes("text-xs")
                else:
                    ui.label("Inline block").classes("ce-tb-label")
                    ui.label("drag moves it out of the flow · side handles resize · double-click edits · Del removes").classes("text-xs")
                ui.button("Place freely", icon="open_with", on_click=lambda: ui.run_javascript("window.colloquiumEditor.convertBlock()")).props("flat dense size=sm")
                return
            ui.label("Select a text element to format it · double-click to edit text").classes("ce-tb-label")
            return
        kind, i, obj = t
        ui.label("Cell" if kind == "cell" else "Text").classes("ce-tb-label")
        if kind != "cell":
            for icon, fmt, tip in [("format_bold", "bold", "Bold (Ctrl+B)"), ("format_italic", "italic", "Italic (Ctrl+I)"), ("code", "code", "Code")]:
                ui.button(icon=icon, on_click=lambda e, f=fmt: ui.run_javascript(f"window.colloquiumEditor.format({js(f)})")).props("flat dense size=sm").tooltip(tip)
        ui.label("Size").classes("ce-tb-label")
        ui.button(icon="remove", on_click=lambda: self.font_step(-1)).props("flat dense size=sm")
        if kind == "place":
            ui.label(f"{(obj.size or 1.0):.1f}x").classes("text-xs")
        else:
            fs = px_or_none(self._style_get(t, "font-size")) or float((sel or {}).get("font") or 0)
            ui.label(f"{int(fs)}px" if fs else "auto").classes("text-xs")
        ui.button(icon="add", on_click=lambda: self.font_step(1)).props("flat dense size=sm")
        ui.label("Colour").classes("ce-tb-label")
        ui.input(value=hex_color(self._style_get(t, "color")) or "#000000").props("type=color dense borderless").tooltip("Text colour").on(
            "change", lambda e: self.set_style("color", e.sender.value)
        )
        ui.button(icon="format_color_reset", on_click=lambda: self.set_style("color", None)).props("flat dense size=sm").tooltip("Default colour")
        ui.label("Fill").classes("ce-tb-label")
        ui.input(value=hex_color(self._style_get(t, "background")) or "#ffffff").props("type=color dense borderless").tooltip("Background").on(
            "change", lambda e: self.set_style("background", e.sender.value)
        )
        ui.button(icon="format_color_reset", on_click=lambda: self.set_style("background", None)).props("flat dense size=sm").tooltip("No background")
        ui.button(icon="border_outer", on_click=lambda: self.toggle_border()).props("flat dense size=sm").tooltip("Toggle border")
        pad = self._style_get(t, "padding")
        ui.button(icon="padding", on_click=lambda: self.set_style("padding", None if pad else "0.3em 0.6em")).props("flat dense size=sm").tooltip("Toggle padding")
        ui.label("Align").classes("ce-tb-label")
        cur_align = obj.align if kind == "place" else (self._style_get(t, "text-align") or "")
        for icon, val in [("format_align_left", "left"), ("format_align_center", "center"), ("format_align_right", "right")]:
            ui.button(icon=icon, on_click=lambda e, v=val: self.set_text_align("" if cur_align == v else v)).props(
                "flat dense size=sm" + (" color=primary" if cur_align == val else "")
            )
        ui.button(icon="edit", on_click=lambda: ui.run_javascript(f"window.colloquiumEditor.edit({js({'kind': kind, 'index': i})})")).props("flat dense size=sm").tooltip("Edit text (Enter)")
