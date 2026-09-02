"""Document mutations triggered from the UI (slides, placed elements, groups, clipboard, theme)."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from colloquium.editor import images
from colloquium.editor import theme as theme_mod
from colloquium.editor.picker import fs_browser
from colloquium.elements import place


class ActionsMixin:
    # ------------------------------------------------------------- deck / slides
    def undo(self):
        if self.st.do_undo():
            self.ses.selection = None
            self.ses.extra = []
            self.refresh_all()
        else:
            self.notify("Nothing to undo", "warning")

    def redo(self):
        if self.st.do_redo():
            self.ses.selection = None
            self.ses.extra = []
            self.refresh_all()
        else:
            self.notify("Nothing to redo", "warning")

    def build_html(self):
        from colloquium.build import build_file

        out = build_file(str(self.st.path))
        self.notify(f"Built {Path(out).name}")

    def new_slide(self):
        def apply():
            self.st.doc.insert_slide(self.ses.index + 1)
            self.ses.index += 1
            self.ses.selection = None

        self.mutate(apply, whole_deck=True)

    def dup_slide(self):
        def apply():
            self.st.doc.duplicate_slide(self.ses.index)
            self.ses.index += 1
            self.ses.selection = None

        self.mutate(apply, whole_deck=True)

    def del_slide(self):
        if len(self.st.doc.slides) <= 1:
            self.notify("Cannot delete the only slide", "warning")
            return

        def apply():
            self.st.doc.delete_slide(self.ses.index)
            self.ses.index = min(self.ses.index, len(self.st.doc.slides) - 1)
            self.ses.selection = None

        self.mutate(apply, whole_deck=True)

    def move_slide_to(self, src: int, dst: int):
        def apply():
            self.st.doc.move_slide(src, dst)
            self.ses.index = dst

        self.mutate(apply, whole_deck=True)

    def theme_slide(self):
        masters = self.st.doc.master_indices()
        if masters:
            self.goto(masters[0])
            return

        def apply():
            self.st.doc.add_master_slide()
            self.ses.index = 0
            self.ses.selection = None
            self.ses.extra = []

        self.mutate(apply, whole_deck=True)
        self.notify("Theme slide added at the top; it is not part of the presentation")

    def goto_master(self, i: int):
        """Open the theme slide and select the element that produced master element *i*."""
        for mi in self.st.doc.master_indices():
            n = len(self.st.doc.slides[mi].place_refs())
            if i < n:
                self.goto(mi)
                self.select({"kind": "place", "index": i})
                return
            i -= n

    # ------------------------------------------------------------- slide text
    def set_title(self, value: str):
        if value.strip() == self.slide.get_title():
            return
        self.mutate(lambda: self.slide.set_title(value))

    def set_directive(self, key: str, value: str | None):
        cur = self.slide.get_directive(key) or ""
        if (value or "").strip() == cur:
            return
        self.mutate(lambda: self.slide.set_directive(key, value), whole_deck=key in {"after", "master"})

    def set_cell(self, i: int, value: str):
        if value.strip("\n") == self.slide.get_cell(i):
            return
        self.mutate(lambda: self.slide.set_cell(i, value))

    def set_cell_style_raw(self, i: int, value: str):
        if value.strip().rstrip(";") == self.slide.get_cell_style(i):
            return
        self.mutate(lambda: self.slide.set_cell_style(i, value))

    def set_raw(self, value: str):
        if value.strip("\n") == self.slide.text:
            return

        def apply():
            self.slide.text = value.strip("\n")

        self.mutate(apply, whole_deck=True)

    # ------------------------------------------------------------- blocks
    def block_ok(self, c: int, b: int, count=None) -> bool:
        """The browser counts rendered blocks; refuse when the source disagrees."""
        chunk = self.slide
        if c >= len(chunk.cell_spans()):
            return False
        blocks = chunk.cell_blocks(c)
        sel = self.ses.selection
        if count is None and sel and sel.get("kind") == "block" and sel.get("index") == c * 100 + b:
            count = sel.get("count")
        if b >= len(blocks) or (count is not None and int(count) != len(blocks)):
            self.notify("Cannot map this block to the markdown source; edit the cell instead", "warning")
            return False
        return True

    def set_block(self, c: int, b: int, value: str, count=None):
        if not self.block_ok(c, b, count):
            return
        if value.strip("\n") == self.slide.get_cell_block(c, b).strip("\n"):
            return
        self.mutate(lambda: self.slide.set_cell_block(c, b, value))

    def delete_block(self, c: int, b: int, count=None):
        if not self.block_ok(c, b, count):
            return
        self.ses.selection = None
        self.mutate(lambda: self.slide.remove_cell_block(c, b))

    def convert_block(self, c: int, b: int, count, x: float, y: float, w: float, img=None):
        """Lift a flow block (or one image inside it) out of the cell into a place block."""
        if not self.block_ok(c, b, count):
            self.refresh_all()
            return

        def apply():
            chunk = self.slide
            if img is not None and img < len(chunk.block_images(c, b)):
                idx = chunk.convert_block_image_to_place(c, b, int(img), x, y, w)
            else:
                idx = chunk.convert_cell_block_to_place(c, b, x, y, w)
            self.ses.selection = {"kind": "place", "index": idx}
            self.ses.extra = []

        if self.mutate(apply):
            self.notify("Now a free object (was inline)")

    # ------------------------------------------------------------- placed elements
    def select_none(self):
        self.select(None)

    def select_place(self, i: int):
        self.select({"kind": "place", "index": i})

    def set_place_text(self, i: int, value: str):
        spec = self.slide.get_place(i)
        if value.rstrip("\n") == spec.text.rstrip("\n"):
            return
        spec.text = (value.rstrip("\n") + "\n") if value.strip() else ""
        self.mutate(lambda: self.slide.set_place(i, spec))

    def set_place_attr(self, i: int, attr: str, value):
        spec = self.slide.get_place(i)
        if getattr(spec, attr) == value:
            return
        setattr(spec, attr, value)
        self.mutate(lambda: self.slide.set_place(i, spec))

    def delete_place(self, i: int):
        self.ses.selection = None
        self.mutate(lambda: self.slide.remove_place(i))

    def clear_crop(self, i: int):
        spec = self.slide.get_place(i)
        spec.crop = None
        self.mutate(lambda: self.slide.set_place(i, spec))

    def add_shape(self, shape: str):
        if shape in {"line", "arrow"}:
            spec = place.PlaceSpec(x=20, y=50, w=30, h=0.5, shape=shape)
        else:
            spec = place.PlaceSpec(x=30, y=30, w=25, h=20, shape=shape)
        self._add_spec(spec)

    def add_text(self):
        self._add_spec(place.PlaceSpec(x=10, y=40, w=30, text="New text\n"))

    def _add_spec(self, spec: place.PlaceSpec):
        def apply():
            idx = self.slide.add_place(spec)
            self.ses.selection = {"kind": "place", "index": idx}
            self.ses.extra = []

        self.mutate(apply)

    def add_image_from(self, p: Path, replace_index: int | None = None):
        rel = images.import_image(p, self.deck_dir)
        size = images.image_size(self.deck_dir / rel)

        def apply():
            if replace_index is None:
                spec = place.PlaceSpec(x=30, y=20, w=images.default_place_width(size), src=rel)
                idx = self.slide.add_place(spec)
                self.ses.selection = {"kind": "place", "index": idx}
            else:
                spec = self.slide.get_place(replace_index)
                spec.src = rel
                spec.crop = None
                self.slide.set_place(replace_index, spec)

        self.mutate(apply)
        self.notify(f"Image: {rel}")

    def add_image_dialog(self, replace_index: int | None = None):
        self._image_dialog("Pick an image (copied into the deck folder if outside it)", lambda p: self.add_image_from(p, replace_index))

    def _image_dialog(self, title: str, on_pick):
        with ui.dialog() as dlg, ui.card().classes("w-[760px] max-w-full"):
            ui.label(title).classes("text-sm")

            def pick(p: Path):
                dlg.close()
                on_pick(p)

            fs_browser(ui, self.deck_dir, images.IMAGE_SUFFIXES, pick, height="55vh")
            ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    # ------------------------------------------------------------- formatting
    def apply_format(self, fmt: str, i: int):
        md = {"bold": ("**", "**"), "italic": ("*", "*"), "code": ("`", "`")}
        spec = self.slide.get_place(i)
        a, b = md[fmt]
        text = spec.text.rstrip("\n")
        if not text:
            return
        text = text[len(a):-len(b)] if text.startswith(a) and text.endswith(b) else f"{a}{text}{b}"
        self.set_place_text(i, text)

    # ------------------------------------------------------------- arrange / groups / clipboard
    def arrange(self, item: dict, mode: str):
        i = int(item["index"])
        chunk = self.slide
        n = len(chunk.place_refs())
        if item.get("kind") != "place" or i >= n:
            return
        target = {"front": n - 1, "back": 0, "forward": min(i + 1, n - 1), "backward": max(i - 1, 0)}[mode]
        if target == i:
            return

        def apply():
            j = chunk.reorder_place(i, target)
            self.ses.selection = {"kind": "place", "index": j}
            self.ses.extra = []

        self.mutate(apply)

    def _place_items(self, items) -> list[int]:
        n = len(self.slide.place_refs())
        return sorted({int(x["index"]) for x in items if x and x.get("kind") == "place" and int(x["index"]) < n})

    def copy_to_clipboard(self, items):
        chunk = self.slide
        blocks = [chunk.place_refs()[i].spec.to_markdown() for i in self._place_items(items)]
        self.ses.clipboard = blocks
        if blocks:
            self.notify(f"Copied {len(blocks)} element(s)")

    def paste_clipboard(self, offset: bool = True):
        if not self.ses.clipboard:
            self.notify("Clipboard is empty", "warning")
            return
        dp = 2 if offset else 0

        def apply():
            chunk = self.slide
            pasted = []
            for block in self.ses.clipboard:
                chunk.append_raw(block)
                if block.startswith("```place"):
                    idx = len(chunk.place_refs()) - 1
                    spec = chunk.get_place(idx)
                    spec.x += dp
                    spec.y += dp
                    chunk.set_place(idx, spec)
                    pasted.append({"kind": "place", "index": idx})
            self._remap_copied_groups(chunk, pasted)
            self.ses.selection = pasted[0] if pasted else None
            self.ses.extra = pasted[1:]

        self.mutate(apply)

    def duplicate_items(self, items):
        idxs = self._place_items(items)
        if not idxs:
            return

        def apply():
            chunk = self.slide
            # duplicate from the highest index down so earlier indices stay
            # valid; each duplicate lands right after its original, which
            # shifts every later original by one per earlier duplicate.
            for i in reversed(idxs):
                chunk.duplicate_place(i)
            sels = [{"kind": "place", "index": i + 1 + k} for k, i in enumerate(idxs)]
            self._remap_copied_groups(chunk, sels)
            self.ses.selection = sels[0]
            self.ses.extra = sels[1:]

        self.mutate(apply)

    def delete_items(self, items):
        idxs = self._place_items(items)
        if not idxs:
            return

        def apply():
            for i in reversed(idxs):
                self.slide.remove_place(i)
            self.ses.selection = None
            self.ses.extra = []

        self.mutate(apply)

    def _fresh_group_number(self, extra_used=()) -> int:
        """Group names are unique across the deck (theme-slide groups included)."""
        used = {r.spec.group for c in self.st.doc.slides for r in c.place_refs() if r.spec.group} | set(extra_used)
        n = 1
        while f"g{n}" in used:
            n += 1
        return n

    def _remap_copied_groups(self, chunk, sels):
        """Copies of grouped elements get a fresh group per original group."""
        mapping = {}
        for s2 in sels:
            if s2["index"] >= len(chunk.place_refs()):
                continue
            spec = chunk.get_place(s2["index"])
            if not spec.group:
                continue
            if spec.group not in mapping:
                mapping[spec.group] = f"g{self._fresh_group_number(set(mapping.values()))}"
            spec.group = mapping[spec.group]
            chunk.set_place(s2["index"], spec)

    def group_items(self, items):
        idxs = self._place_items(items)
        if len(idxs) < 2:
            self.notify("Select 2+ placed elements to group (shift-click)", "warning")
            return

        def apply():
            chunk = self.slide
            name = f"g{self._fresh_group_number()}"
            for k in idxs:
                spec = chunk.get_place(k)
                spec.group = name
                chunk.set_place(k, spec)
            sels = [{"kind": "place", "index": k} for k in idxs]
            self.ses.selection = sels[0]
            self.ses.extra = sels[1:]

        if self.mutate(apply):
            self.notify("Grouped: moves and resizes as one · Alt+click picks a single member")

    def ungroup_items(self, items):
        chunk = self.slide
        idxs = [k for k in self._place_items(items) if chunk.get_place(k).group]
        if not idxs:
            self.notify("No grouped elements selected", "warning")
            return

        def apply():
            for k in idxs:
                spec = chunk.get_place(k)
                spec.group = ""
                chunk.set_place(k, spec)

        self.mutate(apply)
        self.notify("Ungrouped")

    # ------------------------------------------------------------- theme
    def _set_css(self, new: str):
        css = self.st.doc.get_custom_css()
        if new == css:
            return
        self.mutate(lambda: self.st.doc.set_custom_css(new), whole_deck=True)

    def set_theme_var(self, name: str, value: str | None):
        self._set_css(theme_mod.set_root_var(self.st.doc.get_custom_css(), name, value))

    def set_custom_css_raw(self, value: str):
        if value.rstrip("\n") == self.st.doc.get_custom_css().rstrip("\n"):
            return
        self._set_css(value)

    def set_background(self, path: str | None):
        self._set_css(theme_mod.set_background_image(self.st.doc.get_custom_css(), path))

    def background_dialog(self):
        self._image_dialog(
            "Pick a background image (copied into the deck folder if outside it)",
            lambda p: self.set_background(images.import_image(p, self.deck_dir)),
        )
