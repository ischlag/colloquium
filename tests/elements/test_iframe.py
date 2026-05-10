from colloquium.elements.iframe import PATTERN, process


def _render_iframe_block(yaml_body: str) -> str:
    html = f'<pre><code class="language-iframe">{yaml_body}</code></pre>'
    return PATTERN.sub(lambda m: process(m.group(1)), html)


def test_iframe_renders_with_required_src():
    out = _render_iframe_block("src: https://example.com/embed.html")
    assert '<iframe' in out
    assert 'src="https://example.com/embed.html"' in out
    assert 'height="480"' in out  # default
    assert 'loading="eager"' in out  # default
    assert 'allowfullscreen' in out
    assert 'data-colloquium-preserve-keyboard="true"' in out


def test_iframe_renders_optional_fields():
    out = _render_iframe_block(
        "\n".join(
            [
                "src: https://example.com/x",
                "width: 480",
                "height: 520",
                "title: Demo Frame",
                "loading: lazy",
                "allowfullscreen: false",
                "preserve_keyboard: false",
            ]
        )
    )
    assert 'width="480"' in out
    assert 'height="520"' in out
    assert 'title="Demo Frame"' in out
    assert 'loading="lazy"' in out
    assert 'allowfullscreen' not in out
    assert 'data-colloquium-preserve-keyboard="false"' in out


def test_iframe_invalid_yaml():
    out = _render_iframe_block("src: [not valid")
    assert "Invalid iframe YAML" in out


def test_iframe_requires_mapping():
    out = _render_iframe_block("- src: https://example.com")
    assert "Iframe spec must be a YAML mapping" in out


def test_iframe_requires_src():
    out = _render_iframe_block("height: 500")
    assert "Iframe requires src" in out


def test_iframe_rejects_null_src():
    out = _render_iframe_block("src: null")
    assert "Iframe requires src" in out
    assert 'src="None"' not in out


def test_iframe_sanitizes_src_and_title():
    out = _render_iframe_block(
        "\n".join(
            [
                'src: https://example.com/?q="x"&k=<tag>',
                'title: "<unsafe>"',
            ]
        )
    )
    assert 'src="https://example.com/?q=&quot;x&quot;&amp;k=&lt;tag&gt;"' in out
    assert 'title="&lt;unsafe&gt;"' in out


def test_iframe_height_falls_back_to_default_for_invalid_values():
    for bad in ["0", "-10", "abc"]:
        out = _render_iframe_block(f"src: https://example.com\nheight: {bad}")
        assert 'height="480"' in out


def test_iframe_loading_falls_back_to_default_for_invalid_values():
    out = _render_iframe_block("src: https://example.com\nloading: banana")
    assert 'loading="eager"' in out


def test_iframe_supports_embed_attributes():
    out = _render_iframe_block(
        "\n".join(
            [
                "src: https://www.interconnects.ai/embed",
                "width: 480",
                "height: 320",
                'style: "border: 1px solid #EEE; background: white"',
                "frameborder: 0",
                "scrolling: no",
            ]
        )
    )
    assert 'width="480"' in out
    assert 'height="320"' in out
    assert 'frameborder="0"' in out
    assert 'scrolling="no"' in out
    assert 'style="border: 1px solid #EEE; background: white"' in out
