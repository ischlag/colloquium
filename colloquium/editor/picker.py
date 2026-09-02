"""Minimal local file-system browser used to pick a deck or an image."""

from __future__ import annotations

from pathlib import Path


def file_picker_page(ui, on_pick, root: Path) -> None:
    """Page shown when ``colloquium edit`` is started without a deck."""
    from colloquium.templates import create_deck

    with ui.column().classes("items-center w-full p-8 gap-4"):
        ui.label("Open a colloquium deck").classes("text-xl")
        with ui.row().classes("items-center gap-2 w-full max-w-3xl"):
            target = ui.input(label="New deck folder", value=str(root / "new-deck")).props("dense outlined").classes("flex-1")

            def create():
                try:
                    on_pick(create_deck(Path(target.value)))
                except (ValueError, FileExistsError, OSError) as exc:
                    ui.notify(str(exc), color="warning")

            ui.button("New deck from template", icon="add", on_click=create).props("dense")
        ui.label("or pick an existing .md below").classes("text-sm text-gray-500")
        fs_browser(ui, root, {".md"}, on_pick, height="60vh", root=root)


def fs_browser(ui, start: Path, suffixes: set[str], on_pick, height="50vh", root: Path | None = None) -> None:
    """Directory listing; calls ``on_pick(Path)`` for a chosen file. Never browses above *root*."""
    root = (root or Path("/")).resolve()
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
            if d != root and root in d.parents:
                ui.item("..", on_click=lambda: go(d.parent)).props("clickable").classes("text-gray-500")
            for p in entries:
                if p.name.startswith("."):
                    continue
                if p.is_dir():
                    ui.item(f"📁 {p.name}", on_click=lambda p=p: go(p)).props("clickable")
                elif p.suffix.lower() in suffixes:
                    ui.item(f"📄 {p.name}", on_click=lambda p=p: on_pick(p)).props("clickable").classes("text-blue-700")

    def go(p: Path):
        p = p.resolve()
        if p == root or root in p.parents:
            current["dir"] = p
            render()

    render()
