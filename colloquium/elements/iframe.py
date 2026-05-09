import html as html_module
import re
import yaml

PATTERN = re.compile(r'<pre><code class="language-iframe">(.*?)</code></pre>', re.DOTALL)
IFRAME_DEFAULT_HEIGHT = 480

def reset() -> None:
    return None

def _height(v):
    try:
        n = int(v)
        return n if n > 0 else IFRAME_DEFAULT_HEIGHT
    except (TypeError, ValueError):
        return IFRAME_DEFAULT_HEIGHT

def process(yaml_str: str) -> str:
    raw = html_module.unescape(yaml_str.strip())
    try:
        spec = yaml.safe_load(raw)
    except yaml.YAMLError:
        return '<p style="color:red">Invalid iframe YAML</p>'
    if not isinstance(spec, dict):
        return '<p style="color:red">Iframe spec must be a YAML mapping</p>'

    src = str(spec.get("src", "")).strip()
    if not src:
        return '<p style="color:red">Iframe requires src</p>'

    h = _height(spec.get("height", IFRAME_DEFAULT_HEIGHT))
    title = html_module.escape(str(spec.get("title", "")).strip())
    loading = html_module.escape(str(spec.get("loading", "lazy")).strip() or "lazy")
    allow = spec.get("allowfullscreen", True) not in {False, "false", "off", "0"}

    src_attr = html_module.escape(src, quote=True)
    allow_attr = " allowfullscreen" if allow else ""
    return (
        f'<div class="colloquium-iframe-container" style="width:100%;height:auto;min-height:{h}px;">'
        f'<iframe class="colloquium-iframe" src="{src_attr}" title="{title}" loading="{loading}" '
        f'width="100%" height="{h}" frameborder="0"{allow_attr} '
        f'style="border:none;display:block;width:100%;height:{h}px"></iframe></div>'
    )
