from urllib.request import urlopen

from colloquium.export import _serve_html_for_export


def test_serve_html_for_export_serves_deck_over_loopback(tmp_path):
    html_path = tmp_path / "deck file.html"
    html_path.write_text("<!doctype html><title>Deck</title>", encoding="utf-8")

    with _serve_html_for_export(str(html_path)) as url:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/deck%20file.html")
        with urlopen(url, timeout=2) as response:
            body = response.read().decode("utf-8")

    assert "<title>Deck</title>" in body
