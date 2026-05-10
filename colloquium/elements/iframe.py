import html as html_module
import re

import yaml

PATTERN = re.compile(r'<pre><code class="language-iframe">(.*?)</code></pre>', re.DOTALL)
IFRAME_DEFAULT_HEIGHT = 480
IFRAME_DEFAULT_LOADING = "lazy"
IFRAME_DEFAULT_WIDTH = "100%"
_FALSE_VALUES = {"false", "off", "0", "no"}


def reset() -> None:
    return None


def _height(value) -> int:
    try:
        height = int(value)
        return height if height > 0 else IFRAME_DEFAULT_HEIGHT
    except (TypeError, ValueError):
        return IFRAME_DEFAULT_HEIGHT


def _width(value) -> str:
    if value is None or value == "":
        return IFRAME_DEFAULT_WIDTH
    text = str(value).strip()
    if not text:
        return IFRAME_DEFAULT_WIDTH
    if text.endswith("%"):
        try:
            return text if float(text[:-1]) > 0 else IFRAME_DEFAULT_WIDTH
        except ValueError:
            return IFRAME_DEFAULT_WIDTH
    try:
        width = int(text)
        return str(width) if width > 0 else IFRAME_DEFAULT_WIDTH
    except ValueError:
        return IFRAME_DEFAULT_WIDTH


def _loading(value) -> str:
    loading = str(value or IFRAME_DEFAULT_LOADING).strip().lower()
    return loading if loading in {"lazy", "eager"} else IFRAME_DEFAULT_LOADING


def _allowfullscreen(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_VALUES
    return bool(value)


def _scrolling(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    scrolling = str(value).strip().lower()
    return scrolling if scrolling in {"auto", "yes", "no"} else None


def _frameborder(value) -> str:
    frameborder = str(value if value is not None else "0").strip()
    return frameborder if frameborder in {"0", "1"} else "0"


def _width_css(width: str) -> str:
    return f"{width}px" if width.isdigit() else width


def process(yaml_str: str) -> str:
    raw = html_module.unescape(yaml_str.strip())
    try:
        spec = yaml.safe_load(raw)
    except yaml.YAMLError:
        return '<p style="color:red">Invalid iframe YAML</p>'
    if not isinstance(spec, dict):
        return '<p style="color:red">Iframe spec must be a YAML mapping</p>'

    src_value = spec.get("src")
    src = src_value.strip() if isinstance(src_value, str) else ""
    if not src:
        return '<p style="color:red">Iframe requires src</p>'

    height = _height(spec.get("height", IFRAME_DEFAULT_HEIGHT))
    width = _width(spec.get("width", IFRAME_DEFAULT_WIDTH))
    title = html_module.escape(str(spec.get("title", "") or "").strip(), quote=True)
    loading = html_module.escape(
        _loading(spec.get("loading", IFRAME_DEFAULT_LOADING)),
        quote=True,
    )
    allow = _allowfullscreen(spec.get("allowfullscreen", True))
    scrolling = _scrolling(spec.get("scrolling"))
    frameborder = html_module.escape(
        _frameborder(spec.get("frameborder", "0")),
        quote=True,
    )
    style_value = spec.get("style")
    style = (
        str(style_value).strip()
        if style_value is not None and style_value != ""
        else f"border:none;display:block;width:{_width_css(width)};height:{height}px"
    )

    src_attr = html_module.escape(src, quote=True)
    allow_attr = " allowfullscreen" if allow else ""
    scrolling_attr = (
        f' scrolling="{html_module.escape(scrolling, quote=True)}"' if scrolling else ""
    )
    container_style = f"width:{_width_css(width)};height:auto;min-height:{height}px;"
    return (
        f'<div class="colloquium-iframe-container" style="{container_style}">'
        f'<iframe class="colloquium-iframe" src="{src_attr}" title="{title}" loading="{loading}" '
        f'width="{html_module.escape(width, quote=True)}" height="{height}" '
        f'frameborder="{frameborder}"{scrolling_attr}{allow_attr} '
        f'style="{html_module.escape(style, quote=True)}"></iframe></div>'
    )
