"""Theme helpers for the editor: CSS variables and marked rules in custom_css."""

from __future__ import annotations

import re
from pathlib import Path

COLOR_VARS = [
    ("--colloquium-bg", "Background"),
    ("--colloquium-text", "Text"),
    ("--colloquium-heading", "Headings"),
    ("--colloquium-accent", "Accent"),
    ("--colloquium-link", "Links"),
    ("--colloquium-muted", "Muted"),
    ("--colloquium-border", "Borders"),
    ("--colloquium-code-bg", "Code background"),
]
FONT_VARS = [
    ("--colloquium-font-heading", "Heading font"),
    ("--colloquium-font-body", "Body font"),
    ("--colloquium-font-mono", "Mono font"),
]
BG_MARKER = "/* colloquium-editor: slide background */"

_ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.DOTALL)


def theme_defaults(theme: str = "default") -> dict[str, str]:
    """Variables declared in the theme's own :root block."""
    css_path = Path(__file__).resolve().parent.parent / "themes" / theme / "theme.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for m in _ROOT_RE.finditer(css):
        for name, value in _decls(m.group(1)):
            out.setdefault(name, value)
    return out


def _decls(body: str) -> list[tuple[str, str]]:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    out = []
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip():
                out.append((k.strip(), v.strip()))
    return out


def get_root_var(css: str, name: str) -> str | None:
    value = None
    for m in _ROOT_RE.finditer(css):
        for k, v in _decls(m.group(1)):
            if k == name:
                value = v  # last declaration wins, like the cascade
    return value


def set_root_var(css: str, name: str, value: str | None) -> str:
    """Set (or remove with None) a variable in the first :root block, creating one if needed."""
    decl_re = re.compile(r"[ \t]*" + re.escape(name) + r"\s*:[^;\n}]*;?[ \t]*\n?")
    blocks = list(_ROOT_RE.finditer(css))
    for m in blocks:
        body = m.group(1)
        if decl_re.search(body):
            if value is None:
                new_body = decl_re.sub("", body, count=1)
            else:
                new_body = decl_re.sub(lambda mm: f"  {name}: {value};\n", body, count=1)
            return css[: m.start(1)] + new_body + css[m.end(1):]
    if value is None:
        return css
    if blocks:
        m = blocks[0]
        body = m.group(1)
        if not body.endswith("\n"):
            body += "\n"
        return css[: m.start(1)] + body + f"  {name}: {value};\n" + css[m.end(1):]
    block = f":root {{\n  {name}: {value};\n}}\n"
    return block + ("\n" + css if css.strip() else "")


_BG_RULE_RE = re.compile(re.escape(BG_MARKER) + r"\n\.slide\s*\{[^}]*\}\n?")
_ANY_SLIDE_BG_RE = re.compile(r"(\.slide\s*\{[^}]*?background-image:\s*url\()([\"\']?)([^\"\')]+)(\2\))")


def get_background_image(css: str) -> str | None:
    m = _ANY_SLIDE_BG_RE.search(css)
    return m.group(3) if m else None


def set_background_image(css: str, path: str | None) -> str:
    """Point the slide background at *path* (relative to the deck) or remove it."""
    if path is None:
        css = _BG_RULE_RE.sub("", css)
        # unmarked hand-written rule: drop just the background-image declaration
        css = re.sub(r"(\.slide\s*\{[^}]*?)[ \t]*background-image:\s*url\([^)]*\);?[ \t]*", r"\1", css)
        return css
    if _BG_RULE_RE.search(css):
        rule = _bg_rule(path)
        return _BG_RULE_RE.sub(lambda _: rule, css)
    if _ANY_SLIDE_BG_RE.search(css):
        return _ANY_SLIDE_BG_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{path}{m.group(4)}", css, count=1)
    return css.rstrip("\n") + ("\n" if css.strip() else "") + _bg_rule(path)


def _bg_rule(path: str) -> str:
    return (
        f"{BG_MARKER}\n.slide {{ background-image: url(\"{path}\"); background-size: cover; "
        "background-position: center; background-repeat: no-repeat; "
        "-webkit-print-color-adjust: exact; print-color-adjust: exact; }\n"
    )
